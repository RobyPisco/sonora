"""Motore di separazione stem (Demucs) in un ambiente Python isolato.

Perche' isolato: l'app gira su Python 3.14, dove PyTorch ha solo wheel CPU
(niente CUDA). Per usare la GPU il motore vive in un venv Python 3.12 con
torch CUDA + demucs, provisionato con `uv` e richiamato come subprocess.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from . import config, paths

# Modello demucs per modalita': 6 stem usa htdemucs_6s, gli altri il fine-tuned.
MODEL_FOR_MODE = {"2": "htdemucs_ft", "4": "htdemucs_ft", "6": "htdemucs_6s"}

# Modello Roformer (via audio-separator). BS-Roformer top per voce/strumentale.
ROFORMER_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"

# Nomi stem prodotti, per modalita' (per messaggi/verifica).
STEMS_FOR_MODE = {
    "2": ["vocals", "no_vocals"],
    "4": ["vocals", "drums", "bass", "other"],
    "6": ["vocals", "drums", "bass", "guitar", "piano", "other"],
    "rof": ["vocals", "no_vocals"],
    "rof6": ["vocals", "drums", "bass", "guitar", "piano", "other"],
}

# Modalita' Roformer note (separazione via audio-separator + eventuale cascade).
ROFORMER_MODES = ("rof", "rof6")

LogCb = Callable[[str], None]
ProgCb = Callable[[float], None]
Cancel = Callable[[], bool]

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


# ---------------- percorsi motore ----------------

def engine_dir() -> Path:
    return config.config_dir() / "stem-engine"


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
    e["TORCH_HOME"] = str(_torch_home())          # contiene i checkpoint dei modelli
    e["UV_PYTHON_INSTALL_DIR"] = str(engine_dir() / "python")
    e["PYTHONUTF8"] = "1"
    return e


# ---------------- rilevamento GPU ----------------

def has_nvidia() -> bool:
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True,
                            text=True, timeout=8, creationflags=_NO_WINDOW)
        return r.returncode == 0 and "GPU" in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


# ---------------- esecuzione subprocess con stream + cancel ----------------

def _stream(cmd: list[str], on_text: Callable[[str], None], cancel: Cancel) -> int:
    """Esegue cmd, streamma stdout(+stderr) a on_text, killabile via cancel.

    Ritorna il return code (o -1 se annullato).
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=0, env=_env(), creationflags=_NO_WINDOW,
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
    """Riscrive `home` in pyvenv.cfg alla cartella REALE del Python 3.12.

    uv crea un alias minor-version come *junction* (`cpython-3.12-...` →
    `cpython-3.12.NN-...`). Con la mitigazione «redirection trust» di uv quella
    junction non è attraversabile e l'ispezione del venv fallisce con
    «untrusted mount point» (os error 448). Puntando `home` alla cartella reale
    si elimina la junction dal percorso. Ritorna True se ha modificato il file.
    """
    cfg = venv / "pyvenv.cfg"
    if not cfg.exists():
        return False
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    out: list[str] = []
    changed = False
    for ln in lines:
        if ln.split("=", 1)[0].strip().lower() == "home" and "=" in ln:
            try:
                cur = Path(ln.split("=", 1)[1].strip())
                real = Path(os.path.realpath(cur))
                if real != cur and real.exists():
                    ln = f"home = {real}"
                    changed = True
            except OSError:
                pass  # Se realpath fallisce per la junction (errore 448), teniamo il percorso originale
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


def _create_venv(uv: str, venv: Path, log_cb: LogCb, cancel: Cancel) -> bool:
    """Crea il venv 3.12, robusto al fallimento del link minor-version di uv.

    In alcuni contesti di processo (token ristretto/sandbox) uv non può creare la
    junction `cpython-3.12-...` del Python gestito → «untrusted mount point»
    (os error 448). Però il Python REALE viene comunque scaricato: in quel caso si
    crea il venv puntando direttamente all'eseguibile concreto, senza alcun link.
    """
    if cancel():
        return False
    exe = _managed_py312()
    if exe is None:
        # Python non ancora presente: tentativo standard (uv lo scarica). Può
        # riuscire del tutto, oppure fallire SOLO sulla creazione del link.
        shutil.rmtree(venv, ignore_errors=True)
        rc = _stream([uv, "venv", str(venv), "--python", "3.12"], log_cb, cancel)
        if rc == -1:
            return False
        if rc == 0 and venv_python().exists():
            _normalize_pyvenv_home(venv, log_cb)
            return _seed_pip(log_cb, cancel)
        exe = _managed_py312()   # il download del Python è comunque avvenuto?
    if exe is None:
        log_cb("Python 3.12 non disponibile dopo il download.")
        return False
    # Crea il venv dall'eseguibile concreto: nessun link da creare, niente 448.
    log_cb("Creo il venv dal Python scaricato (evito il link che dà errore 448)…")
    shutil.rmtree(venv, ignore_errors=True)
    rc = _stream([uv, "venv", str(venv), "--python", str(exe)], log_cb, cancel)
    if rc == -1:
        return False
    if rc == 0 and venv_python().exists():
        _normalize_pyvenv_home(venv, log_cb)
        return _seed_pip(log_cb, cancel)
    return False


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

    # verifica torch importabile
    rc = _stream([str(venv_python()), "-c",
                  "import torch,demucs;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"],
                 log_cb, cancel)
    if rc != 0:
        log_cb("Verifica motore fallita.")
        return False

    _marker().write_text("ok", encoding="utf-8")
    progress_cb(100.0)
    log_cb("Motore stem pronto.")
    return True


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


def _run_roformer(src: Path, out_format: str,
                  log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> Path:
    """Separa src in voce + strumentale con Roformer. Ritorna la cartella di output."""
    script = _roformer_script_path()
    if not script:
        raise RuntimeError("script Roformer non trovato")
    out_dir = engine_dir() / "_rof"
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    models = separator_models_dir()
    models.mkdir(parents=True, exist_ok=True)
    log_cb(f"Separo «{src.stem}» — Roformer ({ROFORMER_MODEL})…")

    def on_text(line: str) -> None:
        m = _PCT.search(line)
        if m:
            try:
                progress_cb(float(m.group(1)))
            except ValueError:
                pass

    rc = _stream([str(venv_python()), script, str(src), str(out_dir),
                  str(models), ROFORMER_MODEL, out_format], on_text, cancel)
    if rc == -1:
        raise RuntimeError("annullato")
    if rc != 0:
        raise RuntimeError(f"Roformer uscito con codice {rc}")
    return out_dir


def _run_demucs(src: Path, model: str, out_format: str, two_stems: bool,
                log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> Path:
    """Esegue demucs per un modello. Ritorna la cartella con gli stem prodotti."""
    device = "cuda" if has_nvidia() else "cpu"
    tmp_out = engine_dir() / "_out"
    out_model = tmp_out / model
    cmd = [str(venv_python()), "-m", "demucs", "-n", model, "-d", device,
           "-o", str(tmp_out)]
    # Qualità: più sovrapposizione = meno artefatti ai bordi dei segmenti.
    # --shifts media più passate sfasate (guadagno reale ma ~Nx tempo): solo su
    # GPU, su CPU sarebbe troppo lento.
    cmd += ["--overlap", "0.5"]
    if device == "cuda":
        cmd += ["--shifts", "2"]
    if two_stems:
        cmd += ["--two-stems", "vocals"]
    if out_format == "flac":
        cmd += ["--flac"]
    elif out_format == "mp3":
        cmd += ["--mp3", "--mp3-bitrate", "320"]

    def run(extra: list[str]) -> int:
        full = cmd + extra + [str(src)]
        log_cb(f"Separo «{src.stem}» — {model} su {device.upper()}…")

        def on_text(line: str) -> None:
            m = _PCT.search(line)
            if m:
                try:
                    progress_cb(float(m.group(1)))
                except ValueError:
                    pass
        return _stream(full, on_text, cancel)

    rc = run([])
    if rc != 0 and not cancel():
        log_cb("Riprovo con segmenti ridotti (memoria)…")
        rc = run(["--segment", "7"])
    if rc == -1:
        raise RuntimeError("annullato")
    if rc != 0:
        raise RuntimeError(f"demucs uscito con codice {rc}")

    produced = out_model / src.stem
    if not produced.exists():
        cand = list(out_model.glob("*")) if out_model.exists() else []
        produced = cand[0] if cand else produced
    if not produced.exists():
        raise RuntimeError("output demucs non trovato")
    return produced


def separate(input_file: str, mode: str, out_format: str,
             log_cb: LogCb, progress_cb: ProgCb, cancel: Cancel) -> list[str]:
    """Separa input_file negli stem. Ritorna i path dei file prodotti.

    mode: "2" | "4" | "6" | "6hq" (ensemble Demucs qualità massima)
          | "rof" (Roformer voce/strumentale) | "rof6" (Roformer + cascade Demucs).
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
                                       log_cb, progress_cb, cancel)
                for stem in ENSEMBLE_PICK[model]:
                    take(produced / f"{stem}{ext}")
        elif mode == "rof":
            # solo voce + strumentale via Roformer
            rof = _run_roformer(src, out_format, log_cb, progress_cb, cancel)
            voc, inst = _pick_voc_inst(rof, ext)
            take(voc, f"vocals{ext}")
            take(inst, f"no_vocals{ext}")
        elif mode == "rof6":
            # voce da Roformer, strumenti da Demucs sullo strumentale (cascade)
            log_cb("Qualità massima — passo 1/3 (Roformer)")
            rof = _run_roformer(src, out_format, log_cb, progress_cb, cancel)
            voc, inst = _pick_voc_inst(rof, ext)
            take(voc, f"vocals{ext}")
            if not inst or not inst.exists():
                raise RuntimeError("strumentale Roformer non prodotto")
            for i, model in enumerate(("htdemucs_ft", "htdemucs_6s"), start=2):
                if cancel():
                    raise RuntimeError("annullato")
                log_cb(f"Qualità massima — passo {i}/3 ({model} sullo strumentale)")
                produced = _run_demucs(inst, model, out_format, False,
                                       log_cb, progress_cb, cancel)
                for stem in ROF_PICK[model]:
                    take(produced / f"{stem}{ext}")
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
