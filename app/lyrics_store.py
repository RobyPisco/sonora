"""Libreria locale dei testi: salva e richiama i testi in %APPDATA%/Sonora/testi.

Ogni testo è un semplice file .txt il cui nome è «Artista - Titolo» (ripulito
dai caratteri non validi per il filesystem). Nessun indice: la cartella È la
libreria, così i file restano leggibili/copiabili a mano.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import config

_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def store_dir() -> Path:
    d = config.config_dir() / "testi"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    """Nome file valido su Windows: via caratteri riservati e spazi doppi."""
    name = _INVALID_RE.sub(" ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    return name or "testo"


def save(name: str, text: str) -> Path:
    p = store_dir() / f"{safe_name(name)}.txt"
    p.write_text(text or "", encoding="utf-8")
    return p


def list_all() -> list[str]:
    return sorted((p.stem for p in store_dir().glob("*.txt")), key=str.lower)


def path_of(name: str) -> Path:
    return store_dir() / f"{safe_name(name)}.txt"


def load(name: str) -> str:
    return path_of(name).read_text(encoding="utf-8")


def delete(name: str) -> None:
    path_of(name).unlink(missing_ok=True)
