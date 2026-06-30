"""FlowLayout: dispone i widget in orizzontale mandandoli a capo quando manca
spazio. Versione adattata dall'esempio ufficiale Qt (PySide6).

Usato nel mixer per le file di controlli/card/presenza, così su schermi stretti
i widget vanno a capo invece di sforare.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0,
                 hspacing: int = 6, vspacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    # --- API QLayout ---
    def addItem(self, item) -> None:  # noqa: ANN001
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        # dimensione "naturale" su una sola riga: somma le larghezze. Serve
        # quando il FlowLayout sta dentro un layout orizzontale (es. le card
        # accanto al titolo): così occupa la riga intera se c'è spazio e va a
        # capo solo quando viene compresso sotto la sua minimumSize.
        w, h = 0, 0
        for i, item in enumerate(self._items):
            s = item.sizeHint()
            w += s.width() + (self._hspace if i else 0)
            h = max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    # --- disposizione ---
    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_height = eff.x(), eff.y(), 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            next_x = x + w + self._hspace
            # eff.right() è inclusivo (x+larghezza-1): senza il +1 l'ultimo
            # elemento, con larghezza pari al sizeHint, andrebbe a capo per un px.
            if next_x - self._hspace > eff.right() + 1 and line_height > 0:
                x = eff.x()
                y = y + line_height + self._vspace
                next_x = x + w + self._hspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x = next_x
            line_height = max(line_height, h)
        return y + line_height - rect.y() + m.bottom()
