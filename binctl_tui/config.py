"""Secure on-disk configuration for binctl-tui."""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir
from tomli_w import dumps

CONFIG: dict[str, str] = {}
_profiles: dict[str, dict[str, str]] = {}


def config_directory() -> Path:
    """Return the platform-specific configuration directory."""
    directory = Path(user_config_dir("binctl-tui"))

    return directory


def config_path() -> Path:
    """Return the configuration file location."""
    path = config_directory() / "config.toml"

    return path


def _secure_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)

    if os.name == "posix":
        directory.chmod(0o700)


def _secure_file(path: Path) -> None:
    if os.name == "posix" and path.exists():
        path.chmod(0o600)


def _clean_profile(raw_profile: object) -> dict[str, str]:
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    fields = ("url", "token", "username", "password", "theme")
    cleaned = {
        field: value
        for field in fields
        if isinstance((value := profile.get(field)), str)
    }

    return cleaned


def load_config(profile: str = "default") -> dict[str, str]:
    """Load one profile and update the module-level configuration singleton."""
    global CONFIG, _profiles

    path = config_path()
    data: dict[str, Any] = {}

    if path.exists():
        _secure_directory(path.parent)
        _secure_file(path)
        with path.open("rb") as file:
            data = tomllib.load(file)

    raw_profiles = data.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ValueError("Configuration profiles must be a TOML table")

    _profiles = {
        name: _clean_profile(value)
        for name, value in raw_profiles.items()
        if isinstance(name, str) and isinstance(value, dict)
    }
    CONFIG = dict(_profiles.get(profile, {}))

    return dict(CONFIG)


def save_config(data: dict[str, str], profile: str = "default") -> dict[str, str]:
    """Atomically save a profile with permissions appropriate for credentials."""
    global CONFIG, _profiles

    directory = config_directory()
    path = config_path()
    cleaned = _clean_profile(data)
    serialized = dumps({"profiles": {**_profiles, profile: cleaned}})
    temporary_name = ""

    _secure_directory(directory)
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".config.",
            suffix=".toml",
            dir=directory,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            if os.name == "posix":
                os.fchmod(file.fileno(), 0o600)
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
        _secure_file(path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)

    _profiles = {**_profiles, profile: cleaned}
    CONFIG = dict(cleaned)

    return dict(CONFIG)
