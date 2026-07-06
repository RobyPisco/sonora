"""Player minimale per anteprime audio (breve estratto scaricato in temp).

Mono-traccia, nessun mixing/EQ/pitch: carica un file audio locale e lo
riproduce per intero. Ricalcato su `MixerEngine` (mixer_engine.py) ma
semplificato al minimo indispensabile per un'anteprima usa-e-getta.
"""

from __future__ import annotations

import threading

import numpy as np
import soundfile as sf
import sounddevice as sd


class PreviewPlayer:
    """Carica e riproduce un singolo file audio (anteprima)."""

    def __init__(self):
        self._data: np.ndarray | None = None
        self._sr = 44100
        self._pos = 0
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None

    def load(self, path: str) -> None:
        self.stop()
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] > 2:
            data = data[:, :2]
        with self._lock:
            self._data = np.ascontiguousarray(data)
            self._sr = sr
            self._pos = 0

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            data, pos = self._data, self._pos
            if data is None:
                outdata.fill(0)
                raise sd.CallbackStop
            end = min(pos + frames, len(data))
            n = end - pos
            outdata[:n] = data[pos:end]
            if n < frames:
                outdata[n:].fill(0)
            self._pos = end
        if end >= len(data):
            raise sd.CallbackStop

    def play(self) -> None:
        if self._data is None:
            return
        self.stop_stream()
        with self._lock:
            self._pos = 0
        self._stream = sd.OutputStream(
            samplerate=self._sr, channels=2, dtype="float32",
            blocksize=1024, callback=self._callback)
        self._stream.start()

    def stop_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    def stop(self) -> None:
        self.stop_stream()
        with self._lock:
            self._data = None
            self._pos = 0

    def is_playing(self) -> bool:
        return self._stream is not None and self._stream.active
