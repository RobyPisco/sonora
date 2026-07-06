"""Pagina Impostazioni: nav a sinistra + sezioni (Download / Motore stem /
Aggiornamenti / Licenza).

Raccoglie i controlli di manutenzione prima sparsi nel tab Scarica. I worker
(installazione/verifica/disinstallazione motore, update) restano in
MainWindow: questa pagina espone i widget e richiama i suoi handler.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__


def _card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(14)
    return f, lay


def _row(title: str, desc: str, widget: QWidget | None = None) -> QWidget:
    """Riga impostazione: titolo+descrizione a sinistra, controllo a destra."""
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    text = QVBoxLayout()
    text.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet("font-weight:600;")
    text.addWidget(t)
    if desc:
        d = QLabel(desc)
        d.setProperty("class", "Muted")
        d.setWordWrap(True)
        text.addWidget(d)
    lay.addLayout(text, 1)
    if widget is not None:
        lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    return host


def _switch() -> QCheckBox:
    sw = QCheckBox()
    sw.setObjectName("Switch")
    return sw


class SettingsPage(QWidget):
    """main = MainWindow: fornisce cfg, handler motore/update/licenza."""

    SECTIONS = ["Download", "Motore stem", "Aggiornamenti", "Licenza"]

    def __init__(self, main):
        super().__init__()
        self.setObjectName("Root")
        self._main = main

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("Root")
        scroll.setWidget(content)

        center = QHBoxLayout(content)
        center.addStretch(1)
        wrap = QWidget()
        wrap.setMaximumWidth(900)
        center.addWidget(wrap, 20)
        center.addStretch(1)

        root = QVBoxLayout(wrap)
        root.setContentsMargins(28, 26, 28, 20)
        root.setSpacing(18)
        title = QLabel("Impostazioni")
        title.setObjectName("H1")
        root.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(20)
        self.nav = QListWidget()
        self.nav.setObjectName("SetNav")
        self.nav.setFixedWidth(190)
        self.nav.addItems(self.SECTIONS)
        self.stack = QStackedWidget()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        body.addWidget(self.nav, 0)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        root.addStretch(1)

        self.stack.addWidget(self._page_download())
        self.stack.addWidget(self._page_engine())
        self.stack.addWidget(self._page_updates())
        self.stack.addWidget(self._page_license())
        self.nav.setCurrentRow(0)

    # ---------- pagine ----------

    def _page_download(self) -> QWidget:
        card, lay = _card()
        self.watch_chk = _switch()
        lay.addWidget(_row("Monitora appunti",
                           "Aggiunge in coda i link YouTube che copi; l'app "
                           "resta attiva nella tray alla chiusura.",
                           self.watch_chk))
        self.notify_chk = _switch()
        lay.addWidget(_row("Avvisa a fine coda",
                           "Notifica di sistema e suono quando i download finiscono.",
                           self.notify_chk))
        lay.addStretch(1)
        return card

    def _page_engine(self) -> QWidget:
        card, lay = _card()
        self.engine_lbl = QLabel("")
        self.engine_lbl.setProperty("class", "Muted")
        self.engine_lbl.setWordWrap(True)
        lay.addWidget(_row("Motore di separazione",
                           "Demucs + PyTorch (~3 GB), scaricato una sola volta. "
                           "Serve per separare i brani in stem.", None))
        lay.addWidget(self.engine_lbl)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.engine_btn = QPushButton("Installa motore")
        self.engine_btn.clicked.connect(self._main._on_install_engine)
        self.verify_btn = QPushButton("Verifica / Ripara")
        self.verify_btn.setObjectName("Ghost")
        self.verify_btn.clicked.connect(self._main._on_verify_engine)
        self.uninstall_btn = QPushButton("Disinstalla")
        self.uninstall_btn.setObjectName("Ghost")
        self.uninstall_btn.clicked.connect(self._main._on_uninstall_engine)
        self.location_btn = QPushButton("Cartella…")
        self.location_btn.setObjectName("Ghost")
        self.location_btn.setToolTip("Cambia la cartella di installazione del motore.")
        self.location_btn.clicked.connect(self._main._on_change_engine_location)
        for b in (self.engine_btn, self.verify_btn, self.uninstall_btn, self.location_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: transparent;")
        lay.addWidget(sep)

        self.ytdlp_lbl = QLabel("")
        self.ytdlp_lbl.setProperty("class", "Muted")
        self.update_btn = QPushButton("Aggiorna yt-dlp")
        self.update_btn.setObjectName("Ghost")
        self.update_btn.setToolTip(
            "Scarica l'ultima versione di yt-dlp.\n"
            "Necessario ogni tanto: YouTube cambia spesso.\n"
            "Ha effetto dopo il riavvio dell'app.")
        self.update_btn.clicked.connect(self._main._on_update_ytdlp)
        row = QHBoxLayout()
        row.addWidget(_row("Downloader (yt-dlp)",
                           "Il componente che scarica l'audio da YouTube.", None), 1)
        lay.addLayout(row)
        yrow = QHBoxLayout()
        yrow.addWidget(self.ytdlp_lbl, 1)
        yrow.addWidget(self.update_btn, 0)
        lay.addLayout(yrow)
        lay.addStretch(1)
        return card

    def _page_updates(self) -> QWidget:
        card, lay = _card()
        ver = QLabel(f"Sonora v{__version__} · © 2026 Pisco Factory")
        ver.setProperty("class", "Muted")
        lay.addWidget(_row("Versione installata", "", None))
        lay.addWidget(ver)
        self.check_btn = QPushButton("Controlla aggiornamenti")
        self.check_btn.clicked.connect(self._main._on_check_app_update)
        crow = QHBoxLayout()
        crow.addWidget(self.check_btn)
        crow.addStretch(1)
        lay.addLayout(crow)
        hint = QLabel("All'avvio Sonora controlla da sola se c'è una versione nuova.")
        hint.setProperty("class", "Hint")
        lay.addWidget(hint)

        self.about_btn = QPushButton("Informazioni su Sonora")
        self.about_btn.setObjectName("Ghost")
        self.about_btn.clicked.connect(self._main._show_about)
        arow = QHBoxLayout()
        arow.addWidget(self.about_btn)
        arow.addStretch(1)
        lay.addLayout(arow)
        lay.addStretch(1)
        return card

    def _page_license(self) -> QWidget:
        card, lay = _card()
        self.license_lbl = QLabel("")
        self.license_lbl.setWordWrap(True)
        lay.addWidget(_row("Stato licenza", "", None))
        lay.addWidget(self.license_lbl)

        self.activate_btn = QPushButton("Attiva con un codice…")
        self.activate_btn.clicked.connect(self._main._open_activation)
        act_row = QHBoxLayout()
        act_row.addWidget(self.activate_btn)
        act_row.addStretch(1)
        lay.addLayout(act_row)

        try:
            from . import licensing
            mid = licensing.machine_id()
        except Exception:  # noqa: BLE001
            mid = "?"
        mid_lbl = QLabel(f"ID dispositivo: {mid}")
        mid_lbl.setProperty("class", "Hint")
        mid_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy_btn = QPushButton("Copia")
        copy_btn.setObjectName("GhostMini")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(mid))
        mrow = QHBoxLayout()
        mrow.addWidget(mid_lbl, 1)
        mrow.addWidget(copy_btn, 0)
        lay.addLayout(mrow)

        disclaimer = QLabel("Usa solo contenuti di cui detieni i diritti.")
        disclaimer.setProperty("class", "Hint")
        lay.addWidget(disclaimer)
        lay.addStretch(1)
        return card
