"""Resolve Arduino libraries per library.properties and sketch includes."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from acmake.parse_txt import load_properties_file
from acmake.sketch import list_sketch_inos


@dataclass(frozen=True)
class Library:
    root: Path
    name: str
    architectures: str  # comma list or * 
    depends: tuple[str, ...]
    includes_override: str | None
    version: str | None = None

    @property
    def include_roots(self) -> list[Path]:
        if self.includes_override:
            p = self.root / self.includes_override.strip()
            if p.is_dir():
                return [p.resolve()]
        src = self.root / "src"
        if src.is_dir():
            return [src.resolve(), self.root.resolve()]
        return [self.root.resolve()]


@dataclass(frozen=True)
class LibraryResolveNote:
    """Why one library was linked (token + where that dependency was discovered)."""

    library_name: str
    library_root: str
    include_token: str
    via: str
    public_header_relpath: str | None = None


_LIB_SOURCE_EXTS = frozenset(
    {".h", ".hh", ".hpp", ".cpp", ".cc", ".cxx", ".c", ".ino", ".s", ".S"}
)


def _parse_arch(s: str) -> set[str]:
    return {x.strip().lower() for x in s.split(",") if x.strip()}


def ensure_build_libraries_stub_dirs(build_dir: Path, libraries: list[Library]) -> None:
    """Create ``<build>/libraries/<folder>/`` for each linked library.

    Matches the Arduino IDE build layout. The ESP32 platform's
    ``recipe.hooks.objcopy.postobjcopy.*`` hooks gate on paths like
    ``{build.path}/libraries/ESP_SR`` and ``.../libraries/Insights``.
    """
    root = build_dir / "libraries"
    root.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for lib in libraries:
        folder = lib.root.name
        if folder in seen:
            continue
        seen.add(folder)
        (root / folder).mkdir(parents=True, exist_ok=True)


def _arch_matches(lib_arch: str, fqbn_arch: str) -> bool:
    lib_arch = lib_arch.strip()
    if not lib_arch or lib_arch == "*":
        return True
    allowed = _parse_arch(lib_arch)
    return "*" in allowed or fqbn_arch.lower() in allowed


def discover_libraries(library_dirs: list[Path]) -> dict[str, Library]:
    """Map canonical library name (properties name=) -> Library."""
    found: dict[str, Library] = {}
    for base in library_dirs:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            prop = child / "library.properties"
            if not prop.is_file():
                continue
            raw = load_properties_file(prop)
            name = raw.get("name", child.name).strip()
            arch = raw.get("architectures", "*").strip() or "*"
            deps_raw = raw.get("depends", "").strip()
            depends = tuple(x.strip() for x in deps_raw.split(",") if x.strip())
            inc = raw.get("includes")
            ver = (raw.get("version") or "").strip() or None
            lib = Library(
                root=child.resolve(),
                name=name,
                architectures=arch,
                depends=depends,
                includes_override=inc.strip() if inc else None,
                version=ver,
            )
            found[name.lower()] = lib
            found[child.name.lower()] = lib
    return found


# Quoted or angle-bracket includes ending in ``.h`` (full path inside delimiters).
_INCLUDE_RE = re.compile(
    r'^\s*#\s*include\s*"(?P<q>[^"]+\.h)"|^\s*#\s*include\s*<(?P<a>[^>]+\.h)>',
    flags=re.MULTILINE,
)

# Lowercase ``*.h`` basenames supplied by the host C library / toolchain — never treat as
# Arduino libraries (e.g. ``#include <string.h>`` must not enqueue token ``string``).
_STANDARD_DOT_H_BASENAMES_LOWER = frozenset(
    f"{name}.h"
    for name in (
        "alloca",
        "assert",
        "complex",
        "ctype",
        "errno",
        "fenv",
        "float",
        "inttypes",
        "iso646",
        "limits",
        "locale",
        "malloc",
        "math",
        "pthread",
        "sched",
        "semaphore",
        "setjmp",
        "signal",
        "stdalign",
        "stdarg",
        "stdatomic",
        "stdbool",
        "stddef",
        "stdint",
        "stdio",
        "stdlib",
        "stdnoreturn",
        "string",
        "strings",
        "tgmath",
        "threads",
        "time",
        "uchar",
        "unistd",
        "wchar",
        "wctype",
    )
)


def _is_toolchain_std_dot_h_include(include_path: str) -> bool:
    base = Path(include_path.replace("\\", "/")).name.lower()
    return base in _STANDARD_DOT_H_BASENAMES_LOWER


def _is_multi_segment_include_path(include_path: str) -> bool:
    """True when the include path has a directory component (SDK / core style).

    ``#include <freertos/task.h>`` must not be reduced to token ``task`` and matched
    against a sketchbook library; it is resolved via the core / toolchain ``-I`` tree.
    """
    norm = include_path.replace("\\", "/").strip()
    return "/" in norm


_HEADER_SUFFIX_FOR_INDEX = frozenset({".h", ".hh", ".hpp", ".hxx"})

# Skip scanning these subtrees when inferring transitive #includes from a library.
_SKIP_LIB_SUBDIRS = frozenset(
    {
        "examples",
        "extras",
        "documentation",
        "doc",
        "test",
        "tests",
        ".github",
        ".git",
        "tmp",
        "legacy",
    }
)


def ancestor_library_container_dirs(sketch_dir: Path) -> list[Path]:
    """``.../libraries`` folders above the sketch (e.g. core-bundled ``hardware/.../libraries``).

    Examples live under ``libraries/<Lib>/examples/<Sketch>``; those libraries live
    next to ``<Lib>`` under the same ``libraries`` directory, which is not always on
    the default sketchbook search path.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    cur = sketch_dir.resolve()
    for _ in range(64):
        parent = cur.parent
        if parent.name == "libraries" and parent.is_dir():
            pr = parent.resolve()
            if pr not in seen:
                seen.add(pr)
                found.append(pr)
        if parent == cur:
            break
        cur = parent
    return found


def _is_excluded_lib_scan_path(path: Path) -> bool:
    return any(p in _SKIP_LIB_SUBDIRS for p in path.parts)


def _unique_libraries(by_key: dict[str, Library]) -> list[Library]:
    """Stable de-dupe by install root (``by_key`` maps several keys to the same ``Library``)."""
    out: dict[Path, Library] = {}
    for lib in by_key.values():
        out[lib.root.resolve()] = lib
    return sorted(out.values(), key=lambda L: L.name.lower())


def platform_header_scan_roots(
    core_path: Path, variant_path: Path, platform_root: Path
) -> list[Path]:
    """Trees whose headers are on the compiler path **before** bundled libraries.

    Always the core package folder. The variant directory is included only when it
    lies under ``<platform>/variants/`` — if ``build.variant`` is unset, Arduino-style
    properties often set ``build.variant.path`` to the whole platform, which would
    incorrectly treat every bundled library header as a "core" header.
    """
    roots: list[Path] = []
    cr = core_path.resolve()
    if cr.is_dir():
        roots.append(cr)
    pr = platform_root.resolve()
    variants_base = (pr / "variants").resolve()
    vr = variant_path.resolve()
    try:
        vr.relative_to(variants_base)
    except ValueError:
        return roots
    if vr.is_dir() and vr != cr:
        roots.append(vr)
    return roots


def _platform_header_stems(roots: list[Path]) -> frozenset[str]:
    """Lowercased stems of headers under core / safe variant roots (shadows library resolution)."""
    stems: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _HEADER_SUFFIX_FOR_INDEX:
                continue
            stems.add(path.stem.lower())
    return frozenset(stems)


def _header_stem_to_library(
    by_key: dict[str, Library], platform_stems: frozenset[str]
) -> tuple[dict[str, Library], dict[str, str]]:
    """Map lowercased header stem (``bledevice`` for ``BLEDevice.h``) -> owning ``Library``.

    Sketch ``#include`` tokens often name a **header** in the library (e.g. ``BLEDevice.h``)
    rather than the library's marketing ``name=`` (``BLE``). ``resolve_libraries_for_sketch``
    uses this after the direct name / folder lookup in ``by_key``.

    Stems that already exist under the platform core (or variant) are omitted so bundled
    libraries do not "steal" names the compiler resolves from ``-I`` core first.
    """
    stem_to_lib: dict[str, Library] = {}
    stem_to_header: dict[str, str] = {}
    for lib in _unique_libraries(by_key):
        roots: list[Path] = []
        seen_r: set[Path] = set()
        for r in lib.include_roots:
            rp = r.resolve()
            if rp not in seen_r:
                seen_r.add(rp)
                roots.append(rp)
        lr = lib.root.resolve()
        if lr not in seen_r:
            roots.append(lr)
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in _HEADER_SUFFIX_FOR_INDEX:
                    continue
                if _is_excluded_lib_scan_path(path):
                    continue
                if path.name.lower() in _STANDARD_DOT_H_BASENAMES_LOWER:
                    continue
                stem = path.stem.lower()
                if stem in platform_stems:
                    continue
                if stem not in stem_to_lib:
                    stem_to_lib[stem] = lib
                    try:
                        stem_to_header[stem] = str(
                            path.resolve().relative_to(lib.root.resolve())
                        ).replace("\\", "/")
                    except ValueError:
                        stem_to_header[stem] = path.name
    return stem_to_lib, stem_to_header


def header_stem_index_for_linked_libraries(
    libraries: list[Library], platform_header_stems: frozenset[str]
) -> dict[str, Library]:
    """Like the sketch resolver stem map, but only among *libraries* already linked."""
    by_key: dict[str, Library] = {}
    for lib in libraries:
        by_key[lib.name.lower()] = lib
        by_key[lib.root.name.lower()] = lib
    stem_to_lib, _ = _header_stem_to_library(by_key, platform_header_stems)
    return stem_to_lib


def _library_source_candidate_paths(lib: Library) -> list[Path]:
    roots: list[Path] = []
    seen_root: set[Path] = set()
    for r in lib.include_roots:
        rp = r.resolve()
        if rp not in seen_root:
            seen_root.add(rp)
            roots.append(rp)
    lr = lib.root.resolve()
    if lr not in seen_root:
        roots.append(lr)

    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _LIB_SOURCE_EXTS:
                continue
            if _is_excluded_lib_scan_path(path):
                continue
            candidates.append(path.resolve())
    candidates.sort(key=lambda p: str(p).replace("\\", "/").lower())
    return candidates


def _library_header_candidate_paths(lib: Library) -> list[Path]:
    """Like :func:`_library_source_candidate_paths` but only Arduino-style ``*.h*`` APIs."""
    return [
        p
        for p in _library_source_candidate_paths(lib)
        if p.suffix.lower() in _HEADER_SUFFIX_FOR_INDEX
    ]


def _iter_transitive_include_enqueues_from_headers_only(
    lib: Library, *, max_total_bytes: int = 3_000_000
) -> list[tuple[str, str]]:
    """``(include_token, provenance)`` used to **enqueue more libraries** during resolution."""
    items: list[tuple[str, str]] = []
    total = 0
    lib_root = lib.root.resolve()
    seen_files: set[Path] = set()
    for rp in _library_header_candidate_paths(lib):
        if rp in seen_files:
            continue
        seen_files.add(rp)
        try:
            txt = rp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(txt)
        try:
            rel = str(rp.relative_to(lib_root)).replace("\\", "/")
        except ValueError:
            rel = rp.name
        for h in includes_from_source(txt):
            items.append(
                (
                    h,
                    f'in library "{lib.name}" file {rel}: #include "{h}.h"',
                )
            )
        if total >= max_total_bytes:
            break
    return items


def _iter_transitive_include_enqueues(
    lib: Library, *, max_total_bytes: int = 3_000_000
) -> list[tuple[str, str]]:
    """``(include_token, provenance)`` from this library's ``.c`` / ``.cpp`` sources.

    Used for **include-path closure** among already-linked libs (cached compiles): a
    ``.cpp`` may ``#include`` another linked library header without exporting that
    dependency from a public ``.h``.
    """
    items: list[tuple[str, str]] = []
    total = 0
    lib_root = lib.root.resolve()
    seen_files: set[Path] = set()
    for rp in _library_source_candidate_paths(lib):
        if rp.suffix.lower() in _HEADER_SUFFIX_FOR_INDEX:
            continue
        if rp in seen_files:
            continue
        seen_files.add(rp)
        try:
            txt = rp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += len(txt)
        try:
            rel = str(rp.relative_to(lib_root)).replace("\\", "/")
        except ValueError:
            rel = rp.name
        for h in includes_from_source(txt):
            items.append(
                (
                    h,
                    f'in library "{lib.name}" file {rel}: #include "{h}.h"',
                )
            )
        if total >= max_total_bytes:
            break
    return items


def includes_from_source(text: str) -> list[str]:
    """Basenames (without ``.h``) of ``#include`` lines, first occurrence order (deterministic).

    ISO C / common POSIX ``*.h`` includes (e.g. ``<string.h>``, ``<stdio.h>``) are omitted:
    they come from the toolchain, not from Arduino libraries.

    Includes whose path contains a directory (e.g. ``<freertos/task.h>``) are omitted:
    those are resolved from the core / SDK include path, not by Arduino library name.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _INCLUDE_RE.finditer(text):
        raw = (m.group("q") or m.group("a") or "").strip()
        if not raw or _is_toolchain_std_dot_h_include(raw):
            continue
        if _is_multi_segment_include_path(raw):
            continue
        stem = Path(raw.replace("\\", "/")).stem
        if stem not in seen:
            seen.add(stem)
            out.append(stem)
    return out


def resolve_libraries_for_sketch(
    sketch_dir: Path,
    sketch_cpp_text: str,
    fqbn_arch: str,
    library_dirs: list[Path],
    *,
    platform_include_roots: list[Path] | None = None,
    resolution_notes: list[LibraryResolveNote] | None = None,
) -> list[Library]:
    """Pick libraries from sketch #includes, ``depends=``, and recursive library #includes.

    Headers found under ``platform_include_roots`` (core and, when applicable, variant)
    are treated as satisfied by the platform: no library is linked for that include
    token, and library stem index entries do not override those names.

    Transitive **library** selection scans each linked library's public headers
    (``.h`` / ``.hh`` / ``.hpp`` under the library tree, excluding ``examples/`` /
    ``tests/``, etc.). ``library.properties`` ``depends=`` is also honored. Pass
    ``resolution_notes`` for ``-v`` / ``-vv`` logging.
    """
    by_key = discover_libraries(library_dirs)
    platform_stems = _platform_header_stems(
        list(platform_include_roots) if platform_include_roots else []
    )
    stem_to_lib, stem_to_header = _header_stem_to_library(by_key, platform_stems)
    queue: deque[tuple[str, str]] = deque()
    queued_lower: set[str] = set()

    def enqueue(token: str, via: str) -> None:
        t = token.strip()
        if not t:
            return
        k = t.lower()
        if k not in queued_lower:
            queued_lower.add(k)
            queue.append((t, via))

    for h in includes_from_source(sketch_cpp_text):
        enqueue(h, 'sketch (preprocessed sketch.cpp): #include "{0}.h"'.format(h))
    for p in list_sketch_inos(sketch_dir):
        for h in includes_from_source(p.read_text(encoding="utf-8", errors="replace")):
            enqueue(h, f'sketch ({p.name}): #include "{h}.h"')

    selected: dict[str, Library] = {}

    while queue:
        token, via = queue.popleft()
        key = token.lower()
        if key in platform_stems:
            continue
        lib_from_key = by_key.get(key)
        lib = lib_from_key if lib_from_key is not None else stem_to_lib.get(key)
        if lib is None:
            continue
        if not _arch_matches(lib.architectures, fqbn_arch):
            continue
        lk = lib.name.lower()
        if lk in selected:
            continue
        selected[lk] = lib
        if resolution_notes is not None:
            pub: str | None = None
            if stem_to_lib.get(key) is lib:
                pub = stem_to_header.get(key)
            resolution_notes.append(
                LibraryResolveNote(
                    library_name=lib.name,
                    library_root=str(lib.root.resolve()),
                    include_token=token,
                    via=via,
                    public_header_relpath=pub,
                )
            )
        for h, h_via in _iter_transitive_include_enqueues_from_headers_only(lib):
            enqueue(h, h_via)
        for dep in lib.depends:
            d = dep.strip()
            if d:
                enqueue(
                    d,
                    f'library.properties depends= of "{lib.name}": {d}',
                )

    return list(selected.values())
