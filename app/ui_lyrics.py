"""Scheda Testi: cerca, mostra, salva e riusa i testi dei brani (LRCLIB).

La ricerca combina più strategie e unisce i risultati senza doppioni:
parametri strutturati artista/titolo, query libera, e le stesse query col
titolo «ripulito» dai suffissi tipici di YouTube ((Official Video), [Lyrics],
feat. …). I testi si salvano nella cartella del brano (`lyrics.txt`,
ricaricato in automatico dal Mixer) e — su richiesta — in una libreria locale
(%APPDATA%/Sonora/testi) richiamabile in ogni momento dal pulsante «Libreria».
I testi sincronizzati LRC vengono convertiti in testo semplice: la modalità
karaoke non esiste più.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import lyrics_store, theme
from .toast import toast

# Timestamp LRC: [mm:ss], [mm:ss.cc], [mm:ss.mmm] (anche più d'uno per riga).
# I tag metadata tipo [ar:...] non matchano (servono cifre in entrambi i gruppi).
_LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")

# Rumore nei titoli YouTube: (Official Video), [Lyrics], (Video Ufficiale)…
_NOISE_RE = re.compile(
    r"[(\[][^)\]]*(official|video|lyric|audio|visualizer|remaster|hq|hd|4k|"
    r"ufficiale|testo|karaoke|live|cover|version|explicit)[^)\]]*[)\]]",
    re.IGNORECASE)
# Qualsiasi blocco fra parentesi quadre (ID YouTube, [HD], …): nei titoli
# musicali non contiene mai parte del titolo vero.
_BRACKETS_RE = re.compile(r"\[[^\]]*\]")
_FEAT_RE = re.compile(r"\s+[(\[]?(feat\.?|ft\.?|featuring)\s[^)\]]*[)\]]?",
                      re.IGNORECASE)


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


def lrc_to_plain(text: str) -> str:
    """Converte un testo LRC in testo semplice (timestamp rimossi)."""
    return "\n".join(line for _t, line in parse_lrc(text))


def clean_title(name: str) -> str:
    """Ripulisce un titolo dai suffissi YouTube che rovinano la ricerca.

    Rimuove blocchi (Official Video)/[Lyrics]/…, qualsiasi [blocco] residuo
    (ID video) e le code «feat. X». Ritorna il nome compattato."""
    s = _NOISE_RE.sub(" ", name or "")
    s = _BRACKETS_RE.sub(" ", s)
    s = _FEAT_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip(" -–—").strip()


def build_lrclib_url(query: str, artist: str = "", track: str = "", duration: float = 0.0) -> str:
    """Costruisce l'URL di ricerca LRCLIB.

    Con `artist` e `track` entrambi presenti usa i parametri strutturati
    (`artist_name`/`track_name`, più precisi di una query libera); altrimenti
    ripiega sul generico `q=query`."""
    base = "https://lrclib.net/api/search?"
    if artist and track:
        params = {"artist_name": artist, "track_name": track}
        if duration > 0:
            params["duration"] = str(int(round(duration)))
        return base + urllib.parse.urlencode(params)
    return base + urllib.parse.urlencode({"q": query or track or artist})


def search_plan(artist: str, track: str, query: str = "", duration: float = 0.0) -> list[str]:
    """La lista (ordinata, senza doppioni) di URL LRCLIB da interrogare.

    Dalla più precisa alla più permissiva: strutturata artista+titolo pulito,
    query libera com'è, query libera ripulita. I risultati delle varie
    chiamate vanno poi uniti deduplicando."""
    urls: list[str] = []
    ca, ct = (artist or "").strip(), clean_title(track)
    if ca and ct:
        urls.append(build_lrclib_url("", ca, ct, duration))
    q = (query or f"{artist} {track}").strip()
    for cand in (q, clean_title(q)):
        if cand:
            u = build_lrclib_url(cand)
            if u not in urls:
                urls.append(u)
    return urls


def split_artist_track(name: str) -> tuple[str, str]:
    """Splitta un nome tipo 'Artista - Titolo' in (artista, titolo).

    Se non c'è ' - ' ritorna ("", name) — solo titolo, nessun artista noto."""
    if " - " in name:
        artist, track = name.split(" - ", 1)
        return artist.strip(), track.strip()
    return "", name.strip()


def plain_text_of(item: dict | None) -> str:
    """Il testo semplice di un risultato LRCLIB (dal sincronizzato se serve)."""
    if not item:
        return ""
    plain = (item.get("plainLyrics") or "").strip()
    if plain:
        return plain
    return lrc_to_plain(item.get("syncedLyrics") or "")


def pick_best_lyrics(data: list, duration: float = 0.0) -> dict | None:
    """Sceglie il risultato LRCLIB migliore per il brano.

    Criteri (in ordine): durata vicina a quella del brano (entro 3s, poi 15s),
    scarto di durata minimo, testo semplice già pronto. Con duration=0
    (sconosciuta) vince il primo con testo. None se nessuno ha testo."""
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
        key = (bucket, diff, 0 if plain else 1)
        if best is None or key < best:
            best, best_item = key, item
    return best_item


class LyricsWorker(QThread):
    """Worker in background: interroga LRCLIB su più strategie e unisce."""

    # success, plain_text_or_error (vuoto in search_only), search_results
    done = Signal(bool, str, list)

    def __init__(self, artist: str = "", track: str = "", query: str = "",
                 duration: float = 0.0, search_only: bool = False):
        super().__init__()
        self.artist = artist
        self.track = track
        self.query = query
        self.duration = duration   # durata del brano nel mixer (s), 0 = ignota
        self.search_only = search_only

    def _fetch(self, url: str) -> list:
        headers = {"User-Agent": "SonoraLyricsFinder/1.0 (https://github.com/RobyPisco/sonora)"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data if isinstance(data, list) else []

    def _search(self) -> list:
        """Unisce i risultati delle strategie di `search_plan`, senza doppioni.

        Si ferma appena ha un elenco ricco (>=10); se una chiamata fallisce ma
        ce ne sono già di buone, la ignora invece di buttare tutto."""
        results: list = []
        seen: set = set()
        for url in search_plan(self.artist, self.track, self.query, self.duration):
            if len(results) >= 10:
                break
            try:
                data = self._fetch(url)
            except Exception:
                if results:
                    continue
                raise
            for item in data:
                key = item.get("id") or (item.get("trackName"),
                                         item.get("artistName"),
                                         item.get("duration"))
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
        return results

    def run(self) -> None:
        try:
            results = self._search()
        except Exception as e:
            self.done.emit(False, f"Errore di rete: {e}", [])
            return
        if self.search_only:
            self.done.emit(bool(results),
                           "" if results else "Nessun testo trovato.", results)
            return
        text = plain_text_of(pick_best_lyrics(results, self.duration))
        if text:
            self.done.emit(True, text, results)
        else:
            self.done.emit(False, "Nessun testo trovato.", results)


def _fmt_duration(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    return f"{s // 60}:{s % 60:02d}" if s > 0 else ""


class LyricsTab(QWidget):
    """Scheda Testi: ricerca potenziata, libreria locale, modifica ed export."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_folder = ""
        # Worker vivi: un QThread perde l'ultimo riferimento Python mentre gira
        # → Qt lo distrugge a thread attivo e abortisce il processo. Ogni worker
        # resta qui dentro finché il suo thread non è davvero terminato.
        self._workers: list[LyricsWorker] = []
        self._req_id = 0
        self._is_editing = False
        self._duration = 0.0        # durata del brano corrente (s), per il match
        self._text = ""             # testo attualmente mostrato (plain)
        self._current_name = ""     # nome proposto per libreria/export
        self._source_path: Path | None = None   # file da cui viene il testo
        self._panel_mode = "results"             # results | library

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # Barra superiore: ricerca (artista/titolo) + azioni sul testo
        top = QHBoxLayout()
        top.setSpacing(8)
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("Artista (opzionale)")
        self.artist_edit.returnPressed.connect(self._on_search)
        self.artist_edit.setMinimumHeight(38)

        self.track_edit = QLineEdit()
        self.track_edit.setPlaceholderText("Titolo (es. Bohemian Rhapsody)…")
        self.track_edit.returnPressed.connect(self._on_search)
        self.track_edit.setMinimumHeight(38)

        self.search_btn = QPushButton("Cerca")
        self.search_btn.setObjectName("Ghost")
        self.search_btn.clicked.connect(self._on_search)

        self.library_btn = QPushButton("Libreria")
        self.library_btn.setObjectName("Ghost")
        self.library_btn.setCheckable(True)
        self.library_btn.setToolTip(
            "I testi che hai salvato: clicca uno per rileggerlo quando vuoi.")
        self.library_btn.clicked.connect(self._toggle_library)

        self.save_btn = QPushButton("Salva")
        self.save_btn.setObjectName("Ghost")
        self.save_btn.setToolTip("Salva il testo nella libreria per ritrovarlo in seguito.")
        self.save_btn.clicked.connect(self._on_save_to_library)
        self.save_btn.setEnabled(False)

        self.edit_btn = QPushButton("Modifica")
        self.edit_btn.setObjectName("Ghost")
        self.edit_btn.setCheckable(True)
        self.edit_btn.clicked.connect(self._toggle_edit)
        self.edit_btn.setEnabled(False)

        self.export_btn = QPushButton("Esporta…")
        self.export_btn.setObjectName("Ghost")
        self.export_btn.clicked.connect(self._on_export)
        self.export_btn.setEnabled(False)

        for b in (self.search_btn, self.library_btn, self.save_btn,
                  self.edit_btn, self.export_btn):
            b.setMinimumHeight(38)

        top.addWidget(self.artist_edit, 1)
        top.addWidget(self.track_edit, 1)
        top.addWidget(self.search_btn)
        top.addWidget(self.library_btn)
        top.addWidget(self.save_btn)
        top.addWidget(self.edit_btn)
        top.addWidget(self.export_btn)
        root.addLayout(top)

        # Barra di stato
        self.status_lbl = QLabel("Carica un brano nel Mixer o cerca un testo qui sopra.")
        self.status_lbl.setStyleSheet(
            f"color:{theme.COLORS['muted']}; font-size:13px; font-style:italic;")
        root.addWidget(self.status_lbl)

        # Splitter: testo a sinistra, pannello risultati/libreria a destra
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter, 1)

        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("LyricsView")
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Segoe UI", 12))
        self.splitter.addWidget(self.text_edit)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        self.panel_lbl = QLabel("Risultati")
        self.panel_lbl.setStyleSheet(
            f"color:{theme.COLORS['muted']}; font-size:12px; font-weight:600;")
        self.results_list = QListWidget()
        self.results_list.setObjectName("LyricsResults")
        self.results_list.itemClicked.connect(self._on_panel_item_clicked)
        self.results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._on_panel_menu)
        pl.addWidget(self.panel_lbl)
        pl.addWidget(self.results_list, 1)
        self.panel = panel
        self.splitter.addWidget(panel)
        self.panel.hide()

        self.splitter.setSizes([600, 220])

    # ---------------- gestione worker ----------------

    def _launch(self, worker: LyricsWorker) -> None:
        """Avvia il worker tenendolo vivo finché il thread non termina.

        Le risposte fuori tempo massimo vengono già scartate dai controlli
        su `_req_id`: qui serve solo che l'oggetto non venga distrutto
        a thread in corsa."""
        self._workers.append(worker)
        worker.finished.connect(lambda: self._reap(worker))
        worker.start()

    def _reap(self, worker: LyricsWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def shutdown(self) -> None:
        """Attende i worker di ricerca ancora attivi (chiamare alla chiusura).

        urlopen ha timeout 10s per chiamata: dopo un'attesa ragionevole i
        thread rimasti vengono terminati a forza — stiamo comunque uscendo,
        e distruggerli ancora in corsa abortirebbe il processo."""
        for worker in self._workers:
            if worker.isRunning() and not worker.wait(3000):
                worker.terminate()
                worker.wait(1000)
        self._workers.clear()

    # ---------------- caricamento dal Mixer ----------------

    def load_song_lyrics(self, folder: str, duration: float = 0.0) -> None:
        """Carica il testo locale del brano (se esiste) o lo cerca da solo.

        Priorità: `lyrics.txt` nella cartella del brano → migrazione di un
        vecchio `lyrics.lrc` (karaoke rimosso: viene convertito in testo
        semplice) → ricerca automatica su LRCLIB. `duration` (s) affina il
        match (scarta risultati con durata lontana dal brano)."""
        self.current_folder = folder
        self._duration = max(0.0, duration or 0.0)
        self._stop_editing()
        self._hide_panel()

        if not folder:
            self._set_text("", name="", source=None)
            self.status_lbl.setText("Carica un brano nel Mixer o cerca un testo qui sopra.")
            return

        song_name = os.path.basename(folder.rstrip("/\\"))
        if song_name.lower().endswith(" - stems"):
            song_name = song_name[:-8]
        elif song_name.lower().endswith("-stems"):
            song_name = song_name[:-6]
        artist, track = split_artist_track(clean_title(song_name))
        self.artist_edit.setText(artist)
        self.track_edit.setText(track)

        lyrics_path = Path(folder) / "lyrics.txt"
        lrc_path = Path(folder) / "lyrics.lrc"

        # 1. Copia locale nella cartella del brano
        if lyrics_path.exists():
            try:
                self._set_text(lyrics_path.read_text(encoding="utf-8"),
                               name=song_name, source=lyrics_path)
                self.status_lbl.setText(f"Testo caricato dal file locale: {lyrics_path.name}")
                return
            except Exception:  # noqa: BLE001
                pass
        # 1b. Migrazione da vecchio lyrics.lrc (karaoke rimosso)
        if lrc_path.exists():
            try:
                plain = lrc_to_plain(lrc_path.read_text(encoding="utf-8"))
                if plain:
                    lyrics_path.write_text(plain, encoding="utf-8")
                    self._set_text(plain, name=song_name, source=lyrics_path)
                    self.status_lbl.setText(
                        "Testo convertito dal vecchio formato sincronizzato e salvato.")
                    return
            except Exception:  # noqa: BLE001
                pass

        # 2. Ricerca automatica
        self.status_lbl.setText(f"Ricerca automatica testo per '{song_name}' su LRCLIB...")
        self.text_edit.setHtml(
            f"<div style='text-align:center; color:{theme.COLORS['muted']};'><br><br>"
            "Ricerca automatica del testo in corso...</div>"
        )
        self._current_name = song_name
        self._req_id += 1
        req_id = self._req_id
        worker = LyricsWorker(artist=artist, track=track, query=song_name,
                              duration=self._duration)
        worker.done.connect(
            lambda ok, result, data: self._on_auto_download_done(req_id, ok, result))
        self._launch(worker)

    def _on_auto_download_done(self, req_id: int, success: bool, result: str) -> None:
        if req_id != self._req_id:
            return   # ricerca superata da una più recente, ignora
        if success and self.current_folder:
            source = None
            try:
                lyrics_path = Path(self.current_folder) / "lyrics.txt"
                lyrics_path.write_text(result, encoding="utf-8")
                source = lyrics_path
            except Exception as e:  # noqa: BLE001
                toast(self, f"Testo scaricato ma non salvato: {e}", "warn")
            self._set_text(result, name=self._current_name, source=source)
            self.status_lbl.setText("Testo scaricato automaticamente e salvato col brano.")
        else:
            self.text_edit.setHtml(
                f"<div style='text-align:center; color:{theme.COLORS['muted']};'><br><br>"
                "Nessun testo trovato automaticamente.<br>"
                "Usa il campo in alto per cercare manualmente.</div>"
            )
            self.status_lbl.setText("Testo automatico non trovato. Cerca manualmente.")

    # ---------------- visualizzazione ----------------

    def _set_text(self, text: str, name: str, source: Path | None) -> None:
        """Aggiorna testo corrente, nome proposto e file sorgente; ridisegna."""
        self._text = text or ""
        self._current_name = name or ""
        self._source_path = source
        has = bool(self._text.strip())
        self.save_btn.setEnabled(has)
        self.edit_btn.setEnabled(has or self.current_folder != "")
        self.export_btn.setEnabled(has)
        self._render()

    def _render(self) -> None:
        """Formatta e centra le righe del testo con HTML per una resa elegante."""
        if not self._text:
            self.text_edit.clear()
            return
        html_lines = []
        for line in self._text.splitlines():
            line_stripped = line.strip()
            # Evidenzia i tag di sezione (es. [Chorus], [Verse 1]...) in arancione
            if line_stripped.startswith("[") and line_stripped.endswith("]"):
                html_lines.append(
                    f"<br><b style='color:{theme.COLORS['warn']};"
                    f" font-size:15px;'>{line_stripped}</b>")
            else:
                html_lines.append(line_stripped)
        self.text_edit.setHtml(
            "<div style='text-align:center; line-height:1.6; font-size:16px;'>"
            + "<br>".join(html_lines) + "</div>")

    # ---------------- ricerca manuale ----------------

    def _on_search(self) -> None:
        artist = self.artist_edit.text().strip()
        track = self.track_edit.text().strip()
        if not track and not artist:
            return
        query = f"{artist} {track}".strip()

        self.status_lbl.setText(f"Ricerca per '{query}'...")
        self._show_panel("results")
        self.results_list.clear()

        self._req_id += 1
        req_id = self._req_id
        worker = LyricsWorker(artist=artist, track=track, query=query,
                              duration=self._duration, search_only=True)
        worker.done.connect(
            lambda ok, result, data: self._on_search_done(req_id, ok, data))
        self._launch(worker)

    def _on_search_done(self, req_id: int, success: bool, data: list) -> None:
        if req_id != self._req_id:
            return   # ricerca superata da una più recente, ignora
        if self._panel_mode != "results":
            return   # l'utente è passato alla libreria nel frattempo
        self.results_list.clear()
        if success and data:
            for item in data:
                track = item.get("trackName") or item.get("name") or "?"
                artist = item.get("artistName") or item.get("artist") or "?"
                album = item.get("albumName") or ""
                label = f"{artist} - {track}"
                if album:
                    label += f" ({album})"
                dur = _fmt_duration(item.get("duration"))
                if dur:
                    label += f" · {dur}"
                list_item = QListWidgetItem(label)
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                self.results_list.addItem(list_item)
            self.status_lbl.setText(
                f"Trovati {len(data)} risultati. Clicca su uno per scaricarlo.")
        else:
            self.status_lbl.setText("Nessun testo trovato. Prova a semplificare il titolo.")

    def _on_result_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        text = plain_text_of(data)
        if not text:
            toast(self, "Questo risultato non contiene un testo disponibile.", "warn")
            return

        track = (data.get("trackName") or "").strip()
        artist = (data.get("artistName") or "").strip()
        name = f"{artist} - {track}".strip(" -") or self._current_name

        # Salva col brano se c'è una cartella attiva nel mixer
        source = None
        if self.current_folder:
            try:
                lyrics_path = Path(self.current_folder) / "lyrics.txt"
                lyrics_path.write_text(text, encoding="utf-8")
                # via un eventuale .lrc del vecchio karaoke: non serve più
                (Path(self.current_folder) / "lyrics.lrc").unlink(missing_ok=True)
                source = lyrics_path
                self.status_lbl.setText("Testo salvato col brano. Con «Salva» lo tieni anche in libreria.")
            except Exception as e:  # noqa: BLE001
                self.status_lbl.setText(f"Testo caricato ma impossibile salvare il file: {e}")
        else:
            self.status_lbl.setText("Testo caricato. Con «Salva» lo tieni in libreria.")
        self._set_text(text, name=name, source=source)
        self._hide_panel()

    # ---------------- libreria locale ----------------

    def _toggle_library(self) -> None:
        if self.library_btn.isChecked():
            self._show_panel("library")
            self._refresh_library()
        else:
            self._hide_panel()

    def _refresh_library(self) -> None:
        self.results_list.clear()
        names = lyrics_store.list_all()
        for name in names:
            self.results_list.addItem(QListWidgetItem(name))
        if names:
            self.status_lbl.setText(
                f"Libreria: {len(names)} testi salvati. Clicca per rileggere, "
                "tasto destro per eliminare.")
        else:
            self.status_lbl.setText(
                "Libreria vuota: carica un testo e premi «Salva» per tenerlo qui.")

    def _on_panel_item_clicked(self, item: QListWidgetItem) -> None:
        if self._panel_mode == "library":
            name = item.text()
            try:
                text = lyrics_store.load(name)
            except Exception as e:  # noqa: BLE001
                toast(self, f"Impossibile leggere il testo salvato: {e}", "error")
                return
            self._stop_editing()
            self._set_text(text, name=name, source=lyrics_store.path_of(name))
            self.status_lbl.setText(f"Dalla libreria: {name}")
        else:
            self._on_result_clicked(item)

    def _on_panel_menu(self, pos) -> None:
        if self._panel_mode != "library":
            return
        item = self.results_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        act = menu.addAction("Elimina dalla libreria")
        if menu.exec(self.results_list.mapToGlobal(pos)) is act:
            lyrics_store.delete(item.text())
            self._refresh_library()

    def _on_save_to_library(self) -> None:
        if not self._text.strip():
            return
        suggestion = f"{self.artist_edit.text().strip()} - {self.track_edit.text().strip()}"
        suggestion = suggestion.strip(" -") or self._current_name or "testo"
        name, ok = QInputDialog.getText(
            self, "Salva nella libreria", "Nome del testo:",
            text=lyrics_store.safe_name(suggestion))
        if not ok or not name.strip():
            return
        try:
            lyrics_store.save(name, self._text)
        except Exception as e:  # noqa: BLE001
            toast(self, f"Impossibile salvare nella libreria: {e}", "error")
            return
        toast(self, f"«{lyrics_store.safe_name(name)}» salvato nella libreria.", "ok")
        if self._panel_mode == "library":
            self._refresh_library()

    # ---------------- pannello destro ----------------

    def _show_panel(self, mode: str) -> None:
        self._panel_mode = mode
        self.panel_lbl.setText("Libreria" if mode == "library" else "Risultati")
        self.library_btn.setChecked(mode == "library")
        self.results_list.clear()
        self.panel.show()

    def _hide_panel(self) -> None:
        self.panel.hide()
        self.library_btn.setChecked(False)
        self._panel_mode = "results"

    # ---------------- modifica ed esportazione ----------------

    def _stop_editing(self) -> None:
        self._is_editing = False
        self.edit_btn.setChecked(False)
        self.edit_btn.setText("Modifica")
        self.text_edit.setReadOnly(True)

    def _toggle_edit(self) -> None:
        """Modifica il testo corrente; al salvataggio aggiorna anche il file
        da cui proviene (lyrics.txt del brano o voce della libreria)."""
        if not self._is_editing:
            self._is_editing = True
            self.edit_btn.setText("Salva")
            self.text_edit.setReadOnly(False)
            self.text_edit.setPlainText(self._text)
            self.status_lbl.setText(
                "Modalità modifica: correggi il testo e premi 'Salva'.")
        else:
            text = self.text_edit.toPlainText()
            self._stop_editing()
            saved = ""
            if self._source_path is not None:
                try:
                    self._source_path.write_text(text, encoding="utf-8")
                    saved = f" ({self._source_path.name})"
                except Exception as e:  # noqa: BLE001
                    toast(self, f"Impossibile salvare le modifiche: {e}", "error")
            self._set_text(text, name=self._current_name, source=self._source_path)
            self.status_lbl.setText(f"Modifiche salvate{saved}.")

    def _on_export(self) -> None:
        """Esporta il testo corrente in un file .txt scelto dall'utente."""
        default_name = lyrics_store.safe_name(self._current_name or "testo")
        path, _sel = QFileDialog.getSaveFileName(
            self, "Esporta testo", f"{default_name}.txt", "Testo semplice (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self._text, encoding="utf-8")
            toast(self, f"Testo esportato in {Path(path).name}", "ok")
        except Exception as e:  # noqa: BLE001
            toast(self, f"Esportazione fallita: {e}", "error")
