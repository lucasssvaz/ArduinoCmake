"""Default Arduino directory layout by OS."""

from pathlib import Path

import pytest

from acmake.config import _default_user_dir


def test_default_user_dir_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("acmake.config.platform.system", lambda: "Linux")
    assert _default_user_dir() == Path.home() / "Arduino"


def test_default_user_dir_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("acmake.config.platform.system", lambda: "Darwin")
    assert _default_user_dir() == Path.home() / "Documents" / "Arduino"


def test_default_user_dir_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("acmake.config.platform.system", lambda: "Windows")
    assert _default_user_dir() == Path.home() / "Documents" / "Arduino"
