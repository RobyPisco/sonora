"""PlayBar: barra player globale in basso (brano, play/pausa, seek, attività).

Visibile da qualsiasi schermata: controllo minimo del playback del mixer +
chip attività per i task lunghi (separazione stem, installazione motore,
download aggiornamento). Il trasporto completo resta nella pagina Mixer.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme


def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class PlayBar(QFrame):
    play_clicked = Signal()
    stop_clicked = Signal()
    seek_frac = Signal(float)      # 0..1
    task_cancel = Signal()
    task_state_changed = Signal(bool)   # True = un task lungo è in corso

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlayBar")
        self.setFixedHeight(72)
        self._duration = 0.0
        self._seeking = False
        self._task_active = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(14)

        # --- brano corrente ---
        art = QFrame()
        art.setObjectName("SongArt")
        art.setFixedSize(44, 44)
        al = QHBoxLayout(art)
        al.setContentsMargins(0, 0, 0, 0)
        art_ico = QLabel()
        art_ico.setPixmap(icons.pixmap("music", theme.COLORS["faint"], 18))
        art_ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        al.addWidget(art_ico)

        meta = QVBoxLayout()
        meta.setSpacing(1)
        self.title_lbl = QLabel("Nessun brano")
        self.title_lbl.setObjectName("PlayTitle")
        self.sub_lbl = QLabel("Carica degli stem nel Mixer")
        self.sub_lbl.setObjectName("PlaySub")
        meta.addWidget(self.title_lbl)
        meta.addWidget(self.sub_lbl)
        np_box = QHBoxLayout()
        np_box.setSpacing(10)
        np_box.addWidget(art)
        np_box.addLayout(meta)
        np_host = QWidget()
        np_host.setLayout(np_box)
        np_host.setMinimumWidth(170)
        np_host.setMaximumWidth(260)
        lay.addWidget(np_host, 0)

        # --- trasporto minimo ---
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayButton")
        self.play_btn.setFixedSize(46, 46)
        self.play_btn.setIconSize(QSize(19, 19))
        self.play_btn.setCheckable(True)   # checked = in riproduzione (icona pausa)
        self.play_btn.setIcon(icons.icon("play", "#ffffff", 19, on_name="pause"))
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("GhostMini")
        self.stop_btn.setFixedSize(32, 32)
        self.stop_btn.setIconSize(QSize(14, 14))
        self.stop_btn.setIcon(icons.icon("stop", theme.COLORS["muted"], 14))
        self.stop_btn.setToolTip("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        lay.addWidget(self.play_btn, 0)
        lay.addWidget(self.stop_btn, 0)

        # --- seek ---
        self.pos_lbl = QLabel("0:00")
        self.pos_lbl.setObjectName("TimeLabel")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setObjectName("SeekSlider")
        self.seek.setRange(0, 10000)
        self.seek.setEnabled(False)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._on_seek_released)
        self.dur_lbl = QLabel("0:00")
        self.dur_lbl.setObjectName("TimeLabel")
        lay.addWidget(self.pos_lbl, 0)
        lay.addWidget(self.seek, 1)
        lay.addWidget(self.dur_lbl, 0)

        # --- chip attività ---
        self.task_chip = QFrame()
        self.task_chip.setObjectName("TaskChip")
        tc = QHBoxLayout(self.task_chip)
        tc.setContentsMargins(12, 6, 8, 6)
        tc.setSpacing(8)
        self.task_lbl = QLabel("")
        self.task_bar = QProgressBar()
        self.task_bar.setRange(0, 100)
        self.task_bar.setTextVisible(False)
        self.task_bar.setFixedWidth(80)
        self.task_cancel_btn = QPushButton()
        self.task_cancel_btn.setObjectName("GhostMini")
        self.task_cancel_btn.setFixedSize(24, 24)
        self.task_cancel_btn.setIconSize(QSize(11, 11))
        self.task_cancel_btn.setIcon(icons.icon("x", theme.COLORS["muted"], 11))
        self.task_cancel_btn.setToolTip("Annulla operazione")
        self.task_cancel_btn.clicked.connect(self.task_cancel.emit)
        tc.addWidget(self.task_lbl)
        tc.addWidget(self.task_bar)
        tc.addWidget(self.task_cancel_btn)
        self.task_chip.hide()
        lay.addWidget(self.task_chip, 0)

    # ---------- API brano / playback ----------

    def set_song(self, title: str, subtitle: str) -> None:
        self.title_lbl.setText(title or "Nessun brano")
        self.sub_lbl.setText(subtitle or "")
        loaded = bool(title)
        self.play_btn.setEnabled(loaded)
        self.stop_btn.setEnabled(loaded)
        self.seek.setEnabled(loaded)

    def set_position(self, pos: float, duration: float) -> None:
        self._duration = duration
        self.pos_lbl.setText(_fmt_time(pos))
        self.dur_lbl.setText(_fmt_time(duration))
        if not self._seeking and duration > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int(pos / duration * 10000))
            self.seek.blockSignals(False)

    def set_playing(self, playing: bool) -> None:
        if self.play_btn.isChecked() != playing:
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(playing)
            self.play_btn.blockSignals(False)

    def _on_play_clicked(self) -> None:
        # lo stato "vero" arriva da set_playing() al prossimo tick del mixer
        self.play_clicked.emit()

    def _on_seek_released(self) -> None:
        self._seeking = False
        if self._duration > 0:
            self.seek_frac.emit(self.seek.value() / 10000.0)

    # ---------- API attività ----------

    @property
    def task_active(self) -> bool:
        """True mentre un'operazione lunga è in corso (chip attività visibile)."""
        return self._task_active

    def task_update(self, text: str, pct: float | None = None,
                    cancellable: bool = False) -> None:
        """Mostra/aggiorna il chip attività. pct=None → barra indeterminata."""
        if pct is None:
            self.task_lbl.setText(text)
            self.task_bar.setRange(0, 0)
        else:
            pct = max(0.0, min(100.0, pct))
            self.task_lbl.setText(f"{text} · {pct:.0f}%")
            self.task_bar.setRange(0, 100)
            self.task_bar.setValue(int(pct))
        self.task_cancel_btn.setVisible(cancellable)
        self.task_chip.show()
        if not self._task_active:
            self._task_active = True
            self.task_state_changed.emit(True)

    def task_done(self) -> None:
        self.task_chip.hide()
        if self._task_active:
            self._task_active = False
            self.task_state_changed.emit(False)
