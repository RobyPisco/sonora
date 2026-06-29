"""Widget waveform con playhead e click-to-seek."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


def compute_peaks(mono: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray]:
    """Riduce un segnale mono a `columns` coppie (min, max) per il disegno."""
    n = len(mono)
    if n == 0 or columns <= 0:
        return np.zeros(columns), np.zeros(columns)
    columns = min(columns, n)
    # taglia al multiplo e fai reshape per max/min vettoriale
    step = n // columns
    usable = step * columns
    block = mono[:usable].reshape(columns, step)
    mins = block.min(axis=1)
    maxs = block.max(axis=1)
    return mins.astype("float32"), maxs.astype("float32")


class WaveformWidget(QWidget):
    """Disegna la waveform di una traccia con playhead. Click/drag → seek (frazione)."""

    seeked = Signal(float)          # 0..1
    loop_selected = Signal(float, float)   # (a_frac, b_frac) ordinati, da Shift+trascina

    def __init__(self, color: str = "#ff3b5c"):
        super().__init__()
        self._mins = np.zeros(0, dtype="float32")
        self._maxs = np.zeros(0, dtype="float32")
        self._color = QColor(color)
        self._progress = 0.0
        self._dim = False
        self._loop = None     # (a_frac, b_frac) o None
        self._loop_drag = None  # frazione iniziale durante Shift+trascina, o None
        self._markers: list[float] = []   # confini di sezione (frazioni 0..1)
        self._beats: list[float] = []      # beat grid (frazioni 0..1)
        self.setMinimumHeight(56)
        self.setMouseTracking(True)
        self.setToolTip("Click = vai al punto · Ctrl/Shift+trascina = seleziona il loop")

    def set_peaks(self, mins: np.ndarray, maxs: np.ndarray) -> None:
        self._mins, self._maxs = mins, maxs
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_progress(self, frac: float) -> None:
        self._progress = max(0.0, min(1.0, frac))
        self.update()

    def set_dim(self, dim: bool) -> None:
        """Traccia mutata/non udibile: disegnata più spenta."""
        if dim != self._dim:
            self._dim = dim
            self.update()

    def set_loop(self, region) -> None:
        """region = (a_frac, b_frac) o None."""
        self._loop = region
        self.update()

    def set_markers(self, fracs) -> None:
        """Confini di sezione come frazioni 0..1 (linee verticali tratteggiate)."""
        self._markers = list(fracs or [])
        self.update()

    def set_beats(self, fracs) -> None:
        """Beat grid come frazioni 0..1 (linee verticali tenui)."""
        self._beats = list(fracs or [])
        self.update()

    def _frac(self, x: float) -> float:
        w = max(1, self.width())
        return max(0.0, min(1.0, x / w))

    def _emit_seek(self, x: float) -> None:
        self.seeked.emit(self._frac(x))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        mods = e.modifiers()
        loop_mod = bool(mods & (Qt.KeyboardModifier.ShiftModifier
                                | Qt.KeyboardModifier.ControlModifier))
        if e.button() == Qt.MouseButton.LeftButton and loop_mod:
            # inizio selezione loop trascinabile (Ctrl o Shift + trascina)
            self._loop_drag = self._frac(e.position().x())
            self._loop = (self._loop_drag, self._loop_drag)
            self.update()
            return
        self._emit_seek(e.position().x())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._loop_drag is not None:
            a, b = sorted((self._loop_drag, self._frac(e.position().x())))
            self._loop = (a, b)
            self.update()
            return
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._emit_seek(e.position().x())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._loop_drag is not None:
            a, b = sorted((self._loop_drag, self._frac(e.position().x())))
            self._loop_drag = None
            self.loop_selected.emit(a, b)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        mid = h / 2.0
        p.fillRect(self.rect(), QColor("#161922"))

        n = len(self._maxs)
        if n:
            col = QColor(self._color)
            if self._dim:
                col.setAlpha(70)
            p.setPen(QPen(col, 1))
            for x in range(w):
                idx = int(x / w * n)
                if idx >= n:
                    idx = n - 1
                top = mid - self._maxs[idx] * (mid - 2)
                bot = mid - self._mins[idx] * (mid - 2)
                p.drawLine(x, int(top), x, int(bot))

        # linea centrale tenue
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(0, int(mid), w, int(mid))

        # beat grid (linee verticali tenui); saltato se i beat sono troppo
        # fitti per la larghezza attuale, così non diventano un muro grigio
        if self._beats and w / len(self._beats) >= 5:
            p.setPen(QPen(QColor(255, 255, 255, 24), 1))
            for fr in self._beats:
                if 0.0 < fr < 1.0:
                    bx = int(fr * w)
                    p.drawLine(bx, 0, bx, h)

        # marker di sezione (linee verticali tratteggiate)
        if self._markers:
            pen = QPen(QColor(150, 160, 190, 120), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            for fr in self._markers:
                if 0.0 < fr < 1.0:
                    mx = int(fr * w)
                    p.drawLine(mx, 0, mx, h)

        # regione loop A-B
        if self._loop is not None:
            a, b = self._loop
            ax, bx = int(a * w), int(b * w)
            p.fillRect(QRectF(ax, 0, max(1, bx - ax), h), QColor(61, 220, 132, 30))
            p.setPen(QPen(QColor("#3ddc84"), 1))
            p.drawLine(ax, 0, ax, h)
            p.drawLine(bx, 0, bx, h)

        # playhead
        px = int(self._progress * w)
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawLine(px, 0, px, h)
        p.fillRect(QRectF(0, 0, px, h), QColor(255, 255, 255, 12))
        p.end()
