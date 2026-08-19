"""Checks that bhoonidhi_downloader is importable in QGIS's own Python, and
offers to pip-install it in place if not."""

from __future__ import annotations

import importlib
import sys

from qgis.PyQt.QtCore import QProcess
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog

REQUIRED_PACKAGE = "bhoonidhi-downloader"
IMPORT_NAME = "bhoonidhi_downloader"


def is_installed() -> bool:
    try:
        importlib.import_module(IMPORT_NAME)
        return True
    except ImportError:
        return False


def ensure_installed(parent=None) -> bool:
    """Return True if bhoonidhi_downloader is importable, prompting to
    install it into QGIS's Python if it's missing. Blocking (modal)."""
    if is_installed():
        return True

    reply = QMessageBox.question(
        parent,
        "Bhoonidhi Downloader — dependency missing",
        f"The '{REQUIRED_PACKAGE}' package isn't installed in QGIS's Python "
        f"environment.\n\nInstall it now with:\n"
        f"  {sys.executable} -m pip install {REQUIRED_PACKAGE}\n\n"
        "Proceed?",
        QMessageBox.Yes | QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return False

    progress = QProgressDialog(
        f"Installing {REQUIRED_PACKAGE}...", None, 0, 0, parent
    )
    progress.setWindowTitle("Bhoonidhi Downloader")
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()

    process = QProcess(parent)
    process.setProgram(sys.executable)
    process.setArguments(["-m", "pip", "install", REQUIRED_PACKAGE])

    loop_result = {"finished": False, "code": -1}

    def _on_finished(code, _status):
        loop_result["finished"] = True
        loop_result["code"] = code

    process.finished.connect(_on_finished)
    process.start()
    process.waitForStarted()
    while not loop_result["finished"]:
        process.waitForFinished(200)
        from qgis.PyQt.QtWidgets import QApplication

        QApplication.processEvents()

    progress.close()

    stderr = bytes(process.readAllStandardError()).decode(errors="replace")
    stdout = bytes(process.readAllStandardOutput()).decode(errors="replace")

    importlib.invalidate_caches()
    if is_installed():
        QMessageBox.information(
            parent, "Bhoonidhi Downloader", f"'{REQUIRED_PACKAGE}' installed successfully."
        )
        return True

    QMessageBox.critical(
        parent,
        "Bhoonidhi Downloader — install failed",
        "pip install failed. Try running this manually in the OSGeo4W Shell "
        f"/ QGIS Python console:\n\n{sys.executable} -m pip install {REQUIRED_PACKAGE}\n\n"
        f"--- stdout ---\n{stdout[-1500:]}\n--- stderr ---\n{stderr[-1500:]}",
    )
    return False
