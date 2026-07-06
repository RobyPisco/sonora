"""Scheda Testi: scarica e mostra i testi dei brani in tempo reale da LRCLIB.

Se LRCLIB fornisce anche i testi sincronizzati (`syncedLyrics`, formato LRC
`[mm:ss.xx] riga`), vengono salvati in `lyrics.lrc` accanto a `lyrics.txt` e la
scheda entra in modalità karaoke: la riga corrente viene evidenziata e centrata
seguendo la posizione di playback del mixer (segnale `MixerTab.position_changed`).
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from bisect import bisect_right
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPalette,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .toast import toast

# Timestamp LRC: [mm:ss], [mm:ss.cc], [mm:ss.mmm] (anche più d'uno per riga).
# I tag metadata tipo [ar:...] non matchano (servono cifre in entrambi i gruppi).
_LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Parsa un testo LRC in [(secondi, riga)] ordinati per tempo.

    Supporta più timestamp sulla stessa riga ([00:12][00:45]testo = riga
    ripetuta) e ignora righe senza timestamp (metadata [ar:], [ti:], vuote)."""
    out: list[tuple[float, str]] = []
    for raw in (text or "").splitlines():
        stamps = list(_LRC_TIME_RE.finditer(raw))
        if not stamps:
            continue
        line = _LRC_TIME_RE.sub("", raw).strip()
        for m in stamps:
            frac = m.group(3) or "0"
            t = int(m.group(1)) * 60 + int(m.group(2)) + int(frac) / (10 ** len(frac))
            out.append((t, line))
    out.sort(key=lambda x: x[0])
    return out


def pick_best_lyrics(data: list, duration: float = 0.0) -> dict | None:
    """Sceglie il risultato LRCLIB migliore per il brano.

    Criteri (in ordine): durata vicina a quella del brano (entro 3s, poi 15s),
    presenza di testo sincronizzato, scarto di durata minimo. Con duration=0
    (sconosciuta) conta solo il sincronizzato. None se nessun risultato ha testo."""
    best: tuple | None = None
    best_item: dict | None = None
    for item in data or []:
        plain = (item.get("plainLyrics") or "").strip()
        synced = (item.get("syncedLyrics") or "").strip()
        if not plain and not synced:
            continue
        d = float(item.get("duration") or 0)
        if duration > 0 and d > 0:
            diff = abs(d - duration)
            bucket = 0 if diff <= 3 else (1 if diff <= 15 else 2)
        else:
            diff, bucket = 999.0, 2
        key = (bucket, 0 if synced else 1, diff)
        if best is None or key < best:
            best, best_item = key, item
    return best_item


class LyricsWorker(QThread):
    """Worker in background per cercare e scaricare i testi da LRCLIB."""

    # success, plain_text_or_error, synced_lrc (può essere ""), search_results
    done = Signal(bool, str, str, list)

    def __init__(self, query: str, search_only: bool = False, duration: float = 0.0):
        super().__init__()
        self.query = query
        self.search_only = search_only
        self.duration = duration   # durata del brano nel mixer (s), 0 = ignota

    def run(self) -> None:
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": self.query})
        headers = {"User-Agent": "SonoraLyricsFinder/1.0 (https://github.com/RobyPisco/sonora)"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                if not data:
                    self.done.emit(False, "Nessun testo trovato.", "", [])
                    return

                if self.search_only:
                    self.done.emit(True, "", "", data)
                    return

                item = pick_best_lyrics(data, self.duration)
                if item is None:
                    self.done.emit(False, "Testo non disponibile nei risultati trovati.", "", data)
                    return
                plain = (item.get("plainLyrics") or "").strip()
                synced = (item.get("syncedLyrics") or "").strip()
                self.done.emit(True, plain or synced, synced, data)
        except Exception as e:
            self.done.emit(False, f"Errore di rete: {e}", "", [])


class LyricsTab(QWidget):
    """Scheda Testi: visualizza, scarica e permette di modificare i testi dei brani."""

    seek_requested = Signal(float)   # click su una riga karaoke → seek (secondi)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_folder = ""
        self._worker: LyricsWorker | None = None
        self._search_results: list = []
        self._is_editing = False
        self._duration = 0.0   # durata del brano corrente (s), per il match LRCLIB
        # stato karaoke (testo sincronizzato)
        self._synced: list[tuple[float, str]] = []
        self._times: list[float] = []
        self._current_line = -1
        self._synced_active = False

        # Configurazione Layout
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # Barra superiore: Ricerca manuale e Modifica
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Cerca testo manualmente (es. Queen Bohemian Rhapsody)…")
        self.search_edit.returnPressed.connect(self._on_search)
        self.search_edit.setMinimumHeight(38)

        self.search_btn = QPushButton("Cerca")
        self.search_btn.setObjectName("Ghost")
        self.search_btn.setMinimumHeight(38)
        self.search_btn.clicked.connect(self._on_search)

        self.edit_btn = QPushButton("Modifica")
        self.edit_btn.setObjectName("Ghost")
        self.edit_btn.setMinimumHeight(38)
        self.edit_btn.setCheckable(True)
        self.edit_btn.clicked.connect(self._toggle_edit)
        self.edit_btn.setEnabled(False)

        top.addWidget(self.search_edit, 1)
        top.addWidget(self.search_btn)
        top.addWidget(self.edit_btn)
        root.addLayout(top)

        # Barra di stato
        self.status_lbl = QLabel("Carica un brano nel Mixer per vedere il testo.")
        self.status_lbl.setStyleSheet(
            f"color:{theme.COLORS['muted']}; font-size:13px; font-style:italic;")
        root.addWidget(self.status_lbl)

        # Splitter principale: Area Testo (sinistra) e Risultati Ricerca (destra)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter, 1)

        # Editor di testo (stile nel QSS centrale, selettore #LyricsView)
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("LyricsView")
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Segoe UI", 12))
        # click su una riga in modalità karaoke = seek nel brano
        self.text_edit.viewport().installEventFilter(self)
        self.splitter.addWidget(self.text_edit)

        # Lista risultati ricerca (nascosta di default; stile nel QSS centrale)
        self.results_list = QListWidget()
        self.results_list.setObjectName("LyricsResults")
        self.results_list.itemClicked.connect(self._on_result_clicked)
        self.splitter.addWidget(self.results_list)
        self.results_list.hide()

        # Imposta proporzioni iniziali splitter
        self.splitter.setSizes([600, 200])

    def load_song_lyrics(self, folder: str, duration: float = 0.0) -> None:
        """Carica il testo locale (se esiste) o tenta il download automatico.

        Priorità: `lyrics.lrc` (sincronizzato, modalità karaoke) → `lyrics.txt`
        (statico) → download automatico da LRCLIB. `duration` (s) affina il
        match su LRCLIB (scarta risultati con durata lontana dal brano)."""
        self.current_folder = folder
        self._duration = max(0.0, duration or 0.0)
        self._is_editing = False
        self.edit_btn.setChecked(False)
        self.edit_btn.setText("Modifica")
        self.text_edit.setReadOnly(True)
        self.results_list.hide()
        self._reset_synced()

        if not folder:
            self.text_edit.clear()
            self.status_lbl.setText("Carica un brano nel Mixer per vedere il testo.")
            self.edit_btn.setEnabled(False)
            return

        self.edit_btn.setEnabled(True)
        lrc_path = Path(folder) / "lyrics.lrc"
        lyrics_path = Path(folder) / "lyrics.txt"

        # 1. Tenta caricamento locale: prima il sincronizzato, poi lo statico
        if lrc_path.exists():
            try:
                lines = parse_lrc(lrc_path.read_text(encoding="utf-8"))
                if lines:
                    self._display_synced(lines)
                    self.status_lbl.setText(
                        f"Testo sincronizzato caricato: {lrc_path.name} — segue la riproduzione.")
                    return
            except Exception:  # noqa: BLE001
                pass
        if lyrics_path.exists():
            try:
                lyrics_text = lyrics_path.read_text(encoding="utf-8")
                self._display_lyrics(lyrics_text)
                self.status_lbl.setText(f"Testo caricato dal file locale: {lyrics_path.name}")
                return
            except Exception:  # noqa: BLE001
                pass

        # 2. Tenta download automatico
        song_name = os.path.basename(folder.rstrip("/\\"))
        if song_name.lower().endswith(" - stems"):
            song_name = song_name[:-8]
        elif song_name.lower().endswith("-stems"):
            song_name = song_name[:-6]

        self.status_lbl.setText(f"Ricerca automatica testo per '{song_name}' su LRCLIB...")
        self.text_edit.setHtml(
            f"<div style='text-align:center; color:{theme.COLORS['muted']};'><br><br>"
            "Ricerca automatica del testo in corso...</div>"
        )

        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()

        self._worker = LyricsWorker(song_name, search_only=False, duration=self._duration)
        self._worker.done.connect(self._on_auto_download_done)
        self._worker.start()

    def _on_auto_download_done(self, success: bool, result: str, synced: str, _data: list) -> None:
        if success and self.current_folder:
            # Salva locale (testo statico sempre, LRC se disponibile)
            try:
                lyrics_path = Path(self.current_folder) / "lyrics.txt"
                lyrics_path.write_text(result, encoding="utf-8")
                if synced:
                    (Path(self.current_folder) / "lyrics.lrc").write_text(
                        synced, encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            lines = parse_lrc(synced) if synced else []
            if lines:
                self._display_synced(lines)
                self.status_lbl.setText(
                    "Testo sincronizzato scaricato e salvato — segue la riproduzione.")
            else:
                self._display_lyrics(result)
                self.status_lbl.setText("Testo scaricato automaticamente e salvato in locale.")
        else:
            self.text_edit.setHtml(
                f"<div style='text-align:center; color:{theme.COLORS['muted']};'><br><br>"
                "Nessun testo trovato automaticamente.<br>"
                "Usa il campo in alto per cercare manualmente.</div>"
            )
            self.status_lbl.setText("Testo automatico non trovato. Cerca manualmente.")

    def _display_lyrics(self, text: str) -> None:
        """Formata e centra le linee di testo con HTML per una resa elegante."""
        self._reset_synced()
        if not text:
            self.text_edit.clear()
            return

        lines = text.splitlines()
        html_lines = []
        for line in lines:
            line_stripped = line.strip()
            # Evidenzia i tag di sezione (es. [Chorus], [Verse 1]...) in arancione grassetto
            if line_stripped.startswith("[") and line_stripped.endswith("]"):
                html_lines.append(
                    f"<br><b style='color:{theme.COLORS['warn']};"
                    f" font-size:15px;'>{line_stripped}</b>")
            else:
                html_lines.append(line_stripped)

        html_content = (
            "<div style='text-align:center; line-height:1.6; font-size:16px;'>"
            + "<br>".join(html_lines)
            + "</div>"
        )
        self.text_edit.setHtml(html_content)

    # ---------------- modalità karaoke (testo sincronizzato) ----------------

    def _reset_synced(self) -> None:
        self._synced = []
        self._times = []
        self._current_line = -1
        self._synced_active = False
        self.text_edit.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (API Qt)
        """Click sinistro su una riga karaoke → seek a quel timestamp."""
        if (obj is self.text_edit.viewport()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self._synced_active and not self._is_editing):
            cursor = self.text_edit.cursorForPosition(event.position().toPoint())
            idx = cursor.blockNumber()
            if 0 <= idx < len(self._synced):
                self.seek_requested.emit(self._synced[idx][0])
            return True   # niente spostamento del caret
        return super().eventFilter(obj, event)

    @staticmethod
    def _char_fmt(current: bool) -> QTextCharFormat:
        fmt = QTextCharFormat()
        if current:
            fmt.setForeground(QBrush(QColor("#ffffff")))
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontPointSize(19)
        else:
            fmt.setForeground(QBrush(QColor(theme.COLORS["muted"])))
            fmt.setFontWeight(QFont.Weight.Normal)
            fmt.setFontPointSize(13)
        return fmt

    def _display_synced(self, lines: list[tuple[float, str]]) -> None:
        """Mostra il testo LRC come blocchi centrati, pronti per l'highlight."""
        self._synced = lines
        self._times = [t for t, _ in lines]
        self._current_line = -1
        self._synced_active = True

        self.text_edit.clear()
        cursor = QTextCursor(self.text_edit.document())
        block_fmt = QTextBlockFormat()
        block_fmt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        block_fmt.setBottomMargin(8)
        normal = self._char_fmt(current=False)
        for i, (_t, line) in enumerate(lines):
            if i:
                cursor.insertBlock()
            cursor.setBlockFormat(block_fmt)
            cursor.insertText(line or "♪", normal)
        self.text_edit.verticalScrollBar().setValue(0)
        self.text_edit.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def set_position(self, seconds: float) -> None:
        """Aggiorna l'evidenziazione karaoke alla posizione di playback (s).

        Chiamato dal tick del mixer (~40ms): fa lavoro solo quando la riga
        corrente cambia e la scheda è visibile."""
        if not self._synced_active or self._is_editing or not self.isVisible():
            return
        idx = bisect_right(self._times, max(0.0, seconds)) - 1
        if idx == self._current_line:
            return
        doc = self.text_edit.document()
        if self._current_line >= 0:
            self._format_block(doc, self._current_line, self._char_fmt(current=False))
        if idx >= 0:
            self._format_block(doc, idx, self._char_fmt(current=True))
            self._scroll_to_block(idx)
        self._current_line = idx

    def _format_block(self, doc, block_no: int, fmt: QTextCharFormat) -> None:
        block = doc.findBlockByNumber(block_no)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        cursor.setCharFormat(fmt)

    def _scroll_to_block(self, block_no: int) -> None:
        """Centra verticalmente la riga evidenziata nella viewport."""
        block = self.text_edit.document().findBlockByNumber(block_no)
        if not block.isValid():
            return
        rect = self.text_edit.document().documentLayout().blockBoundingRect(block)
        target = int(rect.center().y() - self.text_edit.viewport().height() / 2)
        sb = self.text_edit.verticalScrollBar()
        sb.setValue(max(0, min(target, sb.maximum())))

    def _on_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return

        self.status_lbl.setText(f"Ricerca manuale per '{query}'...")
        self.results_list.clear()
        self.results_list.show()

        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()

        self._worker = LyricsWorker(query, search_only=True)
        self._worker.done.connect(self._on_search_done)
        self._worker.start()

    def _on_search_done(self, success: bool, _result: str, _synced: str, data: list) -> None:
        self.results_list.clear()
        if success and data:
            self._search_results = data
            for item in data:
                track = item.get("trackName") or item.get("name") or "?"
                artist = item.get("artistName") or item.get("artist") or "?"
                album = item.get("albumName") or ""
                label = f"{artist} - {track}"
                if album:
                    label += f" ({album})"
                if (item.get("syncedLyrics") or "").strip():
                    label = "🎤 " + label   # risultato con testo sincronizzato

                list_item = QListWidgetItem(label)
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                self.results_list.addItem(list_item)
            self.status_lbl.setText(f"Trovati {len(data)} risultati. Clicca su uno per scaricarlo.")
        else:
            self.status_lbl.setText("Nessun testo trovato per la ricerca manuale.")
            self.results_list.hide()

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        lyrics = (data.get("plainLyrics") or "").strip()
        synced = (data.get("syncedLyrics") or "").strip()
        if not lyrics and not synced:
            toast(self, "Questo risultato non contiene un testo disponibile.", "warn")
            return

        self._reset_synced()
        lines = parse_lrc(synced) if synced else []
        if lines:
            self._display_synced(lines)
        else:
            self._display_lyrics(lyrics)
        self.results_list.hide()

        # Salva se c'è un brano attivo nel mixer
        if self.current_folder:
            try:
                folder = Path(self.current_folder)
                (folder / "lyrics.txt").write_text(lyrics or synced, encoding="utf-8")
                if synced:
                    (folder / "lyrics.lrc").write_text(synced, encoding="utf-8")
                else:
                    # il testo scelto non è sincronizzato: rimuovi un eventuale
                    # .lrc del brano precedente per non ripresentarlo al reload
                    (folder / "lyrics.lrc").unlink(missing_ok=True)
                extra = " (sincronizzato)" if synced else ""
                self.status_lbl.setText(f"Testo salvato in locale{extra}.")
            except Exception as e:  # noqa: BLE001
                self.status_lbl.setText(f"Testo caricato ma impossibile salvare il file: {e}")
        else:
            self.status_lbl.setText(
                "Testo visualizzato. Carica una cartella nel Mixer per poterlo salvare in locale."
            )

    def _toggle_edit(self) -> None:
        """Modifica il file sorgente attivo: `lyrics.lrc` (grezzo, con i
        timestamp) in modalità karaoke, altrimenti `lyrics.txt`."""
        if not self.current_folder:
            return

        edit_lrc = self._synced_active
        src = Path(self.current_folder) / ("lyrics.lrc" if edit_lrc else "lyrics.txt")

        if not self._is_editing:
            # Passa a editing (testo grezzo)
            self._is_editing = True
            self.edit_btn.setText("Salva")
            self.text_edit.setReadOnly(False)
            self.text_edit.viewport().setCursor(Qt.CursorShape.IBeamCursor)

            if src.exists():
                try:
                    self.text_edit.setPlainText(src.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
            hint = " (formato LRC, [mm:ss.xx] riga)" if edit_lrc else ""
            self.status_lbl.setText(
                f"Modalità modifica{hint}: effettua le modifiche e premi 'Salva'.")
        else:
            # Salva modifiche
            self._is_editing = False
            self.edit_btn.setText("Modifica")
            self.edit_btn.setChecked(False)
            self.text_edit.setReadOnly(True)

            text = self.text_edit.toPlainText()
            try:
                src.write_text(text, encoding="utf-8")
                self.status_lbl.setText("Modifiche salvate con successo.")
            except Exception as e:  # noqa: BLE001
                self.status_lbl.setText(f"Impossibile salvare le modifiche: {e}")

            if edit_lrc:
                lines = parse_lrc(text)
                if lines:
                    self._display_synced(lines)
                else:
                    # LRC svuotato/rotto: torna alla visualizzazione statica
                    self._reset_synced()
                    self._display_lyrics(text)
            else:
                self._display_lyrics(text)
