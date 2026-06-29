"""Accordatore: generatore di tono di riferimento (A440 / corde) e rilevatore di
pitch dal microfono. Modulo audio puro (niente Qt).

- ToneGenerator: riproduce un seno continuo a una frequenza data.
- PitchDetector: legge il microfono e stima la frequenza fondamentale
  (autocorrelazione via FFT) con interpolazione parabolica.
"""

from __future__ import annotations

import math
import threading

import numpy as np
import sounddevice as sd

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# corde standard (nome, frequenza Hz)
GUITAR_STRINGS = [
    ("Mi₂ (E2)", 82.41), ("La₂ (A2)", 110.00), ("Re₃ (D3)", 146.83),
    ("Sol₃ (G3)", 196.00), ("Si₃ (B3)", 246.94), ("Mi₄ (E4)", 329.63),
]
BASS_STRINGS = [
    ("Mi₁ (E1)", 41.20), ("La₁ (A1)", 55.00),
    ("Re₂ (D2)", 73.42), ("Sol₂ (G2)", 98.00),
]


def freq_to_note(freq: float):
    """(nome_nota, cents_di_scarto, freq_target) per la frequenza data, o None."""
    if freq <= 0:
        return None
    midi = 69.0 + 12.0 * math.log2(freq / 440.0)
    nearest = int(round(midi))
    cents = (midi - nearest) * 100.0
    name = NOTE_NAMES[nearest % 12] + str(nearest // 12 - 1)
    target = 440.0 * (2.0 ** ((nearest - 69) / 12.0))
    return name, cents, target


class ToneGenerator:
    """Riproduce un seno continuo (tono di riferimento) via OutputStream."""

    def __init__(self, sr: int = 44100):
        self.sr = sr
        self._freq = 440.0
        self._gain = 0.2
        self._phase = 0.0
        self._on = False
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            if not self._on:
                outdata.fill(0)
                return
            f, g, ph = self._freq, self._gain, self._phase
            t = (ph + 2.0 * np.pi * f * np.arange(frames) / self.sr)
            wave = (g * np.sin(t)).astype("float32")
            self._phase = float((ph + 2.0 * np.pi * f * frames / self.sr) % (2.0 * np.pi))
        outdata[:, 0] = wave
        outdata[:, 1] = wave

    def _ensure_stream(self) -> None:
        if self._stream is None:
            self._stream = sd.OutputStream(
                samplerate=self.sr, channels=2, dtype="float32",
                blocksize=512, callback=self._callback)
            self._stream.start()

    def play(self, freq: float) -> None:
        self._ensure_stream()
        with self._lock:
            self._freq = float(freq)
            self._on = True

    def stop(self) -> None:
        with self._lock:
            self._on = False

    @property
    def playing(self) -> bool:
        return self._on

    @property
    def freq(self) -> float:
        return self._freq

    def close(self) -> None:
        self.stop()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None


class PitchDetector:
    """Stima la frequenza fondamentale dal microfono (autocorrelazione FFT)."""

    def __init__(self, sr: int = 44100, block: int = 4096):
        self.sr = sr
        self.block = block
        self._freq = 0.0
        self._level = 0.0
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _estimate(self, x: np.ndarray) -> float:
        x = x.astype("float64")
        x = x - x.mean()
        rms = float(np.sqrt(np.mean(x ** 2)))
        with self._lock:
            self._level = rms
        if rms < 0.004:        # troppo silenzio
            return 0.0
        n = len(x)
        # autocorrelazione via FFT (niente finestra: riduce il bias del picco)
        spec = np.fft.rfft(x, 2 * n)
        acf = np.fft.irfft(spec * np.conj(spec))[:n]
        if acf[0] <= 0:
            return 0.0
        lo = max(1, int(self.sr / 1000.0))   # fino a ~1000 Hz
        hi = min(n - 1, int(self.sr / 40.0))  # giù a ~40 Hz
        if hi <= lo:
            return 0.0
        seg = acf[lo:hi]
        lag = lo + int(np.argmax(seg))
        if acf[lag] <= 0.2 * acf[0]:          # picco troppo debole → poco affidabile
            return 0.0
        # interpolazione parabolica per affinare il lag
        if 1 <= lag < n - 1:
            a, b, c = acf[lag - 1], acf[lag], acf[lag + 1]
            denom = (a - 2 * b + c)
            if denom != 0:
                lag = lag + 0.5 * (a - c) / denom
        return self.sr / lag if lag > 0 else 0.0

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        mono = indata[:, 0] if indata.ndim > 1 else indata
        f = self._estimate(np.asarray(mono, dtype="float32"))
        if f > 0:
            with self._lock:
                # leggero smoothing per stabilità
                self._freq = f if self._freq <= 0 else 0.6 * self._freq + 0.4 * f

    def start(self) -> None:
        if self._stream is None:
            self._stream = sd.InputStream(
                samplerate=self.sr, channels=1, dtype="float32",
                blocksize=self.block, callback=self._callback)
            self._stream.start()

    def read(self) -> tuple[float, float]:
        """(frequenza stimata Hz, livello RMS). 0 se nessun pitch affidabile."""
        with self._lock:
            return self._freq, self._level

    def reset(self) -> None:
        with self._lock:
            self._freq = 0.0

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
