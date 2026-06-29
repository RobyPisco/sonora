"""Scheda Testi: scarica e mostra i testi dei brani in tempo reale da LRCLIB."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class LyricsWorker(QThread):
    """Worker in background per cercare e scaricare i testi da LRCLIB."""

    done = Signal(bool, str, list)  # success, lyrics_text or error_msg, search_results

    def __init__(self, query: str, search_only: bool = False):
        super().__init__()
        self.query = query
        self.search_only = search_only

    def run(self) -> None:
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode({"q": self.query})
        headers = {"User-Agent": "SonoraLyricsFinder/1.0 (https://github.com/RobyPisco/sonora)"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                if not data:
                    self.done.emit(False, "Nessun testo trovato.", [])
                    return

                if self.search_only:
                    self.done.emit(True, "", data)
                else:
                    # Ritorna il primo risultato che contiene testi non vuoti
                    for item in data:
                        lyrics = item.get("plainLyrics")
                        if lyrics and lyrics.strip():
                            self.done.emit(True, lyrics, data)
                            return
                    self.done.emit(False, "Testo non disponibile nei risultati trovati.", data)
        except Exception as e:
            self.done.emit(False, f"Errore di rete: {e}", [])


class LyricsTab(QWidget):
    """Scheda Testi: visualizza, scarica e permette di modificare i testi dei brani."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_folder = ""
        self._worker: LyricsWorker | None = None
        self._search_results: list = []
        self._is_editing = False

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
        self.status_lbl.setStyleSheet("color:#8b90a0; font-size:13px; font-style:italic;")
        root.addWidget(self.status_lbl)

        # Splitter principale: Area Testo (sinistra) e Risultati Ricerca (destra)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter, 1)

        # Editor di testo
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background: #0f1116;
                border: 1px solid #232733;
                border-radius: 10px;
                color: #e6e8ee;
                padding: 20px;
            }
        """)
        self.text_edit.setFont(QFont("Segoe UI", 12))
        self.splitter.addWidget(self.text_edit)

        # Lista risultati ricerca (nascosta di default)
        self.results_list = QListWidget()
        self.results_list.setStyleSheet("""
            QListWidget {
                background: #1c1f28;
                border: 1px solid #2a2e3a;
                border-radius: 10px;
                color: #e6e8ee;
                padding: 6px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #2a2e3a;
            }
            QListWidget::item:selected {
                background: #ff3b5c;
                color: white;
            }
        """)
        self.results_list.itemClicked.connect(self._on_result_clicked)
        self.splitter.addWidget(self.results_list)
        self.results_list.hide()

        # Imposta proporzioni iniziali splitter
        self.splitter.setSizes([600, 200])

    def load_song_lyrics(self, folder: str) -> None:
        """Carica il testo locale (se esiste) o tenta il download automatico."""
        self.current_folder = folder
        self._is_editing = False
        self.edit_btn.setChecked(False)
        self.edit_btn.setText("Modifica")
        self.text_edit.setReadOnly(True)
        self.results_list.hide()

        if not folder:
            self.text_edit.clear()
            self.status_lbl.setText("Carica un brano nel Mixer per vedere il testo.")
            self.edit_btn.setEnabled(False)
            return

        self.edit_btn.setEnabled(True)
        lyrics_path = Path(folder) / "lyrics.txt"

        # 1. Tenta caricamento locale
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
            "<div style='text-align:center; color:#8b90a0;'><br><br>"
            "Ricerca automatica del testo in corso...</div>"
        )

        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()

        self._worker = LyricsWorker(song_name, search_only=False)
        self._worker.done.connect(self._on_auto_download_done)
        self._worker.start()

    def _on_auto_download_done(self, success: bool, result: str, _data: list) -> None:
        if success and self.current_folder:
            # Salva locale
            try:
                lyrics_path = Path(self.current_folder) / "lyrics.txt"
                lyrics_path.write_text(result, encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            self._display_lyrics(result)
            self.status_lbl.setText("Testo scaricato automaticamente e salvato in locale.")
        else:
            self.text_edit.setHtml(
                "<div style='text-align:center; color:#8b90a0;'><br><br>"
                "Nessun testo trovato automaticamente.<br>"
                "Usa il campo in alto per cercare manualmente.</div>"
            )
            self.status_lbl.setText("Testo automatico non trovato. Cerca manualmente.")

    def _display_lyrics(self, text: str) -> None:
        """Formata e centra le linee di testo con HTML per una resa elegante."""
        if not text:
            self.text_edit.clear()
            return

        lines = text.splitlines()
        html_lines = []
        for line in lines:
            line_stripped = line.strip()
            # Evidenzia i tag di sezione (es. [Chorus], [Verse 1]...) in arancione grassetto
            if line_stripped.startswith("[") and line_stripped.endswith("]"):
                html_lines.append(f"<br><b style='color:#ff9f43; font-size:15px;'>{line_stripped}</b>")
            else:
                html_lines.append(line_stripped)

        html_content = (
            "<div style='text-align:center; line-height:1.6; font-size:16px;'>"
            + "<br>".join(html_lines)
            + "</div>"
        )
        self.text_edit.setHtml(html_content)

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

    def _on_search_done(self, success: bool, _result: str, data: list) -> None:
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

        lyrics = data.get("plainLyrics")
        if not lyrics or not lyrics.strip():
            QMessageBox.warning(self, "Testo vuoto", "Questo risultato non contiene un testo disponibile.")
            return

        self._display_lyrics(lyrics)
        self.results_list.hide()

        # Salva se c'è un brano attivo nel mixer
        if self.current_folder:
            try:
                lyrics_path = Path(self.current_folder) / "lyrics.txt"
                lyrics_path.write_text(lyrics, encoding="utf-8")
                self.status_lbl.setText(f"Testo salvato in locale: {lyrics_path.name}")
            except Exception as e:  # noqa: BLE001
                self.status_lbl.setText(f"Testo caricato ma impossibile salvare il file: {e}")
        else:
            self.status_lbl.setText(
                "Testo visualizzato. Carica una cartella nel Mixer per poterlo salvare in locale."
            )

    def _toggle_edit(self) -> None:
        if not self.current_folder:
            return

        if not self._is_editing:
            # Passa a editing (testo grezzo)
            self._is_editing = True
            self.edit_btn.setText("Salva")
            self.text_edit.setReadOnly(False)

            lyrics_path = Path(self.current_folder) / "lyrics.txt"
            if lyrics_path.exists():
                try:
                    self.text_edit.setPlainText(lyrics_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    pass
            self.status_lbl.setText("Modalità modifica: effettua le modifiche e premi 'Salva'.")
        else:
            # Salva modifiche
            self._is_editing = False
            self.edit_btn.setText("Modifica")
            self.edit_btn.setChecked(False)
            self.text_edit.setReadOnly(True)

            text = self.text_edit.toPlainText()
            try:
                lyrics_path = Path(self.current_folder) / "lyrics.txt"
                lyrics_path.write_text(text, encoding="utf-8")
                self.status_lbl.setText("Modifiche salvate con successo.")
            except Exception as e:  # noqa: BLE001
                self.status_lbl.setText(f"Impossibile salvare le modifiche: {e}")

            self._display_lyrics(text)
