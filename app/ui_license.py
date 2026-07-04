"""Dialog di attivazione licenza Sonora.

Mostrato dal gate in app/main.py quando la prova è scaduta e non c'è una
licenza valida. L'utente incolla il codice cliente e attiva; il machineId è
mostrato e copiabile (utile per il supporto).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from . import __version__, licensing


class LicenseDialog(QDialog):
    """Chiede il codice di attivazione. accept() = attivata, reject() = annulla."""

    def __init__(self, parent=None, *, trial_expired: bool = True):
        super().__init__(parent)
        self.setObjectName("Root")
        self.setWindowTitle("Attiva Sonora")
        self.setModal(True)
        self.resize(460, 320)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel("Attiva Sonora")
        title.setObjectName("Title")
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
        mid_lbl.setStyleSheet("color:#6b7080; font-size:11px;")
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
        self.quit_btn = QPushButton("Esci")
        self.quit_btn.setObjectName("Ghost")
        self.quit_btn.clicked.connect(self.reject)
        self.activate_btn = QPushButton("Attiva")
        self.activate_btn.setObjectName("Primary")
        self.activate_btn.clicked.connect(self._activate)
        btns.addWidget(self.quit_btn)
        btns.addStretch(1)
        btns.addWidget(self.activate_btn)
        lay.addLayout(btns)

    def _set_status(self, text: str, ok: bool) -> None:
        color = "#3fb950" if ok else "#f0616d"
        self.status_lbl.setStyleSheet(f"font-size:12px; color:{color};")
        self.status_lbl.setText(text)

    def _activate(self) -> None:
        code = self.code_edit.text().strip()
        if not code:
            self._set_status("Inserisci un codice.", ok=False)
            return
        self.activate_btn.setEnabled(False)
        self.activate_btn.setText("Attivazione…")
        self._set_status("Contatto il server…", ok=True)
        QGuiApplication.processEvents()

        result = licensing.activate(code)

        self.activate_btn.setEnabled(True)
        self.activate_btn.setText("Attiva")
        if result.ok:
            self._set_status(result.message, ok=True)
            self.accept()
        else:
            self._set_status(result.message, ok=False)


def run_activation_gate(trial_expired: bool = True) -> bool:
    """Mostra il dialog modale. True se l'app è stata attivata, False se annulla."""
    dlg = LicenseDialog(trial_expired=trial_expired)
    return dlg.exec() == QDialog.DialogCode.Accepted
