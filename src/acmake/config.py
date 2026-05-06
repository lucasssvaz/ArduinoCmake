"""Arduino-style directory resolution (aligned with Arduino CLI env vars)."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Arduino15"
    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "Arduino15"
        return Path.home() / "AppData" / "Local" / "Arduino15"
    return Path.home() / ".arduino15"


def _default_user_dir() -> Path:
    """Sketchbook default: Linux uses ``~/Arduino``; macOS/Windows use ``~/Documents/Arduino``."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Documents" / "Arduino"
    if system == "Windows":
        return Path.home() / "Documents" / "Arduino"
    return Path.home() / "Arduino"


@dataclass(frozen=True)
class ArduinoPaths:
    """Resolved Arduino data and user (sketchbook) directories."""

    data_dir: Path
    user_dir: Path

    @property
    def packages_dir(self) -> Path:
        return self.data_dir / "packages"

    @property
    def user_libraries_dir(self) -> Path:
        return self.user_dir / "libraries"

    @classmethod
    def from_env(
        cls,
        data_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> ArduinoPaths:
        dd = data_dir
        if dd is None:
            raw = os.environ.get("ARDUINO_DIRECTORIES_DATA")
            dd = Path(raw).expanduser() if raw else _default_data_dir()
        ud = user_dir
        if ud is None:
            raw = os.environ.get("ARDUINO_DIRECTORIES_USER")
            ud = Path(raw).expanduser() if raw else _default_user_dir()
        return cls(data_dir=dd.expanduser().resolve(), user_dir=ud.expanduser().resolve())
