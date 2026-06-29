"""Entrypoint Sonora: avvia QApplication e mostra la finestra principale."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import paths, updater

# Applica l'eventuale yt-dlp aggiornato PRIMA di importare moduli che usano yt_dlp.
updater.apply_override()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Sonora")

    # import ritardato: dopo apply_override(), cosi' eventuale override ha effetto
    from .ui import MainWindow

    icon_path = paths.resource("icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    qss = paths.resource("style.qss")
    if qss.exists():
        css = qss.read_text(encoding="utf-8")
        # i path immagine in QSS vanno con slash; risolti runtime (dev + exe)
        css = css.replace("__CHECK__", paths.resource("check.svg").as_posix())
        css = css.replace("__CHEVRON__", paths.resource("chevron.svg").as_posix())
        app.setStyleSheet(css)

    win = MainWindow()
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
