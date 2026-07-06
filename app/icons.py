"""Icone SVG monocromatiche tintabili (resources/icons/*.svg).

Gli SVG usano `currentColor`: la tinta avviene sostituendo la stringa col
colore richiesto e rasterizzando a 2x per restare nitidi in HiDPI.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import paths, theme


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    """Pixmap quadrata `size`pt (renderizzata a 2x) dell'icona tinta."""
    path = paths.resources_dir() / "icons" / f"{name}.svg"
    svg = path.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


def icon(name: str, color: str | None = None, size: int = 18,
         on_name: str | None = None, on_color: str | None = None) -> QIcon:
    """QIcon tinta. `on_name`/`on_color` = variante per lo stato On
    (bottoni checkable, es. play→pause)."""
    color = color or theme.COLORS["muted"]
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    if on_name or on_color:
        ic.addPixmap(pixmap(on_name or name, on_color or color, size),
                     QIcon.Mode.Normal, QIcon.State.On)
    return ic
