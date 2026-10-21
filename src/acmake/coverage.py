"""Shared coverage-flag detection for cache selection and gcno collection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from acmake.command import split_recipe

_C_CPP_RECIPE_KEYS = ("recipe.c.o.pattern", "recipe.cpp.o.pattern")


def argv_has_coverage(
    argv: Sequence[str],
    *,
    working_directory: Path | None = None,
    _seen: set[Path] | None = None,
) -> bool:
    if any(
        token == "--coverage"
        or token == "-ftest-coverage"
        or token.startswith("-ftest-coverage=")
        for token in argv
    ):
        return True
    seen = _seen if _seen is not None else set()
    for token in argv:
        if not token.startswith("@") or len(token) == 1:
            continue
        path = Path(token[1:])
        if not path.is_absolute() and working_directory is not None:
            path = working_directory / path
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            nested = split_recipe(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if argv_has_coverage(
            nested, working_directory=working_directory, _seen=seen
        ):
            return True
    return False


def compile_recipes_have_coverage(
    expanded: Mapping[str, str], *, working_directory: Path | None = None
) -> bool:
    """Detect coverage in the effective expanded C/C++ compile recipes."""
    for key in _C_CPP_RECIPE_KEYS:
        recipe = str(expanded.get(key, "") or "").strip()
        if recipe and argv_has_coverage(
            split_recipe(recipe), working_directory=working_directory
        ):
            return True
    return False
