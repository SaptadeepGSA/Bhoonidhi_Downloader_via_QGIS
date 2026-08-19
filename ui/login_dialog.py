"""Startup login dialog (req #1): asks for Bhoonidhi username/password and
authenticates via api.session.login()."""

from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..api import session as session_api


class LoginDialog(QDialog):
    def __init__(self, parent=None, message: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Bhoonidhi Downloader — Login")
        self.setModal(True)
        self._username: str | None = None

        layout = QVBoxLayout(self)

        if message:
            info = QLabel(message)
            info.setWordWrap(True)
            layout.addWidget(info)

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #b00020;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._buttons = buttons

        self.username_edit.setFocus()

    def _on_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        self.status_label.setText("Authenticating...")
        self._buttons.setEnabled(False)
        QApplication.processEvents()

        result = session_api.login(username, password)

        self._buttons.setEnabled(True)
        if result.ok:
            self._username = result.username
            self.accept()
        else:
            self.status_label.setText(result.error or "Login failed.")

    @property
    def username(self) -> str | None:
        return self._username

    @staticmethod
    def ensure_logged_in(parent=None) -> bool:
        """Show the login dialog if there's no valid saved session. Returns
        True once a valid session exists (freshly logged in or already
        present), False if the user cancelled."""
        if session_api.has_valid_session():
            return True
        dialog = LoginDialog(
            parent,
            message="Log in with your Bhoonidhi portal credentials to continue.",
        )
        return dialog.exec_() == QDialog.Accepted
