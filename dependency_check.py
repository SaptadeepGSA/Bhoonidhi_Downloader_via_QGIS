"""Checks that bhoonidhi_downloader is importable in QGIS's own Python, and
offers to pip-install it in place if not.

Two real-world gotchas this works around (found via user reports across
several machines, not just this dev box):

- On Windows, a running QGIS Desktop session can report sys.executable as
  the QGIS application binary itself (qgis-bin.exe / qgis-ltr-bin.exe)
  instead of the actual Python interpreter -- see
  https://github.com/qgis/QGIS/issues/45646. Blindly launching
  QProcess(sys.executable, [...]) in that case just opens a second QGIS
  instance instead of running pip, which then loads this plugin again and
  re-triggers the same dependency prompt -- an apparent install loop.
  _resolve_python_executable() detects this and looks for the real
  interpreter (python.exe) sitting alongside it.
- Program Files (or /Applications, or /opt) typically isn't writable
  without admin/sudo rights, so a plain `pip install` fails for any
  non-admin user. `--user` installs into the per-user site-packages
  instead, which needs no elevated rights and is QGIS's own documented
  recommendation for plugin dependencies.
"""

from __future__ import annotations

import importlib
import os
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


def _resolve_python_executable() -> str | None:
    """Return a real Python interpreter path to run pip with, or None if
    none could be found. Never trusts sys.executable blindly -- see the
    module docstring."""
    candidate = sys.executable
    basename = os.path.basename(candidate).lower()

    if "python" in basename:
        return candidate

    # sys.executable is the QGIS application itself (a known Windows
    # behavior): the real interpreter is typically a sibling python.exe
    # in the same directory (QGIS's standalone installer layout puts
    # qgis-bin.exe / qgis-ltr-bin.exe and python.exe side by side in bin/).
    directory = os.path.dirname(candidate)
    for name in ("python.exe", "python3.exe", "pythonw.exe"):
        sibling = os.path.join(directory, name)
        if os.path.isfile(sibling):
            return sibling

    return None


def ensure_installed(parent=None) -> bool:
    """Return True if bhoonidhi_downloader is importable, prompting to
    install it into QGIS's Python if it's missing. Blocking (modal)."""
    if is_installed():
        return True

    python_exe = _resolve_python_executable()
    if python_exe is None:
        QMessageBox.critical(
            parent,
            "Bhoonidhi Downloader — dependency missing",
            f"The '{REQUIRED_PACKAGE}' package isn't installed, and this plugin "
            "couldn't automatically locate QGIS's Python interpreter to install "
            "it for you.\n\nPlease install it manually: open the OSGeo4W Shell "
            "(Windows) or a terminal with QGIS's Python on PATH, then run:\n\n"
            f"  python -m pip install --user {REQUIRED_PACKAGE}\n\n"
            "Then restart QGIS.",
        )
        return False

    reply = QMessageBox.question(
        parent,
        "Bhoonidhi Downloader — dependency missing",
        f"The '{REQUIRED_PACKAGE}' package isn't installed in QGIS's Python "
        f"environment.\n\nInstall it now with:\n"
        f"  {python_exe} -m pip install --user {REQUIRED_PACKAGE}\n\n"
        "This is a one-time download (a few MB, needs an internet connection) "
        "-- it won't be needed again on this machine, and doesn't require "
        "administrator rights. Depending on your connection it can take "
        "anywhere from a few seconds to a minute or so.\n\n"
        "Proceed?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return False

    ok, stdout, stderr = _run_pip_install(python_exe, ["--user", REQUIRED_PACKAGE], parent)

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
        f"/ a terminal with QGIS's Python on PATH:\n\n"
        f"{python_exe} -m pip install --user {REQUIRED_PACKAGE}\n\n"
        f"--- stdout ---\n{stdout[-1500:]}\n--- stderr ---\n{stderr[-1500:]}",
    )
    return False


def _run_pip_install(python_exe: str, pip_args: list[str], parent) -> tuple[bool, str, str]:
    """Run `python_exe -m pip install <pip_args>`, showing progress, and
    return (success, stdout, stderr)."""
    progress = QProgressDialog(
        f"Downloading and installing {REQUIRED_PACKAGE} from PyPI "
        "(one-time, may take a minute)...",
        None,
        0,
        0,
        parent,
    )
    progress.setWindowTitle("Bhoonidhi Downloader")
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()

    process = QProcess(parent)
    process.setProgram(python_exe)
    process.setArguments(["-m", "pip", "install", *pip_args])

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
    return loop_result["code"] == 0, stdout, stderr
