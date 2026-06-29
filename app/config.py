"""Persistenza impostazioni in %APPDATA%/Sonora/settings.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import paths

APP_NAME = "Sonora"

DEFAULTS: dict[str, Any] = {
    "dest_dir": paths.default_download_dir(),
    "audio_format": "mp3",          # mp3 | wav
    "bitrate": "192",               # 128 | 192 | 320 (ignorato per wav)
    "filename_template": "%(title)s",
    "embed_metadata": True,
    "embed_thumbnail": True,
    "per_file_folder": True,
    "normalize": False,
    "clipboard_watch": False,
    "notify_end": True,
    "stem_mode": "6hq",     # 2 | 4 | 6 | 6hq (ensemble qualità max)
    "stem_format": "wav",   # wav | flac | mp3
    "update_repo": "",      # "owner/repo" GitHub per gli aggiornamenti dell'app
    "chord_notation": "latin",   # latin (Do Re Mi) | anglo (C D E)
}


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict[str, Any]) -> None:
    p = config_path()
    try:
        clean = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
        p.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
