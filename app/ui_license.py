"""Dialog di attivazione licenza Sonora.

Mostrato dal gate in app/main.py quando la prova è scaduta e non c'è una
licenza valida. L'utente incolla il codice cliente e attiva; il machineId è
mostrato e copiabile (utile per il supporto). L'attivazione (chiamata di rete)
gira in un QThread: la finestra resta reattiva.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from . import __version__, licensing, theme


class _ActivateWorker(QObject):
    """Esegue licensing.activate() fuori dal thread UI."""

    done = Signal(bool, str)

    def __init__(self, code: str):
        super().__init__()
        self._code = code

    def run(self) -> None:
        try:
            result = licensing.activate(self._code)
            self.done.emit(result.ok, result.message)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc).splitlines()[0] if str(exc) else "errore")


class LicenseDialog(QDialog):
    """Chiede il codice di attivazione. accept() = attivata, reject() = annulla."""

    def __init__(self, parent=None, *, trial_expired: bool = True):
        super().__init__(parent)
        self.setObjectName("Root")
        self.setWindowTitle("Attiva Sonora")
        self.setModal(True)
        self.resize(480, 340)
        self._thread: QThread | None = None
        self._worker: _ActivateWorker | None = None
        self._formatting = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)

        eyebrow = QLabel(f"SONORA · v{__version__}")
        eyebrow.setProperty("class", "Eyebrow")
        lay.addWidget(eyebrow)
        title = QLabel("Attiva Sonora")
        title.setObjectName("H1")
        lay.addWidget(title)

        if trial_expired:
            msg = ("Il periodo di prova è terminato. Inserisci il codice di "
                   "attivazione ricevuto per continuare a usare Sonora.")
        else:
            msg = ("Inserisci il codice di attivazione ricevuto per sbloccare "
                   "Sonora su questo computer.")
        sub = QLabel(msg)
        sub.setObjectName("Subtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self.code_edit.setStyleSheet(
            "font-family:'Cascadia Code','Consolas',monospace;"
            "font-size:16px; letter-spacing:2px;")
        self.code_edit.textChanged.connect(self._format_code)
        self.code_edit.returnPressed.connect(self._activate)
        lay.addWidget(self.code_edit)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("font-size:12px;")
        lay.addWidget(self.status_lbl)

        lay.addStretch(1)

        # machineId (per il supporto): riga piccola con pulsante Copia
        mid = licensing.machine_id()
        mid_row = QHBoxLayout()
        mid_lbl = QLabel(f"ID dispositivo: {mid}")
        mid_lbl.setProperty("class", "Hint")
        mid_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy_btn = QPushButton("Copia")
        copy_btn.setObjectName("GhostMini")
        copy_btn.setFixedWidth(56)
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(mid))
        mid_row.addWidget(mid_lbl, 1)
        mid_row.addWidget(copy_btn)
        lay.addLayout(mid_row)

        # pulsanti azione
        btns = QHBoxLayout()
        # a prova scaduta il dialog è bloccante (annullare = uscire dall'app);
        # se aperto durante la prova, annullare chiude solo la finestra.
        self.quit_btn = QPushButton("Esci" if trial_expired else "Chiudi")
        self.quit_btn.setObjectName("Ghost")
        self.quit_btn.clicked.connect(self.reject)
        self.activate_btn = QPushButton("Attiva")
        self.activate_btn.setObjectName("Primary")
        self.activate_btn.clicked.connect(self._activate)
        btns.addWidget(self.quit_btn)
        btns.addStretch(1)
        btns.addWidget(self.activate_btn)
        lay.addLayout(btns)

    def _format_code(self, text: str) -> None:
        """Auto-formatta il codice in gruppi di 4 (XXXX-XXXX-…), maiuscolo."""
        if self._formatting:
            return
        raw = "".join(ch for ch in text if ch.isalnum()).upper()[:16]
        pretty = "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))
        if pretty != text:
            self._formatting = True
            self.code_edit.setText(pretty)
            self.code_edit.setCursorPosition(len(pretty))
            self._formatting = False

    def _set_status(self, text: str, ok: bool) -> None:
        color = theme.COLORS["ok"] if ok else theme.COLORS["err"]
        self.status_lbl.setStyleSheet(f"font-size:12px; color:{color};")
        self.status_lbl.setText(text)

    def _activate(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        code = self.code_edit.text().strip()
        if not code:
            self._set_status("Inserisci un codice.", ok=False)
            return
        self.activate_btn.setEnabled(False)
        self.activate_btn.setText("Attivazione…")
        self.code_edit.setEnabled(False)
        self._set_status("Contatto il server…", ok=True)

        # rete su thread separato: la finestra non si congela
        self._thread = QThread(self)
        self._worker = _ActivateWorker(code)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_activated)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_activated(self, ok: bool, message: str) -> None:
        self.activate_btn.setEnabled(True)
        self.activate_btn.setText("Attiva")
        self.code_edit.setEnabled(True)
        if ok:
            self._set_status(message, ok=True)
            self.accept()
        else:
            self._set_status(message, ok=False)


def run_activation_gate(trial_expired: bool = True, parent=None) -> bool:
    """Mostra il dialog modale. True se l'app è stata attivata, False se annulla."""
    dlg = LicenseDialog(parent, trial_expired=trial_expired)
    return dlg.exec() == QDialog.DialogCode.Accepted
