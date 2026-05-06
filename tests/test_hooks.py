"""Tests for Arduino ``recipe.hooks.*.pattern`` execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from acmake.hooks import (
    collect_hook_commands,
    collect_ordered_hook_shell_commands,
    objcopy_post_recipe_hook_phases,
    objcopy_pre_recipe_hook_phases,
    ordered_objcopy_hook_phases,
    post_ninja_hook_phases,
    run_hook_phases,
)


def test_collect_hook_commands_numeric_order() -> None:
    expanded = {
        "recipe.hooks.prebuild.11.pattern": "third",
        "recipe.hooks.prebuild.1.pattern": "first",
        "recipe.hooks.prebuild.3.pattern": "second",
    }
    cmds = collect_hook_commands(expanded, "prebuild")
    assert [c[1] for c in cmds] == ["first", "second", "third"]


def test_objcopy_pre_post_split_for_ninja_embedding() -> None:
    expanded = {
        "recipe.hooks.objcopy.preobjcopy.1.pattern": "echo pre",
        "recipe.hooks.objcopy.postobjcopy.1.pattern": "echo post",
    }
    assert objcopy_pre_recipe_hook_phases(expanded) == ("objcopy.preobjcopy",)
    assert objcopy_post_recipe_hook_phases(expanded) == ("objcopy.postobjcopy",)
    cmds = collect_ordered_hook_shell_commands(
        expanded, objcopy_pre_recipe_hook_phases(expanded)
    )
    assert cmds == ["echo pre"]


def test_postobjcopy_runs_after_other_objcopy_hooks() -> None:
    expanded = {
        "recipe.hooks.objcopy.postobjcopy.1.pattern": "echo post",
        "recipe.hooks.objcopy.preobjcopy.1.pattern": "echo pre",
        "recipe.hooks.objcopy.custom.1.pattern": "echo mid",
    }
    assert ordered_objcopy_hook_phases(expanded) == (
        "objcopy.preobjcopy",
        "objcopy.custom",
        "objcopy.postobjcopy",
    )


def test_collect_hook_commands_dynamic_objcopy_subphase() -> None:
    expanded = {
        "recipe.hooks.objcopy.custom.2.pattern": "second",
        "recipe.hooks.objcopy.custom.1.pattern": "first",
    }
    cmds = collect_hook_commands(expanded, "objcopy.custom")
    assert [c[1] for c in cmds] == ["first", "second"]


def test_post_ninja_phases_exclude_objcopy_hooks_embedded_in_ninja() -> None:
    expanded = {
        "recipe.hooks.objcopy.postobjcopy.1.pattern": "true",
        "recipe.hooks.savehex.presavehex.1.pattern": "true",
    }
    phases = post_ninja_hook_phases(expanded)
    assert "objcopy.postobjcopy" not in phases
    assert "savehex.presavehex" not in phases


def test_post_ninja_export_includes_savehex_hooks() -> None:
    expanded = {"recipe.hooks.savehex.presavehex.1.pattern": "true"}
    phases = post_ninja_hook_phases(expanded, export_binaries=True)
    assert "savehex.presavehex" in phases
    assert "savehex.postsavehex" in phases
    assert phases.index("savehex.presavehex") > phases.index("core.postbuild")
    assert phases.index("postbuild") > phases.index("savehex.postsavehex")


def test_post_ninja_savehex_after_link_post_when_export() -> None:
    expanded = {"recipe.hooks.savehex.presavehex.1.pattern": "true"}
    phases = post_ninja_hook_phases(expanded, export_binaries=True)
    assert phases.index("savehex.presavehex") > phases.index("linking.postlink")


def test_run_hook_phases_prebuild(tmp_path: Path) -> None:
    marker = tmp_path / "hook_ran"
    expanded = {"recipe.hooks.prebuild.1.pattern": f"touch {marker}"}
    run_hook_phases(expanded, tmp_path, ("prebuild",))
    assert marker.is_file()


def test_hook_shell_argv_uses_bash_on_windows_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from subprocess import CompletedProcess

    import acmake.hooks as hooks

    recorded: list[tuple[tuple, dict]] = []

    def fake_run(*args, **kwargs):
        recorded.append((args, kwargs))
        return CompletedProcess(args, 0)

    monkeypatch.setattr(hooks.subprocess, "run", fake_run)
    monkeypatch.setattr(hooks.shutil, "which", lambda name: "/fake/bash" if name == "bash" else None)
    monkeypatch.setattr(hooks.os, "name", "nt")
    run_hook_phases(
        {
            "recipe.hooks.prebuild.1.pattern": (
                '/usr/bin/env bash -c "[ ! -f \\"/p/a\\" ] || echo ok"'
            )
        },
        tmp_path,
        ("prebuild",),
    )
    assert len(recorded) == 1
    argv0 = recorded[0][0][0]
    assert isinstance(argv0, list)
    assert argv0[:2] == ["/fake/bash", "-c"]


def test_cmd_hook_runs_payload_with_shell_true_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``cmd /c`` payload must use ``shell=True`` so ``list2cmdline`` does not corrupt quotes."""
    from subprocess import CompletedProcess

    import acmake.hooks as hooks

    recorded: list[tuple[tuple, dict]] = []

    def fake_run(*args, **kwargs):
        recorded.append((args, kwargs))
        return CompletedProcess(args, 0)

    monkeypatch.setattr(hooks.subprocess, "run", fake_run)
    monkeypatch.setattr(hooks.os, "name", "nt")
    monkeypatch.setattr(hooks.shutil, "which", lambda _n: "/bin/bash")
    run_hook_phases(
        {"recipe.hooks.prebuild.1.pattern": 'cmd /c if exist "C:\\a\\b" echo ok'},
        tmp_path,
        ("prebuild",),
    )
    assert len(recorded) == 1
    assert recorded[0][1].get("shell") is True
    assert recorded[0][0][0].startswith("if exist")


def test_hook_shell_argv_falls_back_to_cmd_on_windows_without_bash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from subprocess import CompletedProcess

    import acmake.hooks as hooks

    recorded: list[tuple[tuple, dict]] = []

    def fake_run(*args, **kwargs):
        recorded.append((args, kwargs))
        return CompletedProcess(args, 0)

    monkeypatch.setattr(hooks.subprocess, "run", fake_run)
    monkeypatch.setattr(hooks.shutil, "which", lambda _name: None)
    monkeypatch.setattr(hooks.os, "name", "nt")
    run_hook_phases({"recipe.hooks.prebuild.1.pattern": "echo x"}, tmp_path, ("prebuild",))
    assert recorded[0][1].get("shell") is True
    assert recorded[0][0] == ("echo x",)
