"""Motore di mixaggio multitraccia: mixa N stem in tempo reale su un solo
stream audio (sync campione-esatto). Niente Qt: modulo audio puro.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import soundfile as sf
import sounddevice as sd


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


class Track:
    def __init__(self, name: str, data: np.ndarray):
        self.name = name
        self.data_orig = data     # float32 [n, 2] originale
        self.data_base = data     # dopo pitch/stretch, prima dell'EQ
        self.data = data          # buffer in riproduzione (stretch + EQ)
        self.gain_db = 0.0
        self.mute = False
        self.solo = False
        self.pan = 0.0            # -1 (L) .. +1 (R)
        # EQ a 3 bande (guadagni in dB): bassi / medi / alti
        self.eq_low = 0.0
        self.eq_mid = 0.0
        self.eq_high = 0.0


class MixerEngine:
    """Carica stem e li riproduce mixati. Thread-safe per i parametri live."""

    def __init__(self):
        self.tracks: list[Track] = []
        self.sr = 44100
        self.n_frames = 0
        self._pos = 0
        self._playing = False
        self._master_db = 0.0
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None
        # velocità (time-stretch) e trasposizione (pitch shift)
        self.speed = 1.0
        self.semitones = 0.0
        # loop A-B (frazioni 0..1)
        self.loop_enabled = False
        self.loop_a = 0.0
        self.loop_b = 1.0
        self._loop_count = 0       # quante volte il loop ha riavvolto
        # metronomo
        self._beats: list[float] = []     # tempi beat (secondi, dominio originale)
        self._click = np.zeros(0, dtype="float32")
        self.click_enabled = False
        self.click_gain = 0.6
        self.click_regular = True     # True: griglia uniforme; False: beat rilevati
        self.click_accent = True      # accento sul "1" di ogni battuta
        self.beats_per_bar = 4        # battiti per battuta (per l'accento)

    # ---------- caricamento ----------

    def load_files(self, files: list[tuple[str, str]]) -> None:
        """files: lista (nome, path). Tutti riportati a stereo float32, stessa SR."""
        self.close()
        tracks: list[Track] = []
        sr = None
        max_len = 0
        for name, path in files:
            data, file_sr = sf.read(path, dtype="float32", always_2d=True)
            if sr is None:
                sr = file_sr
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            tracks.append(Track(name, np.ascontiguousarray(data)))
            max_len = max(max_len, data.shape[0])
        # pad alla stessa lunghezza
        for t in tracks:
            if t.data.shape[0] < max_len:
                pad = np.zeros((max_len - t.data.shape[0], 2), dtype="float32")
                t.data = np.concatenate([t.data, pad], axis=0)
            t.data_orig = t.data
            t.data_base = t.data
        with self._lock:
            self.tracks = tracks
            self.sr = sr or 44100
            self.n_frames = max_len
            self._pos = 0
            self._playing = False
            self.speed = 1.0
            self.semitones = 0.0
            self.loop_enabled = False
            self.loop_a, self.loop_b = 0.0, 1.0
            self._beats = []
            self._click = np.zeros(0, dtype="float32")
            self.click_enabled = False

    def _open_stream(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.OutputStream(
            samplerate=self.sr, channels=2, dtype="float32",
            blocksize=1024, callback=self._callback)
        self._stream.start()

    # ---------- callback audio ----------

    def _add_segment(self, mix, write, start, length, any_solo) -> None:  # noqa: ANN001
        """Somma in mix[write:write+length] gli stem (+click) da [start:start+length]."""
        end = start + length
        for t in self.tracks:
            audible = (t.solo if any_solo else not t.mute)
            if not audible:
                continue
            seg = t.data[start:end]
            g = db_to_gain(t.gain_db)
            lpan = np.cos((t.pan + 1) * np.pi / 4)
            rpan = np.sin((t.pan + 1) * np.pi / 4)
            mix[write:write + length, 0] += seg[:, 0] * g * lpan
            mix[write:write + length, 1] += seg[:, 1] * g * rpan
        if self.click_enabled and len(self._click) >= end:
            c = self._click[start:end] * self.click_gain
            mix[write:write + length, 0] += c
            mix[write:write + length, 1] += c

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            if not self._playing or not self.tracks:
                outdata.fill(0)
                return
            mix = np.zeros((frames, 2), dtype="float32")
            any_solo = any(t.solo for t in self.tracks)
            pos = self._pos
            loop_a = int(self.loop_a * self.n_frames)
            loop_b = int(self.loop_b * self.n_frames)
            remaining = frames
            write = 0
            while remaining > 0:
                if self.loop_enabled and pos < loop_b and (pos + remaining) > loop_b:
                    chunk = loop_b - pos
                else:
                    chunk = min(remaining, self.n_frames - pos)
                if chunk <= 0:
                    break
                self._add_segment(mix, write, pos, chunk, any_solo)
                pos += chunk
                write += chunk
                remaining -= chunk
                if self.loop_enabled and pos >= loop_b:
                    pos = loop_a
                    self._loop_count += 1
                elif pos >= self.n_frames:
                    self._playing = False
                    break
            mix *= db_to_gain(self._master_db)
            np.clip(mix, -1.0, 1.0, out=mix)
            outdata[:] = mix
            self._pos = min(pos, self.n_frames)

    # ---------- trasporto ----------

    def play(self) -> None:
        self._open_stream()
        with self._lock:
            if self._pos >= self.n_frames:
                self._pos = 0
            self._playing = True

    def pause(self) -> None:
        with self._lock:
            self._playing = False

    def stop(self) -> None:
        with self._lock:
            self._playing = False
            self._pos = 0

    def seek(self, seconds: float) -> None:
        with self._lock:
            self._pos = int(max(0, min(seconds * self.sr, self.n_frames)))

    def is_playing(self) -> bool:
        return self._playing

    def position(self) -> float:
        return self._pos / self.sr if self.sr else 0.0

    def duration(self) -> float:
        return self.n_frames / self.sr if self.sr else 0.0

    # ---------- parametri traccia ----------

    def set_gain(self, i: int, db: float) -> None:
        if 0 <= i < len(self.tracks):
            self.tracks[i].gain_db = db

    def set_mute(self, i: int, b: bool) -> None:
        if 0 <= i < len(self.tracks):
            self.tracks[i].mute = b

    def set_solo(self, i: int, b: bool) -> None:
        if 0 <= i < len(self.tracks):
            self.tracks[i].solo = b

    def set_pan(self, i: int, x: float) -> None:
        if 0 <= i < len(self.tracks):
            self.tracks[i].pan = float(max(-1.0, min(1.0, x)))

    def set_master(self, db: float) -> None:
        self._master_db = db

    # ---------- EQ a 3 bande (per traccia, fase nulla via FFT) ----------

    def set_eq(self, i: int, low: float | None = None, mid: float | None = None,
               high: float | None = None) -> None:
        """Imposta i guadagni EQ (dB) della traccia e ricostruisce il buffer udibile."""
        if not (0 <= i < len(self.tracks)):
            return
        t = self.tracks[i]
        if low is not None:
            t.eq_low = float(max(-12.0, min(12.0, low)))
        if mid is not None:
            t.eq_mid = float(max(-12.0, min(12.0, mid)))
        if high is not None:
            t.eq_high = float(max(-12.0, min(12.0, high)))
        self._apply_eq_track(t)

    def _eq_curve(self, n: int, low: float, mid: float, high: float) -> np.ndarray:
        """Risposta in ampiezza (reale, fase nulla) di un EQ 3 bande morbido.
        Bassi sotto ~200 Hz, alti sopra ~4 kHz, medi nel mezzo (transizioni log)."""
        f = np.fft.rfftfreq(n, 1.0 / self.sr)
        logf = np.log10(np.maximum(f, 1.0))
        w_low = 0.5 * (1.0 - np.tanh((logf - np.log10(200.0)) / 0.4))
        w_high = 0.5 * (1.0 + np.tanh((logf - np.log10(4000.0)) / 0.4))
        w_mid = np.clip(1.0 - w_low - w_high, 0.0, 1.0)
        gain_db = low * w_low + mid * w_mid + high * w_high
        return (10.0 ** (gain_db / 20.0)).astype("float32")

    def _apply_eq_track(self, t: Track) -> None:
        """Ricostruisce t.data da t.data_base applicando l'EQ (o condivide il
        riferimento se l'EQ è piatto, per non sprecare memoria)."""
        if abs(t.eq_low) < 1e-3 and abs(t.eq_mid) < 1e-3 and abs(t.eq_high) < 1e-3:
            with self._lock:
                t.data = t.data_base
            return
        base = t.data_base
        n = base.shape[0]
        if n == 0:
            return
        H = self._eq_curve(n, t.eq_low, t.eq_mid, t.eq_high)
        out = np.empty_like(base)
        for c in range(base.shape[1]):
            spec = np.fft.rfft(base[:, c])
            out[:, c] = np.fft.irfft(spec * H, n=n)
        out = np.ascontiguousarray(out, dtype="float32")
        with self._lock:
            t.data = out

    # ---------- velocità (time-stretch) + trasposizione (pitch shift) ----------

    def render_buffers(self, speed: float, semitones: float) -> list[np.ndarray]:
        """Calcola (CPU) i buffer trasformati dai dati originali: prima il pitch
        shift (durata invariata), poi il time-stretch. Da chiamare nel worker."""
        from .timestretch import pitch_shift, time_stretch, rubberband_process
        out: list[np.ndarray] = []
        stretch = 1.0 / speed
        for t in self.tracks:
            buf = t.data_orig
            # Prova a fare entrambi in una sola passata con rubberband
            rb_buf = rubberband_process(buf, stretch=stretch, semitones=semitones, sr=self.sr)
            if rb_buf is not None:
                buf = rb_buf
            else:
                # Fallback se rubberband non è disponibile o fallisce
                if abs(semitones) > 1e-6:
                    buf = pitch_shift(buf, semitones, sr=self.sr)
                if abs(speed - 1.0) > 1e-3:
                    buf = time_stretch(buf, stretch, sr=self.sr)
            out.append(np.ascontiguousarray(buf, dtype="float32"))
        return out

    def apply_transform(self, buffers: list[np.ndarray], speed: float, semitones: float) -> None:
        """Sostituisce i buffer di riproduzione (swap sotto lock), conserva la posizione."""
        if len(buffers) != len(self.tracks):
            return
        max_len = max((b.shape[0] for b in buffers), default=0)
        with self._lock:
            frac = (self._pos / self.n_frames) if self.n_frames else 0.0
            for t, b in zip(self.tracks, buffers):
                if b.shape[0] < max_len:
                    b = np.concatenate([b, np.zeros((max_len - b.shape[0], 2), dtype="float32")])
                t.data_base = np.ascontiguousarray(b, dtype="float32")
                t.data = t.data_base   # ricostruito sotto se l'EQ è attivo
            self.n_frames = max_len
            self.speed = speed
            self.semitones = semitones
            self._pos = int(frac * max_len)
        for t in self.tracks:
            self._apply_eq_track(t)
        self._regen_click()

    # ---------- render offline del mix (export) ----------

    def render_mix(self, include_click: bool = False) -> tuple[np.ndarray | None, int]:
        """Mixa gli stem audibili (mute/solo/gain/pan/master correnti) su un buffer
        stereo unico, riflettendo anche velocità/pitch attuali. Per l'export su file.
        Se include_click è True sovrappone il metronomo ai beat."""
        if not self.tracks:
            return None, self.sr
        n = self.n_frames
        mix = np.zeros((n, 2), dtype="float32")
        any_solo = any(t.solo for t in self.tracks)
        for t in self.tracks:
            audible = (t.solo if any_solo else not t.mute)
            if not audible:
                continue
            d = t.data
            m = min(n, d.shape[0])
            g = db_to_gain(t.gain_db)
            lpan = np.cos((t.pan + 1) * np.pi / 4)
            rpan = np.sin((t.pan + 1) * np.pi / 4)
            mix[:m, 0] += d[:m, 0] * g * lpan
            mix[:m, 1] += d[:m, 1] * g * rpan
        mix *= db_to_gain(self._master_db)
        if include_click and len(self._click) > 0:
            c = self._click * self.click_gain
            m = min(n, len(c))
            mix[:m, 0] += c[:m]
            mix[:m, 1] += c[:m]
        np.clip(mix, -1.0, 1.0, out=mix)
        return mix, self.sr

    def render_count_in(self, n_beats: int = 4, gain: float | None = None
                        ) -> tuple[np.ndarray | None, int]:
        """Genera un breve buffer stereo con n_beats click al tempo della canzone,
        pensato come conteggio iniziale ("click, click, click… e parte")."""
        if not self._beats or n_beats <= 0:
            return None, self.sr
        interval = self._beat_interval() or 0.5      # secondi, dominio originale
        interval = interval / max(self.speed, 1e-6)  # dominio playback corrente
        g = self.click_gain if gain is None else max(0.0, min(1.0, gain))
        normal = self._click_burst(False)
        accent = self._click_burst(True)
        total = int(interval * n_beats * self.sr) + len(accent)
        buf = np.zeros(total, dtype="float32")
        for i in range(n_beats):
            burst = accent if (self.click_accent and i == 0) else normal
            pos = int(i * interval * self.sr)
            end = min(pos + len(burst), total)
            buf[pos:end] += burst[:end - pos]
        buf *= g
        np.clip(buf, -1.0, 1.0, out=buf)
        return np.ascontiguousarray(np.column_stack([buf, buf])), self.sr

    # ---------- loop A-B ----------

    def set_loop(self, a: float, b: float, enabled: bool) -> None:
        with self._lock:
            self.loop_a = max(0.0, min(1.0, min(a, b)))
            self.loop_b = max(0.0, min(1.0, max(a, b)))
            self.loop_enabled = enabled and (self.loop_b - self.loop_a) > 0.001
            self._loop_count = 0

    def clear_loop(self) -> None:
        with self._lock:
            self.loop_enabled = False
            self.loop_a, self.loop_b = 0.0, 1.0
            self._loop_count = 0

    def loop_count(self) -> int:
        """Numero di riavvolgimenti del loop (per l'auto-incremento velocità)."""
        return self._loop_count

    # ---------- metronomo ----------

    def set_beats(self, beats: list[float]) -> None:
        self._beats = list(beats or [])
        self._regen_click()

    def set_click(self, enabled: bool, gain: float | None = None) -> None:
        self.click_enabled = enabled
        if gain is not None:
            self.click_gain = max(0.0, min(1.0, gain))

    def set_click_style(self, regular: bool | None = None, accent: bool | None = None,
                        beats_per_bar: int | None = None) -> None:
        """Cambia stile del click (griglia regolare vs beat rilevati, accento, metro)
        e rigenera il buffer."""
        if regular is not None:
            self.click_regular = bool(regular)
        if accent is not None:
            self.click_accent = bool(accent)
        if beats_per_bar is not None:
            self.beats_per_bar = max(1, int(beats_per_bar))
        self._regen_click()

    def _click_burst(self, accent: bool = False) -> np.ndarray:
        """Breve burst del click. Accentato (il '1') = più acuto e più forte."""
        dur = int(0.03 * self.sr)
        tt = np.arange(dur) / self.sr
        freq = 2200 if accent else 1500
        amp = 1.5 if accent else 1.0
        return (amp * np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 80)).astype("float32")

    def _beat_interval(self) -> float:
        """Intervallo tra beat (secondi, dominio originale) = mediana dei delta.
        Robusto al jitter del rilevamento dei beat."""
        if len(self._beats) < 2:
            return 0.0
        return float(np.median(np.diff(sorted(self._beats))))

    def _regular_beats(self) -> list[float]:
        """Griglia di beat UNIFORME al tempo medio, ancorata al primo beat e estesa
        a tutta la durata. Evita che il click acceleri/deceleri seguendo i beat
        rilevati in modo irregolare."""
        interval = self._beat_interval()
        if interval <= 1e-3 or self.n_frames <= 0:
            return list(self._beats)
        first = sorted(self._beats)[0]
        start = first - (int(first / interval)) * interval   # ancora vicino a 0
        end = (self.n_frames / self.sr) * self.speed          # durata dominio originale
        grid: list[float] = []
        t = start
        while t < end:
            if t >= 0:
                grid.append(t)
            t += interval
        return grid

    def _regen_click(self) -> None:
        """Genera il buffer di click (griglia regolare o beat rilevati), con accento
        sul '1' di ogni battuta, scalato dalla velocità corrente."""
        grid = self._regular_beats() if self.click_regular else sorted(self._beats)
        if not grid or self.n_frames <= 0:
            self._click = np.zeros(0, dtype="float32")
            return
        click = np.zeros(self.n_frames, dtype="float32")
        normal = self._click_burst(False)
        accent = self._click_burst(True)
        bpb = max(1, int(self.beats_per_bar))
        for i, bt in enumerate(grid):
            pos = int(bt * self.sr / self.speed)
            if not (0 <= pos < self.n_frames):
                continue
            burst = accent if (self.click_accent and i % bpb == 0) else normal
            end = min(pos + len(burst), self.n_frames)
            click[pos:end] += burst[:end - pos]
        with self._lock:
            self._click = click

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
