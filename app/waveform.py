"""Widget waveform con playhead e click-to-seek."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
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

    seeked = Signal(float)          # 0..1 (frazione globale)
    loop_selected = Signal(float, float)   # (a_frac, b_frac) ordinati, da Shift+trascina
    wheel_zoom = Signal(int, float)        # (passi rotella, centro_frazione_globale)
    wheel_pan = Signal(int)                # (passi rotella; >0 = verso destra)

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
        # finestra di visualizzazione (zoom): porzione globale [start, end] visibile
        self._view_start = 0.0
        self._view_end = 1.0
        self.setMinimumHeight(56)
        self.setMouseTracking(True)
        self.setToolTip("Click = vai al punto · Ctrl/Shift+trascina = loop\n"
                        "Ctrl+rotella = zoom · Shift+rotella = scorri")

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

    def set_view(self, start: float, end: float) -> None:
        """Imposta la porzione globale [start, end] visibile (zoom condiviso)."""
        start = max(0.0, min(1.0, start))
        end = max(start + 1e-4, min(1.0, end))
        self._view_start, self._view_end = start, end
        self.update()

    def _span(self) -> float:
        return max(self._view_end - self._view_start, 1e-9)

    def _frac(self, x: float) -> float:
        """x locale (px) → frazione globale 0..1, tenendo conto dello zoom."""
        w = max(1, self.width())
        gf = self._view_start + (x / w) * self._span()
        return max(0.0, min(1.0, gf))

    def _x_of(self, fr: float) -> int:
        """Frazione globale 0..1 → x locale (px) nella vista corrente."""
        return int((fr - self._view_start) / self._span() * self.width())

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        mid = h / 2.0
        p.fillRect(self.rect(), QColor("#161922"))
        vs, span = self._view_start, self._span()

        n = len(self._maxs)
        px = self._x_of(self._progress)

        if n:
            col_active = QColor(self._color)
            if self._dim:
                col_active.setAlpha(70)

            # Il colore di sfondo della waveform non ancora suonata è più spento
            col_unplayed = QColor(col_active)
            col_unplayed.setAlpha(40 if self._dim else 75)

            def draw_waveform_lines(color: QColor, use_gradient: bool):
                if use_gradient:
                    grad = QLinearGradient(0, 4, 0, h - 4)
                    grad.setColorAt(0.0, color.lighter(130))
                    grad.setColorAt(0.5, color)
                    grad.setColorAt(1.0, color.darker(130))
                    pen = QPen(QBrush(grad), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                else:
                    pen = QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                p.setPen(pen)

                # Disegno a barre verticali con spaziatura (larghezza barra 2px, passo 3px)
                for x in range(0, w, 3):
                    idx = int((vs + (x / w) * span) * n)
                    idx = min(max(idx, 0), n - 1)
                    top = mid - self._maxs[idx] * (mid - 4)
                    bot = mid - self._mins[idx] * (mid - 4)
                    # Forza una minima linea centrale visibile anche per silenzio
                    if bot - top < 2.0:
                        top = mid - 1.0
                        bot = mid + 1.0
                    p.drawLine(x, int(top), x, int(bot))

            # 1. Disegna l'intera waveform nello stato spento (non riprodotto)
            draw_waveform_lines(col_unplayed, use_gradient=False)

            # 2. Sovrascrive con la parte attiva (suonata) applicando il clip a sinistra del playhead
            if px > 0:
                p.save()
                p.setClipRect(0, 0, px, h)
                draw_waveform_lines(col_active, use_gradient=True)
                p.restore()

        # linea centrale tenue
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        p.drawLine(0, int(mid), w, int(mid))

        # beat grid (linee verticali tenui)
        if self._beats:
            visible = [fr for fr in self._beats if vs < fr < self._view_end]
            if visible and w / len(visible) >= 5:
                p.setPen(QPen(QColor(255, 255, 255, 24), 1))
                for fr in visible:
                    bx = self._x_of(fr)
                    p.drawLine(bx, 0, bx, h)

        # marker di sezione (linee verticali tratteggiate)
        if self._markers:
            pen = QPen(QColor(150, 160, 190, 120), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            for fr in self._markers:
                if vs < fr < self._view_end:
                    mx = self._x_of(fr)
                    p.drawLine(mx, 0, mx, h)

        # regione loop A-B
        if self._loop is not None:
            a, b = self._loop
            ax = max(0, min(w, self._x_of(a)))
            bx = max(0, min(w, self._x_of(b)))
            p.fillRect(QRectF(ax, 0, max(1, bx - ax), h), QColor(61, 220, 132, 24))
            p.setPen(QPen(QColor("#3ddc84"), 1))
            p.drawLine(ax, 0, ax, h)
            p.drawLine(bx, 0, bx, h)

        # playhead
        if 0 <= px <= w:
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            p.drawLine(px, 0, px, h)
        p.end()

    def wheelEvent(self, e) -> None:  # noqa: N802
        """Ctrl+rotella = zoom (centrato sul cursore); Shift+rotella = scorri.
        Senza modificatori lascia passare l'evento (scroll verticale del mixer)."""
        mods = e.modifiers()
        steps = 1 if e.angleDelta().y() > 0 else -1
        if mods & Qt.KeyboardModifier.ControlModifier:
            center = self._frac(e.position().x())
            self.wheel_zoom.emit(steps, center)
            e.accept()
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            self.wheel_pan.emit(steps)
            e.accept()
        else:
            e.ignore()
