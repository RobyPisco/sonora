"""Wrapper yt-dlp eseguito in un QThread, con segnali di progresso verso la GUI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

import yt_dlp

from . import paths

# Formati audio supportati. lossless: il bitrate non si applica.
AUDIO_FORMATS = ["mp3", "m4a", "opus", "flac", "wav"]
LOSSLESS_FORMATS = {"wav", "flac"}
# wav non supporta tag/cover incorporati; gli altri si'.
NO_TAG_FORMATS = {"wav"}


@dataclass
class DownloadOptions:
    """Opzioni scelte dall'utente per una sessione di download."""

    dest_dir: str
    audio_format: str = "mp3"          # mp3 | m4a | opus | flac | wav
    bitrate: str = "192"               # 128 | 192 | 320 (ignorato per lossless)
    filename_template: str = "%(title)s"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    per_file_folder: bool = True       # True = ogni file in una sua sottocartella
    normalize: bool = False            # True = normalizza volume (loudnorm)
    is_playlist: bool = False          # True = consenti intera playlist


@dataclass
class QueueItem:
    """Un URL nella coda di download."""

    url: str
    title: str = ""
    status: str = "in attesa"          # in attesa | scaricando | conversione | fatto | errore
    progress: float = 0.0              # 0..100
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def build_ydl_opts(opts: DownloadOptions, progress_hook, postproc_hook) -> dict[str, Any]:
    """Costruisce il dizionario opzioni per yt_dlp.YoutubeDL."""
    is_lossless = opts.audio_format in LOSSLESS_FORMATS
    supports_tags = opts.audio_format not in NO_TAG_FORMATS

    postprocessors: list[dict[str, Any]] = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": opts.audio_format,
            # i formati lossless ignorano la quality
            "preferredquality": "0" if is_lossless else opts.bitrate,
        }
    ]
    # Metadata e thumbnail: supportati da tutti tranne wav
    if opts.embed_metadata and supports_tags:
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    if opts.embed_thumbnail and supports_tags:
        postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

    # opzionale: ogni file in una sottocartella col titolo del video
    if opts.per_file_folder:
        outtmpl = os.path.join(opts.dest_dir, "%(title)s", opts.filename_template + ".%(ext)s")
    else:
        outtmpl = os.path.join(opts.dest_dir, opts.filename_template + ".%(ext)s")

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": postprocessors,
        "writethumbnail": opts.embed_thumbnail and supports_tags,
        "noplaylist": not opts.is_playlist,
        "ignoreerrors": opts.is_playlist,   # in playlist non fermarsi al primo errore
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postproc_hook],
        "windowsfilenames": True,           # sanitizza nomi per Windows
        "restrictfilenames": False,
    }

    # normalizzazione volume: applica filtro loudnorm durante l'estrazione audio
    if opts.normalize:
        ydl_opts["postprocessor_args"] = {
            "extractaudio": ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"],
        }

    ffmpeg_loc = paths.ffmpeg_dir()
    if ffmpeg_loc:
        ydl_opts["ffmpeg_location"] = ffmpeg_loc

    return ydl_opts


def _final_filepath(info: dict[str, Any]) -> str:
    """Estrae il path del file finale prodotto dai postprocessor."""
    reqs = info.get("requested_downloads") or []
    if reqs:
        return reqs[0].get("filepath") or reqs[0].get("_filename") or ""
    return info.get("filepath") or ""


class DownloadWorker(QObject):
    """Esegue la coda di download in un thread separato.

    Segnali:
      item_started(index)              -> item iniziato
      item_progress(index, percent, status, detail)
      item_finished(index, ok, filepath_or_error)
      all_finished()
      log(text)
    """

    item_started = Signal(int)
    item_progress = Signal(int, float, str, str)
    item_finished = Signal(int, bool, str)
    all_finished = Signal()
    log = Signal(str)

    def __init__(self, items: list[QueueItem], opts: DownloadOptions):
        super().__init__()
        self._items = items
        self._opts = opts
        self._cancel = False
        self._current = -1

    def cancel(self) -> None:
        self._cancel = True
        # uccide la conversione ffmpeg in corso (solo i nostri processi figli)
        _kill_ffmpeg_children()

    # --- hook yt-dlp (girano nel thread del worker) ---

    def _progress_hook(self, d: dict[str, Any]) -> None:
        if self._cancel:
            raise _CancelledError()
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100.0) if total else 0.0
            speed = d.get("speed") or 0
            eta = d.get("eta")
            detail = ""
            if speed:
                detail = f"{speed / 1024 / 1024:.1f} MB/s"
            if eta:
                detail += f" · ETA {int(eta)}s"
            self.item_progress.emit(self._current, pct, "scaricando", detail.strip(" ·"))
        elif status == "finished":
            self.item_progress.emit(self._current, 100.0, "conversione", "conversione audio…")

    def _postproc_hook(self, d: dict[str, Any]) -> None:
        if self._cancel:
            raise _CancelledError()
        if d.get("status") == "started":
            pp = d.get("postprocessor", "")
            self.item_progress.emit(self._current, 100.0, "conversione", f"{pp}…")

    # --- ciclo principale ---

    def run(self) -> None:
        for idx, item in enumerate(self._items):
            if self._cancel:
                break
            self._current = idx
            self.item_started.emit(idx)
            self.log.emit(f"▶ {item.url}")
            try:
                ydl_opts = build_ydl_opts(self._opts, self._progress_hook, self._postproc_hook)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(item.url, download=True)
                title = self._extract_title(info)
                if isinstance(info, dict):
                    fp = _final_filepath(info)
                    if fp:
                        item.extra["filepath"] = fp
                self.item_finished.emit(idx, True, title)
                self.log.emit(f"✔ {title}")
            except _CancelledError:
                self.log.emit("✖ annullato")
                break
            except Exception as exc:  # noqa: BLE001 — vogliamo riportare qualsiasi errore in UI
                msg = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
                self.item_finished.emit(idx, False, msg)
                self.log.emit(f"✖ errore: {msg}")
        self.all_finished.emit()

    @staticmethod
    def _extract_title(info: Any) -> str:
        if not isinstance(info, dict):
            return "completato"
        if info.get("_type") == "playlist" or "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            n = len(entries)
            return f"playlist · {n} brani"
        return info.get("title") or "completato"


def _kill_ffmpeg_children() -> None:
    """Termina i processi ffmpeg/ffprobe figli del processo corrente.

    Serve a interrompere subito una conversione audio in corso quando l'utente
    preme Stop. Tocca solo i figli di questo processo: nessun rischio per altri
    ffmpeg sul sistema.
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001 — psutil opzionale
        return
    try:
        me = psutil.Process()
        for child in me.children(recursive=True):
            try:
                if child.name().lower().startswith(("ffmpeg", "ffprobe")):
                    child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:  # noqa: BLE001
        return


class _CancelledError(BaseException):
    """Sollevata dagli hook per interrompere yt-dlp su richiesta di annullamento.

    Eredita da BaseException (non Exception) di proposito: yt-dlp, in modalita'
    playlist con ignoreerrors=True, cattura le Exception per-elemento e prosegue.
    Ereditando da BaseException l'annullamento NON viene inghiottito e aborta
    immediatamente l'intera playlist.
    """


def make_thread(items: list[QueueItem], opts: DownloadOptions) -> tuple[QThread, DownloadWorker]:
    """Crea QThread + worker collegati. Il chiamante connette i segnali e fa thread.start()."""
    thread = QThread()
    worker = DownloadWorker(items, opts)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.all_finished.connect(thread.quit)
    return thread, worker


# ---------------- anteprima info (titolo/durata/thumbnail) ----------------

def format_duration(seconds: Any) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


class InfoSignals(QObject):
    # item, ok, title, duration_str, thumb_bytes
    done = Signal(object, bool, str, str, bytes)


class InfoTask:
    """QRunnable-like: recupera metadati leggeri di un URL senza scaricare."""

    def __init__(self, item: QueueItem, signals: InfoSignals):
        self.item = item
        self.signals = signals

    def run(self) -> None:
        import urllib.request
        try:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                    "noplaylist": True, "extract_flat": False}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.item.url, download=False, process=False)
            if not isinstance(info, dict):
                self.signals.done.emit(self.item, False, "", "", b"")
                return
            title = info.get("title") or ""
            dur = format_duration(info.get("duration"))
            thumb_url = info.get("thumbnail")
            if not thumb_url:
                thumbs = info.get("thumbnails") or []
                if thumbs:
                    thumb_url = thumbs[-1].get("url")
            data = b""
            if thumb_url:
                try:
                    req = urllib.request.Request(thumb_url, headers={"User-Agent": "Sonora"})
                    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310
                        data = r.read()
                except Exception:  # noqa: BLE001 — thumbnail opzionale
                    data = b""
            self.signals.done.emit(self.item, True, title, dur, data)
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(self.item, False, str(exc).splitlines()[0], "", b"")


def run_info_task(task: InfoTask) -> None:
    """Esegue InfoTask in un thread del pool globale."""
    from PySide6.QtCore import QRunnable, QThreadPool

    class _R(QRunnable):
        def run(_self) -> None:  # noqa: N805
            task.run()

    QThreadPool.globalInstance().start(_R())


# ---------------- ricerca video (ytsearch) ----------------

class SearchSignals(QObject):
    # query, ok, results(list[dict]), error
    done = Signal(str, bool, list, str)


class SearchTask:
    """Cerca video su YouTube tramite ytsearch di yt-dlp (nessuna API key)."""

    def __init__(self, query: str, signals: SearchSignals, limit: int = 12):
        self.query = query
        self.signals = signals
        self.limit = limit

    def run(self) -> None:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": True,
                "default_search": "ytsearch",
            }
            spec = f"ytsearch{self.limit}:{self.query}"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(spec, download=False)
            entries = (info or {}).get("entries") or []
            results: list[dict[str, Any]] = []
            for e in entries:
                if not isinstance(e, dict):
                    continue
                vid = e.get("id") or ""
                url = e.get("url") or (
                    f"https://www.youtube.com/watch?v={vid}" if vid else "")
                if not url:
                    continue
                if url.startswith("watch?") or not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={vid}"
                results.append({
                    "url": url,
                    "title": e.get("title") or url,
                    "duration": format_duration(e.get("duration")),
                    "uploader": e.get("uploader") or e.get("channel") or "",
                })
            self.signals.done.emit(self.query, True, results, "")
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(self.query, False, [], str(exc).splitlines()[0])


def run_search_task(task: SearchTask) -> None:
    """Esegue SearchTask in un thread del pool globale."""
    from PySide6.QtCore import QRunnable, QThreadPool

    class _R(QRunnable):
        def run(_self) -> None:  # noqa: N805
            task.run()

    QThreadPool.globalInstance().start(_R())
