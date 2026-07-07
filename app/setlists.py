"""Scalette (setlist): gruppi ordinati di cartelle stem da suonare in sequenza.

Persistenza in %APPDATA%/Sonora/setlists.json:
[{"name": "Prove martedì", "folders": ["C:/…/Brano - stems", …]}, …]
"""

from __future__ import annotations

import json
from typing import Any

from . import config


def _path():
    return config.config_dir() / "setlists.json"


def load() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for e in data:
        if isinstance(e, dict) and isinstance(e.get("name"), str):
            folders = [f for f in e.get("folders", []) if isinstance(f, str)]
            out.append({"name": e["name"], "folders": folders})
    return out


def save(setlists: list[dict[str, Any]]) -> None:
    try:
        _path().write_text(
            json.dumps(setlists, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def find(setlists: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for e in setlists:
        if e["name"] == name:
            return e
    return None


def create(setlists: list[dict[str, Any]], name: str) -> bool:
    """Aggiunge una scaletta vuota. False se il nome esiste già o è vuoto."""
    name = name.strip()
    if not name or find(setlists, name) is not None:
        return False
    setlists.append({"name": name, "folders": []})
    return True


def rename(setlists: list[dict[str, Any]], old: str, new: str) -> bool:
    new = new.strip()
    e = find(setlists, old)
    if e is None or not new or (new != old and find(setlists, new) is not None):
        return False
    e["name"] = new
    return True


def delete(setlists: list[dict[str, Any]], name: str) -> bool:
    e = find(setlists, name)
    if e is None:
        return False
    setlists.remove(e)
    return True


def add_folder(setlists: list[dict[str, Any]], name: str, folder: str) -> bool:
    """Aggiunge una cartella in coda alla scaletta. False se già presente."""
    e = find(setlists, name)
    if e is None or folder in e["folders"]:
        return False
    e["folders"].append(folder)
    return True


def remove_folder(setlists: list[dict[str, Any]], name: str, folder: str) -> bool:
    e = find(setlists, name)
    if e is None or folder not in e["folders"]:
        return False
    e["folders"].remove(folder)
    return True
