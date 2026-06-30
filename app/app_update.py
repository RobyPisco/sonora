"""Controllo e installazione aggiornamenti dell'app via GitHub Releases.

Richiede un repository pubblicato (config `update_repo` = "owner/repo") in cui
caricare le release con allegato l'installer (`SonoraSetup-X.Y.Z.exe`). Senza
repo configurato la funzione è inerte e lo segnala.

Flusso "notifica + download":
  1. `check_latest()` interroga la release più recente e ne ricava versione +
     URL dell'asset installer.
  2. Se più nuova, l'app propone il download (`DownloadInstallerWorker`).
  3. Scaricato l'installer in `%APPDATA%/Sonora/updates/`, `launch_installer()`
     lo avvia e l'app si chiude per liberare i file (l'installer Inno Setup
     chiude comunque l'istanza in esecuzione, vedi CloseApplications nel .iss).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from . import __version__, config

# Nome dell'asset installer pubblicato nelle release (vedi installer/sonora.iss:
# OutputBaseFilename=SonoraSetup-{#AppVersion}).
_INSTALLER_RE = re.compile(r"SonoraSetup.*\.exe$", re.IGNORECASE)


def configured_repo() -> str:
    return (config.load().get("update_repo") or "").strip()


def auto_check_enabled() -> bool:
    return bool(config.load().get("auto_check_updates", True))


def _parse(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return _parse(remote) > _parse(local)


def _pick_installer_asset(assets: list) -> tuple[str, str, int]:
    """Dai `assets` di una release ricava (url, nome, dimensione) dell'installer.
    Ritorna ("", "", 0) se nessun asset corrisponde."""
    for a in assets or []:
        name = a.get("name") or ""
        if _INSTALLER_RE.search(name):
            return (a.get("browser_download_url") or "", name, int(a.get("size") or 0))
    return ("", "", 0)


def check_latest() -> dict | None:
    """Ritorna {version, url, newer, download_url, asset_name, asset_size}
    oppure None se non configurato/errore."""
    repo = configured_repo()
    if not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Sonora", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
            data = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("sonora.update").warning(
            "controllo aggiornamenti fallito (%s): %s", repo, exc)
        return None
    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag:
        return None
    dl_url, asset_name, asset_size = _pick_installer_asset(data.get("assets") or [])
    return {
        "version": tag,
        "url": data.get("html_url", f"https://github.com/{repo}/releases"),
        "newer": is_newer(tag, __version__),
        "download_url": dl_url,
        "asset_name": asset_name,
        "asset_size": asset_size,
    }


# ---------------- download + installazione ----------------

def updates_dir() -> Path:
    d = config.config_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def launch_installer(path: str) -> bool:
    """Avvia l'installer scaricato (processo separato) e ritorna True se partito.

    Il chiamante DEVE chiudere l'app subito dopo: l'installer sovrascrive i file
    in Program Files e, se l'exe è ancora in esecuzione, fallirebbe. L'installer
    Inno Setup è configurato con CloseApplications=yes come ulteriore garanzia.
    """
    p = Path(path)
    if not p.exists():
        return False
    try:
        if os.name == "nt":
            # avvio detached: l'installer sopravvive alla chiusura dell'app
            subprocess.Popen([str(p)], creationflags=0x00000008)  # DETACHED_PROCESS
        else:
            subprocess.Popen([str(p)])
        return True
    except Exception:  # noqa: BLE001
        return False


class CheckWorker(QObject):
    """Controlla in background la release più recente (no blocco UI)."""

    done = Signal(object)   # dict di check_latest() oppure None

    def run(self) -> None:
        try:
            self.done.emit(check_latest())
        except Exception:  # noqa: BLE001
            self.done.emit(None)


def make_check_thread() -> tuple[QThread, CheckWorker]:
    thread = QThread()
    worker = CheckWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(thread.quit)
    return thread, worker


class DownloadInstallerWorker(QObject):
    """Scarica l'installer dalla release in %APPDATA%/Sonora/updates/."""

    progress = Signal(float)        # 0..100
    log = Signal(str)
    finished = Signal(bool, str)    # ok, path_installer_oppure_errore

    def __init__(self, url: str, asset_name: str):
        super().__init__()
        self._url = url
        self._name = asset_name or "SonoraSetup.exe"

    def run(self) -> None:
        try:
            dest = updates_dir() / self._name
            tmp = dest.with_suffix(dest.suffix + ".part")
            self.log.emit(f"Scarico {self._name}…")
            req = urllib.request.Request(self._url, headers={"User-Agent": "Sonora"})
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            self.progress.emit(done / total * 100.0)
            if total and done < total * 0.99:
                raise RuntimeError("download incompleto")
            tmp.replace(dest)
            mb = done / 1024 / 1024
            self.log.emit(f"Scaricato {mb:.1f} MB.")
            self.finished.emit(True, str(dest))
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("sonora.update").exception(
                "download installer fallito: %s", self._url)
            msg = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            self.finished.emit(False, msg)


def make_download_thread(url: str, asset_name: str) -> tuple[QThread, DownloadInstallerWorker]:
    thread = QThread()
    worker = DownloadInstallerWorker(url, asset_name)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread, worker
