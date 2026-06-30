"""Logging su file rotante in %APPDATA%/Sonora/sonora.log.

Diagnostica sul campo: crash non gestiti, download/separazioni fallite, errori
auto-update. Da inizializzare una volta sola all'avvio (main.py), prima della
creazione della finestra.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from . import __version__, config

_CONFIGURED = False
_MAX_BYTES = 1_000_000   # ~1 MB per file
_BACKUPS = 3             # sonora.log + .1 .2 .3


def log_path() -> Path:
    return config.config_dir() / "sonora.log"


def setup() -> None:
    """Configura il root logger con handler su file rotante (+ console in dev).

    Idempotente: chiamate successive non aggiungono handler doppi.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    try:
        fh = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass   # se il file non è scrivibile, l'app prosegue senza log su file

    # In sviluppo (non-frozen) logga anche su console.
    if not getattr(sys, "frozen", False):
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    _install_excepthook()
    logging.getLogger("sonora").info("=== Sonora %s avviata ===", __version__)
    _CONFIGURED = True


def _install_excepthook() -> None:
    """Registra le eccezioni Python non gestite nel log (oltre al comportamento
    di default)."""
    prev = sys.excepthook

    def hook(exc_type, exc, tb):  # noqa: ANN001
        logging.getLogger("sonora").critical(
            "Eccezione non gestita", exc_info=(exc_type, exc, tb))
        prev(exc_type, exc, tb)

    sys.excepthook = hook
