"""Dialog Accordatore: tono di riferimento (A440 / corde) + accordatore dal microfono."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .tuner import BASS_STRINGS, GUITAR_STRINGS, PitchDetector, ToneGenerator, freq_to_note


class CentsMeter(QWidget):
    """Indicatore orizzontale dello scarto in cents (-50..+50), con ago centrale."""

    def __init__(self):
        super().__init__()
        self._cents = None    # None = nessun segnale
        self._in_tune = False
        self.setMinimumHeight(70)

    def set_cents(self, cents) -> None:
        self._cents = cents
        self._in_tune = cents is not None and abs(cents) <= 5.0
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#161922"))
        mid = w / 2.0

        # tacche -50..+50 ogni 10 cents
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for c in range(-50, 51, 10):
            x = mid + (c / 50.0) * (w / 2 - 14)
            top = 10 if c == 0 else (18 if c % 50 == 0 else 24)
            p.drawLine(int(x), top, int(x), h - 22)

        # zona "intonato" centrale
        good = QColor(61, 220, 132, 40)
        gw = (5 / 50.0) * (w / 2 - 14)
        p.fillRect(int(mid - gw), 8, int(2 * gw), h - 30, good)

        # etichette
        p.setPen(QPen(QColor("#8b90a0"), 1))
        p.drawText(6, h - 6, "♭ basso")
        p.drawText(w - 56, h - 6, "alto ♯")

        # ago
        if self._cents is not None:
            cc = max(-50.0, min(50.0, float(self._cents)))
            x = mid + (cc / 50.0) * (w / 2 - 14)
            col = QColor("#3ddc84") if self._in_tune else QColor("#ff9f43")
            p.setPen(QPen(col, 3))
            p.drawLine(int(x), 6, int(x), h - 24)
        p.end()


class TunerDialog(QDialog):
    """Accordatore: riferimento sonoro + rilevamento pitch dal microfono."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accordatore")
        self.setMinimumWidth(440)
        self.tone = ToneGenerator()
        self.detector = PitchDetector()
        self._mic_on = False
        self._ref_btns: list[tuple[float, QPushButton]] = []

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # --- riferimento sonoro ---
        root.addWidget(self._section_label("TONO DI RIFERIMENTO"))
        a440 = QPushButton("A4 · 440 Hz")
        a440.setObjectName("Primary")
        a440.clicked.connect(lambda: self._toggle_tone(440.0, a440))
        self._ref_btns.append((440.0, a440))
        root.addWidget(a440)

        root.addWidget(self._small_label("Chitarra (standard)"))
        root.addLayout(self._string_grid(GUITAR_STRINGS))
        root.addWidget(self._small_label("Basso"))
        root.addLayout(self._string_grid(BASS_STRINGS))

        self.stop_tone_btn = QPushButton("◼ Ferma tono")
        self.stop_tone_btn.setObjectName("Ghost")
        self.stop_tone_btn.clicked.connect(self._stop_tone)
        root.addWidget(self.stop_tone_btn)

        # --- accordatore microfono ---
        root.addWidget(self._section_label("ACCORDATORE (MICROFONO)"))
        self.note_lbl = QLabel("—")
        self.note_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note_lbl.setStyleSheet("color:#e6e8ee; font-size:40px; font-weight:800;")
        root.addWidget(self.note_lbl)
        self.meter = CentsMeter()
        root.addWidget(self.meter)
        self.hz_lbl = QLabel("suona una corda…")
        self.hz_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hz_lbl.setStyleSheet("color:#8b90a0; font-size:12px;")
        root.addWidget(self.hz_lbl)
        self.mic_btn = QPushButton("🎤  Avvia microfono")
        self.mic_btn.setObjectName("Primary")
        self.mic_btn.clicked.connect(self._toggle_mic)
        root.addWidget(self.mic_btn)

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    # ---------- helpers UI ----------

    def _section_label(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet("color:#8b90a0; font-size:11px; font-weight:700;")
        return lb

    def _small_label(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet("color:#6b7080; font-size:11px;")
        return lb

    def _string_grid(self, strings) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (name, freq) in enumerate(strings):
            b = QPushButton(name)
            b.setObjectName("GhostMini")
            b.clicked.connect(lambda _=False, f=freq, btn=b: self._toggle_tone(f, btn))
            self._ref_btns.append((freq, b))
            grid.addWidget(b, 0, i)
        return grid

    # ---------- tono ----------

    def _toggle_tone(self, freq: float, btn: QPushButton) -> None:
        if self.tone.playing and abs(self.tone.freq - freq) < 0.01:
            self._stop_tone()
            return
        self.tone.play(freq)
        self._highlight_ref(btn)

    def _stop_tone(self) -> None:
        self.tone.stop()
        self._highlight_ref(None)

    def _highlight_ref(self, active) -> None:
        for _f, b in self._ref_btns:
            b.setStyleSheet("background:#3ddc84;color:#14161c;" if b is active else "")

    # ---------- microfono ----------

    def _toggle_mic(self) -> None:
        if self._mic_on:
            self._mic_on = False
            self._timer.stop()
            self.detector.close()
            self.detector.reset()
            self.mic_btn.setText("🎤  Avvia microfono")
            self.mic_btn.setStyleSheet("")
            self.note_lbl.setText("—")
            self.meter.set_cents(None)
            self.hz_lbl.setText("suona una corda…")
            return
        try:
            self.detector.start()
        except Exception as e:  # noqa: BLE001
            self.hz_lbl.setText(f"microfono non disponibile: {e}")
            return
        self._mic_on = True
        self.mic_btn.setText("◼  Ferma microfono")
        self.mic_btn.setStyleSheet("background:#ff3b5c;color:#fff;")
        self._timer.start()

    def _tick(self) -> None:
        freq, level = self.detector.read()
        info = freq_to_note(freq) if freq > 0 else None
        if info is None:
            self.note_lbl.setText("—")
            self.meter.set_cents(None)
            self.hz_lbl.setText("suona una corda…")
            return
        name, cents, _target = info
        self.note_lbl.setText(name)
        self.meter.set_cents(cents)
        arrow = "✓ intonato" if abs(cents) <= 5 else ("più alto ↑" if cents < 0 else "più basso ↓")
        self.hz_lbl.setText(f"{freq:.1f} Hz   ·   {cents:+.0f} cents   ·   {arrow}")

    # ---------- chiusura ----------

    def closeEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        try:
            self.tone.close()
            self.detector.close()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)
