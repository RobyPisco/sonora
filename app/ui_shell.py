"""NavRail: barra di navigazione laterale a icone (sostituisce le tab)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from . import icons, theme


class NavRail(QFrame):
    """Colonna 64px: logo + bottoni pagina (esclusivi) + ingranaggio in basso.

    Le pagine sono registrate con add_page(); l'ordine di registrazione è
    l'indice emesso da page_selected.
    """

    page_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setFixedWidth(64)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(10, 14, 10, 14)
        self._lay.setSpacing(6)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        logo = QLabel("S")
        logo.setObjectName("RailLogo")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        self._lay.addSpacing(10)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idToggled.connect(self._on_toggled)
        self._buttons: list[tuple[QPushButton, str]] = []
        self._stretch_added = False

    def _make_btn(self, icon_name: str, tooltip: str) -> QPushButton:
        b = QPushButton()
        b.setObjectName("RailBtn")
        b.setCheckable(True)
        b.setFixedSize(44, 44)
        b.setIconSize(QSize(21, 21))
        b.setToolTip(tooltip)
        b.setIcon(icons.icon(icon_name, theme.COLORS["muted"], 21,
                             on_color=theme.COLORS["text"]))
        return b

    def add_page(self, icon_name: str, tooltip: str, *, bottom: bool = False) -> int:
        """Aggiunge un bottone pagina; ritorna l'indice. bottom=True lo ancora in fondo."""
        idx = len(self._buttons)
        b = self._make_btn(icon_name, tooltip)
        if bottom and not self._stretch_added:
            self._lay.addStretch(1)
            self._stretch_added = True
        self._lay.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        self._group.addButton(b, idx)
        self._buttons.append((b, icon_name))
        return idx

    def select(self, idx: int) -> None:
        b, _ = self._buttons[idx]
        if not b.isChecked():
            b.setChecked(True)

    def _on_toggled(self, idx: int, checked: bool) -> None:
        b, name = self._buttons[idx]
        # icona tinta: attiva = testo pieno, inattiva = muted
        color = theme.COLORS["text"] if checked else theme.COLORS["muted"]
        b.setIcon(icons.icon(name, color, 21))
        if checked:
            self.page_selected.emit(idx)
