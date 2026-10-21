"""Select immutable, content-addressed shared object-cache generations."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from acmake.command import split_recipe
from acmake.fingerprint_cache import ShardedFingerprintCache
from acmake.fqbn import path_component_from_label
from acmake.cache_prune import mark_cache_path_used
from acmake.libraries import (
    Library,
    _is_excluded_lib_scan_path,
)
from acmake.parse_txt import load_properties_file
from acmake.properties import expand_template
from acmake.sources import collect_library_sources

_SOURCE_SUFFIX = frozenset({".c", ".cc", ".cpp", ".cxx", ".ino", ".s"})
_COMPILE_RECIPE_KEYS = (
    "recipe.c.o.pattern",
    "recipe.cpp.o.pattern",
    "recipe.S.o.pattern",
)


def core_version_for_cache(expanded: dict[str, str], platform_root: Path) -> str:
    """Board package / core version string for cache partitioning."""
    for k in ("version", "runtime.platform.version", "platform.version"):
        v = (expanded.get(k) or "").strip()
        if v:
            return v
    raw = load_properties_file(platform_root / "platform.txt")
    v = (raw.get("version") or "").strip()
    if v:
        return v
    return (raw.get("name") or "unknown").strip() or "unknown"


def _read_bytes(path: Path, cache: dict[Path, bytes] | None = None) -> bytes:
    resolved = path.resolve()
    if cache is not None:
        if resolved not in cache:
            cache[resolved] = path.read_bytes()
        return cache[resolved]
    return path.read_bytes()


def _fingerprint_paths(
    paths: list[tuple[str, Path]],
    *,
    file_bytes_cache: dict[Path, bytes] | None = None,
    content_cache: ShardedFingerprintCache | None = None,
    fingerprint_root: Path | None = None,
    fingerprint_scope: str = "files",
) -> str:
    """Stable content digest for logical path names and file bytes."""
    h = hashlib.sha256()
    for logical_name, path in paths:
        h.update(logical_name.replace("\\", "/").encode("utf-8"))
        h.update(b"\0")
        digest = (
            content_cache.digest(
                path,
                root=fingerprint_root,
                scope=fingerprint_scope,
            )
            if content_cache is not None
            else hashlib.sha256(_read_bytes(path, file_bytes_cache)).hexdigest()
        )
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    if content_cache is not None and fingerprint_root is not None:
        content_cache.prune_to(
            fingerprint_root,
            fingerprint_scope,
            {path for _, path in paths},
        )
    return h.hexdigest()


def _platform_input_paths(
    core_path: Path,
    variant_path: Path,
    *,
    sources: bool,
) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for label, root in (("core", core_path), ("variant", variant_path)):
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            is_source = p.suffix.lower() in _SOURCE_SUFFIX
            if is_source != sources:
                continue
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = p.name
            out.append((f"{label}/{rel}", p))
    out.sort(key=lambda item: (item[0].lower(), item[0]))
    return out


def _platform_auxiliary_input_paths(
    core_path: Path, variant_path: Path
) -> list[tuple[str, Path]]:
    """All non-translation-unit files, including extensionless/.inc/.ipp/.tcc."""
    return _platform_input_paths(core_path, variant_path, sources=False)


def _platform_source_paths(
    core_path: Path, variant_path: Path
) -> list[tuple[str, Path]]:
    return _platform_input_paths(core_path, variant_path, sources=True)


def _library_cache_input_paths(lib: Library) -> list[Path]:
    """Exactly cover compiled sources plus regular files under effective include roots."""
    lib_root = lib.root.resolve()
    compiled = {path.resolve() for path in collect_library_sources(lib_root)}
    seen: set[Path] = set(compiled)
    out: list[Path] = list(compiled)
    for root in sorted(
        {path.resolve() for path in lib.include_roots},
        key=lambda path: str(path).lower(),
    ):
        if not root.is_dir():
            continue
        explicit_subroot = root != lib_root
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rp = p.resolve()
            if not explicit_subroot:
                try:
                    relative = rp.relative_to(lib_root)
                except ValueError:
                    relative = Path(rp.name)
                if _is_excluded_lib_scan_path(relative) and rp not in compiled:
                    continue
            if rp not in seen:
                seen.add(rp)
                out.append(p)
    out.sort(key=lambda x: (str(x.resolve()).lower(), str(x.resolve())))
    return out


def _fingerprint_library_cache_inputs(
    lib: Library,
    *,
    file_bytes_cache: dict[Path, bytes] | None = None,
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    """Hash install root, ``library.properties``, and **contents** of library sources/headers.

    Previously the stamp used header mtimes, so indexing tools or a new ``git clone``
    touching mtimes wiped cached ``.o`` files even when bytes were unchanged. Invalidation
    now follows source/header **content** plus metadata in ``library.properties`` (version,
    ``depends=``, ``includes=``, …) and the resolved install path (FQBN cache already scopes
    the board package / core version).
    """
    h = hashlib.sha256()
    h.update(str(lib.root.resolve()).encode("utf-8"))
    h.update(b"\0")
    prop = lib.root / "library.properties"
    if prop.is_file():
        prop_digest = (
            content_cache.digest(
                prop, root=lib.root, scope="library"
            )
            if content_cache is not None
            else hashlib.sha256(_read_bytes(prop, file_bytes_cache)).hexdigest()
        )
        h.update(prop_digest.encode("ascii"))
    h.update(b"\n")
    lib_root = lib.root.resolve()
    input_paths = _library_cache_input_paths(lib)
    for p in input_paths:
        try:
            rel = str(p.resolve().relative_to(lib_root)).replace("\\", "/")
        except ValueError:
            rel = p.name
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        digest = (
            content_cache.digest(p, root=lib.root, scope="library")
            if content_cache is not None
            else hashlib.sha256(_read_bytes(p, file_bytes_cache)).hexdigest()
        )
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    if content_cache is not None:
        scanned = {path.resolve() for path in input_paths}
        if prop.is_file():
            scanned.add(prop.resolve())
        content_cache.prune_to(lib.root, "library", scanned)
    return h.hexdigest()


def _sdk_config_input_paths(sdk_path: Path) -> list[Path]:
    """Config-affecting files under an ESP-style SDK (``compiler.sdk.path``).

    The generated ``sdkconfig`` plus every file under ``flags/`` (``defines``,
    ``includes``, ``c_flags``, ``cpp_flags``, ``S_flags``, …). The recipe bakes these
    straight onto every compile line via ``@flags/defines`` / ``@flags/*_flags`` and the
    ``sdkconfig.h`` regenerated from ``sdkconfig`` is ``#include``-d by the core and
    bundled libraries, so their bytes fully determine preprocessor config. They are small
    (tens of KB total) and change whenever the SDK is regenerated with a different Kconfig.
    The large precompiled ``lib/`` and ``ld/`` trees are intentionally excluded: they only
    affect the (uncached) final link, not the ``.o`` files this cache stores.
    """
    out: list[Path] = []
    sc = sdk_path / "sdkconfig"
    if sc.is_file():
        out.append(sc)
    flags = sdk_path / "flags"
    if flags.is_dir():
        for p in sorted(flags.iterdir(), key=lambda x: x.name.lower()):
            if p.is_file():
                out.append(p)
    return out


def sdk_config_fingerprint(expanded: Mapping[str, str]) -> str:
    """SHA-256 hex digest of the platform SDK config inputs, or ``""`` when there is none.

    Resolves ``compiler.sdk.path`` from *expanded* properties and hashes the **contents**
    of the config files under it (see ``_sdk_config_input_paths``), keyed by filename only
    so the digest is stable across install locations. Toolchains that do not define
    ``compiler.sdk.path`` (or whose SDK tree is absent) return ``""``, which leaves
    ``FQBN.object_cache_key`` unchanged for them.
    """
    raw = (expanded.get("compiler.sdk.path") or "").strip()
    if not raw:
        return ""
    sdk_path = Path(raw)
    h = hashlib.sha256()
    any_file = False
    for p in _sdk_config_input_paths(sdk_path):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        any_file = True
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(data)
        h.update(b"\n")
    if not any_file:
        return ""
    return h.hexdigest()


def _build_opt_bytes(build_dir: Path) -> bytes:
    """Raw ``build_opt.h`` bytes from *build_dir* (missing file is treated like empty).

    Only **contents** matter for fingerprints; mtimes and path are ignored, so two
    sketches with separate ``build/`` copies but identical bytes get the same digest.
    """
    p = build_dir / "build_opt.h"
    if not p.is_file():
        return b""
    try:
        return p.read_bytes()
    except OSError:
        return b""


def _platform_header_fingerprint(
    core_path: Path,
    variant_path: Path,
    *,
    file_bytes_cache: dict[Path, bytes] | None = None,
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    """Fingerprint all non-source core/variant compile-input candidates."""
    paths = _platform_auxiliary_input_paths(core_path, variant_path)
    h = hashlib.sha256()
    for label, root in (("core", core_path), ("variant", variant_path)):
        selected = [
            (logical, path)
            for logical, path in paths
            if logical.startswith(f"{label}/")
        ]
        h.update(
            _fingerprint_paths(
                selected,
                file_bytes_cache=file_bytes_cache,
                content_cache=content_cache,
                fingerprint_root=root,
                fingerprint_scope="platform-aux",
            ).encode("ascii")
        )
    return h.hexdigest()


def _platform_source_fingerprint(
    core_path: Path,
    variant_path: Path,
    *,
    file_bytes_cache: dict[Path, bytes] | None = None,
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    """Content fingerprint of core + variant translation units only."""
    paths = _platform_source_paths(core_path, variant_path)
    h = hashlib.sha256()
    for label, root in (("core", core_path), ("variant", variant_path)):
        selected = [
            (logical, path)
            for logical, path in paths
            if logical.startswith(f"{label}/")
        ]
        h.update(
            _fingerprint_paths(
                selected,
                file_bytes_cache=file_bytes_cache,
                content_cache=content_cache,
                fingerprint_root=root,
                fingerprint_scope="platform-source",
            ).encode("ascii")
        )
    return h.hexdigest()


def _build_opt_fingerprint(build_dir: Path) -> str:
    """SHA-256 hex digest of ``build_opt.h`` **contents** under *build_dir*.

    Uses ``read_bytes()`` only (no mtime). Two different sketch build directories with
    byte-identical ``build_opt.h`` produce the same fingerprint.
    """
    return hashlib.sha256(_build_opt_bytes(build_dir)).hexdigest()


def _replace_path_prefix(value: str, path: Path | None, marker: str) -> str:
    if path is None:
        return value
    candidates = {str(path), str(path).replace("\\", "/")}
    try:
        candidates.add(str(path.resolve()))
        candidates.add(str(path.resolve()).replace("\\", "/"))
    except OSError:
        pass
    out = value
    for candidate in sorted((c for c in candidates if c), key=len, reverse=True):
        out = out.replace(candidate, marker)
    return out


def _is_sketch_include(token: str, sketch_dir: Path | None) -> bool:
    if sketch_dir is None or not token.startswith("-I"):
        return False
    raw = token[2:].strip('"\'')
    try:
        return Path(raw).resolve() == sketch_dir.resolve()
    except OSError:
        return raw.replace("\\", "/").rstrip("/") == str(sketch_dir).replace(
            "\\", "/"
        ).rstrip("/")


def _response_file_inputs(
    argv: list[str],
    *,
    build_dir: Path | None,
    file_bytes_cache: dict[Path, bytes],
    seen: set[Path] | None = None,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Recursively fingerprint ``@response`` files and return their nested tokens."""
    fingerprints: list[tuple[str, str]] = []
    nested_tokens: list[str] = []
    seen = seen if seen is not None else set()
    for token in argv:
        if not token.startswith("@") or len(token) == 1:
            continue
        path = Path(token[1:])
        if not path.is_absolute() and build_dir is not None:
            path = build_dir / path
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        data = _read_bytes(path, file_bytes_cache)
        fingerprints.append(
            (
                _replace_path_prefix(
                    str(resolved), build_dir, "<BUILD>"
                ).replace("\\", "/"),
                hashlib.sha256(data).hexdigest(),
            )
        )
        tokens = split_recipe(data.decode("utf-8", errors="replace"))
        nested_tokens.extend(tokens)
        child_fingerprints, child_tokens = _response_file_inputs(
            tokens,
            build_dir=build_dir,
            file_bytes_cache=file_bytes_cache,
            seen=seen,
        )
        fingerprints.extend(child_fingerprints)
        nested_tokens.extend(child_tokens)
    fingerprints.sort()
    return fingerprints, nested_tokens


def _include_roots_from_tokens(
    tokens: list[str], *, build_dir: Path | None
) -> list[Path]:
    roots: list[Path] = []
    separate = {"-I", "-isystem", "-iquote", "-idirafter"}
    combined = ("-isystem", "-iquote", "-idirafter", "-I")
    i = 0
    while i < len(tokens):
        token = tokens[i]
        raw = ""
        if token in separate and i + 1 < len(tokens):
            raw = tokens[i + 1]
            i += 2
        else:
            for prefix in combined:
                if token.startswith(prefix) and len(token) > len(prefix):
                    raw = token[len(prefix) :]
                    break
            i += 1
        raw = raw.strip().strip('"\'')
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute() and build_dir is not None:
            path = build_dir / path
        if path.is_dir():
            roots.append(path.resolve())
    return roots


def _direct_compiler_inputs(
    tokens: list[str], *, build_dir: Path | None
) -> tuple[list[Path], list[Path]]:
    """Discover file-valued compiler arguments and tool/include directory inputs."""
    files: set[Path] = set()
    directories: set[Path] = set()
    separate_file = {"-include", "-imacros", "-specs", "--specs", "-fplugin"}
    separate_dir = {"-B", "--sysroot", "-isysroot"}
    joined_file = ("-include", "-imacros", "-specs=", "--specs=", "-fplugin=")
    joined_dir = ("-B", "--sysroot=", "-isysroot")

    def resolve(raw: str) -> Path:
        path = Path(raw.strip().strip('"\''))
        if not path.is_absolute() and build_dir is not None:
            path = build_dir / path
        return path

    i = 0
    while i < len(tokens):
        token = tokens[i]
        raw = ""
        directory = False
        if token in separate_file and i + 1 < len(tokens):
            raw = tokens[i + 1]
            i += 2
        elif token in separate_dir and i + 1 < len(tokens):
            raw = tokens[i + 1]
            directory = True
            i += 2
        else:
            for prefix in joined_file:
                if token.startswith(prefix) and len(token) > len(prefix):
                    raw = token[len(prefix) :]
                    break
            if not raw:
                for prefix in joined_dir:
                    if token.startswith(prefix) and len(token) > len(prefix):
                        raw = token[len(prefix) :]
                        directory = True
                        break
            i += 1
        if raw:
            path = resolve(raw)
            if directory and path.is_dir():
                directories.add(path.resolve())
            elif path.is_file():
                files.add(path.resolve())
            continue
        if token.startswith(("-", "@", "<")):
            continue
        path = resolve(token)
        if path.is_file():
            files.add(path.resolve())
    return (
        sorted(files, key=lambda path: str(path).lower()),
        sorted(directories, key=lambda path: str(path).lower()),
    )


def _path_is_covered(path: Path, covered_roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    for root in covered_roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _tree_fingerprint(
    root: Path,
    *,
    file_bytes_cache: dict[Path, bytes],
    tree_digest_cache: dict[Path, str],
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    resolved = root.resolve()
    if resolved in tree_digest_cache:
        return tree_digest_cache[resolved]
    paths: list[tuple[str, Path]] = []
    if resolved.is_dir():
        for path in resolved.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(resolved).as_posix()
            except ValueError:
                rel = path.name
            paths.append((rel, path))
    paths.sort(key=lambda item: (item[0].lower(), item[0]))
    digest = _fingerprint_paths(
        paths,
        file_bytes_cache=file_bytes_cache,
        content_cache=content_cache,
        fingerprint_root=resolved,
        fingerprint_scope="tree",
    )
    tree_digest_cache[resolved] = digest
    return digest


_COMPILER_ENV_KEYS = (
    "SOURCE_DATE_EPOCH",
    "ZERO_AR_DATE",
    "GCC_EXEC_PREFIX",
    "COMPILER_PATH",
    "LIBRARY_PATH",
    "CPATH",
    "C_INCLUDE_PATH",
    "CPLUS_INCLUDE_PATH",
    "OBJC_INCLUDE_PATH",
    "DEPENDENCIES_OUTPUT",
    "SUNPRO_DEPENDENCIES",
    "SDKROOT",
    "MACOSX_DEPLOYMENT_TARGET",
    "RC_ARCHS",
    "PATH",
    "PYTHONPATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)

_COMPILER_ENV_PATH_KEYS = frozenset(
    {
        "GCC_EXEC_PREFIX",
        "COMPILER_PATH",
        "LIBRARY_PATH",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "OBJC_INCLUDE_PATH",
        "SDKROOT",
        "PYTHONPATH",
    }
)


def _environment_compile_inputs() -> tuple[list[tuple[str, str]], list[Path]]:
    values: list[tuple[str, str]] = []
    roots: list[Path] = []
    for key in _COMPILER_ENV_KEYS:
        value = os.environ.get(key, "")
        values.append((key, value))
        if key in _COMPILER_ENV_PATH_KEYS:
            for raw in value.split(os.pathsep):
                if raw and Path(raw).is_dir():
                    roots.append(Path(raw).resolve())
    return values, roots


def _tool_identity(
    executable: str,
    *,
    file_bytes_cache: dict[Path, bytes] | None = None,
    content_cache: ShardedFingerprintCache | None = None,
) -> tuple[str, str]:
    raw = executable.strip().strip('"')
    path = Path(raw)
    if not path.is_file():
        found = shutil.which(raw)
        if found:
            path = Path(found)
    if not path.is_file():
        return (raw.replace("\\", "/"), "<missing>")
    resolved = Path(os.path.realpath(path))
    digest = (
        content_cache.digest(resolved)
        if content_cache is not None
        else hashlib.sha256(_read_bytes(resolved, file_bytes_cache)).hexdigest()
    )
    return (
        str(resolved).replace("\\", "/"),
        digest,
    )


def _normalized_compile_commands(
    expanded: Mapping[str, str],
    *,
    includes: str,
    build_dir: Path | None,
    sketch_dir: Path | None,
    add_core_define: bool,
    tool_identity_cache: dict[str, tuple[str, str]] | None = None,
    file_bytes_cache: dict[Path, bytes] | None = None,
    tree_digest_cache: dict[Path, str] | None = None,
    covered_input_roots: tuple[Path, ...] = (),
    content_cache: ShardedFingerprintCache | None = None,
) -> tuple[
    list[list[str]],
    list[tuple[str, str]],
    list[tuple[str, str]],
    list[tuple[str, str]],
    list[tuple[str, str]],
]:
    """Return effective compiler argv with volatile output/dep/build paths normalized."""
    commands: list[list[str]] = []
    responses: list[tuple[str, str]] = []
    include_inputs: list[tuple[str, str]] = []
    direct_inputs: list[tuple[str, str]] = []
    tools: dict[str, tuple[str, str]] = {}
    tool_identity_cache = tool_identity_cache if tool_identity_cache is not None else {}
    file_bytes_cache = file_bytes_cache if file_bytes_cache is not None else {}
    tree_digest_cache = tree_digest_cache if tree_digest_cache is not None else {}

    def tool_identity(raw: str) -> tuple[str, str]:
        if raw not in tool_identity_cache:
            tool_identity_cache[raw] = _tool_identity(
                raw,
                file_bytes_cache=file_bytes_cache,
                content_cache=content_cache,
            )
        return tool_identity_cache[raw]

    for key in _COMPILE_RECIPE_KEYS:
        template = expanded.get(key, "")
        if not template.strip():
            continue
        context = dict(expanded)
        context["source_file"] = "<SOURCE>"
        context["object_file"] = "<OUTPUT>"
        context["includes"] = includes
        argv = split_recipe(expand_template(template, context))
        if not argv:
            continue
        response_inputs, response_tokens = _response_file_inputs(
            argv,
            build_dir=build_dir,
            file_bytes_cache=file_bytes_cache,
        )
        responses.extend(response_inputs)
        include_roots = _include_roots_from_tokens(
            [*argv, *response_tokens], build_dir=build_dir
        )
        for root in include_roots:
            if _path_is_covered(root, covered_input_roots):
                continue
            include_inputs.append(
                (
                    str(root).replace("\\", "/"),
                    _tree_fingerprint(
                        root,
                        file_bytes_cache=file_bytes_cache,
                        tree_digest_cache=tree_digest_cache,
                        content_cache=content_cache,
                    ),
                )
            )
        direct_files, direct_directories = _direct_compiler_inputs(
            [*argv, *response_tokens], build_dir=build_dir
        )
        for path in direct_files:
            digest = (
                content_cache.digest(path)
                if content_cache is not None
                else hashlib.sha256(
                    _read_bytes(path, file_bytes_cache)
                ).hexdigest()
            )
            direct_inputs.append((str(path).replace("\\", "/"), digest))
        for root in direct_directories:
            if _path_is_covered(root, covered_input_roots):
                continue
            direct_inputs.append(
                (
                    str(root).replace("\\", "/"),
                    _tree_fingerprint(
                        root,
                        file_bytes_cache=file_bytes_cache,
                        tree_digest_cache=tree_digest_cache,
                        content_cache=content_cache,
                    ),
                )
            )
        tools[argv[0]] = tool_identity(argv[0])
        for token in argv[1:]:
            raw = token.strip().strip('"')
            if not raw or raw.startswith(("-", "@", "<")):
                continue
            candidate = Path(raw)
            if candidate.is_file() and (
                os.access(candidate, os.X_OK)
                or candidate.suffix.lower() in (".exe", ".bat", ".cmd")
            ):
                tools[raw] = tool_identity(raw)
        if add_core_define:
            argv.insert(1, "-DARDUINO_CORE_BUILD")
        normalized: list[str] = []
        i = 0
        while i < len(argv):
            token = argv[i]
            if _is_sketch_include(token, sketch_dir):
                i += 1
                continue
            if token == "-MF" and i + 1 < len(argv):
                normalized.extend(("-MF", "<DEPFILE>"))
                i += 2
                continue
            if token.startswith("-MF") and len(token) > 3:
                normalized.append("-MF<DEPFILE>")
                i += 1
                continue
            token = _replace_path_prefix(token, build_dir, "<BUILD>")
            normalized.append(token.replace("\\", "/"))
            i += 1
        commands.append(normalized)
    return (
        commands,
        sorted(set(responses)),
        sorted(tools.values()),
        sorted(set(include_inputs)),
        sorted(set(direct_inputs)),
    )


def _platform_config_fingerprint(
    platform_root: Path | None,
    *,
    file_bytes_cache: dict[Path, bytes] | None = None,
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    if platform_root is None:
        return hashlib.sha256(b"").hexdigest()
    inputs: list[tuple[str, Path]] = []
    for name in (
        "platform.txt",
        "platform.local.txt",
        "boards.txt",
        "boards.local.txt",
    ):
        path = platform_root / name
        if path.is_file():
            inputs.append((name, path))
    return _fingerprint_paths(
        inputs,
        file_bytes_cache=file_bytes_cache,
        content_cache=content_cache,
        fingerprint_root=platform_root,
        fingerprint_scope="platform-config",
    )


def _compile_context_fingerprint(
    expanded: Mapping[str, str] | None,
    *,
    includes: str,
    platform_root: Path | None,
    build_dir: Path | None,
    sketch_dir: Path | None,
    scope: str,
    tool_identity_cache: dict[str, tuple[str, str]] | None = None,
    file_bytes_cache: dict[Path, bytes] | None = None,
    tree_digest_cache: dict[Path, str] | None = None,
    covered_input_roots: tuple[Path, ...] = (),
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    """Hash normalized effective commands, config files, response files and compilers."""
    if expanded is None:
        expanded = {}
    tool_identity_cache = tool_identity_cache if tool_identity_cache is not None else {}
    file_bytes_cache = file_bytes_cache if file_bytes_cache is not None else {}
    tree_digest_cache = tree_digest_cache if tree_digest_cache is not None else {}
    variants = [False, True] if scope == "platform" else [False]
    h = hashlib.sha256()
    h.update(scope.encode("ascii"))
    h.update(b"\0")
    h.update(
        _platform_config_fingerprint(
            platform_root,
            file_bytes_cache=file_bytes_cache,
            content_cache=content_cache,
        ).encode("ascii")
    )
    if scope == "library-platform":
        # Library-specific commands, environment, tools, include roots, and
        # direct inputs are keyed below per dependency closure. Keeping them
        # out of this shared header/config scope prevents unrelated libraries
        # from coupling each other's generations.
        return h.hexdigest()
    environment, environment_roots = _environment_compile_inputs()
    h.update(repr(environment).encode("utf-8"))
    for root in sorted(set(environment_roots), key=lambda path: str(path).lower()):
        if _path_is_covered(root, covered_input_roots):
            continue
        h.update(str(root).encode("utf-8"))
        h.update(
            _tree_fingerprint(
                root,
                file_bytes_cache=file_bytes_cache,
                tree_digest_cache=tree_digest_cache,
                content_cache=content_cache,
            ).encode("ascii")
        )
    if scope == "platform":
        ar_raw = (
            str(expanded.get("compiler.path", ""))
            + str(expanded.get("compiler.ar.cmd", "ar"))
        )
        ar_executable = expand_template(ar_raw, dict(expanded)).strip().strip('"')
        if ar_executable not in tool_identity_cache:
            tool_identity_cache[ar_executable] = _tool_identity(
                ar_executable,
                file_bytes_cache=file_bytes_cache,
                content_cache=content_cache,
            )
        h.update(
            repr(
                ("archive", tool_identity_cache[ar_executable], "rcs")
            ).encode("utf-8")
        )
        h.update(b"\0")
    for add_core_define in variants:
        (
            commands,
            responses,
            tools,
            include_inputs,
            direct_inputs,
        ) = _normalized_compile_commands(
            expanded,
            includes=includes,
            build_dir=build_dir,
            sketch_dir=sketch_dir,
            add_core_define=add_core_define,
            tool_identity_cache=tool_identity_cache,
            file_bytes_cache=file_bytes_cache,
            tree_digest_cache=tree_digest_cache,
            covered_input_roots=covered_input_roots,
            content_cache=content_cache,
        )
        for group in (
            commands,
            responses,
            tools,
            include_inputs,
            direct_inputs,
        ):
            h.update(repr(group).encode("utf-8"))
            h.update(b"\0")
    return h.hexdigest()


def _library_bundle_path(cache_root: Path, lib: Library) -> Path:
    """Match ``acmake.build._library_bundle_dir`` (avoid import cycle)."""
    h = hashlib.sha1(str(lib.root.resolve()).encode()).hexdigest()[:12]
    lab = path_component_from_label(lib.name)
    return cache_root / "lib" / f"{lab}_{h}"


def _library_bundle_cache_stamp(lib: Library, build_dir: Path) -> str:
    """Content generation for one library plus ``build_opt`` bytes.

    The FQBN bucket already contains the build-opt digest. Keeping it in the
    library generation preserves the prior helper's semantics for direct callers.
    """
    lib_fp = _fingerprint_library_cache_inputs(lib)
    bo_fp = _build_opt_fingerprint(build_dir)
    return hashlib.sha256(f"{lib_fp}\0{bo_fp}".encode("ascii")).hexdigest()


def _library_dependency_fingerprint(
    libraries: list[Library],
    *,
    file_bytes_cache: dict[Path, bytes],
    library_digest_cache: dict[Path, str],
    content_cache: ShardedFingerprintCache | None = None,
) -> str:
    h = hashlib.sha256()
    for lib in sorted(libraries, key=lambda item: str(item.root.resolve()).lower()):
        root = lib.root.resolve()
        h.update(str(root).encode("utf-8"))
        h.update(b"\0")
        if root not in library_digest_cache:
            library_digest_cache[root] = _fingerprint_library_cache_inputs(
                lib,
                file_bytes_cache=file_bytes_cache,
                content_cache=content_cache,
            )
        h.update(library_digest_cache[root].encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


@dataclass(frozen=True)
class ObjectCacheGenerations:
    """Selected immutable directories inside an existing FQBN cache bucket."""

    bucket_dir: Path
    platform_fingerprint: str
    platform_dir: Path
    library_platform_fingerprint: str
    library_dirs: Mapping[Path, Path]

    def library_dir(self, lib: Library) -> Path:
        return self.library_dirs[lib.root.resolve()]


def maybe_refresh_object_cache(
    cache_root: Path,
    *,
    build_dir: Path,
    core_path: Path,
    variant_path: Path,
    libraries: list[Library],
    expanded: Mapping[str, str] | None = None,
    platform_root: Path | None = None,
    sketch_dir: Path | None = None,
    platform_includes: str = "",
    library_includes: Mapping[Path, str] | None = None,
    library_dependencies: Mapping[Path, list[Library]] | None = None,
) -> ObjectCacheGenerations:
    """Select immutable platform and library generations without deleting artifacts.

    ``cache_root`` remains the established FQBN/build-option/SDK bucket. Platform
    source/header bytes plus normalized commands/config/toolchain select the core
    generation. Libraries use a separate platform-header/config identity, then
    their own normalized command and transitive dependency contents. Existing
    builds continue using their directories while unchanged inputs reuse paths.
    """
    cache_root.mkdir(parents=True, exist_ok=True)
    mark_cache_path_used(cache_root)
    content_cache = ShardedFingerprintCache(
        cache_root / ".acmake_fingerprints"
    )
    tool_identity_cache: dict[str, tuple[str, str]] = {}
    file_bytes_cache: dict[Path, bytes] = {}
    tree_digest_cache: dict[Path, str] = {}
    library_digest_cache: dict[Path, str] = {}
    platform_covered_roots = tuple(
        sorted(
            {core_path.resolve(), variant_path.resolve()},
            key=lambda path: str(path).lower(),
        )
    )
    header_fingerprint = _platform_header_fingerprint(
        core_path,
        variant_path,
        file_bytes_cache=file_bytes_cache,
        content_cache=content_cache,
    )
    source_fingerprint = _platform_source_fingerprint(
        core_path,
        variant_path,
        file_bytes_cache=file_bytes_cache,
        content_cache=content_cache,
    )
    platform_context = _compile_context_fingerprint(
        expanded,
        includes=platform_includes,
        platform_root=platform_root,
        build_dir=build_dir,
        sketch_dir=sketch_dir,
        scope="platform",
        tool_identity_cache=tool_identity_cache,
        file_bytes_cache=file_bytes_cache,
        tree_digest_cache=tree_digest_cache,
        covered_input_roots=platform_covered_roots,
        content_cache=content_cache,
    )
    platform_fingerprint = hashlib.sha256(
        (
            f"{core_path.resolve()}\0{variant_path.resolve()}\0"
            f"{header_fingerprint}\0{source_fingerprint}\0{platform_context}"
        ).encode("utf-8")
    ).hexdigest()
    platform_dir = cache_root / "core_generations" / platform_fingerprint
    (platform_dir / "core" / "o").mkdir(parents=True, exist_ok=True)
    (platform_dir / "variant" / "o").mkdir(parents=True, exist_ok=True)
    mark_cache_path_used(platform_dir)

    library_platform_context = _compile_context_fingerprint(
        expanded,
        includes=platform_includes,
        platform_root=platform_root,
        build_dir=build_dir,
        sketch_dir=sketch_dir,
        scope="library-platform",
        tool_identity_cache=tool_identity_cache,
        file_bytes_cache=file_bytes_cache,
        tree_digest_cache=tree_digest_cache,
        covered_input_roots=platform_covered_roots,
        content_cache=content_cache,
    )
    library_platform_fingerprint = hashlib.sha256(
        f"{header_fingerprint}\0{library_platform_context}".encode("ascii")
    ).hexdigest()
    library_platform_dir = (
        cache_root / "library_generations" / library_platform_fingerprint
    )
    library_dirs: dict[Path, Path] = {}
    build_opt_fingerprint = _build_opt_fingerprint(build_dir)
    library_includes = library_includes or {}
    library_dependencies = library_dependencies or {}
    for lib in libraries:
        root = lib.root.resolve()
        stable_bundle = _library_bundle_path(library_platform_dir, lib)
        dependencies = library_dependencies.get(root, [lib])
        dependency_covered_roots: set[Path] = set(platform_covered_roots)
        for dependency in dependencies:
            dependency_covered_roots.add(dependency.root.resolve())
            dependency_covered_roots.update(
                path.resolve() for path in dependency.include_roots
            )
        dependency_fingerprint = _library_dependency_fingerprint(
            dependencies,
            file_bytes_cache=file_bytes_cache,
            library_digest_cache=library_digest_cache,
            content_cache=content_cache,
        )
        command_fingerprint = _compile_context_fingerprint(
            expanded,
            includes=library_includes.get(root, platform_includes),
            platform_root=platform_root,
            build_dir=build_dir,
            sketch_dir=sketch_dir,
            scope="library",
            tool_identity_cache=tool_identity_cache,
            file_bytes_cache=file_bytes_cache,
            tree_digest_cache=tree_digest_cache,
            covered_input_roots=tuple(
                sorted(
                    dependency_covered_roots,
                    key=lambda path: str(path).lower(),
                )
            ),
            content_cache=content_cache,
        )
        library_fingerprint = hashlib.sha256(
            (
                f"{build_opt_fingerprint}\0"
                f"{dependency_fingerprint}\0{command_fingerprint}"
            ).encode("ascii")
        ).hexdigest()
        generation = stable_bundle / "generations" / library_fingerprint
        (generation / "o").mkdir(parents=True, exist_ok=True)
        mark_cache_path_used(generation)
        library_dirs[root] = generation

    mark_cache_path_used(library_platform_dir)
    content_cache.flush()
    return ObjectCacheGenerations(
        bucket_dir=cache_root,
        platform_fingerprint=platform_fingerprint,
        platform_dir=platform_dir,
        library_platform_fingerprint=library_platform_fingerprint,
        library_dirs=library_dirs,
    )


def clear_entire_object_cache(temp_parent: Path | None = None) -> Path:
    """Remove ``<temp>/acmake_objcache``. Returns the path removed or that would be removed."""
    import tempfile

    base = Path(temp_parent or tempfile.gettempdir()) / "acmake_objcache"
    if base.is_dir():
        shutil.rmtree(base)
    return base
