"""Interfaccia grafica Sonora (PySide6)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, app_update, changelog, config, history, icons, paths, stems, theme, updater
from .toast import Banner, toast
from .ui_playbar import PlayBar
from .ui_settings import UI_SCALES, SettingsPage
from .ui_shell import NavRail
from .downloader import (
    AUDIO_FORMATS,
    DownloadOptions,
    DownloadWorker,
    InfoSignals,
    InfoTask,
    PreviewSignals,
    PreviewTask,
    QueueItem,
    SearchSignals,
    SearchTask,
    make_thread,
    run_info_task,
    run_preview_task,
    run_search_task,
)
from .preview_player import PreviewPlayer
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

# etichetta breve per il chip Stem (dalla modalità)
STEM_SHORT = {"sw6": "6 · SW", "rof6": "6 · Rof+D", "6hq": "6 · HQ",
              "6": "6 · Demucs", "4": "4 · Demucs", "rof": "2 · Rof", "2": "2 · Demucs"}


class QueueRow(QWidget):
    """Riga visuale per un item della coda: miniatura, titolo, durata, stato, progress."""

    THUMB_W, THUMB_H = 62, 44

    def __init__(self, item: QueueItem):
        super().__init__()
        self.item = item
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 9)
        outer.setSpacing(12)

        # miniatura
        self.thumb_lbl = QLabel()
        self.thumb_lbl.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.thumb_lbl.setStyleSheet(
            f"background:{theme.COLORS['input']}; border-radius:8px;")
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_lbl.setPixmap(icons.pixmap("music", theme.COLORS["faint"], 18))
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
        self.dur_lbl.setProperty("class", "Hint")
        self.status_lbl = QLabel(item.status)
        self.status_lbl.setObjectName("StatusChip")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self.detail_lbl.setProperty("class", "Hint")
        lay.addWidget(self.detail_lbl)

    def _display_title(self) -> str:
        t = self.item.title or self.item.url
        return t if len(t) <= 70 else t[:67] + "…"

    def _style_status(self, status: str) -> None:
        """Colora il chip di stato via dynamic property (regole in style.qss)."""
        key = status
        if status.startswith(("motore", "analisi", "stem")):
            key = "stem"
        if key not in ("fatto", "errore", "scaricando", "conversione", "stem"):
            key = ""
        theme.set_state(self.status_lbl, "status", key)

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
            self.detail_lbl.setStyleSheet(
                f"color:{theme.COLORS['faint']}; font-size:11px;")
        else:
            self.item.status = "errore"
            self.item.error = result
            self.status_lbl.setText("errore")
            self.detail_lbl.setStyleSheet(
                f"color:{theme.COLORS['err']}; font-size:11px;")
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
    return lbl


class MainWindow(QWidget):
    # larghezza massima del contenuto centrato sui monitor grandi
    CONTENT_MAX_W = 1000

    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle(f"Sonora {__version__} — Pisco Factory")
        self.resize(1100, 860)
        self.setMinimumSize(760, 600)

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

        # anteprima audio (estratto breve) sui risultati di ricerca
        self._preview_signals = PreviewSignals()
        self._preview_signals.done.connect(self._on_preview_ready)
        self._preview_player = PreviewPlayer()
        self._preview_url = ""    # url dell'anteprima corrente (caricamento o riproduzione)
        self._preview_path = ""   # file temp corrente, per pulizia
        self._preview_title = ""

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
        """Aggiorna banner prova (Scarica) e pagina Impostazioni·Licenza."""
        status_text = "Stato sconosciuto"
        show_activate = True
        banner_text = ""
        try:
            from . import licensing
            st = licensing.status()
            if st.state == "trial":
                giorni = "1 giorno" if st.days_left == 1 else f"{st.days_left} giorni"
                status_text = f"Prova gratuita — {giorni} rimasti."
                banner_text = f"Prova gratuita: {giorni} rimasti."
            elif st.state == "expired":
                status_text = "Prova scaduta. Inserisci un codice per continuare."
                banner_text = "La prova è scaduta: attiva Sonora con un codice."
            else:  # licensed
                status_text = "Sonora è attiva su questo computer. ✓"
                show_activate = False
        except Exception:  # noqa: BLE001 (lo stato licenza non deve mai bloccare la UI)
            pass
        if hasattr(self, "settings_page"):
            self.settings_page.license_lbl.setText(status_text)
            self.settings_page.activate_btn.setVisible(show_activate)
        if hasattr(self, "trial_banner"):
            self.trial_banner.set_text(banner_text)
            self.trial_banner.setVisible(bool(banner_text))

    def _open_activation(self) -> None:
        """Apre la finestra di attivazione codice (da pulsante Attiva)."""
        from . import licensing
        from .ui_license import run_activation_gate

        expired = licensing.status().state == "expired"
        if run_activation_gate(trial_expired=expired, parent=self):
            self._refresh_license_ui()

    # ---------- costruzione UI ----------

    def _build_ui(self) -> None:
        # shell: rail di navigazione a sinistra, pagine al centro, playbar sotto
        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.rail = NavRail()
        shell.addWidget(self.rail, 0)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.playbar = PlayBar()
        right.addWidget(self.playbar, 0)
        shell.addLayout(right, 1)

        dl_tab = QWidget()
        dl_tab.setObjectName("Root")
        self.mixer_tab = MixerTab()
        self.lyrics_tab = LyricsTab(self)
        self.settings_page = SettingsPage(self)
        # alias: la logica esistente usa questi nomi (ora vivono in Impostazioni)
        self.watch_chk = self.settings_page.watch_chk
        self.notify_chk = self.settings_page.notify_chk
        self.engine_lbl = self.settings_page.engine_lbl
        self.engine_btn = self.settings_page.engine_btn
        self.ytdlp_lbl = self.settings_page.ytdlp_lbl
        self.update_btn = self.settings_page.update_btn
        self.scale_combo = self.settings_page.scale_combo
        self.scale_combo.currentIndexChanged.connect(self._on_ui_scale_changed)

        self.mixer_tab.song_loaded.connect(self.lyrics_tab.load_song_lyrics)

        self.stack.addWidget(dl_tab)                              # 0 · Scarica
        self._mixer_index = self.stack.addWidget(self.mixer_tab)  # 1 · Mixer
        self._lyrics_index = self.stack.addWidget(self.lyrics_tab)  # 2 · Testi
        self.stack.addWidget(self.settings_page)                  # 3 · Impostazioni

        self.rail.add_page("download", "Scarica")
        self.rail.add_page("mixer", "Mixer")
        self.rail.add_page("mic", "Testi")
        self.rail.add_page("settings", "Impostazioni", bottom=True)
        self.rail.page_selected.connect(self.stack.setCurrentIndex)
        # playbar contestuale: fissa solo su Testi, altrove solo con task attivi
        self.rail.page_selected.connect(lambda _i: self._update_playbar_visibility())
        self.playbar.task_state_changed.connect(
            lambda _on: self._update_playbar_visibility())
        self.rail.select(0)
        self._update_playbar_visibility()

        # playbar ↔ mixer: un solo source of truth (il motore del mixer)
        self.playbar.play_clicked.connect(self.mixer_tab.toggle_play)
        self.playbar.stop_clicked.connect(self.mixer_tab.stop_playback)
        self.playbar.seek_frac.connect(self._on_playbar_seek)
        self.playbar.task_cancel.connect(self._on_stop)
        self.mixer_tab.position_changed.connect(self._on_mixer_pos)
        self.mixer_tab.song_loaded.connect(self._on_song_loaded)

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

        outer = QHBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        container = QWidget()
        container.setMaximumWidth(self.CONTENT_MAX_W)
        outer.addWidget(container, 20)
        outer.addStretch(1)

        root = QVBoxLayout(container)
        root.setContentsMargins(32, 24, 32, 10)
        root.setSpacing(14)
        self._dl_root = root

        # banner inline: stato prova + motore stem mancante (niente popup)
        self.trial_banner = Banner("", kind="info", action_text="Attiva",
                                   action=self._open_activation)
        self.trial_banner.hide()
        root.addWidget(self.trial_banner)
        self.engine_banner = Banner(
            "Motore di separazione non installato. Serve un download di ~3 GB, "
            "una volta sola.", kind="warn",
            action_text="Installa motore", action=self._on_install_engine)
        self.engine_banner.hide()
        root.addWidget(self.engine_banner)

        # --- hero: un solo campo per cercare o incollare ---
        root.addSpacing(16)
        eyebrow = QLabel(f"SONORA  ·  v{__version__}")
        eyebrow.setProperty("class", "Eyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero_title = QLabel("Cosa suoniamo oggi?")
        hero_title.setObjectName("Title")
        hero_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero_sub = QLabel("Incolla un link o cerca un brano. Poi scaricalo, "
                          "separalo in stem e suonaci sopra.")
        hero_sub.setObjectName("Subtitle")
        hero_sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(eyebrow)
        root.addWidget(hero_title)
        root.addWidget(hero_sub)
        root.addSpacing(8)

        search_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Cerca un brano o incolla un link…")
        self.url_edit.setMinimumHeight(44)
        self.url_edit.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Aggiungi")
        add_btn.setObjectName("Primary")
        add_btn.setMinimumHeight(44)
        add_btn.clicked.connect(self._on_add)
        load_file_btn = QPushButton()
        load_file_btn.setObjectName("Ghost")
        load_file_btn.setIcon(icons.icon("folder", theme.COLORS["muted"], 16))
        load_file_btn.setIconSize(QSize(16, 16))
        load_file_btn.setMinimumHeight(44)
        load_file_btn.setFixedWidth(48)
        load_file_btn.setToolTip(
            "Aggiungi alla coda un file audio già scaricato (poi separabile in stem).")
        load_file_btn.clicked.connect(self._on_load_file)
        search_host = QWidget()
        sh = QHBoxLayout(search_host)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(8)
        sh.addWidget(self.url_edit, 1)
        sh.addWidget(add_btn, 0)
        sh.addWidget(load_file_btn, 0)
        search_host.setMaximumWidth(680)
        search_row.addStretch(1)
        search_row.addWidget(search_host, 20)
        search_row.addStretch(1)
        root.addLayout(search_row)

        # --- pannello risultati ricerca (inline, nascosto finché non si cerca) ---
        self.search_panel = QWidget()
        sp = QVBoxLayout(self.search_panel)
        sp.setContentsMargins(0, 6, 0, 0)
        sp.setSpacing(6)
        search_head = QHBoxLayout()
        self.search_label = QLabel("Risultati ricerca")
        self.search_label.setObjectName("Subtitle")
        self.preview_lbl = QLabel("")
        self.preview_lbl.setStyleSheet(f"color:{theme.COLORS['muted']}; font-size:12px;")
        self.preview_lbl.hide()
        self.preview_btn = QPushButton()
        self.preview_btn.setObjectName("GhostMini")
        self.preview_btn.setFixedSize(30, 30)
        self.preview_btn.setToolTip("Ferma anteprima")
        self.preview_btn.clicked.connect(self._stop_preview)
        self.preview_btn.hide()
        search_close = QPushButton()
        search_close.setObjectName("GhostMini")
        search_close.setIcon(icons.icon("x", theme.COLORS["muted"], 12))
        search_close.setFixedSize(30, 30)
        search_close.setToolTip("Chiudi i risultati")
        search_close.clicked.connect(self._close_search)
        search_head.addWidget(self.search_label, 1)
        search_head.addWidget(self.preview_lbl, 0)
        search_head.addWidget(self.preview_btn, 0)
        search_head.addWidget(search_close, 0)
        sp.addLayout(search_head)
        self.search_list = QListWidget()
        self.search_list.setMaximumHeight(230)
        self.search_list.itemClicked.connect(self._on_search_preview)
        self.search_list.itemActivated.connect(self._on_search_pick)
        self.search_list.itemDoubleClicked.connect(self._on_search_pick)
        sp.addWidget(self.search_list)
        self.search_panel.hide()
        root.addWidget(self.search_panel)

        # --- chip opzioni rapide (formato / stem / normalizza / altre opzioni) ---
        self._build_chips(root)

        # --- card opzioni (disclosure: aperta dal chip «Altre opzioni») ---
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
        self.fmt_combo.currentTextChanged.connect(
            lambda _t: self._refresh_chips())
        fmt_box.addWidget(self.fmt_combo)
        line1.addLayout(fmt_box, 1)

        br_box = QVBoxLayout()
        br_box.setSpacing(5)
        br_box.addWidget(_section_label("BITRATE (mp3)"))
        self.br_combo = QComboBox()
        self.br_combo.addItems(["128", "192", "320"])
        self.br_combo.currentTextChanged.connect(
            lambda _t: self._refresh_chips())
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

        # toggle download
        tog_row = QHBoxLayout()
        self.meta_chk = QCheckBox("Includi metadata (titolo/artista)")
        self.thumb_chk = QCheckBox("Includi copertina (cover)")
        self.folder_chk = QCheckBox("Sottocartella per ogni file")
        self.folder_chk.setToolTip(
            "Ogni download finisce in una sua cartella col titolo del video,\n"
            "dentro la cartella di destinazione."
        )
        tog_row.addWidget(self.meta_chk)
        tog_row.addWidget(self.thumb_chk)
        tog_row.addWidget(self.folder_chk)
        tog_row.addStretch(1)
        oc.addLayout(tog_row)

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
        self.stem_mode_combo.currentIndexChanged.connect(
            lambda _i: self._refresh_chips())
        self.stem_fmt_combo = QComboBox()
        self.stem_fmt_combo.addItems(STEM_FORMATS)
        self.stem_file_btn = QPushButton("Separa file…")
        self.stem_file_btn.setObjectName("Ghost")
        self.stem_file_btn.setToolTip("Scegli un file audio locale da separare in stem.")
        self.stem_file_btn.clicked.connect(self._on_separate_file_dialog)
        stem_row.addWidget(stem_lbl)
        stem_row.addWidget(self.stem_mode_combo)
        stem_row.addWidget(self.stem_fmt_combo)
        stem_row.addStretch(1)
        stem_row.addWidget(self.stem_file_btn)
        oc.addLayout(stem_row)

        # la card prende l'altezza del contenuto e non si comprime sotto di essa
        opt_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        opt_card.hide()
        root.addWidget(opt_card)
        root.addSpacing(8)

        # altezze minime esplicite: combo e campi non possono sovrapporsi
        for w in (self.fmt_combo, self.br_combo, self.tpl_combo,
                  self.custom_tpl_edit, self.dest_edit):
            w.setMinimumHeight(38)

        # --- blocco CODA (intestazione + lista) ---
        self.queue_block = QWidget()
        q_lay = QVBoxLayout(self.queue_block)
        q_lay.setContentsMargins(0, 0, 0, 0)
        q_lay.setSpacing(10)
        queue_head = QHBoxLayout()
        queue_head.setSpacing(8)
        coda_lbl = QLabel("Coda")
        coda_lbl.setStyleSheet("font-size:15px; font-weight:600;")
        queue_head.addWidget(coda_lbl)
        queue_head.addStretch(1)
        self.stem_all_btn = QPushButton("Separa tutti")
        self.stem_all_btn.setObjectName("Ghost")
        self.stem_all_btn.setToolTip("Separa in stem tutti i brani pronti in coda.")
        self.stem_all_btn.clicked.connect(self._on_separate_all)
        self.history_btn = QPushButton("Cronologia")
        self.history_btn.setObjectName("Ghost")
        self.history_btn.clicked.connect(self._on_show_history)
        self.retry_btn = QPushButton("Riprova falliti")
        self.retry_btn.setObjectName("Ghost")
        self.retry_btn.clicked.connect(self._on_retry_failed)
        self.clear_done_btn = QPushButton("Rimuovi completati")
        self.clear_done_btn.setObjectName("Ghost")
        self.clear_done_btn.setToolTip(
            "Toglie dalla coda i brani completati (restano in Cronologia).")
        self.clear_done_btn.clicked.connect(self._on_clear_done)
        self.clear_btn = QPushButton("Svuota")
        self.clear_btn.setObjectName("Ghost")
        self.clear_btn.clicked.connect(self._on_clear)
        queue_head.addWidget(self.stem_all_btn)
        queue_head.addWidget(self.history_btn)
        queue_head.addWidget(self.retry_btn)
        queue_head.addWidget(self.clear_done_btn)
        queue_head.addWidget(self.clear_btn)
        q_lay.addLayout(queue_head)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_widget.setMinimumHeight(210)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        q_lay.addWidget(self.list_widget, 1)
        # A coda vuota la lista sparisce: al suo posto un invito compatto,
        # e lo spazio verticale resta libero invece di un riquadro deserto.
        self.queue_empty = QLabel(
            "La coda è vuota — cerca un brano o incolla un link qui sopra.")
        self.queue_empty.setObjectName("QueueEmpty")
        self.queue_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_empty.setFixedHeight(120)
        q_lay.addWidget(self.queue_empty)
        self.queue_spacer = QWidget()   # assorbe lo spazio quando la coda è vuota
        self.queue_spacer.setSizePolicy(QSizePolicy.Policy.Preferred,
                                        QSizePolicy.Policy.Expanding)
        q_lay.addWidget(self.queue_spacer, 1)
        root.addWidget(self.queue_block, 1)
        self._refresh_queue_empty()

        # --- log: disclosure in fondo, chiusa di default ---
        self.log_toggle = QToolButton()
        self.log_toggle.setText("Log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setStyleSheet(
            f"QToolButton{{border:none;background:transparent;"
            f"color:{theme.COLORS['faint']};font-size:12px;font-weight:600;}}")
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        self.log_view.hide()
        self.log_toggle.toggled.connect(self._on_log_toggle)
        root.addWidget(self.log_toggle)
        root.addWidget(self.log_view)

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
        actions.setContentsMargins(32, 10, 32, 16)
        self.open_btn = QPushButton("Apri cartella")
        self.open_btn.setObjectName("Ghost")
        self.open_btn.clicked.connect(self._on_open_folder)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("Ghost")
        self.stop_btn.setMinimumWidth(90)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        self.download_btn = QPushButton("Scarica")
        self.download_btn.setObjectName("Primary")
        self.download_btn.setIcon(icons.icon("download", "#ffffff", 16))
        self.download_btn.setIconSize(QSize(16, 16))
        self.download_btn.setMinimumWidth(160)
        self.download_btn.clicked.connect(self._on_download)
        actions.addWidget(self.open_btn)
        actions.addStretch(1)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.download_btn)
        page.addWidget(bar)

        self._refresh_license_ui()

    # ---------- chip opzioni rapide ----------

    def _build_chips(self, root: QVBoxLayout) -> None:
        """Riga di chip sotto la searchbox: formato, stem, normalizza, altre opzioni."""
        row = QHBoxLayout()
        row.setSpacing(8)

        self.chip_format = QPushButton("MP3")
        self.chip_format.setObjectName("Chip")
        self.chip_format.setToolTip("Formato dei download (clic per cambiare)")
        fmt_menu = QMenu(self.chip_format)
        for f in AUDIO_FORMATS:
            fmt_menu.addAction(f, lambda f=f: self.fmt_combo.setCurrentText(f))
        br_menu = fmt_menu.addMenu("Bitrate mp3")
        for b in ("128", "192", "320"):
            br_menu.addAction(f"{b} kbps", lambda b=b: self.br_combo.setCurrentText(b))
        self.chip_format.setMenu(fmt_menu)

        self.chip_stem = QPushButton("Stem")
        self.chip_stem.setObjectName("Chip")
        self.chip_stem.setToolTip("Modalità di separazione stem (clic per cambiare)")
        stem_menu = QMenu(self.chip_stem)
        for i, (label, _v) in enumerate(STEM_MODES):
            stem_menu.addAction(
                label, lambda i=i: self.stem_mode_combo.setCurrentIndex(i))
        self.chip_stem.setMenu(stem_menu)

        # «Normalizza» è un toggle: il chip stesso fa da stato (isChecked)
        self.norm_chk = QPushButton("Normalizza")
        self.norm_chk.setObjectName("Chip")
        self.norm_chk.setCheckable(True)
        self.norm_chk.setToolTip(
            "Applica loudnorm: tutti i brani allo stesso livello di volume.\n"
            "La conversione e' un po' piu lenta.")

        self.chip_more = QPushButton("Altre opzioni ▾")
        self.chip_more.setObjectName("Chip")
        self.chip_more.setCheckable(True)
        self.chip_more.toggled.connect(self._on_more_toggle)

        row.addStretch(1)
        for c in (self.chip_format, self.chip_stem, self.norm_chk, self.chip_more):
            row.addWidget(c)
        row.addStretch(1)
        root.addLayout(row)

    def _refresh_chips(self) -> None:
        """Allinea le etichette dei chip allo stato di combo/bitrate."""
        fmt = self.fmt_combo.currentText()
        label = fmt.upper()
        if fmt == "mp3":
            label += f" · {self.br_combo.currentText()}k"
        self.chip_format.setText(label)
        mode = STEM_MODES[self.stem_mode_combo.currentIndex()][1]
        self.chip_stem.setText(f"Stem · {STEM_SHORT.get(mode, mode)}")

    def _on_more_toggle(self, on: bool) -> None:
        self.chip_more.setText("Altre opzioni ▴" if on else "Altre opzioni ▾")
        self.opt_card.setVisible(on)

    def _on_log_toggle(self, on: bool) -> None:
        self.log_toggle.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.log_view.setVisible(on)

    # ---------- playbar ----------

    def _update_playbar_visibility(self) -> None:
        """Playbar fissa solo sulla pagina Testi (dove non c'è altro trasporto);
        sulle altre compare solo mentre gira un'operazione lunga (chip attività)
        e sparisce a lavoro finito."""
        on_lyrics = self.stack.currentIndex() == self._lyrics_index
        self.playbar.setVisible(on_lyrics or self.playbar.task_active)

    def _on_playbar_seek(self, frac: float) -> None:
        dur = self.mixer_tab.engine.duration()
        if dur > 0:
            self.mixer_tab.seek_seconds(frac * dur)

    def _on_mixer_pos(self, pos: float) -> None:
        eng = self.mixer_tab.engine
        self.playbar.set_position(pos, eng.duration())
        self.playbar.set_playing(eng.is_playing())

    def _on_song_loaded(self, folder: str, duration: float) -> None:
        name = os.path.basename(folder.rstrip("/\\")) or folder
        n = len(self.mixer_tab.engine.tracks)
        self.playbar.set_song(name, f"{n} stem")

    def resizeEvent(self, event) -> None:  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        from .toast import Toast
        Toast._reposition(self)

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
        try:
            scale = float(self.cfg.get("ui_scale") or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        idx = min(range(len(UI_SCALES)), key=lambda i: abs(UI_SCALES[i][1] - scale))
        self.scale_combo.blockSignals(True)   # niente toast «salvata» all'avvio
        self.scale_combo.setCurrentIndex(idx)
        self.scale_combo.blockSignals(False)
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
        self._refresh_chips()

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

    def _refresh_queue_empty(self) -> None:
        """Coda vuota → placeholder compatto al posto della lista."""
        empty = not self.queue
        self.list_widget.setVisible(not empty)
        self.queue_empty.setVisible(empty)
        self.queue_spacer.setVisible(empty)

    def _on_ui_scale_changed(self, idx: int) -> None:
        self.cfg["ui_scale"] = UI_SCALES[idx][1]
        config.save(self.cfg)
        toast(self, "Dimensione salvata: ha effetto al prossimo avvio di Sonora.", "info")

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
        self._stop_preview()
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
        self._stop_preview()
        added = self._add_item(url)
        if added is not None:
            self._log(f"+ {item.text().split('  ·  ')[0]}")
        # segnala visivamente che è già stato aggiunto
        item.setText("✓ " + item.text().lstrip("✓ "))

    def _close_search(self) -> None:
        self._stop_preview()
        self._search_query = ""
        self.search_list.clear()
        self.search_panel.hide()

    # ---------- anteprima audio risultati ricerca ----------

    def _on_search_preview(self, item: QListWidgetItem) -> None:
        url = item.data(Qt.ItemDataRole.UserRole)
        if not url:
            return
        if self._preview_url == url and self._preview_player.is_playing():
            self._stop_preview()
            return
        self._stop_preview()
        self._preview_url = url
        self._preview_title = item.text().split("  ·  ")[0].lstrip("✓ ")
        self.preview_lbl.setText(f"Caricamento anteprima: {self._preview_title}…")
        self.preview_lbl.show()
        self.preview_btn.setIcon(icons.icon("clock", theme.COLORS["muted"], 14))
        self.preview_btn.show()
        run_preview_task(PreviewTask(url, self._preview_signals))

    def _on_preview_ready(self, url: str, ok: bool, path_or_err: str) -> None:
        if url != self._preview_url:
            # anteprima superata da una più recente/chiusa: scarta il file scaricato
            if ok and path_or_err:
                try:
                    os.remove(path_or_err)
                except OSError:
                    pass
            return
        if not ok:
            self.preview_lbl.hide()
            self.preview_btn.hide()
            self._preview_url = ""
            toast(self, f"Anteprima non disponibile: {path_or_err}", "warn")
            return
        try:
            self._preview_player.load(path_or_err)
            self._preview_player.play()
        except Exception as e:  # noqa: BLE001
            self.preview_lbl.hide()
            self.preview_btn.hide()
            self._preview_url = ""
            toast(self, f"Errore riproduzione anteprima: {e}", "error")
            return
        self._preview_path = path_or_err
        self.preview_lbl.setText(f"▶ {self._preview_title}")
        self.preview_btn.setIcon(icons.icon("x", theme.COLORS["muted"], 12))

    def _stop_preview(self) -> None:
        self._preview_player.stop()
        if self._preview_path:
            try:
                os.remove(self._preview_path)
            except OSError:
                pass
        self._preview_path = ""
        self._preview_url = ""
        self.preview_lbl.hide()
        self.preview_btn.hide()

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
        self._refresh_queue_empty()
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
        self._refresh_queue_empty()
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
        self._refresh_queue_empty()

    def _on_clear_done(self) -> None:
        """Toglie dalla coda i brani completati (già registrati in Cronologia)."""
        if self._busy():
            return
        done = sum(1 for it in self.queue if it.status == "fatto")
        if not done:
            toast(self, "Nessun brano completato da rimuovere.", "info")
            return
        for idx in range(len(self.queue) - 1, -1, -1):
            if self.queue[idx].status == "fatto":
                self.queue.pop(idx)
                self.rows.pop(idx)
                self.list_widget.takeItem(idx)
        self._refresh_queue_empty()

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

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Informazioni su Sonora")
        box.setTextFormat(Qt.TextFormat.RichText)
        muted = theme.COLORS["muted"]
        box.setText(
            f"<h2 style='margin:0'>Sonora <span style='color:{muted}'>v{__version__}</span></h2>"
            f"<p style='margin:2px 0 10px 0; color:{muted}'>di <b>Pisco Factory</b></p>"
            "<p>Scarica, separa in stem ed esercitati sui brani: slow-down a tono "
            "invariato, loop, EQ, rilevamento accordi e accordatore — tutto in locale.</p>"
            f"<p style='color:{muted}; font-size:11px'>© 2026 Pisco Factory. Tutti i diritti riservati.</p>")
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
                toast(self, "Impossibile controllare gli aggiornamenti.", "error")
            return
        if not info.get("newer"):
            if verbose:
                toast(self, "Sonora è aggiornata. ✓", "ok")
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
        self.playbar.task_update(f"Aggiornamento {info['version']}…", 0.0)
        self._appupd_thread, self._appupd_worker = app_update.make_download_thread(
            info["download_url"], info.get("asset_name", ""),
            info.get("sha256_url", ""))
        self._appupd_worker.progress.connect(
            lambda p: self.playbar.task_update(
                f"Aggiornamento {info['version']}…", float(p)))
        self._appupd_worker.log.connect(self._log)
        self._appupd_worker.finished.connect(self._on_update_downloaded)
        self._appupd_thread.finished.connect(self._cleanup_appupd_thread)
        self._appupd_thread.start()

    def _cleanup_appupd_thread(self) -> None:
        self._appupd_thread = None
        self._appupd_worker = None

    def _on_update_downloaded(self, ok: bool, path_or_err: str) -> None:
        self.playbar.task_done()
        if not ok:
            self._log(f"✖ download aggiornamento fallito: {path_or_err}")
            toast(self, f"Aggiornamento fallito: {path_or_err}", "error")
            return
        if app_update.launch_installer(path_or_err):
            self._log("Avvio installer, chiudo Sonora…")
            self._really_quit = True
            QApplication.quit()
        else:
            toast(self, "Impossibile avviare l'installer scaricato.", "error")

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
        self._refresh_queue_empty()

    def _on_show_history(self) -> None:
        HistoryDialog(self).exec()

    def _open_in_mixer(self, stems_dir: str) -> None:
        if not stems_dir or not os.path.isdir(stems_dir):
            return
        self.rail.select(self._mixer_index)
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
        """Separa in stem solo i brani non ancora separati (salta quelli già fatti).

        Mai rielaborare i completati: per rifarne uno c'è il tasto destro sul
        brano («Separa in stem»), che sovrascrive senza chiedere."""
        ready = [it for it in self.queue
                 if it.extra.get("filepath") and os.path.exists(it.extra["filepath"])]
        if not ready:
            toast(self, "Nessun brano scaricato o file pronto in coda.", "warn")
            return
        items = [it for it in ready
                 if not (it.extra.get("stems_dir")
                         or stems.already_separated(it.extra["filepath"]))]
        if not items:
            toast(self, "Tutti i brani in coda risultano già separati. "
                        "Per rifarne uno usa il tasto destro sul brano.", "ok")
            return
        skipped = len(ready) - len(items)
        if skipped:
            self._log(f"— {skipped} già separati, li salto —")
        self._start_stem_batch(items)

    def _start_stem_batch(self, items: list[QueueItem]) -> None:
        if self._busy():
            toast(self, "Aspetta la fine dell'operazione in corso.", "warn")
            return
        items = [it for it in items
                 if it.extra.get("filepath") and os.path.exists(it.extra["filepath"])]
        if not items:
            toast(self, "Nessun file valido da separare.", "error")
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
        self.download_btn.setText("Scarica")
        self.stop_btn.setEnabled(running)
        self.stop_btn.setText("Stop")
        self.stem_file_btn.setEnabled(not running)
        self.stem_all_btn.setEnabled(not running)
        sp = self.settings_page
        for b in (sp.engine_btn, sp.verify_btn, sp.uninstall_btn, sp.location_btn):
            b.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.clear_done_btn.setEnabled(not running)
        self.retry_btn.setEnabled(not running)
        tip = "Operazione in corso…" if running else ""
        for b in (self.stem_all_btn, self.stem_file_btn):
            if running:
                b.setToolTip(tip)
        if not running:
            self.stem_all_btn.setToolTip("Separa in stem tutti i brani pronti in coda.")
            self.stem_file_btn.setToolTip("Scegli un file audio locale da separare in stem.")
            self.playbar.task_done()

    def _on_stem_status(self, phase: str) -> None:
        if phase == "motore":
            label, detail = "motore…", "preparo il motore (una volta)…"
            self._stem_task = "Installazione motore"
        elif phase == "analisi":
            label, detail = "analisi…", "BPM, tonalità, beat…"
            self._stem_task = "Analisi"
        else:
            label, detail = "stem", "separazione…"
            title = (self._stem_row.item.title or "") if self._stem_row else ""
            self._stem_task = ("Separazione stem · " + title).rstrip(" ·")
        self._stem_detail = detail
        # chip attività globale sulla playbar (visibile da ogni schermata)
        self.playbar.task_update(self._stem_task, None, cancellable=True)
        if self._stem_row:
            self._stem_row.update_progress(self._stem_row.item.progress, label, detail)

    def _on_stem_progress(self, pct: float) -> None:
        task = getattr(self, "_stem_task", "Elaborazione…")
        self.playbar.task_update(task, pct, cancellable=True)
        if self._stem_row:
            status = self._stem_row.item.status or "stem"
            detail = getattr(self, "_stem_detail", "separazione…")
            self._stem_row.update_progress(pct, status, f"{detail} {pct:.0f}%")

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
        # banner inline nella pagina Scarica: visibile finché il motore manca
        if hasattr(self, "engine_banner"):
            self.engine_banner.setVisible(not ready)

    def _on_install_engine(self) -> None:
        if self._busy():
            toast(self, "Aspetta la fine dell'operazione in corso.", "warn")
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
            toast(self, "Aspetta la fine dell'operazione in corso.", "warn")
            return
        if not stems.engine_ready() and not stems.engine_dir().exists():
            toast(self, "Il motore non è installato.", "info")
            return
        q = ("Disinstallare il motore stem?\n\n"
             f"Verrà rimossa la cartella:\n{stems.engine_dir()}\n\n"
             "Libera ~3 GB. Potrai reinstallarlo quando vuoi.")
        if QMessageBox.question(self, "Disinstalla motore", q) != QMessageBox.StandardButton.Yes:
            return
        self._set_stem_running(True)
        self.playbar.task_update("Disinstallazione motore…")
        self._log("— disinstallazione motore —")
        self._uninst_thread, self._uninst_worker = make_uninstall_thread()
        self._uninst_worker.log.connect(self._log)
        self._uninst_worker.finished.connect(self._on_uninstall_finished)
        self._uninst_thread.finished.connect(self._after_uninstall_thread)
        self._uninst_thread.start()

    def _on_uninstall_finished(self, ok: bool) -> None:
        self._log("✔ motore disinstallato" if ok else "✖ disinstallazione non completata")
        if not ok:
            toast(self, "Non è stato possibile rimuovere tutto: chiudi eventuali "
                        "processi del motore e riprova.", "error")
        self._refresh_engine_label()

    def _after_uninstall_thread(self) -> None:
        self._uninst_thread = None
        self._uninst_worker = None
        self._set_stem_running(False)

    def _on_verify_engine(self) -> None:
        if self._busy():
            toast(self, "Aspetta la fine dell'operazione in corso.", "warn")
            return
        if not stems.venv_python().exists():
            toast(self, "Il motore non è installato: premi «Installa motore».", "info")
            return
        self._set_stem_running(True)
        self._stem_row = None
        self.playbar.task_update("Verifica motore…")
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
            toast(self, "Il motore è a posto e pronto all'uso. ✓", "ok")
        else:
            toast(self, "Verifica non riuscita: controlla il log, oppure "
                        "disinstalla e reinstalla il motore.", "error")

    def _after_verify_thread(self) -> None:
        self._verify_thread = None
        self._verify_worker = None
        self._set_stem_running(False)

    def _on_change_engine_location(self) -> None:
        if self._busy():
            toast(self, "Aspetta la fine dell'operazione in corso.", "warn")
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
            toast(self, "Percorso aggiornato: premi «Installa motore» per "
                        "installarlo nella nuova cartella.", "info")

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
        toast(self, msg, "ok" if ok else "error")

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
            toast(self, "Aggiungi almeno un link alla coda.", "info")
            return
        # riprocessa solo gli item non ancora completati; i file locali (senza
        # url, aggiunti per la separazione) non sono scaricabili: fuori anche loro
        pending = [it for it in self.queue if it.status != "fatto" and it.url]
        if not pending:
            toast(self, "Niente da scaricare: gli elementi in coda sono già "
                        "completati o file locali. ✓", "ok")
            return
        self._start_download(pending)

    def _start_download(self, items: list[QueueItem]) -> None:
        if self._thread and self._thread.isRunning():
            return
        dest = self.dest_edit.text().strip()
        if not dest or not os.path.isdir(dest):
            toast(self, "Scegli una cartella di destinazione valida.", "error")
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
            toast(self, "Nessun download fallito da riprovare.", "info")
            return
        self._start_download(failed)

    def _set_running(self, running: bool) -> None:
        self.download_btn.setEnabled(not running)
        self.download_btn.setText("Scaricando…" if running else "Scarica")
        self.stop_btn.setEnabled(running)
        self.stop_btn.setText("Stop")
        self.clear_btn.setEnabled(not running)
        self.clear_done_btn.setEnabled(not running)
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
        try:
            self.lyrics_tab.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self._stop_preview()
        if self._upd_thread and self._upd_thread.isRunning():
            self._upd_thread.quit()
            self._upd_thread.wait(3000)
        if self.tray:
            self.tray.hide()
        super().closeEvent(event)
