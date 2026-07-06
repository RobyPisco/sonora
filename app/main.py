"""Entrypoint Sonora: avvia QApplication e mostra la finestra principale."""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import config, logging_setup, paths, updater

# Applica l'eventuale yt-dlp aggiornato PRIMA di importare moduli che usano yt_dlp.
updater.apply_override()


def _apply_ui_scale() -> None:
    """Ingrandimento UI opzionale (Impostazioni → Aspetto).

    QT_SCALE_FACTOR va impostato PRIMA di creare QApplication; si moltiplica
    con la scala DPI di Windows, quindi 1.0 = comportamento di sempre."""
    try:
        scale = float(config.load().get("ui_scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    if scale > 1.01 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"


def main() -> int:
    logging_setup.setup()   # logging su file + excepthook, prima di tutto il resto
    _apply_ui_scale()
    app = QApplication(sys.argv)
    app.setApplicationName("Sonora")

    # import ritardato: dopo apply_override(), cosi' eventuale override ha effetto
    from .ui import MainWindow

    icon_path = paths.resource("icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    from . import theme
    app.setStyleSheet(theme.load_qss())

    # gate licenza: durante la prova (3 giorni) o con licenza valida si prosegue;
    # a prova scaduta serve un codice, altrimenti l'app non parte.
    from . import licensing
    from .ui_license import run_activation_gate

    if licensing.status().state == "expired":
        if not run_activation_gate(trial_expired=True):
            return 0

    win = MainWindow()
    if icon_path.exists():
        win.setWindowIcon(QIcon(str(icon_path)))
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
