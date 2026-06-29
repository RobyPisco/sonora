"""Time-stretch pitch-preserving (phase vocoder) in numpy.

Niente librosa (numba non ha wheel per Python 3.14). Implementazione vettoriale
con STFT/ISTFT via np.fft.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

_NFFT = 2048
_HOP = 512


def _stft(x: np.ndarray, win: np.ndarray) -> np.ndarray:
    """STFT di un segnale mono float32 → matrice [frames, nbins] complessa."""
    n = len(x)
    n_frames = 1 + max(0, (n - _NFFT) // _HOP)
    if n_frames <= 0:
        return np.zeros((0, _NFFT // 2 + 1), dtype="complex64")
    idx = np.arange(_NFFT)[None, :] + _HOP * np.arange(n_frames)[:, None]
    frames = x[idx] * win[None, :]
    return np.fft.rfft(frames, axis=1).astype("complex64")


def _istft(spec: np.ndarray, win: np.ndarray, hop_s: int, out_len: int) -> np.ndarray:
    """ISTFT overlap-add con hop di sintesi hop_s."""
    n_frames = spec.shape[0]
    frames = np.fft.irfft(spec, n=_NFFT, axis=1).astype("float32") * win[None, :]
    # il buffer deve coprire l'ultima scrittura: l'arrotondamento di hop_s può
    # spingere (n_frames-1)*hop_s + _NFFT oltre out_len + _NFFT.
    total = max(out_len, (n_frames - 1) * hop_s + _NFFT) + _NFFT
    out = np.zeros(total, dtype="float32")
    norm = np.zeros(total, dtype="float32")
    win_sq = win ** 2
    for i in range(n_frames):
        s = i * hop_s
        out[s:s + _NFFT] += frames[i]
        norm[s:s + _NFFT] += win_sq
    norm[norm < 1e-6] = 1.0
    return (out / norm)[:out_len]


def _stretch_channel(x: np.ndarray, stretch: float, win: np.ndarray) -> np.ndarray:
    """Allunga (stretch>1) o accorcia (stretch<1) un canale mantenendo il pitch."""
    spec = _stft(x, win)
    if spec.shape[0] < 2:
        return x.copy()
    mag = np.abs(spec)
    phase = np.angle(spec)
    nbins = spec.shape[1]
    omega = 2.0 * np.pi * _HOP * np.arange(nbins) / _NFFT   # avanzamento atteso per bin

    # differenza di fase tra frame consecutivi, "true frequency"
    dphi = phase[1:] - phase[:-1] - omega[None, :]
    dphi = dphi - 2.0 * np.pi * np.round(dphi / (2.0 * np.pi))   # wrap in [-pi,pi]
    true_freq = omega[None, :] + dphi                            # [frames-1, nbins]

    hop_s = max(1, int(round(_HOP * stretch)))
    out_frames = spec.shape[0]
    # accumulo di fase di sintesi
    acc = np.empty_like(mag)
    acc[0] = phase[0]
    inc = true_freq * (hop_s / _HOP)
    acc[1:] = np.cumsum(inc, axis=0) + phase[0][None, :]
    new_spec = (mag * np.exp(1j * acc)).astype("complex64")

    out_len = int(round(len(x) * stretch))
    return _istft(new_spec, win, hop_s, out_len)


def _get_rubberband_path() -> Path | None:
    try:
        from .paths import bin_dir
        d = bin_dir()
        exe = "rubberband.exe" if os.name == "nt" else "rubberband"
        p = d / exe
        if p.exists():
            return p
    except Exception:
        pass
    return None


def rubberband_process(
    x: np.ndarray,
    stretch: float = 1.0,
    semitones: float = 0.0,
    sr: int = 44100
) -> np.ndarray | None:
    """Esegue time-stretch e/o pitch-shift tramite rubberband.exe.
    Ritorna None se fallisce o se l'eseguibile non esiste.
    """
    rb_path = _get_rubberband_path()
    if not rb_path:
        return None

    if abs(stretch - 1.0) < 1e-3 and abs(semitones) < 1e-6:
        return x.copy()

    fd_in, temp_in = tempfile.mkstemp(suffix=".wav")
    fd_out, temp_out = tempfile.mkstemp(suffix=".wav")
    try:
        os.close(fd_in)
        os.close(fd_out)

        sf.write(temp_in, x, sr)

        cmd = [str(rb_path), "-3", "-q"]
        if abs(stretch - 1.0) >= 1e-3:
            cmd += ["-t", str(stretch)]
        if abs(semitones) >= 1e-6:
            cmd += ["-p", str(semitones)]

        cmd += [temp_in, temp_out]

        # Cwd impostato alla cartella dell'eseguibile per caricare sndfile.dll
        res = subprocess.run(
            cmd,
            cwd=str(rb_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=0x08000000 if os.name == "nt" else 0
        )

        if res.returncode != 0:
            return None

        out_data, out_sr = sf.read(temp_out, dtype="float32")
        if x.ndim == 2 and out_data.ndim == 1:
            out_data = np.column_stack([out_data, out_data])
        return np.ascontiguousarray(out_data, dtype="float32")

    except Exception:
        return None
    finally:
        for temp_file in (temp_in, temp_out):
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass


def time_stretch(x: np.ndarray, stretch: float, sr: int = 44100) -> np.ndarray:
    """Time-stretch di un segnale [n] o [n, ch]. stretch>1 = più lungo (più lento).

    Mantiene l'intonazione. Per `stretch≈1` ritorna l'originale.
    """
    if abs(stretch - 1.0) < 1e-3:
        return x.astype("float32", copy=True)

    rb_res = rubberband_process(x, stretch=stretch, sr=sr)
    if rb_res is not None:
        return rb_res

    win = np.hanning(_NFFT).astype("float32")
    if x.ndim == 1:
        return _stretch_channel(x.astype("float32"), stretch, win)
    chans = [_stretch_channel(x[:, c].astype("float32"), stretch, win) for c in range(x.shape[1])]
    m = min(len(c) for c in chans)
    return np.stack([c[:m] for c in chans], axis=1)


def _resample_linear(x: np.ndarray, target_len: int) -> np.ndarray:
    """Ricampiona [n] o [n, ch] a `target_len` campioni (interpolazione lineare)."""
    n = x.shape[0]
    if n == target_len or n == 0:
        return x.astype("float32", copy=True)
    idx = np.linspace(0.0, n - 1, target_len)
    lo = np.floor(idx).astype("int64")
    hi = np.minimum(lo + 1, n - 1)
    frac = (idx - lo).astype("float32")
    if x.ndim == 1:
        return ((1.0 - frac) * x[lo] + frac * x[hi]).astype("float32")
    frac = frac[:, None]
    return ((1.0 - frac) * x[lo] + frac * x[hi]).astype("float32")


def pitch_shift(x: np.ndarray, semitones: float, sr: int = 44100) -> np.ndarray:
    """Sposta l'intonazione di `semitones` semitoni mantenendo la durata.

    Allunga col phase-vocoder (pitch invariato) e poi ricampiona alla lunghezza
    originale: il risultato ha la stessa durata ma intonazione traslata.
    """
    if abs(semitones) < 1e-6:
        return x.astype("float32", copy=True)

    rb_res = rubberband_process(x, semitones=semitones, sr=sr)
    if rb_res is not None:
        return rb_res

    ratio = 2.0 ** (semitones / 12.0)
    stretched = time_stretch(x, ratio, sr=sr)
    return _resample_linear(stretched, x.shape[0])

