"""Aggiornamento di yt-dlp a runtime.

Due scenari:
  * Da sorgente (non-frozen): esegue `pip install -U yt-dlp` sull'interprete corrente.
  * Da .exe PyInstaller (frozen): nell'exe non esistono pip ne' python, quindi
    si scarica lo **zipapp** ufficiale di yt-dlp in %APPDATA%/Sonora/yt-dlp.pyz
    e lo si antepone al sys.path all'avvio (apply_override) per scavalcare la
    versione bundled.

In entrambi i casi l'aggiornamento ha effetto dopo il riavvio dell'app.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from . import config

ZIPAPP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def override_path() -> Path:
    return config.config_dir() / "yt-dlp.pyz"


def pending_path() -> Path:
    """File scaricato in attesa di essere installato al prossimo avvio."""
    return config.config_dir() / "yt-dlp.pyz.new"


def _install_pending() -> None:
    """Se c'e' un update scaricato, installalo ora.

    Va chiamato all'avvio PRIMA di caricare lo zipapp: a quel punto il file
    override non e' ancora aperto da zipimport, quindi su Windows non e' lockato
    e la sostituzione riesce. Se per qualche motivo fallisce, il pending resta
    e si riprova al prossimo avvio.
    """
    pend = pending_path()
    if not pend.exists():
        return
    try:
        pend.replace(override_path())   # atomico, override non ancora caricato
    except OSError:
        pass


def apply_override() -> None:
    """Installa l'eventuale update e antepone lo zipapp al sys.path.

    DEVE essere chiamata PRIMA del primo `import yt_dlp` (cioe' prima di
    importare app.ui / app.downloader).
    """
    _install_pending()
    p = override_path()
    if p.exists():
        sp = str(p)
        if sp in sys.path:
            sys.path.remove(sp)
        sys.path.insert(0, sp)


def current_version() -> str:
    try:
        import yt_dlp  # import locale: rispetta l'eventuale override
        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return "?"


class UpdateWorker(QObject):
    """Esegue l'aggiornamento in un thread. Emette log e risultato finale."""

    log = Signal(str)
    finished = Signal(bool, str)   # ok, messaggio

    def run(self) -> None:
        try:
            if is_frozen():
                self._update_zipapp()
            else:
                self._update_pip()
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__)

    # --- sorgente: pip ---
    def _update_pip(self) -> None:
        self.log.emit("Eseguo: pip install -U yt-dlp …")
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        for line in out.splitlines()[-6:]:
            if line.strip():
                self.log.emit(line.rstrip())
        if proc.returncode == 0:
            self.finished.emit(True, "yt-dlp aggiornato. Riavvia l'app per applicare.")
        else:
            self.finished.emit(False, f"pip uscito con codice {proc.returncode}")

    # --- exe: zipapp ---
    def _update_zipapp(self) -> None:
        self.log.emit("Scarico l'ultima versione di yt-dlp…")
        pend = pending_path()
        pend.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(ZIPAPP_URL, headers={"User-Agent": "Sonora"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            data = resp.read()
        if not data or len(data) < 100_000:
            raise RuntimeError("download incompleto")
        # Scrive sul file pending: NON tocca lo zipapp eventualmente gia' caricato
        # (che su Windows sarebbe lockato). Lo swap avviene al prossimo avvio.
        fd, tmp_name = tempfile.mkstemp(suffix=".pyz", dir=str(pend.parent))
        os.close(fd)   # IMPORTANTE: l'handle aperto bloccherebbe replace() su Windows
        tmp = Path(tmp_name)
        try:
            tmp.write_bytes(data)
            tmp.replace(pend)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        mb = len(data) / 1024 / 1024
        self.log.emit(f"Scaricato {mb:.1f} MB ({pend.name})")
        self.finished.emit(True, "yt-dlp aggiornato. Riavvia l'app per applicare.")


def make_update_thread() -> tuple[QThread, UpdateWorker]:
    thread = QThread()
    worker = UpdateWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread, worker
