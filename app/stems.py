"""Motore di separazione stem (Demucs) in un ambiente Python isolato.

Perche' isolato: l'app gira su Python 3.14, dove PyTorch ha solo wheel CPU
(niente CUDA). Per usare la GPU il motore vive in un venv Python 3.12 con
torch CUDA + demucs, provisionato con `uv` e richiamato come subprocess.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from . import config, paths

# Modello demucs per modalita': 6 stem usa htdemucs_6s, gli altri il fine-tuned.
MODEL_FOR_MODE = {"2": "htdemucs_ft", "4": "htdemucs_ft", "6": "htdemucs_6s"}

# Modello Roformer (via audio-separator). BS-Roformer top per voce/strumentale.
ROFORMER_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"

# Roformer multi-stem: BS-Roformer-SW (jarredou) produce 6 stem in un passaggio
# solo, con gli strumenti (batteria/basso/chitarra/piano) ben sopra Demucs.
ROFORMER_SW_MODEL = "BS-Roformer-SW.ckpt"

# Nomi stem prodotti, per modalita' (per messaggi/verifica).
STEMS_FOR_MODE = {
    "2": ["vocals", "no_vocals"],
    "4": ["vocals", "drums", "bass", "other"],
    "6": ["vocals", "drums", "bass", "guitar", "piano", "other"],
    "rof": ["vocals", "no_vocals"],
    "rof6": ["vocals", "drums", "bass", "guitar", "piano", "other"],
    "sw6": ["vocals", "drums", "bass", "guitar", "piano", "other"],
}

# Modalita' Roformer note (separazione via audio-separator + eventuale cascade).
ROFORMER_MODES = ("rof", "rof6", "sw6")

LogCb = Callable[[str], None]
ProgCb = Callable[[float], None]
Cancel = Callable[[], bool]

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


# ---------------- percorsi motore ----------------

def _engine_base() -> Path:
    """Cartella base che contiene il motore.

    Predefinita: %APPDATA%/Sonora. Personalizzabile dalle impostazioni
    (`stem_engine_dir`) per installare il motore su un altro disco/cartella.
    """
    try:
        custom = (config.load().get("stem_engine_dir") or "").strip()
    except Exception:  # noqa: BLE001
        custom = ""
    if custom:
        return Path(custom)
    return config.config_dir()


def engine_dir() -> Path:
    return _engine_base() / "stem-engine"


def venv_python() -> Path:
    if os.name == "nt":
        return engine_dir() / ".venv" / "Scripts" / "python.exe"
    return engine_dir() / ".venv" / "bin" / "python"


def _marker() -> Path:
    return engine_dir() / "engine.ok"


def _torch_home() -> Path:
    return engine_dir() / "torch"


def engine_ready() -> bool:
    return _marker().exists() and venv_python().exists()


def separator_models_dir() -> Path:
    """Cartella dei modelli scaricati da audio-separator (Roformer ecc.)."""
    return engine_dir() / "separator-models"


def _roformer_marker() -> Path:
    return engine_dir() / "roformer.ok"


def roformer_ready() -> bool:
    """True se il motore base c'è e audio-separator è installato nel venv."""
    return engine_ready() and _roformer_marker().exists()


def _torch_index(gpu: bool) -> str:
    return ("https://download.pytorch.org/whl/cu124" if gpu
            else "https://download.pytorch.org/whl/cpu")


def _repair_torch(log_cb: LogCb, cancel: Cancel) -> bool:
    """Reinstalla torch+torchaudio come coppia COERENTE dallo stesso index.

    Serve perché installare audio-separator (che dipende da `torch>=2.3`) può tirare
    su da PyPI una torch più nuova in build **CPU**, scoordinata da torchaudio: il
    risultato è torchaudio che non si carica (ABI) e niente CUDA. Qui si forza la
    coppia giusta (CUDA se c'è la GPU), versione allineata.
    """
    gpu = has_nvidia()
    log_cb(f"Allineo torch/torchaudio ({'CUDA' if gpu else 'CPU'}, build coerente)…")
    rc = _stream([str(venv_python()), "-m", "pip", "install",
                  "torch", "torchaudio", "--index-url", _torch_index(gpu),
                  "--force-reinstall"],
                 log_cb, cancel)
    return rc == 0


def install_roformer(log_cb: LogCb, cancel: Cancel) -> bool:
    """Installa audio-separator (con il provider giusto) nel venv del motore.

    Presuppone il motore base già pronto. Idempotente. Il modello vero e proprio
    viene scaricato automaticamente da audio-separator alla prima separazione.
    """
    if roformer_ready():
        return True
    if not venv_python().exists():
        log_cb("Errore: motore base non pronto.")
        return False
    gpu = has_nvidia()
    pkg = "audio-separator[gpu]" if gpu else "audio-separator[cpu]"
    log_cb(f"Installo Roformer (audio-separator, {'GPU' if gpu else 'CPU'})… "
           "può richiedere alcuni minuti.")
    rc = _stream([str(venv_python()), "-m", "pip", "install", pkg],
                 log_cb, cancel)
    if rc == -1:
        log_cb("Annullato.")
        return False
    if rc != 0:
        log_cb(f"Installazione Roformer fallita (codice {rc}).")
        return False
    # audio-separator può aver sostituito torch con una build CPU/scoordinata da
    # torchaudio: ripristina la coppia coerente (e la CUDA) prima di dare l'ok.
    if not _repair_torch(log_cb, cancel):
        log_cb("Impossibile allineare torch/torchaudio dopo Roformer.")
        return False
    _roformer_marker().write_text("ok", encoding="utf-8")
    log_cb("Roformer pronto.")
    return True


def _env() -> dict[str, str]:
    e = dict(os.environ)
    # Il motore è un Python 3.12 (venv) lanciato dall'app. Quando l'app gira
    # "congelata" (PyInstaller) è un Python 3.14: se una qualunque variabile
    # inietta il suo runtime nel sys.path del venv, all'import di torch il child
    # carica per errore i .pyd/DLL 3.14 e crasha con
    # «Module use of python314.dll conflicts with this version of Python» (exit 1).
    # Rimuovi ogni possibile fonte di contaminazione e isola l'ambiente.
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE",
              "__PYVENV_LAUNCHER__"):
        e.pop(k, None)
    e["PYTHONNOUSERSITE"] = "1"
    # togli dal PATH la cartella del bundle PyInstaller (contiene DLL 3.14)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        mp = os.path.normcase(os.path.abspath(meipass))
        parts = [p for p in e.get("PATH", "").split(os.pathsep) if p]
        kept = [p for p in parts
                if not os.path.normcase(os.path.abspath(p)).startswith(mp)]
        e["PATH"] = os.pathsep.join(kept)
    # Assicura ffmpeg/ffprobe nel PATH del motore anche senza un download
    # precedente: audio_separator (roformer) li invoca per leggere/convertire
    # l'input e senza di essi fallisce con FileNotFoundError [WinError 2].
    # Va fatto DOPO lo strip di _MEIPASS (in frozen bin/ sta lì dentro): bin/
    # contiene solo eseguibili (ffmpeg/uv/rubberband), non DLL di Python 3.14.
    bin_d = paths.bin_dir()
    if (bin_d / "ffmpeg.exe").exists():
        e["PATH"] = str(bin_d) + os.pathsep + e.get("PATH", "")
    e["TORCH_HOME"] = str(_torch_home())          # contiene i checkpoint dei modelli
    e["UV_PYTHON_INSTALL_DIR"] = str(engine_dir() / "python")
    e["PYTHONUTF8"] = "1"
    return e


def _safe_cwd() -> str | None:
    """Working-dir sicura per i subprocess del motore.

    `python -m demucs` mette la cwd in testa a `sys.path`: se la cwd fosse la
    cartella del bundle PyInstaller (piena di .pyd di Python 3.14) il venv 3.12
    caricherebbe l'estensione sbagliata → crash all'import (exit 1). Forziamo la
    cartella del motore, che non contiene moduli Python top-level che possano
    fare ombra alla stdlib/demucs.
    """
    d = engine_dir()
    return str(d) if d.exists() else None


# ---------------- rilevamento GPU ----------------

def has_nvidia() -> bool:
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True,
                            text=True, timeout=8, creationflags=_NO_WINDOW)
        return r.returncode == 0 and "GPU" in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


# ---------------- esecuzione subprocess con stream + cancel ----------------

def _stream(cmd: list[str], on_text: Callable[[str], None], cancel: Cancel,
            extra_env: dict[str, str] | None = None) -> int:
    """Esegue cmd, streamma stdout(+stderr) a on_text, killabile via cancel.

    `extra_env` si somma all'ambiente isolato (es. CUDA_VISIBLE_DEVICES=-1
    per forzare la CPU). Ritorna il return code (o -1 se annullato).
    """
    env = _env()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=0, env=env, creationflags=_NO_WINDOW, cwd=_safe_cwd(),
    )
    buf = b""
    try:
        while True:
            if cancel():
                _kill(proc)
                return -1
            chunk = proc.stdout.read(256) if proc.stdout else b""
            if not chunk:
                if proc.poll() is not None:
                    break
                continue
            buf += chunk
            # demucs/uv usano \r per le barre di avanzamento
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for p in parts:
                if p.strip():
                    on_text(p.decode("utf-8", "replace"))
        if buf.strip():
            on_text(buf.decode("utf-8", "replace"))
        return proc.returncode or 0
    finally:
        if proc.poll() is None:
            _kill(proc)


def _kill(proc: subprocess.Popen) -> None:
    """Uccide il processo e i suoi figli (es. python/torch del motore)."""
    try:
        import psutil
        p = psutil.Process(proc.pid)
        for c in p.children(recursive=True):
            try:
                c.kill()
            except Exception:  # noqa: BLE001
                pass
        p.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


# ---------------- installazione motore ----------------

def _managed_py312() -> Path | None:
    """python.exe 3.12 concreto già scaricato da uv (la cartella REALE
    `cpython-3.12.NN-...`, non la junction `cpython-3.12-...`)."""
    pydir = engine_dir() / "python"
    if not pydir.exists():
        return None
    try:
        for d in sorted(pydir.glob("cpython-3.12.*"), reverse=True):
            exe = d / "python.exe"
            if exe.exists():
                return exe
    except OSError:
        pass
    return None


def _normalize_pyvenv_home(venv: Path, log_cb: LogCb | None = None) -> bool:
    """Riscrive `home` in pyvenv.cfg alla cartella REALE/concreta del Python 3.12.

    uv crea un alias minor-version come *junction* (`cpython-3.12-...` →
    `cpython-3.12.NN-...`). Con la mitigazione «redirection trust» di uv quella
    junction non è attraversabile e l'ispezione del venv fallisce con
    «untrusted mount point» (os error 448). Risolviamo puntando `home` direttamente
    alla cartella reale/concreta scaricata da uv, evitando la junction.
    """
    cfg = venv / "pyvenv.cfg"
    if not cfg.exists():
        return False
    exe = _managed_py312()
    if not exe:
        return False
    concrete_home = exe.parent
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    out: list[str] = []
    changed = False
    for ln in lines:
        if ln.split("=", 1)[0].strip().lower() == "home" and "=" in ln:
            cur = Path(ln.split("=", 1)[1].strip())
            if cur != concrete_home:
                ln = f"home = {concrete_home}"
                changed = True
        out.append(ln)
    if changed:
        try:
            cfg.write_text("\n".join(out) + "\n", encoding="utf-8")
            if log_cb:
                log_cb("Normalizzo il riferimento al Python (evito la junction → errore 448).")
        except OSError:
            return False
    return changed


def _check_venv_python_works() -> bool:
    """Verifica se l'eseguibile Python del venv si avvia correttamente."""
    try:
        r = subprocess.run([str(venv_python()), "-V"], capture_output=True,
                           creationflags=_NO_WINDOW, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _has_pip() -> bool:
    """Verifica se pip è installato nel venv."""
    try:
        r = subprocess.run([str(venv_python()), "-m", "pip", "--version"],
                           capture_output=True, creationflags=_NO_WINDOW, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _seed_pip(log_cb: LogCb, cancel: Cancel) -> bool:
    """Semina pip nel venv usando ensurepip."""
    log_cb("Semino pip nel venv (ensurepip)…")
    rc = _stream([str(venv_python()), "-m", "ensurepip", "--upgrade"], log_cb, cancel)
    if rc != 0:
        log_cb(f"Semina di pip fallita (codice {rc}).")
        return False
    return True


def _ensure_managed_py312(uv: str, log_cb: LogCb, cancel: Cancel) -> Path | None:
    """Garantisce che il Python 3.12 gestito da uv sia scaricato; ritorna l'exe concreto.

    uv può fallire sulla creazione del *link* minor-version (`cpython-3.12-...` →
    «untrusted mount point», os error 448), ma scarica comunque il Python REALE.
    Per questo NON ci interessa il codice d'uscita: dopo il download cerchiamo
    direttamente la cartella concreta `cpython-3.12.NN-...`.
    """
    exe = _managed_py312()
    if exe is not None:
        return exe
    log_cb("Scarico Python 3.12 (uv)…")
    rc = _stream([uv, "python", "install", "3.12"], log_cb, cancel)
    if rc == -1:
        return None
    # anche se il link minor è fallito (448), il Python concreto è ora presente
    return _managed_py312()


def _create_venv(uv: str, venv: Path, log_cb: LogCb, cancel: Cancel) -> bool:
    """Crea il venv 3.12 con lo stdlib `venv` del Python scaricato.

    Perché NON `uv venv`: su questo sistema uv non può creare il link minor-version
    (os error 448, mitigazione «redirection trust»). Il venv di uv produce allora un
    `python.exe` *trampolino* che, per avviare il Python base, deve attraversare quel
    link inesistente → «uv trampoline failed to spawn Python child process» (os error 2).
    Lo stdlib `venv` invece copia un `python.exe` CPython normale, che trova la base via
    `pyvenv.cfg` (percorso concreto diretto, nessuna junction) e include già pip.
    """
    if cancel():
        return False
    exe = _ensure_managed_py312(uv, log_cb, cancel)
    if exe is None:
        if not cancel():
            log_cb("Python 3.12 non disponibile dopo il download.")
        return False
    log_cb("Creo il venv col Python scaricato (stdlib venv, niente trampolino uv)…")
    shutil.rmtree(venv, ignore_errors=True)
    rc = _stream([str(exe), "-m", "venv", str(venv)], log_cb, cancel)
    if rc == -1:
        return False
    if rc != 0 or not venv_python().exists():
        log_cb(f"Creazione venv fallita (codice {rc}).")
        return False
    if not _check_venv_python_works():
        log_cb("Il Python del venv non si avvia.")
        return False
    # lo stdlib venv installa già pip via ensurepip; semina solo se mancasse
    if not _has_pip():
        return _seed_pip(log_cb, cancel)
    return True


def install_engine(log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> bool:
    """Provisiona venv 3.12 + torch (CUDA se GPU) + demucs. Idempotente.

    Ritorna True se il motore e' pronto.
    """
    uv = paths.uv_path()
    if not uv:
        log_cb("Errore: uv non trovato (bin/uv.exe).")
        return False
    edir = engine_dir()
    edir.mkdir(parents=True, exist_ok=True)
    _torch_home().mkdir(parents=True, exist_ok=True)
    venv = edir / ".venv"

    gpu = has_nvidia()
    torch_index = _torch_index(gpu)
    log_cb(f"GPU NVIDIA: {'sì (CUDA)' if gpu else 'no (CPU)'}")

    if not venv_python().exists() or not _check_venv_python_works():
        log_cb("Creo l'ambiente Python 3.12…")
        if not _create_venv(uv, venv, log_cb, cancel):
            if not cancel():
                log_cb("Impossibile creare l'ambiente Python 3.12.")
            else:
                log_cb("Annullato.")
            return False

    # Ripara/previene l'errore 448 ad ogni avvio (idempotente): normalizza il riferimento al Python
    _normalize_pyvenv_home(venv, log_cb)

    if not _has_pip():
        if not _seed_pip(log_cb, cancel):
            return False

    steps: list[tuple[str, list[str]]] = []
    steps.append((f"Installo PyTorch ({'CUDA' if gpu else 'CPU'}) — può richiedere alcuni minuti…",
                  [str(venv_python()), "-m", "pip", "install",
                   "torch", "torchaudio", "--index-url", torch_index]))
    steps.append(("Installo Demucs…",
                  [str(venv_python()), "-m", "pip", "install",
                   "demucs", "soundfile"]))
    steps.append(("Installo l'analisi (librosa)…",
                  [str(venv_python()), "-m", "pip", "install",
                   "librosa", "pyloudnorm"]))

    total = len(steps)
    for i, (msg, cmd) in enumerate(steps):
        if cancel():
            log_cb("Annullato.")
            return False
        log_cb(msg)
        progress_cb((i / total) * 100.0)
        rc = _stream(cmd, log_cb, cancel)
        if rc != 0:
            if rc == -1:
                log_cb("Annullato.")
            else:
                log_cb(f"Errore (codice {rc}) durante: {msg}")
            return False

    # verifica torch importabile; se fallisce (es. torch corrotto, "WinError 127"
    # su shm.dll), riprova UNA volta con reinstallazione pulita di torch — così
    # «Reinstalla» ripara davvero una build rotta senza azzerare tutto a mano.
    if not _verify_torch(log_cb, cancel):
        if cancel():
            log_cb("Annullato.")
            return False
        log_cb("Verifica fallita: reinstallo torch in modo pulito (build corrotta?)…")
        if not _force_reinstall_torch(gpu, log_cb, cancel) or not _verify_torch(log_cb, cancel):
            log_cb("Verifica motore fallita.")
            return False

    _marker().write_text("ok", encoding="utf-8")
    progress_cb(100.0)
    log_cb("Motore stem pronto.")
    return True


def _verify_torch(log_cb: LogCb, cancel: Cancel) -> bool:
    """True se torch+demucs si importano correttamente nel venv."""
    rc = _stream([str(venv_python()), "-c",
                  "import torch,demucs;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"],
                 log_cb, cancel)
    return rc == 0


def _force_reinstall_torch(gpu: bool, log_cb: LogCb, cancel: Cancel) -> bool:
    """Reinstalla torch+torchaudio da zero, ignorando la cache (wheel corrotta)."""
    rc = _stream([str(venv_python()), "-m", "pip", "install",
                  "torch", "torchaudio", "--index-url", _torch_index(gpu),
                  "--force-reinstall", "--no-cache-dir"],
                 log_cb, cancel)
    return rc == 0


# ---------------- disinstallazione motore ----------------

def _rmtree_robust(path: Path, log_cb: LogCb | None = None) -> bool:
    """Rimuove path in modo robusto su Windows (file read-only, junction di uv).

    Ritorna True se al termine la cartella non esiste più.
    """
    if not path.exists():
        return True

    def _on_error(func, p, _exc):  # noqa: ANN001
        # tipico: file di sola lettura nei wheel di torch → togli il flag e ritenta
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:  # noqa: BLE001
            pass

    try:
        shutil.rmtree(path, onerror=_on_error)
    except Exception:  # noqa: BLE001
        pass

    # fallback: rmdir di Windows gestisce bene le junction create da uv
    if path.exists() and os.name == "nt":
        try:
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)],
                           creationflags=_NO_WINDOW, timeout=120)
        except Exception:  # noqa: BLE001
            pass
    ok = not path.exists()
    if log_cb and not ok:
        log_cb("Alcuni file sono in uso: chiudi l'app/processi del motore e riprova.")
    return ok


def uninstall_engine(log_cb: LogCb | None = None) -> bool:
    """Rimuove completamente il motore stem (venv, torch, modelli, marker).

    Dopo, `engine_ready()` torna False: una nuova installazione riparte pulita.
    Utile quando la build di torch è corrotta o per liberare spazio (~3 GB).
    """
    edir = engine_dir()
    if log_cb:
        log_cb(f"Disinstallo il motore stem da: {edir}")
    ok = _rmtree_robust(edir, log_cb)
    if log_cb:
        log_cb("Motore disinstallato." if ok else "Disinstallazione non completata.")
    return ok


# ---------------- verifica / riparazione motore ----------------

def repair_engine(log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> bool:
    """Diagnostica il motore e ripara solo ciò che serve. Ritorna True se a posto.

    Scala dall'intervento più leggero al più pesante:
    1. venv assente / Python che non parte / pip mancante → installazione completa.
    2. torch non importabile (es. WinError 127 su shm.dll) → reinstallazione pulita
       del solo torch (~2.5 GB) senza riscaricare tutto il resto.
    3. tutto ok → riscrive solo il marker `engine.ok`.
    Evita di riscaricare i ~3 GB quando basta molto meno.
    """
    if not venv_python().exists():
        log_cb("Motore non installato: eseguo l'installazione completa…")
        return install_engine(log_cb, progress_cb, cancel)

    progress_cb(10.0)
    if not _check_venv_python_works():
        log_cb("Il Python del venv non si avvia: reinstallo il motore…")
        return install_engine(log_cb, progress_cb, cancel)

    if not _has_pip():
        log_cb("pip mancante nel venv: completo l'installazione…")
        return install_engine(log_cb, progress_cb, cancel)

    progress_cb(40.0)
    log_cb("Verifico l'import di torch e demucs…")
    if _verify_torch(log_cb, cancel):
        _marker().write_text("ok", encoding="utf-8")
        progress_cb(100.0)
        log_cb("Motore verificato: tutto a posto. ✓")
        return True
    if cancel():
        log_cb("Annullato.")
        return False

    log_cb("torch non si carica: reinstallazione pulita di torch…")
    progress_cb(60.0)
    gpu = has_nvidia()
    if _force_reinstall_torch(gpu, log_cb, cancel) and _verify_torch(log_cb, cancel):
        _marker().write_text("ok", encoding="utf-8")
        progress_cb(100.0)
        log_cb("Motore riparato. ✓")
        return True
    if cancel():
        log_cb("Annullato.")
        return False

    log_cb("Riparazione di torch non riuscita: provo l'installazione completa…")
    return install_engine(log_cb, progress_cb, cancel)


# ---------------- separazione ----------------

_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Modalità ensemble "qualità massima": combina due modelli prendendo da ognuno
# gli stem in cui è migliore. htdemucs_ft (fine-tuned) è superiore su
# voce/batteria/basso; htdemucs_6s aggiunge chitarra/piano.
ENSEMBLE_PICK = {
    "htdemucs_ft": ["vocals", "drums", "bass"],
    "htdemucs_6s": ["guitar", "piano", "other"],
}

# Cascade Roformer (rof6): la voce arriva da Roformer, gli strumenti da Demucs
# eseguito sullo strumentale (drums/bass dal fine-tuned, chitarra/piano/resto dal 6s).
ROF_PICK = {
    "htdemucs_ft": ["drums", "bass"],
    "htdemucs_6s": ["guitar", "piano", "other"],
}


def _roformer_script_path() -> str | None:
    """Trova roformer_script.py sia in dev sia in build (bundlato come data)."""
    candidates = [
        Path(__file__).with_name("roformer_script.py"),            # dev
        paths.base_dir() / "app_scripts" / "roformer_script.py",   # frozen
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _pick_voc_inst(folder: Path, ext: str) -> tuple[Path | None, Path | None]:
    """Individua i file voce e strumentale prodotti da Roformer nella cartella."""
    voc = folder / f"vocals{ext}"
    inst = folder / f"no_vocals{ext}"
    if voc.exists() and inst.exists():
        return voc, inst
    # fallback: riconosci dai nomi (audio-separator usa "(Vocals)"/"(Instrumental)")
    v = i = None
    for f in folder.glob(f"*{ext}"):
        low = f.name.lower()
        if "instrument" in low or "no_vocal" in low:
            i = f
        elif "vocal" in low:
            v = f
    return (voc if voc.exists() else v), (inst if inst.exists() else i)


def _pick_stem(folder: Path, stem: str, ext: str) -> Path | None:
    """Trova il file di uno stem nella cartella: nome esatto, altrimenti per
    parola chiave nel nome (audio-separator può usare nomi tipo «song (Drums)»)."""
    exact = folder / f"{stem}{ext}"
    if exact.exists():
        return exact
    for f in folder.glob(f"*{ext}"):
        low = f.name.lower()
        if stem in low and f"no_{stem}" not in low:
            return f
    return None


def _other_by_subtraction(inst: Path, parts: list[Path], out_path: Path) -> bool:
    """Scrive out_path = strumentale − somma(parts). Così, nella cascata rof6,
    vocals+drums+bass+guitar+piano+other ricompone di nuovo il mix.
    Allinea lunghezza e canali; ritorna False (→ fallback) se qualcosa manca o
    se il formato non è scrivibile con soundfile (es. mp3)."""
    if out_path.suffix.lower() == ".mp3":
        return False   # soundfile non codifica mp3
    try:
        import numpy as np
        import soundfile as sf
    except Exception:   # noqa: BLE001
        return False
    try:
        base, sr = sf.read(str(inst), dtype="float32", always_2d=True)
        datas = []
        for p in parts:
            if not p.exists():
                return False
            d, _sr = sf.read(str(p), dtype="float32", always_2d=True)
            datas.append(d)
        length = min([base.shape[0]] + [d.shape[0] for d in datas])
        ch = base.shape[1]

        def fit(a):   # noqa: ANN001, ANN202
            a = a[:length]
            if a.shape[1] == ch:
                return a
            if a.shape[1] == 1:
                return np.repeat(a, ch, axis=1)
            return a[:, :ch]

        acc = np.zeros((length, ch), dtype="float32")
        for d in datas:
            acc += fit(d)
        other = base[:length] - acc
        if out_path.suffix.lower() == ".wav":
            sf.write(str(out_path), other, sr, subtype="PCM_16")
        else:
            sf.write(str(out_path), other, sr)
        return True
    except Exception:   # noqa: BLE001
        return False


def _run_roformer(src: Path, model: str, out_format: str,
                  log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> Path:
    """Separa src col modello Roformer indicato. Ritorna la cartella di output.

    Come per demucs, su GPU con poca VRAM degrada gradualmente invece di
    fallire: prima il profilo pieno, poi segmenti più corti (profilo "low"
    dello script), infine la CPU (GPU nascosta via CUDA_VISIBLE_DEVICES)."""
    script = _roformer_script_path()
    if not script:
        raise RuntimeError("script Roformer non trovato")
    out_dir = engine_dir() / "_rof"
    models = separator_models_dir()
    models.mkdir(parents=True, exist_ok=True)

    if has_nvidia():
        attempts = [
            ("cuda", "full", None, ""),
            ("cuda", "low", None,
             "Poca memoria GPU: riprovo con segmenti più corti…"),
            ("cpu", "full", {"CUDA_VISIBLE_DEVICES": "-1"},
             "GPU insufficiente: ripiego sulla CPU (più lento ma affidabile)…"),
        ]
    else:
        attempts = [("cpu", "full", None, "")]

    tail: list[str] = []
    rc = 1
    for device, profile, extra_env, notice in attempts:
        if cancel():
            rc = -1
            break
        if notice:
            log_cb(notice)
        if out_dir.exists():              # via i file parziali del tentativo prima
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        tail = []
        log_cb(f"Separo «{src.stem}» — Roformer ({model}) su {device.upper()}…")

        def on_text(line: str, _tail: list[str] = tail) -> None:
            m = _PCT.search(line)
            if m:
                try:
                    progress_cb(float(m.group(1)))
                except ValueError:
                    pass
            else:
                # conserva le ultime righe non-progresso per diagnosticare i crash
                _tail.append(line)
                del _tail[:-15]

        rc = _stream([str(venv_python()), script, str(src), str(out_dir),
                      str(models), model, out_format, profile],
                     on_text, cancel, extra_env=extra_env)
        if rc in (0, -1):
            break
        # continua coi ripieghi solo se è davvero un problema di memoria/CUDA;
        # per altri errori insistere è inutile (mostra subito la causa vera)
        if not any(h in " ".join(tail).lower() for h in _OOM_HINTS):
            break

    if rc == -1:
        raise RuntimeError("annullato")
    if rc != 0:
        for line in tail[-6:]:            # porta il vero errore nel log
            log_cb(line)
        detail = _last_error_line(tail)
        raise RuntimeError(f"Roformer: {detail}" if detail
                           else f"Roformer uscito con codice {rc}")
    return out_dir


_OOM_HINTS = ("out of memory", "cuda error", "cublas", "cudnn", "cuda out",
              "not enough memory", "allocat")


def _last_error_line(lines: list[str]) -> str:
    """Miglior riga diagnostica dall'output catturato (ultima riga significativa,
    tipicamente il messaggio d'eccezione di demucs/torch)."""
    for line in reversed(lines):
        s = line.strip()
        if s and not s.startswith(("|", "#", "0%", "100%")):
            return s[:200]
    return ""


# Quanti modelli interni ha ogni "bag" demucs: ognuno stampa la propria barra
# tqdm 0-100%, quindi serve saperlo per rimappare il progresso su un'unica barra.
_BAG_SIZE = {"htdemucs_ft": 4, "htdemucs_6s": 1, "htdemucs": 1}


def _multipass_progress(progress_cb: ProgCb, passes: int) -> ProgCb:
    """Rimappa le N barre 0-100% consecutive di demucs (modelli del bag ×
    shifts) su un unico 0-100% monotono: quando la percentuale letta cala,
    è iniziata la passata successiva. Senza questo la barra della UI riparte
    da zero a ogni passata."""
    state = {"pass": 0, "last": 0.0, "best": -1.0}

    def cb(p: float) -> None:
        p = max(0.0, min(100.0, p))
        if p < state["last"] and state["pass"] < passes - 1:
            state["pass"] += 1
        state["last"] = p
        overall = (state["pass"] * 100.0 + p) / passes
        if overall > state["best"]:
            state["best"] = overall
            progress_cb(overall)

    return cb


def _run_demucs(src: Path, model: str, out_format: str, two_stems: bool,
                log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> Path:
    """Esegue demucs per un modello. Ritorna la cartella con gli stem prodotti."""
    gpu = has_nvidia()
    tmp_out = engine_dir() / "_out"
    out_model = tmp_out / model

    base = [str(venv_python()), "-m", "demucs", "-n", model, "-o", str(tmp_out),
            # più sovrapposizione = meno artefatti ai bordi dei segmenti
            "--overlap", "0.5"]
    if two_stems:
        base += ["--two-stems", "vocals"]
    if out_format == "flac":
        base += ["--flac"]
    elif out_format == "mp3":
        base += ["--mp3", "--mp3-bitrate", "320"]

    # Tentativi dal migliore (qualità/velocità) al più robusto (memoria). Su GPU
    # con poca VRAM (es. 6 GB condivisi col desktop) htdemucs va in "CUDA out of
    # memory": si degrada gradualmente e, come ultima spiaggia, si ripiega su CPU
    # (lento ma non tocca la VRAM) invece di fallire del tutto.
    #   --shifts media più passate sfasate (qualità, ~Nx tempo, solo GPU).
    #   --segment corto abbassa il picco di VRAM (htdemucs: max ~7.8s).
    if gpu:
        attempts = [
            ("cuda", ["-d", "cuda", "--shifts", "2"], ""),
            ("cuda", ["-d", "cuda", "--segment", "4"],
             "Poca memoria GPU: riprovo con segmenti più corti…"),
            ("cpu", ["-d", "cpu"],
             "GPU insufficiente: ripiego sulla CPU (più lento ma affidabile)…"),
        ]
    else:
        attempts = [("cpu", ["-d", "cpu"], "")]

    tail: list[str] = []
    rc = 1
    for device, extra, notice in attempts:
        if cancel():
            rc = -1
            break
        if notice:
            log_cb(notice)
        if out_model.exists():
            shutil.rmtree(out_model, ignore_errors=True)
        tail = []
        log_cb(f"Separo «{src.stem}» — {model} su {device.upper()}…")

        shifts = int(extra[extra.index("--shifts") + 1]) if "--shifts" in extra else 1
        prog = _multipass_progress(progress_cb, _BAG_SIZE.get(model, 1) * shifts)

        def on_text(line: str, _tail: list[str] = tail, _prog: ProgCb = prog) -> None:
            m = _PCT.search(line)
            if m:
                try:
                    _prog(float(m.group(1)))
                except ValueError:
                    pass
            else:
                # conserva le ultime righe non-progresso per diagnosticare i crash
                _tail.append(line)
                del _tail[:-15]

        rc = _stream(base + extra + [str(src)], on_text, cancel)
        if rc in (0, -1):
            break
        # continua coi ripieghi solo se è davvero un problema di memoria/CUDA;
        # per altri errori insistere è inutile (mostra subito la causa vera)
        if not any(h in " ".join(tail).lower() for h in _OOM_HINTS):
            break

    if rc == -1:
        raise RuntimeError("annullato")
    if rc != 0:
        for line in tail[-6:]:            # porta il vero errore nel log
            log_cb(line)
        detail = _last_error_line(tail)
        raise RuntimeError(f"demucs: {detail}" if detail
                           else f"demucs uscito con codice {rc}")

    produced = out_model / src.stem
    if not produced.exists():
        cand = list(out_model.glob("*")) if out_model.exists() else []
        produced = cand[0] if cand else produced
    if not produced.exists():
        raise RuntimeError("output demucs non trovato")
    return produced


def _step_progress(progress_cb: ProgCb, step: int, total: int) -> ProgCb:
    """Rimappa lo 0-100% di un passo sul totale dei passi (modalità multi-passo).

    Così la barra avanza in modo continuo (passo 2 di 3 = 33→66%) invece di
    ripartire da zero a ogni passo."""
    base = (step / total) * 100.0
    scale = 1.0 / total
    return lambda p: progress_cb(base + max(0.0, min(100.0, p)) * scale)


def separate(input_file: str, mode: str, out_format: str,
             log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> list[str]:
    """Separa input_file negli stem. Ritorna i path dei file prodotti.

    mode: "2" | "4" | "6" | "6hq" (ensemble Demucs qualità massima)
          | "rof" (Roformer voce/strumentale) | "rof6" (Roformer + cascade Demucs)
          | "sw6" (Roformer SW multi-stem: 6 stem in un passaggio).
    Output in `<cartella_sorgente>/<nome> - stems/`.
    """
    src = Path(input_file)
    if not src.exists():
        raise RuntimeError("file sorgente non trovato")

    # le modalità Roformer richiedono audio-separator nel venv: installalo al volo
    if mode in ROFORMER_MODES and not roformer_ready():
        log_cb("Preparo Roformer (solo la prima volta)…")
        if not install_roformer(log_cb, cancel):
            raise RuntimeError("Roformer non installato")

    tmp_out = engine_dir() / "_out"
    rof_out = engine_dir() / "_rof"
    for d in (tmp_out, rof_out):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    tmp_out.mkdir(parents=True, exist_ok=True)
    final_dir = src.parent / f"{src.stem} - stems"
    final_dir.mkdir(parents=True, exist_ok=True)
    ext = {"wav": ".wav", "flac": ".flac", "mp3": ".mp3"}.get(out_format, ".wav")

    def take(f: Path, name: str | None = None) -> None:
        if f and f.exists():
            dst = final_dir / (name or f.name)
            shutil.move(str(f), str(dst))
            out_files.append(str(dst))

    out_files: list[str] = []
    try:
        if mode == "6hq":
            # ensemble: due modelli, prende ogni stem dal migliore
            models = ["htdemucs_ft", "htdemucs_6s"]
            for i, model in enumerate(models):
                if cancel():
                    raise RuntimeError("annullato")
                log_cb(f"Qualità massima — passo {i+1}/2 ({model})")
                produced = _run_demucs(src, model, out_format, False,
                                       log_cb, _step_progress(progress_cb, i, 2),
                                       cancel)
                for stem in ENSEMBLE_PICK[model]:
                    take(produced / f"{stem}{ext}")
        elif mode == "sw6":
            # 6 stem in un passaggio solo col Roformer multi-stem (SW):
            # strumenti molto più puliti di Demucs, nessuna cascade
            log_cb("Roformer SW — 6 stem in un passaggio")
            rof = _run_roformer(src, ROFORMER_SW_MODEL, out_format,
                                log_cb, progress_cb, cancel)
            for stem in STEMS_FOR_MODE["sw6"]:
                take(_pick_stem(rof, stem, ext), f"{stem}{ext}")
        elif mode == "rof":
            # solo voce + strumentale via Roformer
            rof = _run_roformer(src, ROFORMER_MODEL, out_format,
                                log_cb, progress_cb, cancel)
            voc, inst = _pick_voc_inst(rof, ext)
            take(voc, f"vocals{ext}")
            take(inst, f"no_vocals{ext}")
        elif mode == "rof6":
            # voce da Roformer, strumenti da Demucs sullo strumentale (cascade)
            log_cb("Qualità massima — passo 1/3 (Roformer)")
            rof = _run_roformer(src, ROFORMER_MODEL, out_format,
                                log_cb, _step_progress(progress_cb, 0, 3), cancel)
            voc, inst = _pick_voc_inst(rof, ext)
            take(voc, f"vocals{ext}")
            if not inst or not inst.exists():
                raise RuntimeError("strumentale Roformer non prodotto")
            demucs_other: Path | None = None
            for i, model in enumerate(("htdemucs_ft", "htdemucs_6s"), start=2):
                if cancel():
                    raise RuntimeError("annullato")
                log_cb(f"Qualità massima — passo {i}/3 ({model} sullo strumentale)")
                produced = _run_demucs(inst, model, out_format, False,
                                       log_cb, _step_progress(progress_cb, i - 1, 3),
                                       cancel)
                for stem in ROF_PICK[model]:
                    if stem == "other":
                        # non lo prendiamo da Demucs: lo ricostruiamo per sottrazione
                        demucs_other = produced / f"other{ext}"
                        continue
                    take(produced / f"{stem}{ext}")
            # other = strumentale − (batteria+basso+chitarra+piano): così la somma
            # degli stem ricompone il mix. Se fallisce, ripiego sull'other di Demucs.
            other_dst = final_dir / f"other{ext}"
            inst_parts = [final_dir / f"{s}{ext}"
                          for s in ("drums", "bass", "guitar", "piano")]
            if _other_by_subtraction(inst, inst_parts, other_dst):
                out_files.append(str(other_dst))
            else:
                log_cb("Ricostruzione «other» non riuscita: uso quello di Demucs.")
                take(demucs_other, f"other{ext}")
        else:
            model = MODEL_FOR_MODE.get(mode, "htdemucs_6s")
            produced = _run_demucs(src, model, out_format, mode == "2",
                                   log_cb, progress_cb, cancel)
            for f in sorted(produced.iterdir()):
                if f.is_file():
                    take(f)
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)
        shutil.rmtree(rof_out, ignore_errors=True)

    if not out_files:
        raise RuntimeError("nessuno stem prodotto")
    log_cb(f"Fatto: {len(out_files)} stem in {final_dir}")
    return out_files


# ---------------- analisi (BPM, tonalità, LUFS, presenza) ----------------

def _analyze_script_path() -> str | None:
    """Trova analyze_script.py sia in dev sia in build (bundlato come data)."""
    candidates = [
        Path(__file__).with_name("analyze_script.py"),                  # dev
        paths.base_dir() / "app_scripts" / "analyze_script.py",         # frozen
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def analyze(folder: str, log_cb: LogCb, cancel: Cancel | None = None) -> dict:
    """Analizza una cartella di stem col motore. Salva e ritorna analysis.json."""
    import json
    script = _analyze_script_path()
    if not script:
        raise RuntimeError("script di analisi non trovato")
    if not venv_python().exists():
        raise RuntimeError("motore non installato")
    cap: list[str] = []

    def grab(line: str) -> None:
        cap.append(line)

    rc = _stream([str(venv_python()), script, folder], grab, cancel or (lambda: False))
    if rc != 0:
        raise RuntimeError(f"analisi fallita (codice {rc})")
    # l'ultima riga JSON valida
    data = None
    for line in reversed(cap):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(data, dict):
        raise RuntimeError("analisi: output non valido")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    try:
        (Path(folder) / "analysis.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    log_cb("Analisi completata.")
    return data


def stems_dir_for(input_file: str) -> Path:
    """Cartella di output stem attesa per un file sorgente: `<nome> - stems/`."""
    src = Path(input_file)
    return src.parent / f"{src.stem} - stems"


def already_separated(input_file: str) -> bool:
    """True se esiste già una cartella stem con almeno un file audio per questo file."""
    d = stems_dir_for(input_file)
    if not d.is_dir():
        return False
    exts = (".wav", ".flac", ".mp3")
    try:
        return any(p.is_file() and p.suffix.lower() in exts for p in d.iterdir())
    except OSError:
        return False


def load_analysis(folder: str) -> dict | None:
    import json
    p = Path(folder) / "analysis.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None
