"""Small JSON config: device aliases and the default target."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    override = os.environ.get("ADBCTL_HOME")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata and os.name == "nt":
        return Path(appdata) / "adbctl"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "adbctl"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"default": None, "aliases": {}}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"default": None, "aliases": {}}
    data.setdefault("default", None)
    data.setdefault("aliases", {})
    return data


def save(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")


def set_default(target: str | None) -> None:
    data = load()
    data["default"] = target
    save(data)


def set_alias(name: str, target: str) -> None:
    data = load()
    data["aliases"][name] = target
    save(data)


def remove_alias(name: str) -> bool:
    data = load()
    existed = data["aliases"].pop(name, None) is not None
    save(data)
    return existed


def resolve_alias(name: str) -> str:
    """Translate an alias such as ``tv`` into a serial, if one is stored."""
    return load()["aliases"].get(name, name)
