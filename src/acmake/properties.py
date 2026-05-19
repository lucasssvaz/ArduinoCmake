"""Merge boards/platform properties and expand {token} placeholders."""

from __future__ import annotations

import re
from pathlib import Path

from acmake.parse_txt import load_properties_file, merge_local

# Match -DNAME="value" for gcc/cpp string macros (value must not contain raw ").
_DQ_DEFINE = re.compile(r'-D([A-Za-z0-9_]+)="([^"]*)"')

# Arduino cores often emit ``-DARDUINO_FQBN={build.fqbn}`` (no quotes). GCC then
# treats the value as preprocessor tokens, not a C string; wrap as a string literal.
_DEFAULT_STRING_MACRO_DEFINES: tuple[str, ...] = (
    "ARDUINO_FQBN",
    "ARDUINO_BOARD",
    "ARDUINO_VARIANT",
    "ARDUINO_HOST_OS",
)
_UNQUOTED_STRING_CPP_DEFINE = re.compile(
    "-D(" + "|".join(re.escape(n) for n in _DEFAULT_STRING_MACRO_DEFINES) + r')=(?!\")(\S+)'
)


def load_platform(platform_root: Path) -> dict[str, str]:
    p = platform_root / "platform.txt"
    props = load_properties_file(p)
    props = merge_local(props, platform_root / "platform.local.txt")
    return props


_MENU_LABEL_OS = frozenset({"linux", "windows", "macosx"})


def default_menu_options_for_board(board_id: str, boards_raw: dict[str, str]) -> dict[str, str]:
    """First menu option per group, in boards.txt order (matches Arduino IDE default).

    Keys counted as option labels: ``<board>.menu.<Group>.<OptionId>=`` or
    ``<board>.menu.<Group>.<OptionId>.<linux|windows|macosx>=`` when no plain
    two-segment label exists first (e.g. upload speed rows split by OS).
    """
    prefix = f"{board_id}.menu."
    first: dict[str, str] = {}
    for k in boards_raw:
        if not k.startswith(prefix):
            continue
        rest = k[len(prefix) :]
        parts = rest.split(".")
        if len(parts) == 2:
            group, opt = parts[0], parts[1]
        elif len(parts) == 3 and parts[2].lower() in _MENU_LABEL_OS:
            group, opt = parts[0], parts[1]
        else:
            continue
        first.setdefault(group, opt)
    return first


def merge_board_properties(
    board_id: str, boards_raw: dict[str, str], options: dict[str, str]
) -> dict[str, str]:
    """Turn boards.txt keys into board-relative property names (build.*, upload.*, ...)."""
    prefix = board_id + "."
    menu_root = f"{board_id}.menu."
    out: dict[str, str] = {}
    for k, v in boards_raw.items():
        if not k.startswith(prefix):
            continue
        rest = k[len(prefix) :]
        if rest.startswith("menu."):
            continue
        out[rest] = v
    for menu_key, option_val in options.items():
        # Full segment match after option value (e.g. 16M must not match 16MB).
        menu_prefix = re.compile(
            "^" + re.escape(f"{board_id}.menu.{menu_key}.{option_val}.")
        )
        for k, v in boards_raw.items():
            m = menu_prefix.match(k)
            if m:
                out[k[m.end() :]] = v
    return out


def load_boards(platform_root: Path) -> dict[str, str]:
    b = platform_root / "boards.txt"
    props = load_properties_file(b)
    props = merge_local(props, platform_root / "boards.local.txt")
    return props


def merge_platform_and_board(
    platform_props: dict[str, str], board_props: dict[str, str]
) -> dict[str, str]:
    merged = dict(platform_props)
    merged.update(board_props)
    return merged


def ensure_whitelisted_defines_use_cpp_string_literals(text: str) -> str:
    """Turn ``-DARDUINO_FQBN=vendor:arch:board`` into ``-DARDUINO_FQBN=\"...\"``.

    Only affects a fixed set of Arduino string macros (FQBN, board name, variant,
    host OS). Already-quoted ``-DNAME=\"...\"`` is left unchanged.
    """

    def repl(m: re.Match[str]) -> str:
        name, inner = m.group(1), m.group(2)
        return f'-D{name}="{inner}"'

    return _UNQUOTED_STRING_CPP_DEFINE.sub(repl, text)


def escape_cpp_string_in_d_define(text: str) -> str:
    r"""Escape inner text of ``-DNAME="..."`` for valid gcc ``-D`` string literals.

    After ``{tokens}`` expand, values like ``-DARDUINO_FQBN="{build.fqbn}"`` must
    remain a single preprocessor string: backslashes and double quotes inside the
    value are escaped for the C string literal form.
    """

    def repl(m: re.Match[str]) -> str:
        name, inner = m.group(1), m.group(2)
        escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
        return f'-D{name}="{escaped}"'

    return _DQ_DEFINE.sub(repl, text)


# C/C++ integer literal suffix (longest token first), case-insensitive via leading ``(?i)`` on patterns.
_INTEGRAL_LITERAL_SUFFIX = r"(?:ull|llu|ll|ul|lu|l|u)?"


def _is_integral_cpp_macro_value(inner: str) -> bool:
    """True if *inner* is a C integer literal (decimal or ``0x`` hex), optional ``u``/``l``/``ll`` suffixes."""
    if re.fullmatch(rf"(?i)-?(?:0|[1-9]\d*){_INTEGRAL_LITERAL_SUFFIX}", inner):
        return True
    if re.fullmatch(rf"(?i)-?0x[0-9a-f]+{_INTEGRAL_LITERAL_SUFFIX}", inner):
        return True
    return False


def unquote_integral_d_defines(text: str) -> str:
    """Rewrite quoted numeric ``-D`` values (incl. ``240000000L``, ``0x10UL``) to unquoted form."""

    def repl(m: re.Match[str]) -> str:
        name, inner = m.group(1), m.group(2)
        if _is_integral_cpp_macro_value(inner):
            return f"-D{name}={inner}"
        return m.group(0)

    return _DQ_DEFINE.sub(repl, text)


def normalize_cpp_d_string_macros_in_text(text: str) -> str:
    """Quote string ``-D`` flags, escape string bodies, then drop quotes for integral values."""
    s = ensure_whitelisted_defines_use_cpp_string_literals(text)
    s = escape_cpp_string_in_d_define(s)
    s = unquote_integral_d_defines(s)
    return s


def escape_dquoted_defines_in_properties(props: dict[str, str]) -> dict[str, str]:
    """Normalize Arduino string-style ``-D`` flags in every property value (see :func:`normalize_cpp_d_string_macros_in_text`)."""
    return {k: normalize_cpp_d_string_macros_in_text(v) for k, v in props.items()}


def collapse_duplicate_path_slashes(text: str) -> str:
    r"""Collapse ``esp32//tools`` → ``esp32/tools`` in file paths.

    Arduino recipes often join ``{runtime.platform.path}/`` (trailing slash) with
    ``/tools/...``, producing ``//``. GCC ``@`` response paths then break on some
    setups. Sequences after ``:`` (e.g. ``http://``, ``file://``) are left alone.
    """
    cur = text
    while True:
        nxt = re.sub(r"([^/:])/{2,}", r"\1/", cur)
        if nxt == cur:
            return nxt
        cur = nxt


def collapse_duplicate_path_slashes_in_properties(props: dict[str, str]) -> dict[str, str]:
    """Apply :func:`collapse_duplicate_path_slashes` to every property value."""
    return {k: collapse_duplicate_path_slashes(v) for k, v in props.items()}


# Match innermost ``{token}`` only (no ``{`` / ``}`` inside the token). Using this
# repeatedly expands nested Arduino placeholders like
# ``{tools.{build.tarch}-esp-elf-gcc.path}`` correctly; a greedy ``{([^}]+)}`` would
# stop at the first ``}`` and break the token name.
_INNER_BRACE = re.compile(r"\{[^{}]+\}")

# ``-DNAME={some.key}`` (single placeholder, no nested ``{`` inside) → string literal
# after expansion. Nested tokens like ``{tools.{build.tarch}-gcc.path}`` are skipped.
_D_VALUE_SINGLE_BRACE = re.compile(r"-D([A-Za-z0-9_]+)=\{([^{}]+)\}")


def quote_brace_placeholder_values_in_d_defines(text: str) -> str:
    """Rewrite ``-DNAME={key}`` as ``-DNAME="{key}"`` (literal braces kept for expansion).

    Platform flags often use ``-DARDUINO_FQBN={build.fqbn}`` without quotes. After this
    rewrite, placeholder expansion yields a proper ``gcc -D`` string literal value.
    """

    def repl(m: re.Match[str]) -> str:
        name, key = m.group(1), m.group(2)
        return f'-D{name}="{{{key}}}"'

    return _D_VALUE_SINGLE_BRACE.sub(repl, text)


def expand_string_placeholders(
    s: str,
    data: dict[str, str],
    *,
    max_rounds: int = 128,
) -> str:
    """Expand ``{key}`` in *s* by repeated innermost substitution (supports nesting)."""
    cur = quote_brace_placeholder_values_in_d_defines(s)
    for _ in range(max_rounds):

        def repl(m: re.Match[str]) -> str:
            key = m.group(0)[1:-1]
            return data.get(key, m.group(0))

        nxt = _INNER_BRACE.sub(repl, cur)
        nxt = quote_brace_placeholder_values_in_d_defines(nxt)
        if nxt == cur:
            break
        cur = nxt
    return cur


def expand_template(template: str, context: dict[str, str], max_rounds: int = 64) -> str:
    """Expand `{token}` placeholders in a single string using context lookups."""
    return expand_string_placeholders(template, dict(context), max_rounds=max_rounds)


def parse_build_property(spec: str) -> tuple[str, str]:
    """Parse one ``arduino-cli --build-property`` argument ``KEY=VALUE`` (first ``=`` separates)."""
    line = spec.strip()
    if not line or "=" not in line:
        raise ValueError(
            f"invalid --build-property {spec!r}: expected non-empty KEY=VALUE"
        )
    k, v = line.split("=", 1)
    k = k.strip()
    if not k:
        raise ValueError(f"invalid --build-property {spec!r}: empty key")
    return k, v


def merged_with_build_properties(
    merged: dict[str, str], property_specs: list[str] | None
) -> dict[str, str]:
    """Return a copy of *merged* with each ``KEY=VALUE`` from *property_specs* applied (last wins)."""
    if not property_specs:
        return merged
    out = dict(merged)
    for spec in property_specs:
        k, v = parse_build_property(spec)
        out[k] = v
    return out


_COMPILER_WARNING_LEVELS = frozenset({"none", "default", "more", "all"})


def normalize_compiler_warning_level(level: str) -> str:
    """Validate ``--warnings`` / ``compiler.warning_flags.*`` level names (arduino-cli)."""
    lv = (level or "").strip().lower()
    if lv not in _COMPILER_WARNING_LEVELS:
        allowed = ", ".join(sorted(_COMPILER_WARNING_LEVELS))
        raise ValueError(f"invalid compiler warning level {level!r} (expected one of: {allowed})")
    return lv


def apply_compiler_warning_level(expanded: dict[str, str], level: str) -> dict[str, str]:
    """Set ``compiler.warning_flags`` from ``compiler.warning_flags.<level>`` (arduino-cli ``--warnings``).

    Platforms define ``compiler.warning_flags`` plus ``.none``, ``.default``, ``.more``, ``.all``.
    If ``compiler.warning_flags.<level>`` is missing, the base ``compiler.warning_flags`` value is used.
    """
    lv = normalize_compiler_warning_level(level)
    key = f"compiler.warning_flags.{lv}"
    if key in expanded:
        v = (expanded.get(key) or "").strip()
    else:
        v = (expanded.get("compiler.warning_flags") or "").strip()
    out = dict(expanded)
    out["compiler.warning_flags"] = v
    return expand_properties(out)


def expand_properties(
    props: dict[str, str],
    extra: dict[str, str] | None = None,
    max_rounds: int = 64,
) -> dict[str, str]:
    """Resolve {key} references recursively. Unknown {x} left unchanged.

    ``-DNAME={token}`` forms are rewritten to ``-DNAME=\"{token}\"`` during
    placeholder expansion so platform variables expand as C string literals.
    """
    cur: dict[str, str] = {}
    for k, v in props.items():
        cur[k] = v
    if extra:
        for k, v in extra.items():
            cur[k] = v

    for _ in range(max_rounds):
        nxt = {k: expand_string_placeholders(v, cur, max_rounds=128) for k, v in cur.items()}
        changed = any(nxt.get(k) != cur.get(k) for k in nxt)
        cur = nxt
        if not changed:
            break
    return cur


_RUNTIME_OS_PROP_SUFFIXES: tuple[str, ...] = ("windows", "macosx", "linux")


def apply_runtime_os_property_overrides(props: dict[str, str]) -> dict[str, str]:
    """Resolve ``*.windows`` / ``*.macosx`` / ``*.linux`` into the base key (Arduino platform.txt).

    After this, ``recipe.hooks.prebuild.3.pattern`` on Windows uses the ``.pattern.windows``
    value (e.g. ``cmd /c …``) instead of the POSIX ``bash -c …`` line. Requires
    ``runtime.os`` in *props* (``windows`` / ``macosx`` / ``linux``). Removes suffixed
    keys so expansion and hook lookup see a single canonical name.
    """
    ros = (props.get("runtime.os") or "").strip().lower()
    if ros not in _RUNTIME_OS_PROP_SUFFIXES:
        return dict(props)
    suf = "." + ros
    suf_len = len(suf)
    out = dict(props)
    for k, v in list(props.items()):
        if len(k) > suf_len and k.lower().endswith(suf.lower()):
            base = k[:-suf_len]
            if base:
                out[base] = v
    for k in list(out.keys()):
        kl = k.lower()
        if any(kl.endswith("." + s) for s in _RUNTIME_OS_PROP_SUFFIXES):
            del out[k]
    return out


def inject_build_paths(
    expanded: dict[str, str],
    *,
    runtime_platform_path: str,
    build_path: str,
    build_project_name: str,
    sketch_path: str,
    runtime_ide_version: str = "10607",
    runtime_os: str | None = None,
    fqbn_string: str | None = None,
    fqbn_arch: str | None = None,
) -> dict[str, str]:
    """Inject ``build.path``, ``build.source.path``, ``runtime.platform.path``, etc.

    On **Windows** (``runtime.os`` / host is ``windows``), directory properties omit a
    forced trailing ``/``. Unix-style ``"{build.source.path}"/file`` patterns from
    ``platform.txt`` then expand like arduino-cli (``SetPath``), instead of producing
    ``...Sketch/"/file`` with a stray ``/`` before the closing quote.

    After injecting paths, :func:`apply_runtime_os_property_overrides` folds
    ``*.pattern.windows`` (etc.) into the base key so ESP32 hooks use ``cmd /c …`` on
    Windows instead of the POSIX ``bash -c …`` lines (matching arduino-cli).
    """
    import platform as pyplatform

    os_name = runtime_os or pyplatform.system().lower()
    if os_name == "darwin":
        ar_os = "macosx"
    elif os_name == "windows":
        ar_os = "windows"
    else:
        ar_os = "linux"

    core = expanded.get("build.core", "arduino")
    variant = (expanded.get("build.variant") or "").strip()
    plat = Path(runtime_platform_path).resolve()
    core_path = (plat / "cores" / core).resolve()
    if variant:
        variant_path = (plat / "variants" / variant).resolve()
    else:
        variant_path = plat

    sketch_resolved = str(Path(sketch_path).expanduser().resolve())
    build_resolved = str(Path(build_path).expanduser().resolve())
    hw_root = str(plat.parent.parent.resolve())

    # Unix Arduino properties use a trailing ``/`` on directory paths. On Windows, forcing
    # ``/`` after a ``\``-style path makes ESP32-style hooks break, e.g.
    # ``[ ! -f "{build.source.path}"/partitions.csv ]`` becomes ``...Secure/"/partitions...``
    # (adjacent quoted strings + ``/``). arduino-cli uses ``SetPath`` (no such trailing ``/``).
    if ar_os == "windows":
        sketch_abs = sketch_resolved.rstrip("/\\")
        build_abs = build_resolved.rstrip("/\\")
        plat_s = str(plat).rstrip("/\\")
        hw_s = hw_root.rstrip("/\\")
        core_s = str(core_path).rstrip("/\\")
        variant_s = str(variant_path).rstrip("/\\")
        sketch_path_prop = sketch_abs
    else:
        sketch_abs = sketch_resolved.rstrip("/") + "/"
        build_abs = build_resolved.rstrip("/") + "/"
        plat_s = str(plat).rstrip("/") + "/"
        hw_s = hw_root.rstrip("/") + "/"
        core_s = str(core_path).rstrip("/") + "/"
        variant_s = str(variant_path).rstrip("/") + "/"
        sketch_path_prop = sketch_resolved.rstrip("/")

    extra = {
        "runtime.platform.path": plat_s,
        "runtime.hardware.path": hw_s,
        "runtime.ide.version": runtime_ide_version,
        "runtime.os": ar_os,
        "build.path": build_abs,
        "build.project_name": build_project_name,
        "build.source.path": sketch_abs,
        # Platform spec (savehex / hooks): same folder as ``build.source.path``, no trailing slash.
        "sketch_path": sketch_path_prop,
        "build.core.path": core_s,
        "build.variant.path": variant_s,
    }
    if fqbn_string:
        extra["build.fqbn"] = fqbn_string
        extra["runtime.fqbn"] = fqbn_string
    if fqbn_arch:
        extra.setdefault("build.arch", fqbn_arch.upper())
    out = dict(expanded)
    out.update(extra)
    out = apply_runtime_os_property_overrides(out)
    return expand_properties(out)
