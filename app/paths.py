"""Risoluzione path: funziona sia in dev sia in build PyInstaller (onefile)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def base_dir() -> Path:
    """Cartella base risorse.

    In build PyInstaller onefile i data files vengono estratti in sys._MEIPASS.
    In dev e' la root del progetto (parent di app/).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def bin_dir() -> Path:
    return base_dir() / "bin"


def resources_dir() -> Path:
    return base_dir() / "resources"


def ffmpeg_dir() -> str | None:
    """Path della cartella che contiene ffmpeg/ffprobe, o None se assenti.

    yt-dlp accetta una directory come `ffmpeg_location`.
    Mette anche bin/ davanti al PATH come ulteriore garanzia per i postprocessor.
    """
    d = bin_dir()
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if (d / exe).exists():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        return str(d)
    return None


def resource(name: str) -> Path:
    return resources_dir() / name


def uv_path() -> str | None:
    """Path all'eseguibile uv bundlato in bin/, o None se assente."""
    exe = "uv.exe" if os.name == "nt" else "uv"
    p = bin_dir() / exe
    return str(p) if p.exists() else None


def default_download_dir() -> str:
    """Cartella download predefinita: ~/Downloads se esiste, altrimenti home."""
    home = Path.home()
    downloads = home / "Downloads"
    return str(downloads if downloads.exists() else home)
