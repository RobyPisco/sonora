"""Interfaccia grafica Sonora (PySide6)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__, app_update, changelog, config, history, paths, stems, updater
from .downloader import (
    AUDIO_FORMATS,
    DownloadOptions,
    DownloadWorker,
    InfoSignals,
    InfoTask,
    QueueItem,
    SearchSignals,
    SearchTask,
    make_thread,
    run_info_task,
    run_search_task,
)
from .ui_mixer import MixerTab
from .ui_lyrics import LyricsTab

# Modalità raggruppate per risultato (quante tracce), poi per motore/qualità.
STEM_MODES = [
    ("6 stem · Roformer SW — consigliato", "sw6"),
    ("6 stem · Roformer+Demucs — top voce, lento", "rof6"),
    ("6 stem · Demucs ensemble", "6hq"),
    ("6 stem · Demucs", "6"),
    ("4 stem · Demucs", "4"),
    ("Voce/strumentale · Roformer — top karaoke", "rof"),
    ("Voce/strumentale · Demucs — veloce", "2"),
]
STEM_FORMATS = ["wav", "flac", "mp3"]


class StemWorker(QObject):
    """Esegue (eventuale install motore +) separazione stem in un QThread."""

    progress = Signal(float)
    status = Signal(str)
    log = Signal(str)
    finished = Signal(bool, str)   # ok, cartella_output o messaggio errore

    def __init__(self, input_file: str, mode: str, out_format: str):
        super().__init__()
        self._input = input_file
        self._mode = mode
        self._format = out_format
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            install_only = not self._input
            if install_only or not stems.engine_ready():
                self.status.emit("motore")
                self.log.emit("Preparo il motore stem…")
                ok = stems.install_engine(self.log.emit, self.progress.emit,
                                          lambda: self._cancel)
                if not ok:
                    self.finished.emit(False, "motore non installato")
                    return
                if install_only:
                    self.finished.emit(True, "")
                    return
            self.status.emit("separazione")
            self.progress.emit(0.0)
            files = stems.separate(self._input, self._mode, self._format,
                                   self.log.emit, self.progress.emit,
                                   lambda: self._cancel)
            out_dir = os.path.dirname(files[0]) if files else ""
            # niente auto-analisi qui: BPM/tonalità/beat si calcolano dal Mixer
            # col pulsante «Analizza», quando serve all'utente.
            self.finished.emit(True, out_dir)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("sonora.stems").exception(
                "separazione fallita (mode=%s): %s", self._mode, self._input)
            self.finished.emit(False, str(exc).splitlines()[0] if str(exc) else "errore")


def make_stem_thread(input_file: str, mode: str, out_format: str) -> tuple[QThread, StemWorker]:
    thread = QThread()
    worker = StemWorker(input_file, mode, out_format)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread, worker


class EngineUninstallWorker(QObject):
    """Disinstalla il motore stem in un QThread (la rimozione di ~3 GB può
    richiedere qualche secondo: evita di bloccare l'interfaccia)."""

    log = Signal(str)
    finished = Signal(bool)

    def run(self) -> None:
        try:
            ok = stems.uninstall_engine(self.log.emit)
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"errore disinstallazione: {exc}")
            ok = False
        self.finished.emit(ok)


def make_uninstall_thread() -> tuple[QThread, EngineUninstallWorker]:
    thread = QThread()
    worker = EngineUninstallWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread, worker


class EngineVerifyWorker(QObject):
    """Verifica e ripara il motore stem in un QThread (reinstalla solo il necessario)."""

    progress = Signal(float)
    log = Signal(str)
    finished = Signal(bool)

    def __init__(self):
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            ok = stems.repair_engine(self.log.emit, self.progress.emit,
                                     lambda: self._cancel)
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"errore verifica motore: {exc}")
            ok = False
        self.finished.emit(ok)


def make_verify_thread() -> tuple[QThread, EngineVerifyWorker]:
    thread = QThread()
    worker = EngineVerifyWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread, worker

# Template nome file: etichetta leggibile -> pattern yt-dlp
TEMPLATES: list[tuple[str, str]] = [
    ("Titolo", "%(title)s"),
    ("Canale - Titolo", "%(uploader)s - %(title)s"),
    ("Indice - Titolo (playlist)", "%(playlist_index)s - %(title)s"),
    ("Titolo [id]", "%(title)s [%(id)s]"),
]

STATUS_COLORS = {
    "in attesa": "#8b90a0",
    "scaricando": "#5aa9ff",
    "conversione": "#ffb454",
    "fatto": "#3ddc84",
    "errore": "#ff4d63",
}


class QueueRow(QWidget):
    """Riga visuale per un item della coda: miniatura, titolo, durata, stato, progress."""

    THUMB_W, THUMB_H = 64, 44

    def __init__(self, item: QueueItem):
        super().__init__()
        self.item = item
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 9)
        outer.setSpacing(12)

        # miniatura
        self.thumb_lbl = QLabel()
        self.thumb_lbl.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.thumb_lbl.setStyleSheet("background:#232733; border-radius:6px;")
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.thumb_lbl, 0)

        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        outer.addLayout(lay, 1)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_lbl = QLabel(self._display_title())
        self.title_lbl.setStyleSheet("font-weight:600;")
        self.title_lbl.setWordWrap(False)
        self.dur_lbl = QLabel("")
        self.dur_lbl.setStyleSheet("color:#6b7080; font-size:11px;")
        self.status_lbl = QLabel(item.status)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._style_status(item.status)
        top.addWidget(self.title_lbl, 1)
        top.addWidget(self.dur_lbl, 0)
        top.addWidget(self.status_lbl, 0)
        lay.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("color:#6b7080; font-size:11px;")
        lay.addWidget(self.detail_lbl)

    def _display_title(self) -> str:
        t = self.item.title or self.item.url
        return t if len(t) <= 70 else t[:67] + "…"

    def _style_status(self, status: str) -> None:
        color = STATUS_COLORS.get(status, "#8b90a0")
        self.status_lbl.setStyleSheet(f"color:{color}; font-weight:600; font-size:12px;")

    def set_info(self, title: str, duration: str, thumb_bytes: bytes) -> None:
        """Aggiorna anteprima (titolo/durata/miniatura) dopo il fetch info."""
        if title:
            self.item.title = title
            self.title_lbl.setText(self._display_title())
        if duration:
            self.dur_lbl.setText(duration)
        if thumb_bytes:
            pix = QPixmap()
            if pix.loadFromData(thumb_bytes):
                scaled = pix.scaled(
                    self.THUMB_W, self.THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_lbl.setPixmap(scaled)

    def update_progress(self, pct: float, status: str, detail: str) -> None:
        self.item.status = status
        self.item.progress = pct
        self.bar.setValue(int(pct))
        self.status_lbl.setText(status)
        self._style_status(status)
        if detail:
            self.detail_lbl.setText(detail)

    def set_finished(self, ok: bool, result: str) -> None:
        if ok:
            self.item.title = result
            self.item.status = "fatto"
            self.title_lbl.setText(self._display_title())
            self.bar.setValue(100)
            self.status_lbl.setText("fatto")
            self.detail_lbl.setText("")
            self.detail_lbl.setStyleSheet("color:#6b7080; font-size:11px;")
        else:
            self.item.status = "errore"
            self.item.error = result
            self.status_lbl.setText("errore")
            self.detail_lbl.setStyleSheet("color:#ff6b7d; font-size:11px;")
            self.detail_lbl.setText(result)
        self._style_status(self.item.status)


class HistoryDialog(QDialog):
    """Finestra cronologia: download passati con apri file/cartella e ri-scarica."""

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self._main = parent
        self.setWindowTitle("Cronologia download")
        self.setObjectName("Root")
        self.resize(620, 460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._open_file())
        lay.addWidget(self.list, 1)

        btns = QHBoxLayout()
        b_file = QPushButton("Apri file"); b_file.setObjectName("Ghost")
        b_file.clicked.connect(self._open_file)
        b_folder = QPushButton("Apri cartella"); b_folder.setObjectName("Ghost")
        b_folder.clicked.connect(self._open_folder)
        b_redl = QPushButton("Ri-scarica"); b_redl.setObjectName("Ghost")
        b_redl.clicked.connect(self._redownload)
        b_clear = QPushButton("Svuota cronologia"); b_clear.setObjectName("Ghost")
        b_clear.clicked.connect(self._clear)
        btns.addWidget(b_file); btns.addWidget(b_folder); btns.addWidget(b_redl)
        btns.addStretch(1); btns.addWidget(b_clear)
        lay.addLayout(btns)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        self._entries = history.load()
        if not self._entries:
            it = QListWidgetItem("(nessun download nella cronologia)")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
            return
        for e in self._entries:
            title = e.get("title") or e.get("url") or "?"
            fmt = e.get("format") or ""
            when = history.format_time(e.get("ts"))
            it = QListWidgetItem(f"{title}   ·   {fmt}   ·   {when}")
            it.setData(Qt.ItemDataRole.UserRole, e)
            self.list.addItem(it)

    def _current(self) -> dict | None:
        it = self.list.currentItem()
        if it is None:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _open_file(self) -> None:
        e = self._current()
        if e:
            self._main._open_path(e.get("filepath", ""))

    def _open_folder(self) -> None:
        e = self._current()
        if e and e.get("filepath"):
            self._main._open_path(os.path.dirname(e["filepath"]))

    def _redownload(self) -> None:
        e = self._current()
        if e and e.get("url"):
            self._main._add_item(e["url"])
            self._main._show_raise()

    def _clear(self) -> None:
        if QMessageBox.question(self, "Svuota cronologia",
                                "Cancellare tutta la cronologia?") == QMessageBox.StandardButton.Yes:
            history.clear()
            self._reload()


def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    return f


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("class", "SectionLabel")
    lbl.setStyleSheet("color:#8b90a0; font-size:11px; font-weight:600;")
    return lbl


class MainWindow(QWidget):
    # soglia (px) sotto la quale il corpo passa da due colonne a colonna unica
    NARROW_W = 900
    # larghezza massima del contenuto centrato sui monitor grandi
    CONTENT_MAX_W = 1500

    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle(f"Sonora {__version__} — Pisco Factory")
        self.resize(760, 880)
        self.setMinimumSize(520, 640)

        self.cfg = config.load()
        self.queue: list[QueueItem] = []
        self.rows: list[QueueRow] = []
        self._thread: QThread | None = None
        self._worker: DownloadWorker | None = None
        self._upd_thread: QThread | None = None
        self._upd_worker = None
        self._appchk_thread: QThread | None = None   # controllo aggiornamenti app
        self._appchk_worker = None
        self._appchk_verbose = False
        self._appupd_thread: QThread | None = None    # download installer app
        self._appupd_worker = None
        self._appupd_progress: QProgressDialog | None = None
        self._stem_thread: QThread | None = None
        self._stem_worker: StemWorker | None = None
        self._uninst_thread: QThread | None = None
        self._uninst_worker: EngineUninstallWorker | None = None
        self._verify_thread: QThread | None = None
        self._verify_worker: EngineVerifyWorker | None = None
        self._stem_row: QueueRow | None = None
        self._stem_batch: list[QueueItem] = []
        self._stem_cancel_batch = False
        self._stem_ok_any = False
        self._stem_last_dir = ""
        self._stem_mode = "6hq"
        self._stem_format = "wav"

        # segnali condivisi per il fetch info (anteprima)
        self._info_signals = InfoSignals()
        self._info_signals.done.connect(self._on_info_done)

        # segnali per la ricerca video (ytsearch)
        self._search_signals = SearchSignals()
        self._search_signals.done.connect(self._on_search_done)
        self._search_query = ""

        self.setAcceptDrops(True)   # drag & drop link

        # stato sessione download (per notifica a fine)
        self._ok_count = 0
        self._was_cancelled = False
        self._really_quit = False

        self._build_ui()
        self._load_settings_into_ui()
        self._setup_tray()
        self._setup_clipboard_watch()
        self._autopaste_clipboard()

        # controllo aggiornamenti app all'avvio (silenzioso, in background)
        if app_update.auto_check_enabled() and app_update.configured_repo():
            QTimer.singleShot(2500, lambda: self._start_update_check(verbose=False))

        # rinnovo silenzioso del token di licenza (revoca/scadenza), in background
        QTimer.singleShot(3500, self._refresh_license)

        # «Novità»: al primo avvio dopo un aggiornamento mostra cosa è cambiato
        QTimer.singleShot(800, self._maybe_show_whats_new)

    def _maybe_show_whats_new(self) -> None:
        """Mostra le novità se questa versione non è ancora stata «vista».

        Alla prima installazione (nessuna versione registrata) non mostra
        nulla: registra e basta, le novità hanno senso solo dopo un update.
        """
        last = str(self.cfg.get("last_seen_version", "") or "")
        if last == __version__:
            return
        try:
            if last:
                entries = changelog.entries_since(last)
                if entries:
                    self._show_changelog(entries, fresh_update=True)
        finally:
            self.cfg["last_seen_version"] = __version__
            config.save(self.cfg)

    def _show_changelog(self, entries: list, fresh_update: bool = False) -> None:
        """Dialogo «Novità»: elenco versioni e migliorie, scorrevole."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Novità di Sonora")
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 12)
        title = QLabel("🎉 Sonora si è aggiornata! Ecco le novità:"
                       if fresh_update else "Novità delle versioni di Sonora")
        title.setStyleSheet("font-size:15px; font-weight:700;")
        lay.addWidget(title)
        body = QLabel(changelog.as_html(entries))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(dlg.accept)
        lay.addWidget(bb)
        dlg.exec()

    def _refresh_license(self) -> None:
        # su thread separato: refresh_if_needed può fare rete (timeout) e non
        # deve bloccare la UI. Non tocca oggetti Qt, quindi è sicuro.
        import threading

        def _work() -> None:
            try:
                from . import licensing
                licensing.refresh_if_needed()
            except Exception:  # noqa: BLE001 (best-effort)
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _refresh_license_ui(self) -> None:
        """Aggiorna il footer (banner prova + pulsante Attiva) secondo lo stato."""
        text = f"Sonora v{__version__}  ·  © 2026 Pisco Factory"
        show_activate = True
        try:
            from . import licensing
            st = licensing.status()
            if st.state == "trial":
                giorni = "1 giorno" if st.days_left == 1 else f"{st.days_left} giorni"
                text += f"  ·  Prova: {giorni}"
            elif st.state == "expired":
                text += "  ·  Prova scaduta"
            else:  # licensed
                text += "  ·  Attivo"
                show_activate = False
        except Exception:  # noqa: BLE001 (il footer non deve mai bloccare la UI)
            pass
        self._brand_label.setText(text)
        self._activate_btn.setVisible(show_activate)

    def _open_activation(self) -> None:
        """Apre la finestra di attivazione codice (da pulsante Attiva)."""
        from . import licensing
        from .ui_license import run_activation_gate

        expired = licensing.status().state == "expired"
        if run_activation_gate(trial_expired=expired, parent=self):
            self._refresh_license_ui()

    # ---------- costruzione UI ----------

    def _build_ui(self) -> None:
        # finestra a schede: Scarica (downloader) + Mixer
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        shell.addWidget(self.tabs, 1)

        # footer globale: brand + copyright + versione + Info (su entrambe le schede)
        footer = QFrame()
        footer.setObjectName("Footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 4, 16, 4)
        fl.setSpacing(10)
        self._brand_label = QLabel()
        self._brand_label.setStyleSheet("color:#6b7080; font-size:11px;")
        disclaimer = QLabel("Usa solo contenuti di cui detieni i diritti.")
        disclaimer.setStyleSheet("color:#565b6b; font-size:11px; font-style:italic;")
        # pulsante Attiva: apre la finestra del codice in qualsiasi momento
        # (visibile durante la prova o se scaduta; nascosto se già attivata).
        self._activate_btn = QPushButton("Attiva")
        self._activate_btn.setObjectName("GhostMini")
        self._activate_btn.setFixedWidth(60)
        self._activate_btn.clicked.connect(self._open_activation)
        info_btn = QPushButton("Info")
        info_btn.setObjectName("GhostMini")
        info_btn.setFixedWidth(50)
        info_btn.clicked.connect(self._show_about)
        news_btn = QPushButton("Novità")
        news_btn.setObjectName("GhostMini")
        news_btn.setFixedWidth(60)
        news_btn.setToolTip("Cosa è cambiato nelle varie versioni di Sonora.")
        news_btn.clicked.connect(lambda: self._show_changelog(changelog.CHANGELOG))
        fl.addWidget(self._brand_label)
        fl.addStretch(1)
        fl.addWidget(disclaimer)
        fl.addWidget(self._activate_btn)
        fl.addWidget(news_btn)
        fl.addWidget(info_btn)
        shell.addWidget(footer, 0)
        self._refresh_license_ui()

        dl_tab = QWidget()
        dl_tab.setObjectName("Root")
        self.mixer_tab = MixerTab()
        self.lyrics_tab = LyricsTab(self)
        self.mixer_tab.song_loaded.connect(self.lyrics_tab.load_song_lyrics)
        self.mixer_tab.position_changed.connect(self.lyrics_tab.set_position)
        self.lyrics_tab.seek_requested.connect(self.mixer_tab.seek_seconds)
        self.tabs.addTab(dl_tab, "Scarica")
        self._mixer_index = self.tabs.addTab(self.mixer_tab, "Mixer")
        self.tabs.addTab(self.lyrics_tab, "Testi")

        # azioni del mixer (Accordatore/Esporta/Analizza/Recenti) sulla barra
        # schede, a destra; visibili solo quando la scheda Mixer è attiva.
        self.tabs.setCornerWidget(self.mixer_tab.actions_host,
                                  Qt.Corner.TopRightCorner)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabs.currentIndex())

        page = QVBoxLayout(dl_tab)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        # area scrollabile: se il contenuto non entra (font grandi, DPI alto,
        # finestra bassa) scorre invece di sovrapporre le sezioni.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("Root")
        scroll.setWidget(content)

        # contenitore centrato con larghezza massima (fluido: niente min-width
        # rigida, così su monitor piccoli il contenuto si adatta invece di
        # sovrapporsi; sui monitor grandi resta centrato entro CONTENT_MAX_W)
        outer = QHBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        container = QWidget()
        container.setMaximumWidth(self.CONTENT_MAX_W)
        outer.addWidget(container, 20)
        outer.addStretch(1)

        root = QVBoxLayout(container)
        root.setContentsMargins(26, 22, 26, 10)
        root.setSpacing(16)

        # header
        header = QVBoxLayout()
        header.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("Sonora")
        title.setObjectName("Title")
        ver = QLabel(f"v{__version__}")
        ver.setStyleSheet("color:#6b7080; font-size:12px; font-weight:600;")
        ver.setAlignment(Qt.AlignmentFlag.AlignBottom)
        title_row.addWidget(title, 0)
        title_row.addWidget(ver, 0, Qt.AlignmentFlag.AlignBottom)
        title_row.addStretch(1)
        sub = QLabel("Scarica l'audio da YouTube — mp3, m4a, opus, flac, wav")
        sub.setObjectName("Subtitle")
        header.addLayout(title_row)
        header.addWidget(sub)
        root.addLayout(header)

        # --- card URL ---
        url_card = _card()
        uc = QVBoxLayout(url_card)
        uc.setContentsMargins(16, 14, 16, 16)
        uc.setSpacing(10)
        uc.addWidget(_section_label("LINK YOUTUBE"))
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "Incolla un link, oppure scrivi cosa cercare e premi Invio…")
        self.url_edit.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Aggiungi")
        add_btn.clicked.connect(self._on_add)
        load_file_btn = QPushButton("Carica file…")
        load_file_btn.setObjectName("Ghost")
        load_file_btn.setToolTip(
            "Aggiungi alla coda un file audio già scaricato (poi separabile in stem).")
        load_file_btn.clicked.connect(self._on_load_file)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(add_btn)
        url_row.addWidget(load_file_btn)
        uc.addLayout(url_row)

        # --- pannello risultati ricerca (inline, nascosto finché non si cerca) ---
        self.search_panel = QWidget()
        sp = QVBoxLayout(self.search_panel)
        sp.setContentsMargins(0, 6, 0, 0)
        sp.setSpacing(6)
        search_head = QHBoxLayout()
        self.search_label = QLabel("Risultati ricerca")
        self.search_label.setObjectName("Subtitle")
        search_close = QPushButton("✕")
        search_close.setObjectName("Ghost")
        search_close.setFixedWidth(34)
        search_close.setToolTip("Chiudi i risultati")
        search_close.clicked.connect(self._close_search)
        search_head.addWidget(self.search_label, 1)
        search_head.addWidget(search_close, 0)
        sp.addLayout(search_head)
        self.search_list = QListWidget()
        self.search_list.setMaximumHeight(230)
        self.search_list.itemActivated.connect(self._on_search_pick)
        self.search_list.itemDoubleClicked.connect(self._on_search_pick)
        sp.addWidget(self.search_list)
        self.search_panel.hide()
        uc.addWidget(self.search_panel)

        url_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root.addWidget(url_card)

        # --- corpo responsive: due colonne su schermi larghi, colonna unica
        # in verticale sui monitor piccoli (disposizione gestita da
        # _apply_layout in base alla larghezza della finestra) ---
        self.body_container = QWidget()
        self.body_container.setObjectName("Root")
        root.addWidget(self.body_container, 1)

        # --- card opzioni ---
        self.opt_card = _card()
        opt_card = self.opt_card
        oc = QVBoxLayout(opt_card)
        oc.setContentsMargins(16, 14, 16, 16)
        oc.setSpacing(12)
        # la card non puo' mai diventare piu corta del suo contenuto:
        # impedisce la sovrapposizione delle righe con i font reali.
        oc.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        # formato + bitrate + template
        line1 = QHBoxLayout()
        line1.setSpacing(14)

        fmt_box = QVBoxLayout()
        fmt_box.setSpacing(5)
        fmt_box.addWidget(_section_label("FORMATO"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(AUDIO_FORMATS)
        self.fmt_combo.currentTextChanged.connect(self._on_format_changed)
        fmt_box.addWidget(self.fmt_combo)
        line1.addLayout(fmt_box, 1)

        br_box = QVBoxLayout()
        br_box.setSpacing(5)
        br_box.addWidget(_section_label("BITRATE (mp3)"))
        self.br_combo = QComboBox()
        self.br_combo.addItems(["128", "192", "320"])
        br_box.addWidget(self.br_combo)
        line1.addLayout(br_box, 1)

        tpl_box = QVBoxLayout()
        tpl_box.setSpacing(5)
        tpl_box.addWidget(_section_label("NOME FILE"))
        self.tpl_combo = QComboBox()
        for label, _pat in TEMPLATES:
            self.tpl_combo.addItem(label)
        self.tpl_combo.addItem("Personalizzato…")
        self.tpl_combo.currentIndexChanged.connect(self._on_template_changed)
        tpl_box.addWidget(self.tpl_combo)
        line1.addLayout(tpl_box, 2)

        oc.addLayout(line1)

        # campo template personalizzato (nascosto di default)
        self.custom_tpl_edit = QLineEdit()
        self.custom_tpl_edit.setPlaceholderText("Pattern yt-dlp, es. %(uploader)s/%(title)s")
        self.custom_tpl_edit.setVisible(False)
        oc.addWidget(self.custom_tpl_edit)

        # cartella destinazione
        dest_box = QVBoxLayout()
        dest_box.setSpacing(5)
        dest_box.addWidget(_section_label("CARTELLA DESTINAZIONE"))
        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        browse_btn = QPushButton("Sfoglia")
        browse_btn.setObjectName("Ghost")
        browse_btn.clicked.connect(self._on_browse)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(browse_btn)
        dest_box.addLayout(dest_row)
        oc.addLayout(dest_box)

        # toggle
        tog_row = QHBoxLayout()
        self.meta_chk = QCheckBox("Includi metadata (titolo/artista)")
        self.thumb_chk = QCheckBox("Includi copertina (cover)")
        self.folder_chk = QCheckBox("Sottocartella per ogni file")
        self.folder_chk.setToolTip(
            "Ogni download finisce in una sua cartella col titolo del video,\n"
            "dentro la cartella di destinazione."
        )
        self.norm_chk = QCheckBox("Normalizza volume")
        self.norm_chk.setToolTip(
            "Applica loudnorm: tutti i brani allo stesso livello di volume.\n"
            "La conversione e' un po' piu lenta."
        )
        tog_row.addWidget(self.meta_chk)
        tog_row.addWidget(self.thumb_chk)
        tog_row.addStretch(1)
        oc.addLayout(tog_row)

        tog_row2 = QHBoxLayout()
        tog_row2.addWidget(self.folder_chk)
        tog_row2.addWidget(self.norm_chk)
        tog_row2.addStretch(1)
        oc.addLayout(tog_row2)

        self.watch_chk = QCheckBox("Monitora appunti")
        self.watch_chk.setToolTip("Aggiunge automaticamente in coda i link YouTube che copi.")
        self.notify_chk = QCheckBox("Avvisa a fine (notifica + suono)")
        tog_row3 = QHBoxLayout()
        tog_row3.addWidget(self.watch_chk)
        tog_row3.addWidget(self.notify_chk)
        tog_row3.addStretch(1)
        oc.addLayout(tog_row3)

        # --- riga STEM (separazione sorgenti) ---
        stem_row = QHBoxLayout()
        stem_row.setSpacing(10)
        stem_lbl = _section_label("STEM")
        self.stem_mode_combo = QComboBox()
        for label, _v in STEM_MODES:
            self.stem_mode_combo.addItem(label)
        self.stem_mode_combo.setToolTip(
            "Quante tracce produrre e con quale motore.\n"
            "• 6 stem: voce, batteria, basso, chitarra, piano, altro\n"
            "• Roformer SW: la migliore qualità sugli strumenti, un solo passaggio\n"
            "• Roformer+Demucs: voce leggermente migliore ma 3 passaggi (lento)\n"
            "• Demucs: più veloce, qualità inferiore\n"
            "• Voce/strumentale: due tracce, ideale per karaoke")
        self.stem_fmt_combo = QComboBox()
        self.stem_fmt_combo.addItems(STEM_FORMATS)
        self.stem_all_btn = QPushButton("Separa tutti")
        self.stem_all_btn.setObjectName("Ghost")
        self.stem_all_btn.setToolTip("Separa in stem tutti i brani pronti in coda.")
        self.stem_all_btn.clicked.connect(self._on_separate_all)
        self.stem_file_btn = QPushButton("Separa file…")
        self.stem_file_btn.setObjectName("Ghost")
        self.stem_file_btn.setToolTip("Scegli un file audio locale da separare in stem.")
        self.stem_file_btn.clicked.connect(self._on_separate_file_dialog)
        stem_row.addWidget(stem_lbl)
        stem_row.addWidget(self.stem_mode_combo)
        stem_row.addWidget(self.stem_fmt_combo)
        stem_row.addStretch(1)
        stem_row.addWidget(self.stem_all_btn)
        stem_row.addWidget(self.stem_file_btn)
        oc.addLayout(stem_row)

        # riga stato motore stem
        eng_row = QHBoxLayout()
        self.engine_lbl = QLabel("")
        self.engine_lbl.setStyleSheet("color:#6b7080; font-size:11px;")
        self.engine_opts_btn = QPushButton("Opzioni ▾")
        self.engine_opts_btn.setObjectName("Ghost")
        self.engine_opts_btn.setToolTip("Disinstalla il motore o cambia la cartella di installazione.")
        eng_menu = QMenu(self.engine_opts_btn)
        eng_menu.addAction("Verifica / Ripara motore", self._on_verify_engine)
        eng_menu.addSeparator()
        eng_menu.addAction("Disinstalla motore", self._on_uninstall_engine)
        eng_menu.addAction("Cartella di installazione…", self._on_change_engine_location)
        self.engine_opts_btn.setMenu(eng_menu)
        self.engine_btn = QPushButton("Installa motore")
        self.engine_btn.setObjectName("Ghost")
        self.engine_btn.setToolTip("Scarica/aggiorna il motore stem (Demucs + PyTorch, ~3GB).")
        self.engine_btn.clicked.connect(self._on_install_engine)
        eng_row.addWidget(self.engine_lbl, 1)
        eng_row.addWidget(self.engine_opts_btn, 0)
        eng_row.addWidget(self.engine_btn, 0)
        oc.addLayout(eng_row)

        # riga manutenzione: versione yt-dlp + aggiorna
        maint_row = QHBoxLayout()
        self.ytdlp_lbl = QLabel("")
        self.ytdlp_lbl.setStyleSheet("color:#6b7080; font-size:11px;")
        self.update_btn = QPushButton("Aggiorna yt-dlp")
        self.update_btn.setObjectName("Ghost")
        self.update_btn.setToolTip(
            "Scarica l'ultima versione di yt-dlp.\n"
            "Necessario ogni tanto: YouTube cambia spesso.\n"
            "Ha effetto dopo il riavvio dell'app."
        )
        self.update_btn.clicked.connect(self._on_update_ytdlp)
        maint_row.addWidget(self.ytdlp_lbl, 1)
        maint_row.addWidget(self.update_btn, 0)
        oc.addLayout(maint_row)

        # la card prende l'altezza del contenuto e non si comprime sotto di essa
        opt_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # altezze minime esplicite: combo e campi non possono sovrapporsi
        for w in (self.url_edit, self.fmt_combo, self.br_combo, self.tpl_combo,
                  self.custom_tpl_edit, self.dest_edit):
            w.setMinimumHeight(38)

        # blocco LOG (etichetta + vista log)
        self.log_block = QWidget()
        log_lay = QVBoxLayout(self.log_block)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(8)
        log_lay.addWidget(_section_label("LOG"))
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        log_lay.addWidget(self.log_view, 1)

        # blocco CODA (intestazione + lista)
        self.queue_block = QWidget()
        q_lay = QVBoxLayout(self.queue_block)
        q_lay.setContentsMargins(0, 0, 0, 0)
        q_lay.setSpacing(12)
        queue_head = QHBoxLayout()
        queue_head.addWidget(_section_label("CODA"))
        queue_head.addStretch(1)
        self.history_btn = QPushButton("Cronologia")
        self.history_btn.setObjectName("Ghost")
        self.history_btn.clicked.connect(self._on_show_history)
        self.retry_btn = QPushButton("Riprova falliti")
        self.retry_btn.setObjectName("Ghost")
        self.retry_btn.clicked.connect(self._on_retry_failed)
        self.clear_btn = QPushButton("Svuota")
        self.clear_btn.setObjectName("Ghost")
        self.clear_btn.clicked.connect(self._on_clear)
        queue_head.addWidget(self.history_btn)
        queue_head.addWidget(self.retry_btn)
        queue_head.addWidget(self.clear_btn)
        q_lay.addLayout(queue_head)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_widget.setMinimumHeight(210)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        q_lay.addWidget(self.list_widget, 1)

        # disponi i blocchi (opzioni/coda/log) in base alla larghezza corrente
        self._narrow: bool | None = None
        self._update_responsive()

        # --- barra azioni fissa in basso (fuori dallo scroll) ---
        bar = QWidget()
        bar.setObjectName("Root")
        bar_outer = QHBoxLayout(bar)
        bar_outer.setContentsMargins(0, 0, 0, 0)
        bar_outer.addStretch(1)
        bar_inner = QWidget()
        bar_inner.setMaximumWidth(self.CONTENT_MAX_W)
        bar_outer.addWidget(bar_inner, 20)
        bar_outer.addStretch(1)

        actions = QHBoxLayout(bar_inner)
        actions.setContentsMargins(26, 10, 26, 16)
        self.open_btn = QPushButton("Apri cartella")
        self.open_btn.setObjectName("Ghost")
        self.open_btn.clicked.connect(self._on_open_folder)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("Ghost")
        self.stop_btn.setMinimumWidth(90)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        self.download_btn = QPushButton("⬇  Scarica")
        self.download_btn.setObjectName("Primary")
        self.download_btn.setMinimumWidth(160)
        self.download_btn.clicked.connect(self._on_download)
        actions.addWidget(self.open_btn)
        actions.addStretch(1)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.download_btn)
        page.addWidget(bar)

    # ---------- layout responsive ----------

    def resizeEvent(self, event) -> None:  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        self._update_responsive()

    def _update_responsive(self) -> None:
        if not hasattr(self, "body_container"):
            return
        self._apply_layout(self.width() < self.NARROW_W)

    def _apply_layout(self, narrow: bool) -> None:
        """Dispone opzioni/coda/log: due colonne se largo, impilati se stretto."""
        if narrow == self._narrow:
            return
        self._narrow = narrow
        # stacca i blocchi (il reparent a None li nasconde: niente flash),
        # poi distruggi il vecchio layout assegnandolo a un widget usa-e-getta
        for w in (self.opt_card, self.queue_block, self.log_block):
            w.setParent(None)
        old = self.body_container.layout()
        if old is not None:
            QWidget().setLayout(old)
        if narrow:
            lay = QVBoxLayout(self.body_container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(16)
            lay.addWidget(self.opt_card, 0)
            lay.addWidget(self.queue_block, 1)
            lay.addWidget(self.log_block, 1)
        else:
            lay = QHBoxLayout(self.body_container)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(18)
            left = QVBoxLayout()
            left.setContentsMargins(0, 0, 0, 0)
            left.setSpacing(16)
            left.addWidget(self.opt_card, 0)
            left.addWidget(self.log_block, 1)
            lay.addLayout(left, 3)
            lay.addWidget(self.queue_block, 2)

    # ---------- settings <-> UI ----------

    def _load_settings_into_ui(self) -> None:
        self.fmt_combo.setCurrentText(self.cfg.get("audio_format", "mp3"))
        self.br_combo.setCurrentText(self.cfg.get("bitrate", "192"))
        self.dest_edit.setText(self.cfg.get("dest_dir", paths.default_download_dir()))
        self.meta_chk.setChecked(bool(self.cfg.get("embed_metadata", True)))
        self.thumb_chk.setChecked(bool(self.cfg.get("embed_thumbnail", True)))
        self.folder_chk.setChecked(bool(self.cfg.get("per_file_folder", True)))
        self.norm_chk.setChecked(bool(self.cfg.get("normalize", False)))
        self.watch_chk.setChecked(bool(self.cfg.get("clipboard_watch", False)))
        self.notify_chk.setChecked(bool(self.cfg.get("notify_end", True)))
        sm = self.cfg.get("stem_mode", "6")
        sm_idx = next((i for i, (_l, v) in enumerate(STEM_MODES) if v == sm), 0)
        self.stem_mode_combo.setCurrentIndex(sm_idx)
        self.stem_fmt_combo.setCurrentText(self.cfg.get("stem_format", "wav"))
        self._refresh_engine_label()
        # template: trova match o personalizzato
        saved = self.cfg.get("filename_template", "%(title)s")
        idx = next((i for i, (_l, p) in enumerate(TEMPLATES) if p == saved), None)
        if idx is None:
            self.tpl_combo.setCurrentIndex(self.tpl_combo.count() - 1)
            self.custom_tpl_edit.setText(saved)
            self.custom_tpl_edit.setVisible(True)
        else:
            self.tpl_combo.setCurrentIndex(idx)
        self._on_format_changed(self.fmt_combo.currentText())
        self._refresh_ytdlp_label()

    def _refresh_ytdlp_label(self) -> None:
        self.ytdlp_lbl.setText(f"yt-dlp {updater.current_version()}")

    def _current_template(self) -> str:
        idx = self.tpl_combo.currentIndex()
        if idx < len(TEMPLATES):
            return TEMPLATES[idx][1]
        return self.custom_tpl_edit.text().strip() or "%(title)s"

    def _gather_settings(self) -> dict:
        return {
            "dest_dir": self.dest_edit.text().strip(),
            "audio_format": self.fmt_combo.currentText(),
            "bitrate": self.br_combo.currentText(),
            "filename_template": self._current_template(),
            "embed_metadata": self.meta_chk.isChecked(),
            "embed_thumbnail": self.thumb_chk.isChecked(),
            "per_file_folder": self.folder_chk.isChecked(),
            "normalize": self.norm_chk.isChecked(),
            "clipboard_watch": self.watch_chk.isChecked(),
            "notify_end": self.notify_chk.isChecked(),
            "stem_mode": STEM_MODES[self.stem_mode_combo.currentIndex()][1],
            "stem_format": self.stem_fmt_combo.currentText(),
        }

    def _persist(self) -> None:
        self.cfg.update(self._gather_settings())
        config.save(self.cfg)

    # ---------- handler UI ----------

    def _on_format_changed(self, fmt: str) -> None:
        from .downloader import LOSSLESS_FORMATS, NO_TAG_FORMATS
        is_lossless = fmt in LOSSLESS_FORMATS    # bitrate non si applica
        no_tags = fmt in NO_TAG_FORMATS          # wav: niente tag/cover
        self.br_combo.setEnabled(not is_lossless)
        self.meta_chk.setEnabled(not no_tags)
        self.thumb_chk.setEnabled(not no_tags)

    def _on_template_changed(self, idx: int) -> None:
        self.custom_tpl_edit.setVisible(idx >= len(TEMPLATES))

    def _on_browse(self) -> None:
        start = self.dest_edit.text() or paths.default_download_dir()
        d = QFileDialog.getExistingDirectory(self, "Scegli cartella destinazione", start)
        if d:
            self.dest_edit.setText(d)
            self._persist()

    def _on_add(self) -> None:
        text = self.url_edit.text().strip()
        if not text:
            return
        if text.startswith("http://") or text.startswith("https://"):
            self._add_item(text)
            self.url_edit.clear()
            self._close_search()
            return
        # non è un link: trattalo come ricerca testuale
        self._start_search(text)

    # ---------- ricerca video ----------

    def _start_search(self, query: str) -> None:
        self._search_query = query
        self.search_panel.show()
        self.search_label.setText(f"Ricerca di “{query}”…")
        self.search_list.clear()
        it = QListWidgetItem("Ricerca in corso…")
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        self.search_list.addItem(it)
        run_search_task(SearchTask(query, self._search_signals))

    def _on_search_done(self, query: str, ok: bool, results: list, error: str) -> None:
        # ignora risultati di ricerche superate da una più recente
        if query != self._search_query:
            return
        self.search_list.clear()
        if not ok:
            self.search_label.setText("Ricerca fallita")
            it = QListWidgetItem(error or "Errore durante la ricerca.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.search_list.addItem(it)
            return
        if not results:
            self.search_label.setText(f"Nessun risultato per “{query}”")
            it = QListWidgetItem("(nessun video trovato)")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.search_list.addItem(it)
            return
        self.search_label.setText(
            f"{len(results)} risultati per “{query}” — doppio clic o Invio per aggiungere")
        for r in results:
            dur = f"  ·  {r['duration']}" if r.get("duration") else ""
            up = f"  ·  {r['uploader']}" if r.get("uploader") else ""
            label = f"{r['title']}{dur}{up}"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, r["url"])
            it.setToolTip(r["url"])
            self.search_list.addItem(it)

    def _on_search_pick(self, item: QListWidgetItem) -> None:
        url = item.data(Qt.ItemDataRole.UserRole)
        if not url:
            return
        added = self._add_item(url)
        if added is not None:
            self._log(f"+ {item.text().split('  ·  ')[0]}")
        # segnala visivamente che è già stato aggiunto
        item.setText("✓ " + item.text().lstrip("✓ "))

    def _close_search(self) -> None:
        self._search_query = ""
        self.search_list.clear()
        self.search_panel.hide()

    def _on_load_file(self) -> None:
        """Aggiunge alla coda uno o più file audio locali già scaricati."""
        start = self.dest_edit.text() or paths.default_download_dir()
        files, _ = QFileDialog.getOpenFileNames(
            self, "Carica file audio", start,
            "Audio (*.mp3 *.wav *.flac *.m4a *.opus *.aac *.ogg *.wma)")
        added = 0
        for f in files:
            if os.path.isfile(f):
                self._add_local_item(f)
                self._log(f"+ file locale: {os.path.basename(f)}")
                added += 1
        if added:
            self._show_raise()

    def _add_item(self, url: str, fetch: bool = True) -> QueueItem | None:
        # evita duplicati
        if url and any(it.url == url for it in self.queue):
            return None
        item = QueueItem(url=url)
        self.queue.append(item)
        row = QueueRow(item)
        self.rows.append(row)
        lw_item = QListWidgetItem(self.list_widget)
        lw_item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(lw_item)
        self.list_widget.setItemWidget(lw_item, row)
        # anteprima async (titolo/durata/miniatura) solo per URL veri
        if fetch and url:
            run_info_task(InfoTask(item, self._info_signals))
        return item

    def _add_local_item(self, filepath: str) -> QueueItem | None:
        """Aggiunge una riga per un file audio locale (per separazione stem)."""
        item = QueueItem(url="", title=os.path.basename(filepath), status="pronto")
        item.extra["filepath"] = filepath
        self.queue.append(item)
        row = QueueRow(item)
        row.update_progress(0.0, "pronto", "file locale")
        self.rows.append(row)
        lw_item = QListWidgetItem(self.list_widget)
        lw_item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(lw_item)
        self.list_widget.setItemWidget(lw_item, row)
        return item

    def _on_info_done(self, item, ok: bool, title: str, duration: str, thumb: bytes) -> None:
        if item not in self.queue:
            return
        row = self.rows[self.queue.index(item)]
        if ok:
            row.set_info(title, duration, thumb)

    def _on_clear(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        self.queue.clear()
        self.rows.clear()
        self.list_widget.clear()

    def _on_open_folder(self) -> None:
        d = self.dest_edit.text().strip()
        if d and os.path.isdir(d):
            if sys.platform == "win32":
                os.startfile(d)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.run(["open", d], check=False)
            else:
                subprocess.run(["xdg-open", d], check=False)

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    # ---------- auto-incolla / drag & drop ----------

    @staticmethod
    def _looks_like_url(text: str) -> bool:
        t = (text or "").strip()
        return t.startswith(("http://", "https://")) and (
            "youtu" in t or "youtube.com" in t or len(t) < 400
        )

    def _autopaste_clipboard(self) -> None:
        """Se gli appunti contengono un link, preriempi il campo URL."""
        try:
            text = QApplication.clipboard().text().strip()
        except Exception:  # noqa: BLE001
            return
        if text and self._looks_like_url(text) and not self.url_edit.text().strip():
            self.url_edit.setText(text)

    # ---------- system tray + monitor appunti ----------

    def _tray_icon(self) -> QIcon:
        p = paths.resource("icon.ico")
        return QIcon(str(p)) if p.exists() else self.windowIcon()

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self._tray_icon(), self)
        self.tray.setToolTip("Sonora")
        menu = QMenu()
        menu.addAction("Mostra Sonora", self._show_raise)
        menu.addAction("Controlla aggiornamenti app", self._on_check_app_update)
        menu.addSeparator()
        menu.addAction("Esci", self._quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_raise()

    def _show_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tab_changed(self, index: int) -> None:
        """Mostra le azioni del mixer solo sulla scheda Mixer."""
        self.mixer_tab.actions_host.setVisible(index == self._mixer_index)

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Informazioni su Sonora")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<h2 style='margin:0'>Sonora <span style='color:#8b90a0'>v{__version__}</span></h2>"
            "<p style='margin:2px 0 10px 0; color:#8b90a0'>di <b>Pisco Factory</b></p>"
            "<p>Scarica, separa in stem ed esercitati sui brani: slow-down a tono "
            "invariato, loop, EQ, rilevamento accordi e accordatore — tutto in locale.</p>"
            "<p style='color:#8b90a0; font-size:11px'>© 2026 Pisco Factory. Tutti i diritti riservati.</p>")
        box.setInformativeText(
            "Costruito con software open source: yt-dlp, Demucs (Meta AI), "
            "audio-separator / BS-RoFormer, PySide6 (Qt), NumPy, soundfile, sounddevice.\n\n"
            "Uso responsabile: separa ed elabora solo contenuti di cui detieni i diritti "
            "o consentiti dalla licenza. L'utente è responsabile dell'uso del software.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _quit_app(self) -> None:
        self._really_quit = True
        self.close()

    def _on_check_app_update(self) -> None:
        """Controllo aggiornamenti richiesto dall'utente (verboso)."""
        self._start_update_check(verbose=True)

    def _start_update_check(self, verbose: bool) -> None:
        """Avvia in background il controllo della release più recente.

        verbose=True (richiesto a mano) mostra anche gli esiti negativi
        ("sei aggiornato" / "errore"); verbose=False (all'avvio) resta silenzioso
        se non c'è nulla di nuovo.
        """
        if not app_update.configured_repo():
            if verbose:
                QMessageBox.information(
                    self, "Aggiornamenti",
                    "Aggiornamenti non configurati.\n\n"
                    "Imposta \"update_repo\": \"owner/repo\" nel file settings.json "
                    "(%APPDATA%/Sonora) e pubblica le release su GitHub.")
            return
        if self._appchk_thread and self._appchk_thread.isRunning():
            return
        self._appchk_verbose = verbose
        self._appchk_thread, self._appchk_worker = app_update.make_check_thread()
        self._appchk_worker.done.connect(self._on_update_checked)
        self._appchk_thread.finished.connect(self._cleanup_appchk_thread)
        self._appchk_thread.start()

    def _cleanup_appchk_thread(self) -> None:
        self._appchk_thread = None
        self._appchk_worker = None

    def _on_update_checked(self, info) -> None:
        import webbrowser
        verbose = self._appchk_verbose
        if info is None:
            if verbose:
                QMessageBox.warning(self, "Aggiornamenti",
                                    "Impossibile controllare gli aggiornamenti.")
            return
        if not info.get("newer"):
            if verbose:
                QMessageBox.information(self, "Aggiornamenti", "Sonora è aggiornata.")
            return
        if info.get("download_url"):
            r = QMessageBox.question(
                self, "Aggiornamento disponibile",
                f"Nuova versione {info['version']} disponibile (hai la {__version__}).\n\n"
                "Scaricare e installare ora? L'app si chiuderà per completare "
                "l'installazione.")
            if r == QMessageBox.StandardButton.Yes:
                self._start_update_download(info)
        else:
            # release senza installer allegato: ripiega sulla pagina web
            r = QMessageBox.question(
                self, "Aggiornamento disponibile",
                f"Nuova versione {info['version']} disponibile (hai la {__version__}).\n\n"
                "Aprire la pagina di download?")
            if r == QMessageBox.StandardButton.Yes:
                webbrowser.open(info["url"])

    def _start_update_download(self, info: dict) -> None:
        if self._appupd_thread and self._appupd_thread.isRunning():
            return
        self._log(f"— scarico aggiornamento {info['version']} —")
        self._appupd_progress = QProgressDialog(
            "Scarico l'aggiornamento…", "", 0, 100, self)
        self._appupd_progress.setWindowTitle("Aggiornamento Sonora")
        self._appupd_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._appupd_progress.setCancelButton(None)   # download non interrompibile
        self._appupd_progress.setMinimumDuration(0)
        self._appupd_progress.setAutoClose(False)
        self._appupd_progress.setAutoReset(False)
        self._appupd_progress.setValue(0)
        self._appupd_thread, self._appupd_worker = app_update.make_download_thread(
            info["download_url"], info.get("asset_name", ""),
            info.get("sha256_url", ""))
        self._appupd_worker.progress.connect(
            lambda p: self._appupd_progress and self._appupd_progress.setValue(int(p)))
        self._appupd_worker.log.connect(self._log)
        self._appupd_worker.finished.connect(self._on_update_downloaded)
        self._appupd_thread.finished.connect(self._cleanup_appupd_thread)
        self._appupd_thread.start()

    def _cleanup_appupd_thread(self) -> None:
        self._appupd_thread = None
        self._appupd_worker = None

    def _on_update_downloaded(self, ok: bool, path_or_err: str) -> None:
        if self._appupd_progress is not None:
            self._appupd_progress.close()
            self._appupd_progress = None
        if not ok:
            self._log(f"✖ download aggiornamento fallito: {path_or_err}")
            QMessageBox.warning(self, "Aggiornamento fallito", path_or_err)
            return
        if app_update.launch_installer(path_or_err):
            self._log("Avvio installer, chiudo Sonora…")
            self._really_quit = True
            QApplication.quit()
        else:
            QMessageBox.warning(self, "Aggiornamento",
                                "Impossibile avviare l'installer scaricato.")

    def _setup_clipboard_watch(self) -> None:
        self._clip = QApplication.clipboard()
        self._last_clip = self._clip.text().strip()   # ignora il contenuto iniziale
        self._clip.dataChanged.connect(self._on_clip_changed)

    def _on_clip_changed(self) -> None:
        if not self.watch_chk.isChecked():
            return
        try:
            text = self._clip.text().strip()
        except Exception:  # noqa: BLE001
            return
        if not text or text == self._last_clip:
            return
        self._last_clip = text
        if self._looks_like_url(text) and not any(it.url == text for it in self.queue):
            self._add_item(text)
            self._log(f"+ da appunti: {text[:60]}")
            if self.tray and not self.isVisible():
                self.tray.showMessage("Sonora", "Link aggiunto in coda",
                                      QSystemTrayIcon.MessageIcon.Information, 3000)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (override Qt)
        md = event.mimeData()
        if md.hasText() or md.hasUrls():
            event.acceptProposedAction()

    _AUDIO_EXT = (".mp3", ".wav", ".flac", ".m4a", ".opus", ".aac", ".ogg", ".wma")

    def dropEvent(self, event) -> None:  # noqa: N802 (override Qt)
        md = event.mimeData()
        added = 0
        local_audio: list[str] = []
        # file locali (drag dal file manager)
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    p = u.toLocalFile()
                    if p.lower().endswith(self._AUDIO_EXT) and os.path.isfile(p):
                        local_audio.append(p)
        # link testuali / web url
        texts: list[str] = []
        if md.hasUrls():
            texts += [u.toString() for u in md.urls() if not u.isLocalFile()]
        if md.hasText():
            texts += [line.strip() for line in md.text().splitlines() if line.strip()]
        for u in texts:
            if self._looks_like_url(u):
                self._add_item(u)
                added += 1
        if added:
            self._log(f"+ {added} link aggiunti")
        for p in local_audio:
            it = self._add_local_item(p)
            self._log(f"+ file locale: {os.path.basename(p)}")
            added += 1
        if added:
            event.acceptProposedAction()

    # ---------- menu contestuale coda ----------

    def _on_context_menu(self, pos) -> None:
        lw_item = self.list_widget.itemAt(pos)
        if lw_item is None:
            return
        idx = self.list_widget.row(lw_item)
        if not (0 <= idx < len(self.queue)):
            return
        item = self.queue[idx]
        running = bool(self._thread and self._thread.isRunning())
        menu = QMenu(self)
        filepath = item.extra.get("filepath", "")

        stem_busy = bool(self._stem_thread and self._stem_thread.isRunning())
        has_file = bool(filepath) and os.path.exists(filepath)

        act_file = menu.addAction("Apri file")
        act_file.setEnabled(has_file)
        act_folder = menu.addAction("Apri cartella")
        act_folder.setEnabled(has_file)
        menu.addSeparator()
        act_stem = menu.addAction("Separa in stem")
        act_stem.setEnabled(has_file and not running and not stem_busy)
        stems_dir = item.extra.get("stems_dir", "")
        act_mixer = menu.addAction("Apri nel mixer")
        act_mixer.setEnabled(bool(stems_dir) and os.path.isdir(stems_dir))
        menu.addSeparator()
        act_retry = menu.addAction("Riprova")
        act_retry.setEnabled(not running and item.url != "" and item.status in ("errore", "fatto"))
        act_remove = menu.addAction("Rimuovi dalla coda")
        act_remove.setEnabled(not running and not stem_busy)

        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_file:
            self._open_path(filepath)
        elif chosen == act_folder:
            self._open_path(os.path.dirname(filepath))
        elif chosen == act_stem:
            self._start_stem(item)
        elif chosen == act_mixer:
            self._open_in_mixer(stems_dir)
        elif chosen == act_retry:
            item.status = "in attesa"
            self.rows[idx].update_progress(0.0, "in attesa", "")
            self._start_download([item])
        elif chosen == act_remove:
            self._remove_item(idx)

    def _open_path(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def _remove_item(self, idx: int) -> None:
        if self._thread and self._thread.isRunning():
            return
        if not (0 <= idx < len(self.queue)):
            return
        self.queue.pop(idx)
        self.rows.pop(idx)
        self.list_widget.takeItem(idx)

    def _on_show_history(self) -> None:
        HistoryDialog(self).exec()

    def _open_in_mixer(self, stems_dir: str) -> None:
        if not stems_dir or not os.path.isdir(stems_dir):
            return
        self.tabs.setCurrentWidget(self.mixer_tab)
        self.mixer_tab.load_folder(stems_dir)

    # ---------- separazione stem ----------

    def _busy(self) -> bool:
        return bool((self._thread and self._thread.isRunning())
                    or (self._stem_thread and self._stem_thread.isRunning())
                    or (self._uninst_thread and self._uninst_thread.isRunning())
                    or (self._verify_thread and self._verify_thread.isRunning()))

    def _on_separate_file_dialog(self) -> None:
        if self._busy():
            return
        start = self.dest_edit.text() or paths.default_download_dir()
        f, _ = QFileDialog.getOpenFileName(
            self, "Scegli un file audio da separare", start,
            "Audio (*.mp3 *.wav *.flac *.m4a *.opus *.aac *.ogg *.wma)")
        if f:
            item = self._add_local_item(f)
            if item:
                self._start_stem(item)

    def _start_stem(self, item: QueueItem) -> None:
        self._start_stem_batch([item])

    def _on_separate_all(self) -> None:
        """Separa in stem solo i brani non ancora separati (salta quelli già fatti)."""
        ready = [it for it in self.queue
                 if it.extra.get("filepath") and os.path.exists(it.extra["filepath"])]
        if not ready:
            QMessageBox.information(self, "Niente da separare",
                                    "Nessun brano scaricato/file pronto in coda.")
            return
        items = [it for it in ready
                 if not (it.extra.get("stems_dir")
                         or stems.already_separated(it.extra["filepath"]))]
        if not items:
            r = QMessageBox.question(
                self, "Già separati",
                "Tutti i brani in coda risultano già separati.\n\n"
                "Vuoi separarli di nuovo (sovrascrive)?")
            if r != QMessageBox.StandardButton.Yes:
                return
            items = ready
        self._start_stem_batch(items)

    def _start_stem_batch(self, items: list[QueueItem]) -> None:
        if self._busy():
            QMessageBox.information(self, "Occupato", "Aspetta la fine dell'operazione in corso.")
            return
        items = [it for it in items
                 if it.extra.get("filepath") and os.path.exists(it.extra["filepath"])]
        if not items:
            QMessageBox.warning(self, "File mancante", "Nessun file valido da separare.")
            return

        # primo uso: serve installare il motore (~3GB)
        if not stems.engine_ready():
            r = QMessageBox.question(
                self, "Motore stem",
                "La separazione in stem richiede un motore (Demucs + PyTorch).\n"
                "Va scaricato una sola volta (~3 GB) e userà la tua GPU.\n\nProcedere ora?")
            if r != QMessageBox.StandardButton.Yes:
                return

        self._persist()
        cfg = self._gather_settings()
        self._stem_mode = cfg["stem_mode"]
        self._stem_format = cfg["stem_format"]
        self._stem_batch = list(items)
        self._set_stem_running(True)
        self._run_next_stem()

    def _run_next_stem(self) -> None:
        if not self._stem_batch:
            self._set_stem_running(False)
            self._log("— stem: coda finita —")
            return
        item = self._stem_batch.pop(0)
        filepath = item.extra["filepath"]
        self._stem_row = self.rows[self.queue.index(item)]
        self._stem_row.update_progress(0.0, "stem", "avvio…")
        self._stem_thread, self._stem_worker = make_stem_thread(
            filepath, self._stem_mode, self._stem_format)
        self._stem_worker.progress.connect(self._on_stem_progress)
        self._stem_worker.status.connect(self._on_stem_status)
        self._stem_worker.log.connect(self._log)
        self._stem_worker.finished.connect(self._on_stem_finished)
        self._stem_thread.finished.connect(self._after_stem_thread)
        self._stem_thread.start()

    def _set_stem_running(self, running: bool) -> None:
        self.download_btn.setEnabled(not running)
        self.download_btn.setText("⬇  Scarica")
        self.stop_btn.setEnabled(running)
        self.stop_btn.setText("Stop")
        self.stem_file_btn.setEnabled(not running)
        self.stem_all_btn.setEnabled(not running)
        self.engine_btn.setEnabled(not running)
        self.engine_opts_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.retry_btn.setEnabled(not running)

    def _on_stem_status(self, phase: str) -> None:
        if not self._stem_row:
            return
        if phase == "motore":
            label, detail = "motore…", "preparo il motore (una volta)…"
        elif phase == "analisi":
            label, detail = "analisi…", "BPM, tonalità, beat…"
        else:
            label, detail = "stem", "separazione…"
        self._stem_row.update_progress(self._stem_row.item.progress, label, detail)

    def _on_stem_progress(self, pct: float) -> None:
        if self._stem_row:
            status = self._stem_row.item.status or "stem"
            self._stem_row.update_progress(pct, status, "")

    def _on_stem_finished(self, ok: bool, result: str) -> None:
        if self._stem_row:
            item = self._stem_row.item
            if ok:
                self._stem_row.update_progress(100.0, "fatto", f"stem in {os.path.basename(result)}")
                self._stem_row._style_status("fatto")
                item.extra["stems_dir"] = result
                history.add(
                    title=(item.title or os.path.basename(item.extra.get("filepath", ""))),
                    url=item.url,
                    audio_format=f"stem {self._stem_mode}",
                    filepath=result,
                )
                self._stem_ok_any = True
                self._stem_last_dir = result
            else:
                self._stem_row.set_finished(False, result)
        self._log("— stem: fatto —" if ok else f"✖ stem: {result}")

    def _after_stem_thread(self) -> None:
        self._stem_thread = None
        self._stem_worker = None
        self._stem_row = None
        if self._stem_cancel_batch:
            self._stem_batch = []
        if self._stem_batch:
            self._run_next_stem()
            return
        # batch finito
        self._set_stem_running(False)
        cancelled = self._stem_cancel_batch
        self._stem_cancel_batch = False
        if self._stem_ok_any and not cancelled:
            if self.notify_chk.isChecked():
                if self.tray:
                    self.tray.showMessage("Sonora", "Stem pronti",
                                          QSystemTrayIcon.MessageIcon.Information, 4000)
                QApplication.beep()
            if self._stem_last_dir:
                self._open_path(self._stem_last_dir)
        self._stem_ok_any = False
        self._stem_last_dir = ""

    # ---------- motore stem: stato / install ----------

    def _refresh_engine_label(self) -> None:
        ready = stems.engine_ready()
        custom = (self.cfg.get("stem_engine_dir") or "").strip()
        where = f" — {custom}" if custom else ""
        self.engine_lbl.setText(("Motore stem: installato ✓" if ready
                                 else "Motore stem: non installato") + where)
        self.engine_lbl.setToolTip(f"Cartella motore: {stems.engine_dir()}")
        self.engine_btn.setText("Reinstalla motore" if ready else "Installa motore")

    def _on_install_engine(self) -> None:
        if self._busy():
            QMessageBox.information(self, "Occupato", "Aspetta la fine dell'operazione in corso.")
            return
        ready = stems.engine_ready()
        q = ("Reinstallare il motore stem (~3 GB)?" if ready
             else "Scaricare il motore stem (Demucs + PyTorch, ~3 GB)?")
        if QMessageBox.question(self, "Motore stem", q) != QMessageBox.StandardButton.Yes:
            return
        self._set_stem_running(True)
        self._stem_row = None
        self._stem_thread, self._stem_worker = make_stem_thread("", self._stem_mode, self._stem_format)
        self._stem_worker.log.connect(self._log)
        self._stem_worker.finished.connect(self._on_engine_install_finished)
        self._stem_thread.finished.connect(self._after_stem_thread)
        self._stem_thread.start()

    def _on_engine_install_finished(self, ok: bool, _result: str) -> None:
        self._log("✔ motore stem pronto" if ok else "✖ installazione motore fallita")
        self._refresh_engine_label()

    def _on_uninstall_engine(self) -> None:
        if self._busy():
            QMessageBox.information(self, "Occupato", "Aspetta la fine dell'operazione in corso.")
            return
        if not stems.engine_ready() and not stems.engine_dir().exists():
            QMessageBox.information(self, "Motore stem", "Il motore non è installato.")
            return
        q = ("Disinstallare il motore stem?\n\n"
             f"Verrà rimossa la cartella:\n{stems.engine_dir()}\n\n"
             "Libera ~3 GB. Potrai reinstallarlo quando vuoi.")
        if QMessageBox.question(self, "Disinstalla motore", q) != QMessageBox.StandardButton.Yes:
            return
        self._set_stem_running(True)
        self.engine_btn.setEnabled(False)
        self.engine_opts_btn.setEnabled(False)
        self._log("— disinstallazione motore —")
        self._uninst_thread, self._uninst_worker = make_uninstall_thread()
        self._uninst_worker.log.connect(self._log)
        self._uninst_worker.finished.connect(self._on_uninstall_finished)
        self._uninst_thread.finished.connect(self._after_uninstall_thread)
        self._uninst_thread.start()

    def _on_uninstall_finished(self, ok: bool) -> None:
        self._log("✔ motore disinstallato" if ok else "✖ disinstallazione non completata")
        if not ok:
            QMessageBox.warning(self, "Disinstalla motore",
                                "Non è stato possibile rimuovere tutto.\n"
                                "Chiudi eventuali processi del motore e riprova.")
        self._refresh_engine_label()

    def _after_uninstall_thread(self) -> None:
        self._uninst_thread = None
        self._uninst_worker = None
        self.engine_btn.setEnabled(True)
        self.engine_opts_btn.setEnabled(True)
        self._set_stem_running(False)

    def _on_verify_engine(self) -> None:
        if self._busy():
            QMessageBox.information(self, "Occupato", "Aspetta la fine dell'operazione in corso.")
            return
        if not stems.venv_python().exists():
            QMessageBox.information(
                self, "Motore stem",
                "Il motore non è installato. Premi «Installa motore».")
            return
        self._set_stem_running(True)
        self._stem_row = None
        self._log("— verifica / riparazione motore —")
        self._verify_thread, self._verify_worker = make_verify_thread()
        self._verify_worker.progress.connect(self._on_stem_progress)
        self._verify_worker.log.connect(self._log)
        self._verify_worker.finished.connect(self._on_verify_finished)
        self._verify_thread.finished.connect(self._after_verify_thread)
        self._verify_thread.start()

    def _on_verify_finished(self, ok: bool) -> None:
        self._log("✔ motore verificato/riparato" if ok else "✖ verifica motore fallita")
        self._refresh_engine_label()
        if ok:
            QMessageBox.information(self, "Motore stem", "Il motore è a posto e pronto all'uso. ✓")
        else:
            QMessageBox.warning(self, "Motore stem",
                                "Verifica/riparazione non riuscita. Controlla il log; "
                                "in alternativa disinstalla e reinstalla il motore.")

    def _after_verify_thread(self) -> None:
        self._verify_thread = None
        self._verify_worker = None
        self._set_stem_running(False)

    def _on_change_engine_location(self) -> None:
        if self._busy():
            QMessageBox.information(self, "Occupato", "Aspetta la fine dell'operazione in corso.")
            return
        current = (self.cfg.get("stem_engine_dir") or "").strip()
        start = current or str(config.config_dir())
        d = QFileDialog.getExistingDirectory(
            self, "Scegli dove installare il motore stem", start)
        if not d:
            return
        old_dir = stems.engine_dir()
        had_engine = stems.engine_ready()
        # salva il nuovo percorso base
        self.cfg["stem_engine_dir"] = d
        self._persist()
        new_dir = stems.engine_dir()
        self._log(f"Cartella motore impostata su: {new_dir}")
        self._refresh_engine_label()
        # il motore vecchio (se c'era) resta dov'è: offri di rimuoverlo per liberare spazio
        if had_engine and old_dir.exists() and old_dir != new_dir:
            if QMessageBox.question(
                self, "Motore esistente",
                f"Un motore è già installato in:\n{old_dir}\n\n"
                "Il nuovo percorso è vuoto: dovrai reinstallare il motore.\n"
                "Vuoi rimuovere quello vecchio per liberare ~3 GB?"
            ) == QMessageBox.StandardButton.Yes:
                ok = stems._rmtree_robust(old_dir, self._log)
                self._log("✔ vecchio motore rimosso" if ok
                          else "✖ rimozione vecchio motore non completata")
        if not stems.engine_ready():
            QMessageBox.information(
                self, "Motore stem",
                "Percorso aggiornato. Premi «Installa motore» per installarlo nella nuova cartella.")

    # ---------- aggiornamento yt-dlp ----------

    def _on_update_ytdlp(self) -> None:
        if self._upd_thread and self._upd_thread.isRunning():
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Aggiorno…")
        self._log("— aggiornamento yt-dlp —")
        self._upd_thread, self._upd_worker = updater.make_update_thread()
        self._upd_worker.log.connect(self._log)
        self._upd_worker.finished.connect(self._on_update_finished)
        self._upd_thread.finished.connect(self._cleanup_update_thread)
        self._upd_thread.start()

    def _on_update_finished(self, ok: bool, msg: str) -> None:
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Aggiorna yt-dlp")
        self._log(("✔ " if ok else "✖ ") + msg)
        if ok:
            QMessageBox.information(self, "yt-dlp aggiornato", msg)
        else:
            QMessageBox.warning(self, "Aggiornamento fallito", msg)

    def _cleanup_update_thread(self) -> None:
        self._upd_thread = None
        self._upd_worker = None

    # ---------- download ----------

    def _on_download(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        # se coda vuota ma c'e' un url nel campo, aggiungilo
        if not self.queue and self.url_edit.text().strip():
            self._on_add()
        if not self.queue:
            QMessageBox.information(self, "Coda vuota", "Aggiungi almeno un link.")
            return
        # riprocessa solo gli item non ancora completati
        pending = [it for it in self.queue if it.status != "fatto"]
        if not pending:
            QMessageBox.information(self, "Nulla da fare", "Tutti gli elementi sono gia' completati.")
            return
        self._start_download(pending)

    def _start_download(self, items: list[QueueItem]) -> None:
        if self._thread and self._thread.isRunning():
            return
        dest = self.dest_edit.text().strip()
        if not dest or not os.path.isdir(dest):
            QMessageBox.warning(self, "Cartella mancante", "Scegli una cartella di destinazione valida.")
            return

        self._persist()
        cfg = self._gather_settings()
        self._ok_count = 0
        self._was_cancelled = False
        self._session_format = cfg["audio_format"]
        opts = DownloadOptions(
            dest_dir=cfg["dest_dir"],
            audio_format=cfg["audio_format"],
            bitrate=cfg["bitrate"],
            filename_template=cfg["filename_template"],
            embed_metadata=cfg["embed_metadata"],
            embed_thumbnail=cfg["embed_thumbnail"],
            per_file_folder=cfg["per_file_folder"],
            normalize=cfg["normalize"],
            is_playlist=True,   # consenti playlist; noplaylist gestito da yt-dlp sui video singoli
        )

        self._set_running(True)
        self._thread, self._worker = make_thread(items, opts)
        # mappa indice-pending -> riga reale
        self._pending_rows = [self.rows[self.queue.index(it)] for it in items]

        self._worker.item_started.connect(self._on_item_started)
        self._worker.item_progress.connect(self._on_item_progress)
        self._worker.item_finished.connect(self._on_item_finished)
        self._worker.log.connect(self._log)
        self._worker.all_finished.connect(self._on_all_finished)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_stop(self) -> None:
        if self._worker and self._thread and self._thread.isRunning():
            self._was_cancelled = True
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Annullo…")
            self._worker.cancel()
            self._log("⏹ annullamento richiesto…")
        elif self._stem_worker and self._stem_thread and self._stem_thread.isRunning():
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Annullo…")
            self._stem_cancel_batch = True
            self._stem_worker.cancel()
            self._log("⏹ annullamento stem richiesto…")

    def _on_retry_failed(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        failed = [it for it in self.queue if it.status == "errore"]
        if not failed:
            QMessageBox.information(self, "Niente da riprovare", "Nessun download fallito.")
            return
        self._start_download(failed)

    def _set_running(self, running: bool) -> None:
        self.download_btn.setEnabled(not running)
        self.download_btn.setText("Scaricando…" if running else "⬇  Scarica")
        self.stop_btn.setEnabled(running)
        self.stop_btn.setText("Stop")
        self.clear_btn.setEnabled(not running)
        self.retry_btn.setEnabled(not running)
        for w in (self.fmt_combo, self.br_combo, self.tpl_combo, self.url_edit,
                  self.norm_chk, self.folder_chk, self.meta_chk, self.thumb_chk):
            w.setEnabled(not running)
        if not running:
            self._on_format_changed(self.fmt_combo.currentText())

    def _on_item_started(self, idx: int) -> None:
        row = self._pending_rows[idx]
        row.update_progress(0.0, "scaricando", "avvio…")

    def _on_item_progress(self, idx: int, pct: float, status: str, detail: str) -> None:
        self._pending_rows[idx].update_progress(pct, status, detail)

    def _on_item_finished(self, idx: int, ok: bool, result: str) -> None:
        row = self._pending_rows[idx]
        row.set_finished(ok, result)
        if ok:
            self._ok_count += 1
            history.add(
                title=result,
                url=row.item.url,
                audio_format=getattr(self, "_session_format", ""),
                filepath=row.item.extra.get("filepath", ""),
            )

    def _on_all_finished(self) -> None:
        self._set_running(False)
        self._log("— fine —")
        if self._was_cancelled or self._ok_count == 0:
            return
        if self.notify_chk.isChecked():
            n = self._ok_count
            msg = f"{n} download completati" if n > 1 else "Download completato"
            if self.tray:
                self.tray.showMessage("Sonora", msg,
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            QApplication.beep()

    def _cleanup_thread(self) -> None:
        self._thread = None
        self._worker = None

    def closeEvent(self, event) -> None:  # noqa: N802 (override Qt)
        self._persist()
        # se il monitor appunti e' attivo, riduci a tray invece di uscire
        if (not self._really_quit and self.tray
                and self.watch_chk.isChecked() and not self._busy()):
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "Sonora", "In esecuzione: monitoro gli appunti. Click destro sull'icona per uscire.",
                QSystemTrayIcon.MessageIcon.Information, 3500)
            return
        if self._thread and self._thread.isRunning() and self._worker:
            self._worker.cancel()
            self._thread.quit()
            self._thread.wait(3000)
        if self._stem_thread and self._stem_thread.isRunning() and self._stem_worker:
            self._stem_worker.cancel()
            self._stem_thread.quit()
            self._stem_thread.wait(5000)
        try:
            self.mixer_tab.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if self._upd_thread and self._upd_thread.isRunning():
            self._upd_thread.quit()
            self._upd_thread.wait(3000)
        if self.tray:
            self.tray.hide()
        super().closeEvent(event)
