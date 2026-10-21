"""Concurrency-safe compile wrapper for shared object-cache artifacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if not __package__:  # Direct script: prefer this bundle over installed acmake.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acmake.cache_fs import artifact_lock, atomic_replace, same_directory_temp_path


def _strip_redundant_outer_double_quotes(s: str) -> str:
    """One layer of outer ``"…"`` when the interior has no ``"`` (see ``acmake.command``).

    Copied here so this file runs as ``python /path/to/cache_compile.py`` from the
    portable cache without ``acmake`` on ``PYTHONPATH`` (same rule as
    ``acmake.command._strip_redundant_outer_double_quotes`` — keep in sync).
    """
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        if '"' not in inner:
            return inner
    return s


def _replace_output_argument(
    argv: list[str], expected_output: Path, temporary_output: Path
) -> list[str] | None:
    """Redirect GCC-style ``-o`` output to a same-directory temporary path."""
    out = list(argv)
    expected = str(expected_output)
    found = False
    i = 0
    while i < len(out):
        token = out[i]
        if token in ("-o", "--output"):
            if i + 1 >= len(out):
                return None
            if token == "-o" or out[i + 1] == expected:
                out[i + 1] = str(temporary_output)
                found = True
            i += 2
            continue
        if token.startswith("-o") and len(token) > 2:
            if token[2:] == expected:
                out[i] = "-o" + str(temporary_output)
                found = True
        elif token.startswith("--output=") and token[len("--output=") :] == expected:
            out[i] = "--output=" + str(temporary_output)
            found = True
        i += 1
    return out if found else None


def _sidecar(path: Path, suffix: str) -> Path:
    if path.suffix == ".o":
        return path.with_suffix(suffix)
    return path.with_name(path.name + suffix)


def _is_current(obj: Path, src: Path) -> bool:
    return obj.is_file() and src.is_file()


def _remove_abandoned_temporaries(obj: Path) -> None:
    for path in obj.parent.glob(f".{obj.name}.tmp-*"):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def _compile_and_publish(
    obj: Path,
    compile_argv: list[str],
    temporary_output: Path,
) -> int:
    redirected = _replace_output_argument(compile_argv, obj, temporary_output)
    if redirected is None:
        print(
            f"acmake.cache_compile: compiler argv has no output argument for {obj}",
            file=sys.stderr,
        )
        return 2

    temporary_gcno = _sidecar(temporary_output, ".gcno")
    try:
        result = subprocess.run(redirected)
        rc = int(result.returncode) if result.returncode is not None else 1
        if rc != 0:
            return rc
        if not temporary_output.is_file():
            print(
                f"acmake.cache_compile: compiler produced no output: {temporary_output}",
                file=sys.stderr,
            )
            return 1

        # Generation paths are immutable; callers only publish when absent.
        atomic_replace(temporary_output, obj)
        return 0
    finally:
        temporary_output.unlink(missing_ok=True)
        temporary_gcno.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """``python -m acmake.cache_compile <object.o> <source> -- <compiler> [args...]``"""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4 or "--" not in args:
        print(
            "usage: python -m acmake.cache_compile <object.o> <source> "
            "-- <compiler> [args...]",
            file=sys.stderr,
        )
        return 2
    sep = args.index("--")
    obj = Path(args[0])
    src = Path(args[1])
    compile_argv = args[sep + 1 :]
    if not compile_argv:
        print("acmake.cache_compile: missing compiler argv after --", file=sys.stderr)
        return 2
    # Ninja + ``cmd.exe /C`` can leave grouped tokens as ``"@path"`` / ``"-I..."``;
    # GCC then treats them as literal filenames (``@`` response-file semantics are lost).
    compile_argv = [_strip_redundant_outer_double_quotes(a) for a in compile_argv]
    if _is_current(obj, src):
        return 0

    with artifact_lock(obj):
        # A competing process may have published while this process waited.
        if _is_current(obj, src):
            return 0
        _remove_abandoned_temporaries(obj)
        temporary_output = same_directory_temp_path(obj)
        return _compile_and_publish(obj, compile_argv, temporary_output)


if __name__ == "__main__":
    raise SystemExit(main())
