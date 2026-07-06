"""Toast (notifiche transitorie) e Banner (avvisi inline con azione).

Sostituiscono i QMessageBox puramente informativi: il toast appare in basso a
destra sopra la playbar e sparisce da solo; il banner vive dentro un layout
finché lo stato che segnala non si risolve.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from . import icons, theme

_KIND_ICON = {"info": "info", "ok": "check", "warn": "alert", "error": "alert"}
_KIND_COLOR = {"info": "info", "ok": "ok", "warn": "warn", "error": "err"}


class Toast(QFrame):
    """Notifica flottante auto-dismiss. Usa Toast.show_message(parent, ...)."""

    _active: list["Toast"] = []

    def __init__(self, parent, text: str, kind: str = "info", msec: int = 4000):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        ico = QLabel()
        color = theme.COLORS[_KIND_COLOR.get(kind, "info")]
        ico.setPixmap(icons.pixmap(_KIND_ICON.get(kind, "info"), color, 16))
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(360)
        lay.addWidget(ico, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(lbl, 1)

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)

        QTimer.singleShot(msec, self._fade_out)

    @classmethod
    def show_message(cls, parent, text: str, kind: str = "info",
                     msec: int = 4000) -> "Toast":
        t = cls(parent, text, kind, msec)
        cls._active = [x for x in cls._active if x.parent() is parent and not x.isHidden()]
        cls._active.append(t)
        t.adjustSize()
        t.show()
        t.raise_()
        cls._reposition(parent)
        t._anim.start()
        return t

    @classmethod
    def _reposition(cls, parent) -> None:
        """Impila i toast attivi in basso a destra (sopra la playbar)."""
        margin = 16
        bottom = parent.height() - 72 - margin   # 72 = altezza playbar
        for t in reversed([x for x in cls._active if not x.isHidden()]):
            t.adjustSize()
            t.move(parent.width() - t.width() - margin, bottom - t.height())
            bottom -= t.height() + 8

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._done)
        self._anim.start()

    def _done(self) -> None:
        self.hide()
        self.deleteLater()
        if self in Toast._active:
            Toast._active.remove(self)


def toast(parent, text: str, kind: str = "info") -> None:
    """Scorciatoia: toast sul MainWindow (risale al top-level)."""
    win = parent.window() if parent is not None else None
    if win is not None:
        Toast.show_message(win, text, kind)


class Banner(QFrame):
    """Avviso inline persistente con eventuale bottone azione."""

    def __init__(self, text: str, kind: str = "warn",
                 action_text: str = "", action=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("kind", kind)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)
        ico = QLabel()
        color = theme.COLORS[_KIND_COLOR.get(kind, "warn")]
        ico.setPixmap(icons.pixmap("alert" if kind in ("warn", "error") else "info",
                                   color, 16))
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        lay.addWidget(ico, 0)
        lay.addWidget(self.label, 1)
        self.action_btn: QPushButton | None = None
        if action_text:
            self.action_btn = QPushButton(action_text)
            self.action_btn.setObjectName("Ghost")
            if action:
                self.action_btn.clicked.connect(action)
            lay.addWidget(self.action_btn, 0)

    def set_text(self, text: str) -> None:
        self.label.setText(text)
