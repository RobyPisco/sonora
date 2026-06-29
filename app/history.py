"""Cronologia download persistente in %APPDATA%/Sonora/history.json."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from . import config

MAX_ENTRIES = 200


def _path():
    return config.config_dir() / "history.json"


def load() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def add(title: str, url: str, audio_format: str, filepath: str) -> None:
    """Aggiunge una voce in cima alla cronologia (dedup per filepath/url)."""
    entries = load()
    key = filepath or url
    entries = [e for e in entries if (e.get("filepath") or e.get("url")) != key]
    entries.insert(0, {
        "title": title,
        "url": url,
        "format": audio_format,
        "filepath": filepath,
        "ts": int(time.time()),
    })
    del entries[MAX_ENTRIES:]
    _save(entries)


def stem_recents(limit: int = 12) -> list[dict[str, Any]]:
    """Voci di cronologia che puntano a una cartella di stem esistente, dalla più
    recente, dedup per cartella. Per la 'Recenti' del mixer (apri stem in 1 click)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for e in load():
        fp = e.get("filepath") or ""
        if not fp or fp in seen or not os.path.isdir(fp):
            continue
        seen.add(fp)
        out.append(e)
        if len(out) >= limit:
            break
    return out


def clear() -> None:
    _save([])


def _save(entries: list[dict[str, Any]]) -> None:
    try:
        _path().write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def format_time(ts: Any) -> str:
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(int(ts)))
    except (TypeError, ValueError):
        return ""
