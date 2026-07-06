"""Scheda Mixer: riproduce gli stem sincronizzati con analisi BPM/tonalità."""

from __future__ import annotations

import bisect
import json
import math
import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QPoint, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QPolygon, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import config, history, icons, paths, stems, theme
from .flowlayout import FlowLayout
from .toast import toast
from .mixer_engine import MixerEngine
from .waveform import WaveformWidget, compute_peaks

# notazione note: anglosassone (C D E…) e latina (Do Re Mi…)
NOTES_ANGLO = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTES_LATIN = ["Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]


def chord_label(root: int, quality: str, notation: str) -> str:
    """Nome accordo in notazione 'latin' (Do Re Mi) o 'anglo' (C D E)."""
    names = NOTES_LATIN if notation == "latin" else NOTES_ANGLO
    if not (0 <= root < 12):
        return "—"
    return names[root] + ("m" if quality == "min" else "")

# Colori per stem: definiti in theme.py (unica fonte di verità)
STEM_COLORS = theme.STEM_COLORS
STEM_ORDER = ["vocals", "drums", "bass", "guitar", "piano", "other"]
STEM_LABEL = {"vocals": "Vocals", "drums": "Drums", "bass": "Bass",
              "guitar": "Guitar", "piano": "Piano", "other": "Other"}
# Prefisso file per gli stem mutati durante l'export (es. NO_BASSO - …)
STEM_NO = {"vocals": "NO_VOCE", "drums": "NO_BATTERIA", "bass": "NO_BASSO",
           "guitar": "NO_CHITARRA", "piano": "NO_PIANO", "other": "NO_ALTRO"}
# Nome italiano per l'export dei singoli stem (es. BASSO - titolo.wav)
STEM_IT = {"vocals": "VOCE", "drums": "BATTERIA", "bass": "BASSO",
           "guitar": "CHITARRA", "piano": "PIANO", "other": "ALTRO",
           "no_vocals": "BASE"}

# Larghezza fissa del pannello controlli di ogni traccia. Condivisa fra
# TrackStrip e TimelineWidget così le waveform partono alla stessa x e
# restano allineate ai tick della timeline. Cambiala in un solo punto.
CTRL_W = 250


def _fader_qss(color: str) -> str:
    """Stylesheet per un fader volume con la parte riempita del colore dello stem."""
    groove = theme.COLORS["raise"]
    return (
        f"QSlider::groove:horizontal{{height:6px;background:{groove};border-radius:3px;}}"
        f"QSlider::sub-page:horizontal{{background:{color};border-radius:3px;}}"
        "QSlider::handle:horizontal{background:#ffffff;width:14px;height:14px;"
        "margin:-4px 0;border-radius:7px;border:1px solid #cdd1de;}"
        f"QSlider::handle:horizontal:hover{{background:#ffffff;border:2px solid {color};}}"
    )


def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class AnalyzeWorker(QObject):
    done = Signal(bool, dict)
    log = Signal(str)

    def __init__(self, folder: str):
        super().__init__()
        self._folder = folder

    def run(self) -> None:
        try:
            data = stems.analyze(self._folder, self.log.emit)
            self.done.emit(True, data)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, {"error": str(exc).splitlines()[0] if str(exc) else "errore"})


class TransformWorker(QObject):
    """Calcola i buffer trasformati (velocità + trasposizione) in un thread."""

    done = Signal(object, float, float)   # buffers, speed, semitones

    def __init__(self, engine: MixerEngine, speed: float, semitones: float):
        super().__init__()
        self._engine = engine
        self._speed = speed
        self._semitones = semitones

    def run(self) -> None:
        try:
            bufs = self._engine.render_buffers(self._speed, self._semitones)
        except Exception:  # noqa: BLE001
            bufs = None
        self.done.emit(bufs, self._speed, self._semitones)


class EqWorker(QObject):
    """Ricostruisce il buffer EQ (FFT full-file) fuori dal thread UI."""

    done = Signal(int)   # indice traccia

    def __init__(self, engine: MixerEngine, index: int, low: float, mid: float, high: float):
        super().__init__()
        self._engine = engine
        self._index = index
        self._low = low
        self._mid = mid
        self._high = high

    def run(self) -> None:
        try:
            self._engine.set_eq(self._index, self._low, self._mid, self._high)
        except Exception:  # noqa: BLE001
            pass
        self.done.emit(self._index)


def _export_audio(mix: np.ndarray, sr: int, path: str, fmt: str) -> None:
    """Scrive il mix su file. WAV diretto via soundfile; MP3 via ffmpeg (bin/)."""
    import soundfile as sf

    if fmt == "wav":
        sf.write(path, mix, sr, subtype="PCM_16")
        return

    import subprocess
    import tempfile

    ff = paths.bin_dir() / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ff.exists():
        raise RuntimeError("ffmpeg non trovato in bin/")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        sf.write(tmp.name, mix, sr, subtype="PCM_16")
        cmd = [str(ff), "-y", "-i", tmp.name, "-b:a", "320k", path]
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        r = subprocess.run(cmd, capture_output=True, startupinfo=si)
        if r.returncode != 0:
            tail = (r.stderr.decode("utf-8", "ignore").splitlines() or ["errore"])[-1]
            raise RuntimeError(f"ffmpeg: {tail}")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


class ExportWorker(QObject):
    """Renderizza e scrive uno o più file (mix, count-in) su disco in un thread."""

    done = Signal(bool, str)   # ok, path-o-errore

    def __init__(self, jobs: list[tuple], sr: int, fmt: str):
        super().__init__()
        # lista (buffer | callable→buffer, path). I callable rendono il mix al
        # momento della scrittura: N export "minus one" senza N buffer in RAM.
        self._jobs = jobs
        self._sr = sr
        self._fmt = fmt

    def run(self) -> None:
        try:
            for mix, path in self._jobs:
                if callable(mix):
                    mix = mix()
                _export_audio(mix, self._sr, path, self._fmt)
            self.done.emit(True, self._jobs[0][1] if self._jobs else "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc).splitlines()[0] if str(exc) else "errore")


class ExportOptionsDialog(QDialog):
    """Chiede cosa esportare (mix o stem separati), formato e opzioni metronomo."""

    def __init__(self, parent, click_available: bool):
        super().__init__(parent)
        self.setWindowTitle("Opzioni di esportazione")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        # cosa esportare (QButtonGroup separati: senza, tutti i radio del
        # dialogo diventerebbero mutuamente esclusivi tra loro)
        what_lbl = QLabel("COSA ESPORTARE")
        what_lbl.setProperty("class", "Eyebrow")
        self.rb_mix = QRadioButton("Mix unico (come lo senti: volumi, mute/solo, EQ)")
        self.rb_minus = QRadioButton("Basi «senza una traccia» — un mix completo per ogni\n"
                                     "stem escluso (NO_VOCE, NO_BASSO, …)")
        self.rb_stems = QRadioButton("Tutti gli stem — un file per traccia, puri,\n"
                                     "con velocità e tono attuali applicati")
        self.rb_mix.setChecked(True)
        self._grp_what = QButtonGroup(self)
        self._grp_what.addButton(self.rb_mix)
        self._grp_what.addButton(self.rb_minus)
        self._grp_what.addButton(self.rb_stems)
        lay.addWidget(what_lbl)
        lay.addWidget(self.rb_mix)
        lay.addWidget(self.rb_minus)
        lay.addWidget(self.rb_stems)

        # formato
        fmt_lbl = QLabel("FORMATO")
        fmt_lbl.setProperty("class", "Eyebrow")
        self.rb_wav = QRadioButton("WAV (qualità piena)")
        self.rb_mp3 = QRadioButton("MP3 320 kbps (file più piccoli)")
        self.rb_wav.setChecked(True)
        self._grp_fmt = QButtonGroup(self)
        self._grp_fmt.addButton(self.rb_wav)
        self._grp_fmt.addButton(self.rb_mp3)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self.rb_wav)
        fmt_row.addWidget(self.rb_mp3)
        fmt_row.addStretch(1)
        lay.addWidget(fmt_lbl)
        lay.addLayout(fmt_row)

        # opzioni metronomo (valgono solo per il mix unico)
        self.chk_click = QCheckBox("Includi il click (metronomo) per tutto il brano")
        self.chk_countin = QCheckBox("Aggiungi un count-in iniziale (nello stesso file)")
        beats_row = QHBoxLayout()
        beats_row.setContentsMargins(22, 0, 0, 0)
        self.lbl_beats = QLabel("Battute del count-in:")
        self.spin_beats = QSpinBox()
        self.spin_beats.setRange(1, 16)
        self.spin_beats.setValue(4)
        beats_row.addWidget(self.lbl_beats)
        beats_row.addWidget(self.spin_beats)
        beats_row.addStretch(1)

        if click_available:
            lay.addWidget(self.chk_click)
            lay.addWidget(self.chk_countin)
            lay.addLayout(beats_row)
            self.lbl_beats.setEnabled(False)
            self.spin_beats.setEnabled(False)
            self.chk_countin.toggled.connect(self.lbl_beats.setEnabled)
            self.chk_countin.toggled.connect(self.spin_beats.setEnabled)
            # click/count-in non hanno senso sugli stem separati
            for w in (self.chk_click, self.chk_countin):
                self.rb_stems.toggled.connect(
                    lambda on, _w=w: (_w.setEnabled(not on), on and _w.setChecked(False)))
        else:
            info = QLabel("Ri-analizza il brano per abilitare le opzioni del click.")
            info.setProperty("class", "Muted")
            lay.addWidget(info)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def options(self) -> tuple[str, str, bool, bool, int]:
        """(what, fmt, click, countin, beats) — what: 'mix'|'minus'|'stems',
        fmt: 'wav'|'mp3'."""
        what = ("stems" if self.rb_stems.isChecked()
                else "minus" if self.rb_minus.isChecked() else "mix")
        return (what,
                "mp3" if self.rb_mp3.isChecked() else "wav",
                self.chk_click.isChecked(),
                self.chk_countin.isChecked(),
                self.spin_beats.value())


def _hgroup(*widgets, spacing: int = 6) -> QWidget:
    """Raggruppa più widget in una riga orizzontale compatta (un blocco unico).
    Usato coi FlowLayout così ogni cluster di controlli va a capo come unità."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        lay.addWidget(x, 0, Qt.AlignmentFlag.AlignVCenter)
    return w


def _card(title: str, value: str, color: str = "") -> tuple[QFrame, QLabel]:
    """Card di analisi compatta (etichetta minuscola in alto, valore sotto)."""
    color = color or theme.COLORS["text"]
    f = QFrame()
    f.setObjectName("StatCard")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 7, 12, 7)
    lay.setSpacing(1)
    t = QLabel(title)
    t.setStyleSheet(f"color:{theme.COLORS['faint']}; font-size:9px; font-weight:700;"
                    " letter-spacing:1px;")
    v = QLabel(value)
    v.setStyleSheet(f"color:{color}; font-size:16px; font-weight:800;")
    lay.addWidget(t)
    lay.addWidget(v)
    return f, v


class TimelineWidget(QWidget):
    """Disegna la timeline con misure/beat (se disponibili dopo l'analisi)
    o secondi (come fallback) allineata con le waveform.
    """

    seeked = Signal(float)          # 0..1 (frazione globale)

    def __init__(self, engine: MixerEngine):
        super().__init__()
        self.engine = engine
        self._view_start = 0.0
        self._view_end = 1.0
        self._beats = []
        self._duration = 0.0
        self._progress = 0.0
        self.setFixedHeight(24)

    def set_view(self, start: float, end: float) -> None:
        self._view_start = start
        self._view_end = end
        self.update()

    def set_progress(self, frac: float) -> None:
        self._progress = frac
        self.update()

    def set_data(self, beats: list[float], duration: float) -> None:
        self._beats = list(beats or [])
        self._duration = duration
        self.update()

    def _span(self) -> float:
        return max(self._view_end - self._view_start, 1e-9)

    def _x_of(self, fr: float) -> int:
        w = self.width()
        w_timeline = w - CTRL_W
        if w_timeline <= 0:
            return 0
        return int(CTRL_W + (fr - self._view_start) / self._span() * w_timeline)

    def _frac(self, x: float) -> float:
        w = self.width()
        w_timeline = w - CTRL_W
        if w_timeline <= 0:
            return 0.0
        gf = self._view_start + ((x - CTRL_W) / w_timeline) * self._span()
        return max(0.0, min(1.0, gf))

    def _emit_seek(self, x: float) -> None:
        if x >= CTRL_W:
            self.seeked.emit(self._frac(x))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._emit_seek(e.position().x())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._emit_seek(e.position().x())

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        mid = h / 2.0

        # Background: pannello sinistro come le strisce, area destra come le waveform
        p.fillRect(0, 0, CTRL_W, h, QColor(theme.COLORS["panel"]))
        p.fillRect(CTRL_W, 0, w - CTRL_W, h, QColor(theme.COLORS["wave_bg"]))

        # Bordo inferiore e separatore sinistro
        p.setPen(QPen(QColor(theme.COLORS["strip_sep"]), 1))
        p.drawLine(0, h - 1, w, h - 1)
        p.drawLine(CTRL_W, 0, CTRL_W, h)

        # Label nel pannello sinistro (allineata ai nomi traccia)
        p.setPen(QPen(QColor(theme.COLORS["muted"]), 1))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(16, int(mid + 5), "TIMELINE")

        span = self._span()
        vs = self._view_start
        ve = self._view_end

        p.setFont(QFont("Segoe UI", 8))

        bpb = self.engine.beats_per_bar if hasattr(self.engine, "beats_per_bar") else 4

        if self._beats and self._duration > 0:
            n_beats = len(self._beats)
            beat_interval_sec = self._duration / max(1, n_beats)
            beat_spacing_px = (w - CTRL_W) * (beat_interval_sec / self._duration) / span

            decimation = 1
            show_ticks = True
            if beat_spacing_px >= 30:
                decimation = 1
            elif beat_spacing_px >= 12:
                decimation = bpb
            elif beat_spacing_px >= 6:
                decimation = bpb * 2
            elif beat_spacing_px >= 3:
                decimation = bpb * 4
            else:
                show_ticks = False

            if show_ticks:
                for i, bt in enumerate(self._beats):
                    fr = bt / self._duration
                    if vs <= fr <= ve:
                        bx = self._x_of(fr)
                        is_bar_start = (i % bpb == 0)
                        
                        if i % decimation == 0:
                            if is_bar_start:
                                bar_num = (i // bpb) + 1
                                p.setPen(QPen(QColor(theme.COLORS["text"]), 1))
                                p.drawLine(bx, h - 8, bx, h - 1)
                                p.drawText(bx - 15, h - 10, 30, 10, Qt.AlignmentFlag.AlignCenter, f"{bar_num}")
                            else:
                                beat_in_bar = (i % bpb) + 1
                                p.setPen(QPen(QColor("#50566d"), 1))
                                p.drawLine(bx, h - 5, bx, h - 1)
                                if beat_spacing_px >= 30:
                                    p.drawText(bx - 10, h - 10, 20, 10, Qt.AlignmentFlag.AlignCenter, f".{beat_in_bar}")
                        else:
                            p.setPen(QPen(QColor("#3a3f50"), 1))
                            p.drawLine(bx, h - 4, bx, h - 1)

        elif self._duration > 0:
            span_sec = self._duration * span
            if span_sec <= 5:
                step_sec = 0.5
            elif span_sec <= 15:
                step_sec = 1.0
            elif span_sec <= 45:
                step_sec = 5.0
            elif span_sec <= 120:
                step_sec = 10.0
            elif span_sec <= 300:
                step_sec = 30.0
            elif span_sec <= 900:
                step_sec = 60.0
            else:
                step_sec = 120.0

            start_sec = math.floor(vs * self._duration / step_sec) * step_sec
            end_sec = math.ceil(ve * self._duration)

            t = start_sec
            while t <= end_sec:
                fr = t / self._duration
                if vs <= fr <= ve:
                    bx = self._x_of(fr)
                    p.setPen(QPen(QColor(theme.COLORS["muted"]), 1))
                    p.drawLine(bx, h - 6, bx, h - 1)
                    
                    lbl = f"{int(t)}s" if t < 60 else f"{int(t)//60}:{int(t)%60:02d}"
                    p.drawText(bx - 20, h - 18, 40, 10, Qt.AlignmentFlag.AlignCenter, lbl)
                t += step_sec

        # playhead
        px = self._x_of(self._progress)
        if CTRL_W <= px <= w:
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.drawLine(px, 0, px, h)
            
            # Triangolino arancione
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.COLORS["warn"]))
            points = [
                QPoint(px - 5, 0),
                QPoint(px + 5, 0),
                QPoint(px, 6)
            ]
            p.drawPolygon(points)

        p.end()


class TrackStrip(QWidget):
    """Una striscia traccia: nome, fader volume, pan, M/S, waveform."""

    def __init__(self, index: int, name: str, engine: MixerEngine, on_change=None):
        super().__init__()
        self.index = index
        self.name = name
        self.engine = engine
        self._on_change = on_change
        color = STEM_COLORS.get(name, "#ff3b5c")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # pannello controlli sinistra (larghezza fissa per allineare le waveform):
        # 3 righe → nome+dB / fader volume / pan + EQ/M/S
        ctrl = QFrame()
        ctrl.setObjectName("StripPanel")
        ctrl.setFixedWidth(CTRL_W)
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(14, 6, 14, 6)
        cl.setSpacing(4)

        # riga 1: nome traccia (colorato) + valore dB a destra
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        name_lbl = QLabel(STEM_LABEL.get(name, name.title()))
        name_lbl.setStyleSheet(f"color:{color}; font-weight:700; font-size:14px;")
        self.db_lbl = QLabel("0.0 dB")
        self.db_lbl.setStyleSheet(
            f"color:{theme.COLORS['muted']}; font-size:11px;"
            " font-family:'Cascadia Code','Consolas',monospace;")
        head.addWidget(name_lbl)
        head.addStretch(1)
        head.addWidget(self.db_lbl)
        cl.addLayout(head)

        # riga 2: fader volume a tutta larghezza, riempito col colore dello stem
        self.fader = QSlider(Qt.Orientation.Horizontal)
        self.fader.setRange(-40, 6)
        self.fader.setValue(0)
        self.fader.setStyleSheet(_fader_qss(color))
        self.fader.valueChanged.connect(self._on_gain)
        self.fader.sliderReleased.connect(self._notify)
        cl.addWidget(self.fader)

        # riga 3: pan (corto, a sinistra) + EQ / M / S (a destra)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(6)
        # pan: -100 (L) .. +100 (R), doppio click per ricentrare
        self.pan = QSlider(Qt.Orientation.Horizontal)
        self.pan.setRange(-100, 100)
        self.pan.setValue(0)
        self.pan.setFixedWidth(96)
        self.pan.setToolTip("Pan (doppio click: centro)")
        self.pan.valueChanged.connect(self._on_pan)
        self.pan.sliderReleased.connect(self._notify)
        self.pan.mouseDoubleClickEvent = self._reset_pan  # type: ignore[method-assign]
        self.m_btn = QPushButton("M")
        self.s_btn = QPushButton("S")
        for b in (self.m_btn, self.s_btn):
            b.setCheckable(True)
            b.setFixedSize(30, 22)
            b.setObjectName("GhostMini")
        self.m_btn.setProperty("accent", "danger")
        self.m_btn.setToolTip("Muta la traccia (tasto 1-6)")
        self.s_btn.setProperty("accent", "solo")
        self.s_btn.setToolTip("Solo (Shift+1-6)")
        self.m_btn.toggled.connect(self._on_mute)
        self.s_btn.toggled.connect(self._on_solo)
        # EQ a 3 bande: pulsante che apre un popup con Bassi/Medi/Alti
        self.eq_btn = QPushButton("EQ")
        self.eq_btn.setFixedSize(34, 22)
        self.eq_btn.setObjectName("GhostMini")
        self.eq_btn.setProperty("accent", "ok")
        self.eq_btn.setToolTip("Equalizzatore 3 bande (Bassi / Medi / Alti)")
        self.eq_btn.clicked.connect(self._show_eq)
        self._eq = {"low": 0, "mid": 0, "high": 0}   # dB correnti
        self._eq_inflight: dict[str, int] = {}
        self._eq_thread: QThread | None = None
        self._eq_worker: EqWorker | None = None
        foot.addWidget(self.pan)
        foot.addStretch(1)
        foot.addWidget(self.eq_btn)
        foot.addWidget(self.m_btn)
        foot.addWidget(self.s_btn)
        cl.addLayout(foot)

        row.addWidget(ctrl, 0)

        self.wave = WaveformWidget(color)
        self.wave.setMinimumHeight(64)
        row.addWidget(self.wave, 1)

    def _notify(self) -> None:
        if self._on_change:
            self._on_change()

    def _on_gain(self, v: int) -> None:
        self.engine.set_gain(self.index, float(v))
        self.db_lbl.setText(f"{v:.1f} dB")

    def _on_pan(self, v: int) -> None:
        self.engine.set_pan(self.index, v / 100.0)

    def _reset_pan(self, _event) -> None:
        self.pan.setValue(0)
        self._notify()

    def _on_mute(self, b: bool) -> None:
        self.engine.set_mute(self.index, b)
        self._notify()

    def _on_solo(self, b: bool) -> None:
        self.engine.set_solo(self.index, b)
        self._notify()

    # ---------- EQ a 3 bande ----------

    def _eq_active(self) -> bool:
        return any(abs(v) > 0 for v in self._eq.values())

    def _refresh_eq_btn(self) -> None:
        theme.set_state(self.eq_btn, "on", self._eq_active())

    def _show_eq(self) -> None:
        """Popup con 3 cursori verticali per Bassi/Medi/Alti (-12..+12 dB)."""
        menu = QMenu(self)
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(14)
        sliders: dict[str, QSlider] = {}
        for key, label in (("low", "Bassi"), ("mid", "Medi"), ("high", "Alti")):
            col = QVBoxLayout(); col.setSpacing(4)
            val_lbl = QLabel(self._fmt_eq(self._eq[key]))
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            val_lbl.setStyleSheet(f"color:{theme.COLORS['text']}; font-size:11px;")
            sl = QSlider(Qt.Orientation.Vertical)
            sl.setRange(-12, 12); sl.setValue(int(self._eq[key]))
            sl.setFixedHeight(110)
            sl.valueChanged.connect(lambda v, lb=val_lbl: lb.setText(self._fmt_eq(v)))
            sl.sliderReleased.connect(self._apply_eq)
            name_lbl = QLabel(label)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            name_lbl.setStyleSheet(f"color:{theme.COLORS['muted']}; font-size:11px;")
            col.addWidget(val_lbl)
            col.addWidget(sl, 1, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(name_lbl)
            lay.addLayout(col)
            sliders[key] = sl
        reset = QPushButton("Reset")
        reset.setObjectName("GhostMini")
        reset.clicked.connect(lambda: ([s.setValue(0) for s in sliders.values()],
                                       self._apply_eq()))
        outer = QVBoxLayout(); outer.addWidget(host); outer.addWidget(reset)
        wrap = QWidget(); wrap.setLayout(outer)
        act = QWidgetAction(menu); act.setDefaultWidget(wrap)
        menu.addAction(act)
        self._eq_sliders = sliders
        menu.exec(self.eq_btn.mapToGlobal(self.eq_btn.rect().bottomLeft()))

    @staticmethod
    def _fmt_eq(v: int) -> str:
        return "0 dB" if v == 0 else f"{v:+d} dB"

    def _apply_eq(self) -> None:
        sliders = getattr(self, "_eq_sliders", None)
        if not sliders:
            return
        self._eq = {k: sl.value() for k, sl in sliders.items()}
        self._refresh_eq_btn()
        self._notify()
        if self._eq_thread and self._eq_thread.isRunning():
            return  # _on_eq_done ricontrolla e rilancia se serve
        self._start_eq_worker()

    def _start_eq_worker(self) -> None:
        """FFT full-file su thread separato: niente freeze UI al rilascio slider."""
        self._eq_inflight = dict(self._eq)
        self._eq_thread = QThread()
        self._eq_worker = EqWorker(self.engine, self.index, self._eq_inflight["low"],
                                    self._eq_inflight["mid"], self._eq_inflight["high"])
        self._eq_worker.moveToThread(self._eq_thread)
        self._eq_thread.started.connect(self._eq_worker.run)
        self._eq_worker.done.connect(self._on_eq_done)
        self._eq_worker.done.connect(self._eq_thread.quit)
        self._eq_thread.start()

    def _on_eq_done(self, _index: int) -> None:
        if self._eq != self._eq_inflight:
            self._start_eq_worker()   # slider mosso durante il calcolo

    def state(self) -> dict:
        return {
            "gain": self.fader.value(),
            "pan": self.pan.value() / 100.0,
            "mute": self.m_btn.isChecked(),
            "solo": self.s_btn.isChecked(),
            "eq": dict(self._eq),
        }

    def apply_state(self, st: dict) -> None:
        """Imposta i controlli da uno stato salvato senza riemettere segnali di salvataggio."""
        gain = int(st.get("gain", 0))
        self.fader.blockSignals(True)
        self.fader.setValue(gain)
        self.fader.blockSignals(False)
        self.db_lbl.setText(f"{gain:.1f} dB")
        self.engine.set_gain(self.index, float(gain))

        pan = int(round(float(st.get("pan", 0.0)) * 100))
        self.pan.blockSignals(True)
        self.pan.setValue(pan)
        self.pan.blockSignals(False)
        self.engine.set_pan(self.index, pan / 100.0)

        mute = bool(st.get("mute", False))
        self.m_btn.blockSignals(True)
        self.m_btn.setChecked(mute)
        self.m_btn.blockSignals(False)
        theme.repolish(self.m_btn)
        self.engine.set_mute(self.index, mute)

        solo = bool(st.get("solo", False))
        self.s_btn.blockSignals(True)
        self.s_btn.setChecked(solo)
        self.s_btn.blockSignals(False)
        theme.repolish(self.s_btn)
        self.engine.set_solo(self.index, solo)

        eq = st.get("eq")
        if isinstance(eq, dict):
            self._eq = {k: int(eq.get(k, 0)) for k in ("low", "mid", "high")}
            self._refresh_eq_btn()
            self.engine.set_eq(self.index, self._eq["low"], self._eq["mid"], self._eq["high"])


class MixerTab(QWidget):
    """Scheda mixer completa."""

    song_loaded = Signal(str, float)   # cartella, durata brano in secondi
    position_changed = Signal(float)   # posizione playback in secondi (dal _tick)

    def __init__(self):
        super().__init__()
        self.engine = MixerEngine()
        self.strips: list[TrackStrip] = []
        self._folder = ""
        self._an_thread: QThread | None = None
        self._an_worker: AnalyzeWorker | None = None
        self._st_thread: QThread | None = None
        self._st_worker: TransformWorker | None = None
        self._ex_thread: QThread | None = None
        self._ex_worker: ExportWorker | None = None
        self._xform_cache: dict[tuple[float, int], object] = {}
        self._loop_a: float | None = None
        self._loop_b: float | None = None
        # zoom waveform: finestra di vista globale [start, end] condivisa fra le tracce
        self._view: list[float] = [0.0, 1.0]
        # beat grid: frazioni dei beat correnti (per mostrarle/nasconderle)
        self._beat_fracs: list[float] = []
        # loop progressivo (auto-incremento velocità)
        self._autospeed_on = False
        self._autospeed_start = 60   # %
        self._autospeed_step = 5     # %
        self._autospeed_reps = 2     # giri di loop prima di accelerare
        self._autospeed_cycles = 0
        self._autospeed_last_lc = 0

        self._build_ui()
        self._setup_shortcuts()

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _setup_shortcuts(self) -> None:
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
        sc(Qt.Key.Key_Space, self._on_play)
        sc("L", lambda: self.loop_btn.toggle())
        sc(Qt.Key.Key_Home, lambda: self.engine.seek(0))
        sc("A", lambda: self._set_ab("a"))
        sc("B", lambda: self._set_ab("b"))
        for i in range(6):
            sc(str(i + 1), lambda i=i: self._toggle_track_mute(i))
            sc(f"Shift+{i + 1}", lambda i=i: self._toggle_track_solo(i))

    def _toggle_track_mute(self, i: int) -> None:
        if i < len(self.strips):
            self.strips[i].m_btn.toggle()

    def _toggle_track_solo(self, i: int) -> None:
        if i < len(self.strips):
            self.strips[i].s_btn.toggle()

    # ---------- costruzione ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== contenuto principale (margini interni) =====
        body = QVBoxLayout()
        body.setContentsMargins(18, 10, 18, 6)
        body.setSpacing(6)

        # --- bottoni azione (Accordatore / Esporta / Analizza / Recenti):
        #     montati da MainWindow come corner widget della barra schede ---
        self.recent_btn = QPushButton("Recenti")
        self.recent_btn.setObjectName("Ghost")
        self.recent_btn.setIcon(icons.icon("clock", theme.COLORS["muted"], 15))
        self.recent_btn.setToolTip("Apri / riapri una cartella di stem.")
        self.recent_btn.clicked.connect(self._show_recent_menu)
        self.analyze_btn = QPushButton("Analizza")
        self.analyze_btn.setObjectName("Ghost")
        self.analyze_btn.clicked.connect(self._on_analyze)
        self.analyze_btn.setEnabled(False)
        self.export_btn = QPushButton("Esporta…")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.setIcon(icons.icon("export", theme.COLORS["muted"], 15))
        self.export_btn.clicked.connect(self._on_export)
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip(
            "Esporta il mix corrente (mute/solo/volume/pan/velocità) in un file,\n"
            "oppure tutti gli stem come file separati con velocità/tono applicati.")
        self.tuner_btn = QPushButton("Accordatore")
        self.tuner_btn.setObjectName("Ghost")
        self.tuner_btn.setIcon(icons.icon("tuner", theme.COLORS["muted"], 15))
        self.tuner_btn.setToolTip("Accordatore: tono di riferimento A440 / corde + accordatore dal microfono.")
        self.tuner_btn.clicked.connect(self._open_tuner)
        self.actions_host = QWidget()
        ah = QHBoxLayout(self.actions_host)
        ah.setContentsMargins(0, 0, 12, 0)
        ah.setSpacing(6)
        for b in (self.tuner_btn, self.export_btn, self.analyze_btn, self.recent_btn):
            ah.addWidget(b)

        # --- header: titolo brano (sx) + azioni (dx); card di analisi sotto ---
        top = QHBoxLayout()
        top.setSpacing(12)
        self.title_lbl = QLabel("Nessuno stem caricato")
        self.title_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.title_lbl.setStyleSheet(
            f"font-size:20px; font-weight:700; color:{theme.COLORS['muted']};")
        self.title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_lbl.setMinimumWidth(0)
        top.addWidget(self.title_lbl, 1)
        top.addWidget(self.actions_host, 0)
        body.addLayout(top)

        cards_host = QWidget()
        self.cards_row = FlowLayout(cards_host, hspacing=6, vspacing=6)
        self.card_key = _card("TONALITÀ", "—", theme.COLORS["warn"])
        self.card_bpm = _card("BPM", "—")
        self.card_scale = _card("SCALA", "—")
        self.card_dur = _card("DURATA", "—")
        self.card_lufs = _card("LUFS", "—")
        self.card_dr = _card("DYN RANGE", "—")
        self.card_ts = _card("TEMPO STAB", "—", theme.COLORS["ok"])
        for c, _v in (self.card_key, self.card_bpm, self.card_scale, self.card_dur,
                      self.card_lufs, self.card_dr, self.card_ts):
            c.setMinimumWidth(74)
            self.cards_row.addWidget(c)
        body.addWidget(cards_host)

        # --- presenza per stem: pallino colorato + nome + % (reflow) ---
        presence_host = QWidget()
        self.presence_row = FlowLayout(presence_host, hspacing=18, vspacing=4)
        self.presence_lbls: dict[str, QLabel] = {}
        for name in STEM_ORDER:
            cell = QWidget()
            cb = QHBoxLayout(cell)
            cb.setContentsMargins(0, 0, 0, 0)
            cb.setSpacing(6)
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{STEM_COLORS[name]}; font-size:11px;")
            t = QLabel(STEM_LABEL[name].upper())
            t.setStyleSheet(f"color:{theme.COLORS['muted']}; font-size:11px;"
                            " font-weight:700; letter-spacing:1px;")
            v = QLabel("—")
            v.setStyleSheet(f"color:{STEM_COLORS[name]}; font-size:12px; font-weight:800;")
            cb.addWidget(dot)
            cb.addWidget(t)
            cb.addWidget(v)
            self.presence_lbls[name] = v
            self.presence_row.addWidget(cell)
        body.addWidget(presence_host)

        # --- riga meta: SEZIONI (sx) · ACCORDO (dx) · notazione ---
        self._sections: list[dict] = []
        self._sec_duration = 0.0
        self._chords: list[dict] = []
        self._chord_times: list[float] = []
        self._chord_shown = -2
        self._notation = config.load().get("chord_notation", "latin")

        meta = QHBoxLayout()
        meta.setSpacing(10)
        sec_title = QLabel("SEZIONI")
        sec_title.setProperty("class", "Eyebrow")
        self.sections_box = QHBoxLayout(); self.sections_box.setSpacing(4)
        self._sections_hint = QLabel("— analizza per rilevarle —")
        self._sections_hint.setStyleSheet(
            f"color:{theme.COLORS['faint']}; font-size:11px; font-style:italic;")
        self.sections_box.addWidget(self._sections_hint)
        self.sections_box.addStretch(1)
        sec_inner = QWidget(); sec_inner.setLayout(self.sections_box)

        ch_title = QLabel("ACCORDO")
        ch_title.setProperty("class", "Eyebrow")
        self.chord_now = QLabel("—")
        self.chord_now.setStyleSheet(
            f"color:{theme.COLORS['warn']}; font-size:22px; font-weight:800;")
        self.chord_now.setMinimumWidth(46)
        self.chord_next = QLabel("")
        self.chord_next.setStyleSheet(f"color:{theme.COLORS['muted']}; font-size:14px;")
        self.notation_btn = QPushButton("Do Re Mi" if self._notation == "latin" else "C D E")
        self.notation_btn.setObjectName("GhostMini")
        self.notation_btn.setFixedWidth(84)
        self.notation_btn.setToolTip("Cambia notazione accordi (Do Re Mi ↔ C D E)")
        self.notation_btn.clicked.connect(self._toggle_notation)
        meta.addWidget(sec_title)
        meta.addWidget(sec_inner, 1)
        meta.addWidget(ch_title)
        meta.addWidget(self.chord_now)
        meta.addWidget(self.chord_next)
        meta.addWidget(self.notation_btn)
        body.addLayout(meta)

        # --- timeline + strisce + scrollbar zoom ---
        self.timeline = TimelineWidget(self.engine)
        self.timeline.seeked.connect(self._on_wave_seek)
        body.addWidget(self.timeline)

        self.strips_box = QVBoxLayout()
        self.strips_box.setSpacing(1)
        strips_host = QWidget()
        strips_host.setObjectName("StripsHost")
        strips_host.setLayout(self.strips_box)
        body.addWidget(strips_host, 1)

        self.zoom_scrollbar = QScrollBar(Qt.Orientation.Horizontal)
        self.zoom_scrollbar.setObjectName("ZoomScrollBar")
        self.zoom_scrollbar.setRange(0, 10000)
        self.zoom_scrollbar.setValue(0)
        self.zoom_scrollbar.setPageStep(10000)
        self.zoom_scrollbar.valueChanged.connect(self._on_scrollbar_changed)
        body.addWidget(self.zoom_scrollbar)

        root.addLayout(body, 1)

        # ===== barra di trasporto: gruppi etichettati che vanno a capo =====
        mut = theme.COLORS["muted"]
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(40, 120)
        self.speed_slider.setValue(100)
        self.speed_slider.setMinimumWidth(120)
        self.speed_slider.setMaximumWidth(160)
        self.speed_slider.setToolTip(
            "Velocità a tono invariato (40–120%).\nUsa i preset per scendere di colpo allo studio lento.")
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.speed_slider.sliderReleased.connect(self._apply_transform)
        self.speed_lbl = QLabel("x1.00")
        self.speed_lbl.setStyleSheet(
            f"color:{theme.COLORS['text']}; font-size:12px; font-weight:600;")
        self.speed_presets: list[tuple[int, QPushButton]] = []
        preset_box = QHBoxLayout(); preset_box.setSpacing(3)
        preset_box.setContentsMargins(0, 0, 0, 0)
        for pct in (50, 75, 90, 100):
            b = QPushButton(f"{pct}")
            b.setObjectName("GhostMini"); b.setMinimumWidth(34); b.setCheckable(True)
            b.setProperty("accent", "ok")
            b.setToolTip(f"Imposta la velocità al {pct}% (tono invariato)")
            b.clicked.connect(lambda _=False, p=pct: self._set_speed_preset(p))
            self.speed_presets.append((pct, b))
            preset_box.addWidget(b)
        preset_host = QWidget(); preset_host.setLayout(preset_box)
        # trasposizione (semitoni)
        self.pitch_slider = QSlider(Qt.Orientation.Horizontal)
        self.pitch_slider.setRange(-6, 6)
        self.pitch_slider.setValue(0)
        self.pitch_slider.setMinimumWidth(90)
        self.pitch_slider.setMaximumWidth(120)
        self.pitch_slider.setToolTip("Trasposizione in semitoni (tempo invariato)")
        self.pitch_slider.valueChanged.connect(
            lambda v: self.pitch_lbl.setText(self._fmt_semis(v)))
        self.pitch_slider.sliderReleased.connect(self._apply_transform)
        self.pitch_lbl = QLabel("0 st")
        self.pitch_lbl.setStyleSheet(
            f"color:{theme.COLORS['text']}; font-size:12px; font-weight:600;")
        # step rapido ±1 semitono
        self.pitch_down_btn = QPushButton()
        self.pitch_down_btn.setIcon(icons.icon("minus", mut, 12))
        self.pitch_up_btn = QPushButton()
        self.pitch_up_btn.setIcon(icons.icon("plus", mut, 12))
        for b in (self.pitch_down_btn, self.pitch_up_btn):
            b.setObjectName("GhostMini"); b.setMinimumWidth(28)
        self.pitch_down_btn.setToolTip("Un semitono in giù")
        self.pitch_up_btn.setToolTip("Un semitono in su")
        self.pitch_down_btn.clicked.connect(lambda: self._step_pitch(-1))
        self.pitch_up_btn.clicked.connect(lambda: self._step_pitch(+1))
        # loop
        self.a_btn = QPushButton("A"); self.b_btn = QPushButton("B")
        self.loop_btn = QPushButton("Loop"); self.loop_btn.setCheckable(True)
        self.loop_btn.setProperty("accent", "ok")
        self.loop_btn.setIcon(icons.icon("repeat", mut, 13, on_color=theme.COLORS["bg"]))
        self.loopclr_btn = QPushButton()
        self.loopclr_btn.setIcon(icons.icon("x", mut, 12))
        for b in (self.a_btn, self.b_btn, self.loopclr_btn):
            b.setObjectName("GhostMini"); b.setMinimumWidth(32)
        self.loop_btn.setObjectName("GhostMini"); self.loop_btn.setMinimumWidth(64)
        self.a_btn.setToolTip("Imposta l'inizio del loop al punto attuale (tasto A)\n"
                              "Suggerimento: Ctrl/Shift+trascina sulla waveform per selezionare il loop")
        self.b_btn.setToolTip("Imposta la fine del loop al punto attuale (tasto B)")
        self.loop_btn.setToolTip("Attiva/disattiva la ripetizione della regione A-B (tasto L)")
        self.loopclr_btn.setToolTip("Cancella il loop A-B")
        self.a_btn.clicked.connect(lambda: self._set_ab("a"))
        self.b_btn.clicked.connect(lambda: self._set_ab("b"))
        self.loop_btn.toggled.connect(self._on_loop_toggle)
        self.loopclr_btn.clicked.connect(self._on_loop_clear)
        # loop progressivo: accelera ad ogni N giri fino al 100%
        self.autospeed_btn = QPushButton("Auto")
        self.autospeed_btn.setObjectName("GhostMini")
        self.autospeed_btn.setMinimumWidth(56)
        self.autospeed_btn.setProperty("accent", "warn")
        self.autospeed_btn.setIcon(icons.icon("gauge", mut, 13))
        self.autospeed_btn.setToolTip(
            "Loop progressivo: parte lento e accelera ad ogni giro fino a 100%.\n"
            "Clicca per configurare e attivare.")
        self.autospeed_btn.clicked.connect(self._show_autospeed)
        # zoom waveform (vista condivisa fra le tracce)
        self.zoomout_btn = QPushButton()
        self.zoomout_btn.setIcon(icons.icon("zoom-out", mut, 13))
        self.zoomin_btn = QPushButton()
        self.zoomin_btn.setIcon(icons.icon("zoom-in", mut, 13))
        self.zoomfit_btn = QPushButton()
        self.zoomfit_btn.setIcon(icons.icon("maximize", mut, 13))
        for b in (self.zoomout_btn, self.zoomin_btn, self.zoomfit_btn):
            b.setObjectName("GhostMini"); b.setMinimumWidth(32)
        self.zoomout_btn.setToolTip("Zoom indietro (anche Ctrl+rotella sulla traccia)")
        self.zoomin_btn.setToolTip("Zoom avanti (anche Ctrl+rotella sulla traccia)")
        self.zoomfit_btn.setToolTip("Adatta: mostra tutto il brano")
        self.zoomin_btn.clicked.connect(lambda: self._zoom_at(2, None))
        self.zoomout_btn.clicked.connect(lambda: self._zoom_at(-2, None))
        self.zoomfit_btn.clicked.connect(self._zoom_reset)
        # toggle griglia beat sulle waveform (default acceso)
        self.beatgrid_btn = QPushButton("Griglia"); self.beatgrid_btn.setCheckable(True)
        self.beatgrid_btn.setObjectName("GhostMini"); self.beatgrid_btn.setMinimumWidth(64)
        self.beatgrid_btn.setProperty("accent", "ok")
        self.beatgrid_btn.setIcon(icons.icon("grid", mut, 13, on_color=theme.COLORS["bg"]))
        self.beatgrid_btn.setChecked(True)
        self.beatgrid_btn.setToolTip("Mostra/nascondi la griglia dei beat sulle waveform.")
        self.beatgrid_btn.toggled.connect(self._on_beatgrid_toggle)
        # metronomo
        self.click_btn = QPushButton("Click"); self.click_btn.setCheckable(True)
        self.click_btn.setObjectName("GhostMini"); self.click_btn.setMinimumWidth(60)
        self.click_btn.setProperty("accent", "danger")
        self.click_btn.setIcon(icons.icon("metronome", mut, 13, on_color="#ffffff"))
        self.click_btn.toggled.connect(self._on_click_toggle)
        # toggle griglia regolare (steady) vs beat rilevati
        self.steady_btn = QPushButton("Steady"); self.steady_btn.setCheckable(True)
        self.steady_btn.setObjectName("GhostMini"); self.steady_btn.setMinimumWidth(58)
        self.steady_btn.setProperty("accent", "ok")
        self.steady_btn.setChecked(True)
        self.steady_btn.setToolTip(
            "ON: click a tempo costante (steady).\nOFF: segue i beat rilevati dal brano.")
        self.steady_btn.toggled.connect(self._on_steady_toggle)
        self.click_vol = QSlider(Qt.Orientation.Horizontal)
        self.click_vol.setRange(0, 100); self.click_vol.setValue(60)
        self.click_vol.setMinimumWidth(60)
        self.click_vol.setMaximumWidth(80)
        self.click_vol.setToolTip("Volume del click")
        self.click_vol.valueChanged.connect(lambda v: self.engine.set_click(self.click_btn.isChecked(), v / 100))

        # transport play/stop/tempo: play tondo con icona play/pausa
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayButton")
        self.play_btn.setFixedSize(46, 46)
        self.play_btn.setIconSize(QSize(19, 19))
        self.play_btn.setCheckable(True)   # checked = in riproduzione (icona pausa)
        self.play_btn.setIcon(icons.icon("play", "#ffffff", 19, on_name="pause"))
        self.play_btn.setToolTip("Riproduci / pausa (Spazio)")
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("GhostMini")
        self.stop_btn.setFixedSize(32, 32)
        self.stop_btn.setIcon(icons.icon("stop", mut, 13))
        self.stop_btn.setToolTip("Stop (torna all'inizio)")
        self.stop_btn.clicked.connect(self._on_stop)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setStyleSheet(
            f"color:{theme.COLORS['text']}; font-size:13px;"
            " font-family:'Cascadia Code','Consolas',monospace;")
        # master
        self.master = QSlider(Qt.Orientation.Horizontal)
        self.master.setRange(-40, 6)
        self.master.setValue(0)
        self.master.setMinimumWidth(100)
        self.master.setMaximumWidth(130)
        self.master.valueChanged.connect(lambda v: self.engine.set_master(float(v)))

        # altezza uniforme per i pulsantini → allineati ai cursori
        for _b in (self.a_btn, self.b_btn, self.loop_btn,
                   self.loopclr_btn, self.autospeed_btn, self.zoomout_btn,
                   self.zoomin_btn, self.zoomfit_btn, self.beatgrid_btn,
                   self.click_btn, self.steady_btn,
                   self.pitch_down_btn, self.pitch_up_btn,
                   *(pb for _p, pb in self.speed_presets)):
            _b.setFixedHeight(30)
        for _s in (self.speed_slider, self.pitch_slider, self.click_vol, self.master):
            _s.setFixedHeight(22)

        def _tgroup(caption: str, *widgets) -> QFrame:
            """Gruppo etichettato del trasporto (frame + eyebrow + riga controlli)."""
            f = QFrame()
            f.setObjectName("TransportGroup")
            v = QVBoxLayout(f)
            v.setContentsMargins(12, 6, 12, 8)
            v.setSpacing(3)
            cap = QLabel(caption)
            cap.setProperty("class", "Eyebrow")
            v.addWidget(cap)
            rw = QHBoxLayout()
            rw.setSpacing(6)
            for w in widgets:
                rw.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
            v.addLayout(rw)
            return f

        # ancore fisse (play/stop/tempo a sinistra, master a destra); i gruppi
        # centrali stanno in un FlowLayout: su finestre strette vanno a capo
        # invece di uscire dallo schermo.
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(12)
        bar.addWidget(_hgroup(self.play_btn, self.stop_btn, self.time_lbl, spacing=10),
                      0, Qt.AlignmentFlag.AlignVCenter)
        groups_host = QWidget()
        groups_host.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Preferred)
        groups = FlowLayout(groups_host, hspacing=8, vspacing=6)
        groups.addWidget(_tgroup("VELOCITÀ", self.speed_lbl, self.speed_slider,
                                 preset_host))
        groups.addWidget(_tgroup("TONO", self.pitch_lbl, self.pitch_down_btn,
                                 self.pitch_slider, self.pitch_up_btn))
        groups.addWidget(_tgroup("LOOP", self.a_btn, self.b_btn, self.loop_btn,
                                 self.loopclr_btn, self.autospeed_btn))
        groups.addWidget(_tgroup("ZOOM", self.zoomout_btn, self.zoomin_btn,
                                 self.zoomfit_btn, self.beatgrid_btn))
        groups.addWidget(_tgroup("CLICK", self.click_btn, self.steady_btn,
                                 self.click_vol))
        groups.addWidget(_tgroup("MASTER", self.master))
        bar.addWidget(groups_host, 1)

        transport = QFrame()
        transport.setObjectName("TransportBar")
        # verticale Preferred (non Fixed): quando i gruppi vanno a capo nel
        # FlowLayout la barra cresce invece di tagliarli (heightForWidth)
        transport.setSizePolicy(QSizePolicy.Policy.Preferred,
                                QSizePolicy.Policy.Preferred)
        tb = QHBoxLayout(transport)
        tb.setContentsMargins(16, 8, 16, 8)
        tb.addLayout(bar)
        root.addWidget(transport, 0)

        self._set_loaded(False)

    def _set_loaded(self, loaded: bool) -> None:
        self.play_btn.setEnabled(loaded)
        self.stop_btn.setEnabled(loaded)
        self.export_btn.setEnabled(loaded)

    # ---------- caricamento ----------

    def _on_load_dialog(self) -> None:
        # parti dalla stessa cartella di destinazione impostata nella scheda Scarica
        start = config.load().get("dest_dir", "") or paths.default_download_dir()
        d = QFileDialog.getExistingDirectory(self, "Scegli una cartella di stem", start)
        if d:
            self.load_folder(d)

    def _set_song_title(self, name: str) -> None:
        """Titolo brano: nome cartella in evidenza (rosa)."""
        safe = name.replace("<", "&lt;").replace(">", "&gt;")
        self.title_lbl.setText(
            f"<span style='color:{STEM_COLORS['vocals']};'>♪ {safe}</span>")

    def _show_recent_menu(self) -> None:
        """Menu: carica una cartella + stem recenti (dalla cronologia)."""
        recents = history.stem_recents()
        menu = QMenu(self)
        menu.addAction("Carica cartella stem…", self._on_load_dialog)
        menu.addSeparator()
        if not recents:
            act = menu.addAction("(nessuno stem recente)")
            act.setEnabled(False)
        else:
            for e in recents:
                title = e.get("title") or os.path.basename(e.get("filepath", "")) or "?"
                fmt = e.get("format") or ""
                label = f"{title}   ·   {fmt}" if fmt else title
                folder = e.get("filepath", "")
                menu.addAction(label, lambda f=folder: self.load_folder(f))
        menu.exec(self.recent_btn.mapToGlobal(self.recent_btn.rect().bottomLeft()))

    def load_folder(self, folder: str) -> None:
        exts = (".wav", ".flac", ".mp3")
        all_files = [f for f in os.listdir(folder) if f.lower().endswith(exts)] if os.path.isdir(folder) else []
        if not all_files:
            toast(self, "Nessun file audio nella cartella scelta.", "warn")
            return
        # ordina secondo STEM_ORDER, gli altri in coda
        def keyf(fn: str) -> int:
            stem = os.path.splitext(fn)[0].lower()
            return STEM_ORDER.index(stem) if stem in STEM_ORDER else 99
        all_files.sort(key=keyf)
        files = [(os.path.splitext(f)[0].lower(), os.path.join(folder, f)) for f in all_files]

        self.engine.stop()
        self.engine.load_files(files)
        self._folder = folder
        self._set_song_title(os.path.basename(folder))
        self._view = [0.0, 1.0]   # nuovo brano: zoom azzerato
        self._build_strips(files)
        self._set_loaded(True)
        self.analyze_btn.setEnabled(True)

        # reset velocità / trasposizione / loop / click
        self._xform_cache = {}
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(100)
        self.speed_slider.blockSignals(False)
        self.speed_lbl.setText("x1.00")
        self._refresh_speed_presets(100)
        self.pitch_slider.blockSignals(True)
        self.pitch_slider.setValue(0)
        self.pitch_slider.blockSignals(False)
        self.pitch_lbl.setText("0 st")
        self._loop_a = self._loop_b = None
        self.loop_btn.setChecked(False)
        self.click_btn.setChecked(False)
        self.click_btn.setEnabled(False)

        # analisi: usa la cache se c'è, altrimenti analizza subito da solo
        data = stems.load_analysis(folder)
        if data:
            self._apply_analysis(data)
        else:
            self._clear_analysis()
            # auto-analisi in background se il motore è pronto. Silenzioso:
            # niente popup qui (a differenza del click manuale su "Analizza");
            # _on_analyze gestisce già il caso di un'analisi già in corso.
            if stems.engine_ready():
                self._on_analyze()

        # ripristina la sessione mixer salvata (fader/pan/mute/solo/velocità/tono)
        self._load_session()

        # registra in cronologia per la 'Recenti' (senza sovrascrivere le voci di
        # separazione che riportano la modalità: aggiunge solo cartelle non note)
        try:
            known = {e.get("filepath") for e in history.load()}
            if folder not in known:
                history.add(os.path.basename(folder), "", "stem", folder)
        except Exception:  # noqa: BLE001
            pass

        self.song_loaded.emit(folder, self.engine.duration())

    def _build_strips(self, files: list[tuple[str, str]]) -> None:
        # svuota
        while self.strips_box.count():
            it = self.strips_box.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.strips = []
        # peaks dal buffer già caricato nell'engine
        for i, t in enumerate(self.engine.tracks):
            strip = TrackStrip(i, t.name, self.engine, on_change=self._save_session)
            mono = t.data.mean(axis=1)
            mn, mx = compute_peaks(mono, 1600)
            strip.wave.set_peaks(mn, mx)
            strip.wave.seeked.connect(self._on_wave_seek)
            strip.wave.loop_selected.connect(self._on_wave_loop)
            strip.wave.wheel_zoom.connect(self._on_wheel_zoom)
            strip.wave.wheel_pan.connect(self._on_wheel_pan)
            self.strips_box.addWidget(strip)
            self.strips.append(strip)
        self._apply_view()

    # ---------- zoom waveform (vista condivisa fra le tracce) ----------

    MIN_VIEW_SPAN = 0.02   # zoom massimo ~50x

    def _apply_view(self) -> None:
        for s in self.strips:
            s.wave.set_view(self._view[0], self._view[1])
        if hasattr(self, "timeline"):
            self.timeline.set_view(self._view[0], self._view[1])
        if hasattr(self, "zoom_scrollbar"):
            s, e = self._view
            span = e - s
            self.zoom_scrollbar.blockSignals(True)
            self.zoom_scrollbar.setRange(0, int(10000 * (1.0 - span)))
            self.zoom_scrollbar.setPageStep(int(10000 * span))
            self.zoom_scrollbar.setValue(int(10000 * s))
            self.zoom_scrollbar.blockSignals(False)

    def _zoom_at(self, steps: int, center: float | None) -> None:
        """Zoom tenendo fisso `center` (frazione globale); None = centro vista."""
        s, e = self._view
        span = e - s
        if span <= 0:
            return
        if center is None:
            center = s + span / 2.0
        new_span = max(self.MIN_VIEW_SPAN, min(1.0, span * (0.8 ** steps)))
        ns = center - (center - s) * (new_span / span)
        ne = ns + new_span
        if ns < 0.0:
            ns, ne = 0.0, new_span
        if ne > 1.0:
            ne, ns = 1.0, 1.0 - new_span
        self._view = [max(0.0, ns), min(1.0, ne)]
        self._apply_view()

    def _zoom_reset(self) -> None:
        self._view = [0.0, 1.0]
        self._apply_view()

    def _on_wheel_zoom(self, steps: int, center: float) -> None:
        self._zoom_at(steps, center)

    def _on_wheel_pan(self, steps: int) -> None:
        s, e = self._view
        span = e - s
        if span >= 1.0:
            return
        delta = steps * span * 0.15
        delta = max(delta, -s)            # non oltre il bordo sinistro
        delta = min(delta, 1.0 - e)       # né oltre il destro
        self._view = [s + delta, e + delta]
        self._apply_view()

    def _on_scrollbar_changed(self, value: int) -> None:
        s, e = self._view
        span = e - s
        ns = value / 10000.0
        ne = ns + span
        self._view = [max(0.0, ns), min(1.0, ne)]
        self._apply_view()

    def _on_beatgrid_toggle(self, on: bool) -> None:
        fr = self._beat_fracs if on else []
        for s in getattr(self, "strips", []):
            s.wave.set_beats(fr)

    # ---------- analisi ----------

    def _clear_analysis(self) -> None:
        for _c, v in (self.card_key, self.card_bpm, self.card_scale, self.card_dur,
                      self.card_lufs, self.card_dr, self.card_ts):
            v.setText("—")
        self.card_dur[1].setText(_fmt_time(self.engine.duration()))
        for name in STEM_ORDER:
            self.presence_lbls[name].setText("—")
        self._chords = []
        self._chord_times = []
        self.chord_now.setText("—")
        self.chord_next.setText("")
        self._sections = []
        self._sec_duration = 0.0
        self._build_sections()
        self._update_section_markers()
        self._beat_fracs = []
        for s in getattr(self, "strips", []):
            s.wave.set_beats([])
        if hasattr(self, "timeline"):
            self.timeline.set_data([], self.engine.duration())

    def _apply_analysis(self, d: dict) -> None:
        key = d.get("key")
        mode = d.get("mode", "")
        self.card_key[1].setText(f"{key} {mode}" if key else "—")
        self.card_bpm[1].setText(str(d.get("bpm") or "—"))
        self.card_scale[1].setText(d.get("scale") or "—")
        self.card_dur[1].setText(_fmt_time(d.get("duration", self.engine.duration())))
        self.card_lufs[1].setText(str(d.get("lufs")) if d.get("lufs") is not None else "—")
        self.card_dr[1].setText(str(d.get("dynamic_range")) if d.get("dynamic_range") is not None else "—")
        ts = d.get("tempo_stability")
        self.card_ts[1].setText(f"{ts}%" if ts is not None else "—")
        pres = d.get("presence", {})
        for name in STEM_ORDER:
            self.presence_lbls[name].setText(f"{pres[name]}%" if name in pres else "—")
        # metronomo: abilita se ci sono i beat
        beats = d.get("beat_times") or []
        self.engine.set_beats(beats)
        self.click_btn.setEnabled(bool(beats))
        self.click_btn.setToolTip("" if beats else "Ri-analizza per abilitare il metronomo.")
        # beat grid sulle waveform (rispetta il toggle Griglia)
        dur = float(d.get("duration") or self.engine.duration() or 0.0)
        self._beat_fracs = [t / dur for t in beats if dur > 0 and 0.0 < t < dur]
        show = self._beat_fracs if self.beatgrid_btn.isChecked() else []
        for s in getattr(self, "strips", []):
            s.wave.set_beats(show)
        if hasattr(self, "timeline"):
            self.timeline.set_data(beats, dur)
        # accordi rilevati
        self._chords = [c for c in (d.get("chords") or []) if isinstance(c, dict)]
        self._chord_times = [float(c.get("time", 0.0)) for c in self._chords]
        self._refresh_chords(force=True)
        # sezioni (struttura)
        self._sections = [s for s in (d.get("sections") or []) if isinstance(s, dict)]
        self._sec_duration = float(d.get("duration") or self.engine.duration() or 0.0)
        self._build_sections()
        self._update_section_markers()

    def _on_analyze(self) -> None:
        if not self._folder or (self._an_thread and self._an_thread.isRunning()):
            return
        if not stems.engine_ready():
            toast(self, "Serve il motore stem: installalo da Impostazioni → Motore stem.",
                  "warn")
            return
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("Analizzo…")
        self._an_thread = QThread()
        self._an_worker = AnalyzeWorker(self._folder)
        self._an_worker.moveToThread(self._an_thread)
        self._an_thread.started.connect(self._an_worker.run)
        self._an_worker.done.connect(self._on_analyze_done)
        self._an_worker.done.connect(self._an_thread.quit)
        self._an_thread.start()

    def _on_analyze_done(self, ok: bool, data: dict) -> None:
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText("Analizza")
        if ok:
            self._apply_analysis(data)
        else:
            toast(self, f"Analisi fallita: {data.get('error', '')}", "error")

    # ---------- accordi ----------

    def _toggle_notation(self) -> None:
        self._notation = "anglo" if self._notation == "latin" else "latin"
        self.notation_btn.setText("Do Re Mi" if self._notation == "latin" else "C D E")
        cfg = config.load()
        cfg["chord_notation"] = self._notation
        config.save(cfg)
        self._refresh_chords(force=True)

    def _current_chord_index(self, orig_time: float) -> int:
        """Indice dell'accordo attivo all'istante orig_time (dominio originale), o -1."""
        if not self._chord_times:
            return -1
        return bisect.bisect_right(self._chord_times, orig_time) - 1

    def _refresh_chords(self, force: bool = False) -> None:
        """Aggiorna l'accordo corrente/successivo in base alla posizione di riproduzione.
        I tempi degli accordi sono nel dominio originale → scalati per la velocità."""
        if not self._chords:
            if force:
                self.chord_now.setText("—")
                self.chord_next.setText("")
            return
        orig_time = self.engine.position() * max(self.engine.speed, 1e-6)
        i = self._current_chord_index(orig_time)
        if not force and i == getattr(self, "_chord_shown", -2):
            return
        self._chord_shown = i
        cur = self._chords[i] if i >= 0 else None
        nxt = self._chords[i + 1] if 0 <= i + 1 < len(self._chords) else None
        self.chord_now.setText(
            chord_label(cur["root"], cur["quality"], self._notation) if cur else "—")
        self.chord_next.setText(
            "→ " + chord_label(nxt["root"], nxt["quality"], self._notation) if nxt else "")

    # ---------- sezioni (struttura) ----------

    def _build_sections(self) -> None:
        """(Ri)costruisce i pulsanti-sezione dalla lista corrente."""
        while self.sections_box.count():
            item = self.sections_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not self._sections:
            hint = QLabel("— analizza per rilevarle —")
            hint.setStyleSheet(
                f"color:{theme.COLORS['faint']}; font-size:11px; font-style:italic;")
            self.sections_box.addWidget(hint)
            self.sections_box.addStretch(1)
            return
        for i, sec in enumerate(self._sections):
            t = float(sec.get("time", 0.0))
            lbl = str(sec.get("label", "?"))
            btn = QPushButton(f"{lbl}  {_fmt_time(t)}")
            btn.setObjectName("GhostMini")
            btn.setToolTip("Clic = vai alla sezione · Ctrl+clic = loop su questa sezione")
            btn.clicked.connect(lambda _=False, idx=i: self._on_section_click(idx))
            self.sections_box.addWidget(btn)
        self.sections_box.addStretch(1)

    def _update_section_markers(self) -> None:
        if self._sec_duration > 0 and self._sections:
            fracs = [float(s["time"]) / self._sec_duration
                     for s in self._sections if float(s.get("time", 0)) > 0]
        else:
            fracs = []
        for s in self.strips:
            s.wave.set_markers(fracs)

    def _on_section_click(self, i: int) -> None:
        if not (0 <= i < len(self._sections)) or self._sec_duration <= 0:
            return
        a = max(0.0, min(1.0, float(self._sections[i]["time"]) / self._sec_duration))
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            nt = (float(self._sections[i + 1]["time"]) if i + 1 < len(self._sections)
                  else self._sec_duration)
            b = max(0.0, min(1.0, nt / self._sec_duration))
            self._loop_a, self._loop_b = a, b
            if self.loop_btn.isChecked():
                self._apply_loop()
            else:
                self.loop_btn.setChecked(True)   # → _on_loop_toggle → _apply_loop
        self.engine.seek(a * self.engine.duration())

    # ---------- accordatore ----------

    def _open_tuner(self) -> None:
        from .ui_tuner import TunerDialog
        # ferma la riproduzione del mixer per non interferire con il microfono
        if self.engine.is_playing():
            self.engine.pause()
            self._sync_play_btn()
        dlg = TunerDialog(self)
        dlg.exec()

    # ---------- trasporto ----------

    def _sync_play_btn(self) -> None:
        playing = self.engine.is_playing()
        if self.play_btn.isChecked() != playing:
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(playing)
            self.play_btn.blockSignals(False)

    def _on_play_clicked(self) -> None:
        # il click ha già invertito lo stato checked: riallineato in _on_play
        self._on_play()

    def _on_play(self) -> None:
        if self.engine.is_playing():
            self.engine.pause()
        else:
            self.engine.play()
        self._sync_play_btn()

    def toggle_play(self) -> None:
        """Alias pubblico usato dalla playbar globale."""
        self._on_play()

    def stop_playback(self) -> None:
        """Alias pubblico usato dalla playbar globale."""
        self._on_stop()

    def _on_stop(self) -> None:
        self.engine.stop()
        self._sync_play_btn()

    def _on_wave_seek(self, frac: float) -> None:
        self.engine.seek(frac * self.engine.duration())

    def _on_wave_loop(self, a: float, b: float) -> None:
        """Selezione loop trascinata sulla waveform (Shift+trascina)."""
        if b - a < 0.01:   # selezione troppo piccola: ripristina lo stato attuale
            self._apply_loop()
            return
        self._loop_a, self._loop_b = a, b
        if self.loop_btn.isChecked():
            self._apply_loop()
        else:
            self.loop_btn.setChecked(True)   # attiva il loop → _on_loop_toggle → _apply_loop

    # ---------- velocità (time-stretch) + trasposizione (pitch shift) ----------

    @staticmethod
    def _fmt_semis(v: int) -> str:
        return "0 st" if v == 0 else f"{v:+d} st"

    def _on_speed_changed(self, v: int) -> None:
        self.speed_lbl.setText(f"x{v / 100:.2f}")
        self._refresh_speed_presets(v)

    def _refresh_speed_presets(self, pct: int | None = None) -> None:
        """Evidenzia il preset che corrisponde alla velocità corrente."""
        if pct is None:
            pct = self.speed_slider.value()
        for value, btn in self.speed_presets:
            on = (value == pct)
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
            theme.repolish(btn)

    def _set_speed_preset(self, pct: int) -> None:
        """Imposta la velocità a un valore preimpostato e applica subito."""
        pct = max(self.speed_slider.minimum(), min(self.speed_slider.maximum(), pct))
        self.speed_slider.setValue(pct)   # aggiorna label + evidenza via _on_speed_changed
        self._apply_transform()

    def _step_pitch(self, delta: int) -> None:
        """Sposta la trasposizione di un semitono e applica subito."""
        self.pitch_slider.setValue(self.pitch_slider.value() + delta)  # clampa al range
        self._apply_transform()

    def _set_xform_busy(self, busy: bool) -> None:
        self.speed_slider.setEnabled(not busy)
        self.pitch_slider.setEnabled(not busy)
        self.pitch_down_btn.setEnabled(not busy)
        self.pitch_up_btn.setEnabled(not busy)
        for _v, b in self.speed_presets:
            b.setEnabled(not busy)
        if busy:
            slowing = self.speed_slider.value() < 100
            self.speed_lbl.setStyleSheet(
                f"color:{theme.COLORS['warn']}; font-size:11px;")
            self.speed_lbl.setText("rallento…" if slowing else "elaboro…")
        else:
            self.speed_lbl.setStyleSheet(
                f"color:{theme.COLORS['text']}; font-size:12px; font-weight:600;")
            self.speed_lbl.setText(f"x{self.speed_slider.value() / 100:.2f}")
            self.pitch_lbl.setText(self._fmt_semis(self.pitch_slider.value()))

    def _apply_transform(self) -> None:
        """Applica velocità + trasposizione correnti (cache per combinazione, calcolo in thread)."""
        if not self.engine.tracks:
            return
        speed = self.speed_slider.value() / 100.0
        semis = int(self.pitch_slider.value())
        key = (round(speed, 2), semis)
        if key == (round(self.engine.speed, 2), int(self.engine.semitones)):
            return
        if self._st_thread and self._st_thread.isRunning():
            return  # ricontrollato a fine elaborazione
        if key == (1.0, 0):
            self.engine.apply_transform([t.data_orig for t in self.engine.tracks], speed, semis)
            self._save_session()
            return
        cached = self._xform_cache.get(key)
        if cached is not None:
            self.engine.apply_transform(cached, speed, semis)
            self._save_session()
            return
        self._set_xform_busy(True)
        self._st_thread = QThread()
        self._st_worker = TransformWorker(self.engine, speed, semis)
        self._st_worker.moveToThread(self._st_thread)
        self._st_thread.started.connect(self._st_worker.run)
        self._st_worker.done.connect(self._on_transform_done)
        self._st_worker.done.connect(self._st_thread.quit)
        self._st_thread.start()

    def _on_transform_done(self, buffers, speed: float, semis: float) -> None:
        self._set_xform_busy(False)
        if buffers is None:
            toast(self, "Elaborazione audio fallita.", "error")
            # riallinea i cursori allo stato attuale del motore per non ritentare in loop
            self.speed_slider.blockSignals(True)
            self.speed_slider.setValue(int(round(self.engine.speed * 100)))
            self.speed_slider.blockSignals(False)
            self.pitch_slider.blockSignals(True)
            self.pitch_slider.setValue(int(self.engine.semitones))
            self.pitch_slider.blockSignals(False)
            self._set_xform_busy(False)
            return
        self._xform_cache[(round(speed, 2), int(semis))] = buffers
        self.engine.apply_transform(buffers, speed, semis)
        self._save_session()
        # i cursori potrebbero essere cambiati durante l'elaborazione: ricontrolla
        QTimer.singleShot(0, self._apply_transform)

    # ---------- loop A-B ----------

    def _set_ab(self, which: str) -> None:
        dur = self.engine.duration()
        frac = (self.engine.position() / dur) if dur else 0.0
        if which == "a":
            self._loop_a = frac
        else:
            self._loop_b = frac
        self._apply_loop()

    def _apply_loop(self) -> None:
        a = self._loop_a if self._loop_a is not None else 0.0
        b = self._loop_b if self._loop_b is not None else 1.0
        if b < a:
            a, b = b, a
        self.engine.set_loop(a, b, self.loop_btn.isChecked())
        region = (a, b) if (self._loop_a is not None or self._loop_b is not None) else None
        for s in self.strips:
            s.wave.set_loop(region)
        self._save_session()

    def _on_loop_toggle(self, _b: bool) -> None:
        self._apply_loop()

    def _on_loop_clear(self) -> None:
        self._loop_a = self._loop_b = None
        self.loop_btn.setChecked(False)
        self.engine.clear_loop()
        for s in self.strips:
            s.wave.set_loop(None)
        if self._autospeed_on:
            self._set_autospeed_active(False)
        self._save_session()

    # ---------- loop progressivo (auto-incremento velocità) ----------

    def _show_autospeed(self) -> None:
        """Popup: configura e attiva il loop progressivo (parti da %, +step, giri/step)."""
        menu = QMenu(self)
        grid = QVBoxLayout()
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        def _spin(lo, hi, val, suffix):
            sp = QSpinBox(); sp.setRange(lo, hi); sp.setValue(val); sp.setSuffix(suffix)
            return sp

        rows = [
            ("Parti da", _spin(40, 95, self._autospeed_start, " %"), "_autospeed_start"),
            ("Accelera di", _spin(1, 25, self._autospeed_step, " %"), "_autospeed_step"),
            ("Giri per step", _spin(1, 8, self._autospeed_reps, ""), "_autospeed_reps"),
        ]
        for label, sp, attr in rows:
            line = QHBoxLayout()
            lb = QLabel(label)
            lb.setStyleSheet(f"color:{theme.COLORS['muted']}; font-size:11px;")
            lb.setFixedWidth(96)
            sp.valueChanged.connect(lambda v, a=attr: setattr(self, a, int(v)))
            line.addWidget(lb); line.addWidget(sp)
            grid.addLayout(line)

        chk = QCheckBox("Attiva loop progressivo")
        chk.setChecked(self._autospeed_on)
        chk.toggled.connect(self._set_autospeed_active)
        grid.addWidget(chk)
        hint = QLabel("Serve un loop attivo (A-B).")
        hint.setStyleSheet(
            f"color:{theme.COLORS['faint']}; font-size:10px; font-style:italic;")
        grid.addWidget(hint)

        wrap = QWidget(); wrap.setLayout(grid)
        act = QWidgetAction(menu); act.setDefaultWidget(wrap)
        menu.addAction(act)
        self._autospeed_chk = chk
        menu.exec(self.autospeed_btn.mapToGlobal(self.autospeed_btn.rect().bottomLeft()))

    def _refresh_autospeed_btn(self) -> None:
        theme.set_state(self.autospeed_btn, "on", self._autospeed_on)

    def _set_autospeed_active(self, on: bool) -> None:
        if on:
            if self._loop_a is None and self._loop_b is None:
                toast(self, "Imposta prima un loop (A-B o Ctrl+trascina sulla "
                            "traccia), poi attiva il loop progressivo.", "warn")
                chk = getattr(self, "_autospeed_chk", None)
                if chk is not None:
                    chk.blockSignals(True); chk.setChecked(False); chk.blockSignals(False)
                return
            self._autospeed_on = True
            if not self.loop_btn.isChecked():
                self.loop_btn.setChecked(True)   # → _on_loop_toggle → _apply_loop
            self._autospeed_cycles = 0
            self._autospeed_last_lc = self.engine.loop_count()
            start = max(self.speed_slider.minimum(),
                        min(self.speed_slider.maximum(), self._autospeed_start))
            if self.speed_slider.value() != start:
                self.speed_slider.setValue(start)   # aggiorna label/preset
                self._apply_transform()
        else:
            self._autospeed_on = False
        self._refresh_autospeed_btn()

    def _update_autospeed(self) -> None:
        """Chiamato dal _tick: ad ogni N giri di loop accelera fino al 100%."""
        if not self._autospeed_on or not self.engine.loop_enabled:
            return
        lc = self.engine.loop_count()
        if lc <= self._autospeed_last_lc:
            return
        self._autospeed_cycles += (lc - self._autospeed_last_lc)
        self._autospeed_last_lc = lc
        cur = self.speed_slider.value()
        target = cur
        while self._autospeed_cycles >= self._autospeed_reps and target < 100:
            self._autospeed_cycles -= self._autospeed_reps
            target = min(100, target + self._autospeed_step)
        if target != cur:
            self.speed_slider.setValue(target)
            self._apply_transform()
        if target >= 100:
            self._set_autospeed_active(False)   # progressione completata

    # ---------- metronomo ----------

    def _on_click_toggle(self, b: bool) -> None:
        self.engine.set_click(b, self.click_vol.value() / 100.0)

    def _on_steady_toggle(self, b: bool) -> None:
        self.engine.set_click_style(regular=b)

    # ---------- export del mix ----------

    def _muted_prefix(self) -> str:
        """Prefisso file dagli stem mutati, in ordine: 'NO_BASSO NO_CHITARRA - '."""
        names = [s.name for s in self.strips
                 if s.m_btn.isChecked() and not s.s_btn.isChecked()]
        names.sort(key=lambda n: STEM_ORDER.index(n) if n in STEM_ORDER else 99)
        tags = [STEM_NO.get(n, f"NO_{n.upper()}") for n in names]
        return (" ".join(tags) + " - ") if tags else ""

    def _xform_tag(self) -> str:
        """Etichetta della trasformazione corrente per i nomi file: '+1st', '75%',
        '+1st 75%' — vuota se velocità e tono sono quelli originali."""
        parts = []
        semis = int(self.pitch_slider.value())
        if semis:
            parts.append(f"{semis:+d}st")
        pct = self.speed_slider.value()
        if pct != 100:
            parts.append(f"{pct}%")
        return " ".join(parts)

    def _audible_tracks(self) -> list:
        """Tracce udibili col mute/solo corrente (stessa regola di render_mix)."""
        any_solo = any(t.solo for t in self.engine.tracks)
        return [t for t in self.engine.tracks
                if (t.solo if any_solo else not t.mute)]

    def _on_export(self) -> None:
        if not self.engine.tracks or (self._ex_thread and self._ex_thread.isRunning()):
            return
        dlg = ExportOptionsDialog(self, click_available=self.click_btn.isEnabled())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        what, fmt, include_click, want_countin, countin_beats = dlg.options()
        if what == "stems":
            self._export_all_stems(fmt)
            return
        if what == "minus":
            self._export_minus_one(fmt, include_click, want_countin, countin_beats)
            return

        base = os.path.basename(self._folder.rstrip("/\\")) or "mix"
        tag = self._xform_tag()
        tag_sfx = f" ({tag})" if tag else ""
        audible = self._audible_tracks()
        if len(audible) == 1:
            # un solo stem udibile (solo/mute): nome parlante «BASSO - titolo»
            label = STEM_IT.get(audible[0].name, audible[0].name.upper())
            fname = f"{label} - {base}{tag_sfx}.{fmt}"
        else:
            fname = f"{self._muted_prefix()}{base} - mix{tag_sfx}.{fmt}"
        default = os.path.join(self._folder or "", fname)
        filters = ("WAV (*.wav);;MP3 (*.mp3)" if fmt == "wav"
                   else "MP3 (*.mp3);;WAV (*.wav)")
        path, sel = QFileDialog.getSaveFileName(self, "Esporta mix", default, filters)
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in (".wav", ".mp3"):
            fmt = ext[1:]          # l'estensione scelta a mano vince sul dialogo
        else:
            path += f".{fmt}"

        mix, sr = self.engine.render_mix(include_click=include_click)
        if mix is None:
            toast(self, "Nessun audio da esportare.", "error")
            return

        if want_countin:
            cin, _ = self.engine.render_count_in(countin_beats)
            if cin is None:
                toast(self, "Count-in non disponibile: ri-analizza il brano.", "warn")
            else:
                # anteponi i click al mix → unico file: click, click… e parte il brano
                mix = np.concatenate([cin, mix], axis=0)

        self._start_export([(mix, path)], sr, fmt, kind="mix")

    def _export_minus_one(self, fmt: str, include_click: bool,
                          want_countin: bool, countin_beats: int) -> None:
        """Esporta una base per ogni stem escluso: mix COMPLETO (ignora mute/solo,
        conserva volumi/pan/EQ/velocità/tono) meno una traccia alla volta.
        File: «NO_VOCE - titolo.ext» in una sottocartella automatica."""
        base = os.path.basename(self._folder.rstrip("/\\")) or "mix"
        tag = self._xform_tag()
        sub = f"basi senza una traccia {tag}".rstrip()
        out_dir = os.path.join(self._folder or "", sub)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            toast(self, f"Impossibile creare la cartella: {exc}", "error")
            return

        cin = None
        if want_countin:
            cin, _ = self.engine.render_count_in(countin_beats)
            if cin is None:
                toast(self, "Count-in non disponibile: ri-analizza il brano.", "warn")

        def job_for(name: str):
            # callable: il render avviene nel worker, un mix alla volta in RAM
            def render() -> np.ndarray:
                mix, _sr = self.engine.render_mix(include_click=include_click,
                                                  exclude=name, full=True)
                if cin is not None:
                    return np.concatenate([cin, mix], axis=0)
                return mix
            return render

        jobs = []
        for t in self.engine.tracks:
            tag_no = STEM_NO.get(t.name, f"NO_{t.name.upper()}")
            path = os.path.join(out_dir, f"{tag_no} - {base}.{fmt}")
            jobs.append((job_for(t.name), path))
        self._start_export(jobs, self.engine.sr, fmt, kind="minus")

    def _export_all_stems(self, fmt: str) -> None:
        """Esporta ogni traccia come file separato (stem puri: solo velocità e
        tono applicati, niente volume/pan/EQ) in una sottocartella automatica."""
        base = os.path.basename(self._folder.rstrip("/\\")) or "stems"
        tag = self._xform_tag()
        sub = f"stems {tag}" if tag else "stems export"
        out_dir = os.path.join(self._folder or "", sub)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            toast(self, f"Impossibile creare la cartella: {exc}", "error")
            return
        jobs = []
        for t in self.engine.tracks:
            label = STEM_IT.get(t.name, t.name.upper())
            path = os.path.join(out_dir, f"{label} - {base}.{fmt}")
            jobs.append((t.data_base, path))   # puro: post pitch/stretch, pre-EQ
        self._start_export(jobs, self.engine.sr, fmt, kind="stems")

    def _start_export(self, jobs: list, sr: int, fmt: str, kind: str) -> None:
        self._ex_kind = kind
        self.export_btn.setEnabled(False)
        self.export_btn.setText("Esporto…")
        self._ex_thread = QThread()
        self._ex_worker = ExportWorker(jobs, sr, fmt)
        self._ex_worker.moveToThread(self._ex_thread)
        self._ex_thread.started.connect(self._ex_worker.run)
        self._ex_worker.done.connect(self._on_export_done)
        self._ex_worker.done.connect(self._ex_thread.quit)
        self._ex_thread.start()

    def _on_export_done(self, ok: bool, info: str) -> None:
        self.export_btn.setEnabled(True)
        self.export_btn.setText("Esporta…")
        if not ok:
            toast(self, f"Esportazione fallita: {info}", "error")
        elif getattr(self, "_ex_kind", "mix") == "stems":
            toast(self, f"Stem esportati in {os.path.dirname(info)}", "ok")
        elif self._ex_kind == "minus":
            toast(self, f"Basi esportate in {os.path.dirname(info)}", "ok")
        else:
            toast(self, f"Mix esportato in {info}", "ok")

    # ---------- sessione mixer (mix.json nella cartella stem) ----------

    def _save_session(self) -> None:
        if not self._folder or not self.strips:
            return
        data = {
            "speed": self.speed_slider.value() / 100.0,
            "semitones": int(self.pitch_slider.value()),
            "master": self.master.value(),
            "loop": {
                "a": self._loop_a,
                "b": self._loop_b,
                "on": self.loop_btn.isChecked(),
            },
            "tracks": {s.name: s.state() for s in self.strips},
        }
        try:
            (Path(self._folder) / "mix.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _load_session(self) -> None:
        if not self._folder or not self.strips:
            return
        p = Path(self._folder) / "mix.json"
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        tracks = data.get("tracks", {})
        for s in self.strips:
            st = tracks.get(s.name)
            if isinstance(st, dict):
                s.apply_state(st)
        master = int(data.get("master", 0))
        self.master.blockSignals(True)
        self.master.setValue(master)
        self.master.blockSignals(False)
        self.engine.set_master(float(master))
        # velocità / trasposizione: imposta i cursori e applica (in thread se serve)
        speed = float(data.get("speed", 1.0))
        semis = int(data.get("semitones", 0))
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(int(round(speed * 100)))
        self.speed_slider.blockSignals(False)
        self.speed_lbl.setText(f"x{speed:.2f}")
        self._refresh_speed_presets(int(round(speed * 100)))
        self.pitch_slider.blockSignals(True)
        self.pitch_slider.setValue(semis)
        self.pitch_slider.blockSignals(False)
        self.pitch_lbl.setText(self._fmt_semis(semis))
        if (round(speed, 2), semis) != (1.0, 0):
            self._apply_transform()
        # loop A-B (frazioni 0..1 + stato attivo)
        loop = data.get("loop")
        if isinstance(loop, dict):
            a, b = loop.get("a"), loop.get("b")
            self._loop_a = float(a) if isinstance(a, (int, float)) else None
            self._loop_b = float(b) if isinstance(b, (int, float)) else None
            on = bool(loop.get("on"))
            self.loop_btn.blockSignals(True)
            self.loop_btn.setChecked(on)
            self.loop_btn.blockSignals(False)
            theme.repolish(self.loop_btn)
            self._apply_loop()

    def seek_seconds(self, seconds: float) -> None:
        """Seek assoluto in secondi (usato dal click sulle righe karaoke)."""
        self.engine.seek(max(0.0, seconds))

    def _tick(self) -> None:
        dur = self.engine.duration()
        pos = self.engine.position()
        frac = (pos / dur) if dur else 0.0
        self.position_changed.emit(pos)
        for s in self.strips:
            s.wave.set_progress(frac)
            any_solo = any(st.s_btn.isChecked() for st in self.strips)
            audible = s.s_btn.isChecked() if any_solo else not s.m_btn.isChecked()
            s.wave.set_dim(not audible)
        if hasattr(self, "timeline"):
            self.timeline.set_progress(frac)
        # auto-scroll della vista zoomata: segue il playhead in riproduzione
        vs, ve = self._view
        span = ve - vs
        if span < 1.0 and self.engine.is_playing() and (frac < vs or frac > ve - span * 0.1):
            ns = min(max(0.0, frac - span * 0.15), 1.0 - span)
            if abs(ns - vs) > 1e-4:
                self._view = [ns, ns + span]
                self._apply_view()
        if dur:
            self.time_lbl.setText(f"{_fmt_time(pos)} / {_fmt_time(dur)}")
        self._refresh_chords()
        self._update_autospeed()
        self._sync_play_btn()

    def shutdown(self) -> None:
        self._save_session()
        self._timer.stop()
        self.engine.close()
