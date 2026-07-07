"""Esporta diagnostica: zip sul Desktop con versione, GPU, stato motore,
impostazioni e log recenti.

Per il supporto clienti: l'utente preme «Esporta diagnostica» in
Impostazioni → Motore stem e allega lo zip alla richiesta di aiuto.
Nessun dato sensibile: il token di licenza NON viene incluso (solo lo stato
e l'ID dispositivo, lo stesso che il cliente comunica per ricevere il codice).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from . import __version__, config, logging_setup, paths, stems

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def desktop_dir() -> Path:
    """Desktop dell'utente, o home se non esiste."""
    d = Path.home() / "Desktop"
    return d if d.exists() else Path.home()


def _nvidia_smi() -> str:
    """Output di nvidia-smi, o spiegazione del perché manca."""
    try:
        out = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW)
        return (out.stdout or out.stderr).strip() or "(nessun output)"
    except FileNotFoundError:
        return "nvidia-smi non trovato: nessuna GPU NVIDIA o driver non installati."
    except Exception as exc:  # noqa: BLE001
        return f"nvidia-smi non eseguibile: {exc}"


def _disk_free(path: Path) -> str:
    try:
        usage = shutil.disk_usage(path)
        return f"{usage.free / 2**30:.1f} GB liberi su {usage.total / 2**30:.1f} GB"
    except OSError as exc:
        return f"non rilevabile ({exc})"


def _license_lines() -> list[str]:
    try:
        from . import licensing
        st = licensing.status()
        return [f"Licenza: {st.state} ({st.days_left} giorni rimanenti)",
                f"ID dispositivo: {licensing.machine_id()}"]
    except Exception as exc:  # noqa: BLE001
        return [f"Licenza: stato non rilevabile ({exc})"]


def _engine_lines() -> list[str]:
    eng = stems.engine_dir()
    lines = [
        f"Cartella motore: {eng}",
        f"Motore installato: {'sì' if stems.engine_ready() else 'no'}",
        f"Python venv presente: {'sì' if stems.venv_python().exists() else 'no'}",
        f"Roformer pronto: {'sì' if stems.roformer_ready() else 'no'}",
        f"Spazio disco motore: {_disk_free(eng if eng.exists() else Path.home())}",
    ]
    models = stems.separator_models_dir()
    if models.exists():
        n = sum(1 for _ in models.iterdir())
        lines.append(f"Modelli separator scaricati: {n} in {models}")
    pyvenv = eng / ".venv" / "pyvenv.cfg"
    if pyvenv.exists():
        try:
            cfg_txt = pyvenv.read_text(encoding="utf-8").strip()
            lines.append("pyvenv.cfg:\n  " + cfg_txt.replace("\n", "\n  "))
        except OSError:
            pass
    return lines


def _bin_lines() -> list[str]:
    d = paths.bin_dir()
    if not d.exists():
        return [f"bin/: assente ({d})"]
    names = sorted(p.name for p in d.iterdir())
    return [f"bin/ ({d}): " + (", ".join(names) if names else "vuota")]


def info_text(cfg: dict[str, Any]) -> str:
    """Report testuale della diagnostica (senza nvidia-smi, aggiunto a parte)."""
    lines = [
        f"Sonora {__version__} — diagnostica del "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"OS: {platform.platform()}",
        f"Python app: {platform.python_version()}"
        f" ({'build PyInstaller' if getattr(sys, 'frozen', False) else 'sviluppo'})",
        "",
        "--- Licenza ---",
        *_license_lines(),
        "",
        "--- Motore stem ---",
        *_engine_lines(),
        "",
        "--- Binari inclusi ---",
        *_bin_lines(),
        "",
        "--- Impostazioni ---",
        json.dumps(cfg, indent=2, ensure_ascii=False),
    ]
    return "\n".join(lines)


def export_zip(dest_dir: Path | None = None) -> Path:
    """Crea lo zip di diagnostica e ne restituisce il percorso.

    Contenuto: diagnostica.txt (report + nvidia-smi), settings.json e i log
    rotanti sonora.log*. Solleva OSError se lo zip non è scrivibile.
    """
    dest = Path(dest_dir) if dest_dir else desktop_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = dest / f"Sonora-diagnostica-{stamp}.zip"

    report = info_text(config.load()) + "\n\n--- nvidia-smi ---\n" + _nvidia_smi()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diagnostica.txt", report)
        settings = config.config_path()
        if settings.exists():
            zf.write(settings, "settings.json")
        log = logging_setup.log_path()
        for p in [log] + [log.parent / f"{log.name}.{i}" for i in (1, 2, 3)]:
            if p.exists():
                zf.write(p, p.name)
    return out
