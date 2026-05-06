"""Split Arduino recipe command lines into argv lists."""

from __future__ import annotations

import re
import shlex

# ``shlex.split`` strips quotes used only for grouping, so
# ``-DARDUINO_FQBN="vendor:arch:board"`` becomes ``-DARDUINO_FQBN=vendor:arch:board``.
# GCC needs the literal ``"`` characters in that argv element for a string macro.
_D_STRING_DEFINE = re.compile(r'-D([A-Za-z0-9_]+)="([^"]*)"')
_PH = re.compile(r"^__ACMAKE_D_(\d+)__$")


def _strip_redundant_outer_double_quotes(s: str) -> str:
    """Strip one shell grouping layer from *argv0* when the interior has no ``"``.

    Used for CMake 4 (no quoted executable argv0) and for ``cache_compile`` when
    ``cmd.exe`` still passes ``"@rsp"``-style tokens. ``split_recipe`` uses POSIX
    ``shlex`` so normal recipe paths are already unquoted; this remains a safety net.
    """
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        if '"' not in inner:
            return inner
    return s


def split_recipe(cmd: str) -> list[str]:
    """Split an expanded recipe.pattern string into argv (POSIX rules).

    Double-quoted ``-DNAME="value"`` fragments are kept as single tokens with the
    quotes preserved (not consumed as shell word delimiters).
    """
    placeholders: list[str] = []

    def shield(m: re.Match[str]) -> str:
        placeholders.append(m.group(0))
        return f"__ACMAKE_D_{len(placeholders) - 1}__"

    shielded = _D_STRING_DEFINE.sub(shield, cmd)
    # Always POSIX rules: Arduino/GCC recipes use POSIX-style quotes. Windows
    # ``shlex.split(..., posix=False)`` splits ``-I"C:/My Documents/..."`` into
    # invalid fragments and drops core/variant/library include paths.
    parts = shlex.split(shielded, posix=True)
    out: list[str] = []
    for p in parts:
        m = _PH.match(p)
        if m:
            out.append(placeholders[int(m.group(1))])
        else:
            out.append(p)
    if out:
        out[0] = _strip_redundant_outer_double_quotes(out[0])
    return out
