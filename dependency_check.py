"""Checks that bhoonidhi_downloader is importable in QGIS's own Python, and
offers to pip-install it in place if not.

Real-world gotchas this works around (found via user reports across several
machines, not just the dev box):

- On Windows, a running QGIS Desktop session can report sys.executable as
  the QGIS application binary itself (qgis-bin.exe) instead of the Python
  interpreter -- https://github.com/qgis/QGIS/issues/45646. Launching
  QProcess(sys.executable, [...]) then just opens a second QGIS. The real
  interpreter also lives in different places per install type (standalone
  bin/, OSGeo4W apps/PythonXX/, conda env root, macOS app bundle), so
  several locations are searched and each candidate is verified to be the
  same Python version as the one running QGIS before it is used.
- If no interpreter can be found at all, pip is run in-process (in a worker
  thread) from QGIS's own embedded Python instead of giving up.
- Program Files (or /Applications, or /opt) usually isn't writable without
  admin rights, so the install goes to the per-user site-packages
  (--user). Python only adds that folder to sys.path at startup if it
  already existed then, so it is added to sys.path explicitly afterwards --
  otherwise a first-ever install would look like it failed.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import os
import site
import sys

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QProcess, QThread
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QProgressDialog

REQUIRED_PACKAGE = "bhoonidhi-downloader"
IMPORT_NAME = "bhoonidhi_downloader"

_WINDOWS = os.name == "nt"
_RUNNING_VERSION = "%d.%d" % sys.version_info[:2]

# Tried in order until one works. A plain install (no flags) is last-but-one
# for environments where --user isn't allowed; --break-system-packages is
# only reached on distros whose system Python refuses pip (PEP 668) and only
# ever writes to the per-user folder combined with --user.
_PIP_ATTEMPTS = (
    ["--user"],
    [],
    ["--user", "--break-system-packages"],
)


def _add_user_site_to_path() -> None:
    try:
        user_site = site.getusersitepackages()
    except (AttributeError, OSError):
        return
    if user_site and os.path.isdir(user_site) and user_site not in sys.path:
        site.addsitedir(user_site)


def is_installed() -> bool:
    _add_user_site_to_path()
    importlib.invalidate_caches()
    try:
        importlib.import_module(IMPORT_NAME)
        return True
    except ImportError:
        return False


def _candidate_interpreters() -> list[str]:
    """Existing files that might be QGIS's Python interpreter, best first.
    Only executables whose name contains "python" are ever returned, so the
    QGIS application binary can never be launched by mistake."""
    names = ("python.exe", "python3.exe") if _WINDOWS else ("python3", "python")

    directories: list[str] = []
    executable = sys.executable or ""
    if executable:
        directories.append(os.path.dirname(executable))
    for prefix in (sys.exec_prefix, sys.prefix, sys.base_prefix):
        if prefix:
            directories.append(prefix)
            directories.append(os.path.join(prefix, "bin"))
    qgis_prefix = QgsApplication.prefixPath()
    if qgis_prefix:
        # Standalone/OSGeo4W layout: <root>/apps/qgis*/  next to  <root>/bin/
        directories.append(os.path.normpath(os.path.join(qgis_prefix, "..", "..", "bin")))

    candidates: list[str] = []
    if executable and "python" in os.path.basename(executable).lower():
        candidates.append(executable)
    for directory in directories:
        for name in names:
            candidates.append(os.path.join(directory, name))

    unique: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        key = os.path.normcase(os.path.normpath(path))
        if key not in seen and os.path.isfile(path):
            seen.add(key)
            unique.append(path)
    return unique


def _matches_running_python(path: str) -> bool:
    """True if `path` is a working interpreter of the same major.minor
    version as the Python running QGIS (so packages installed by it are
    importable here)."""
    process = QProcess()
    process.setProgram(path)
    process.setArguments(["-c", "import sys; print('%d.%d' % sys.version_info[:2])"])
    process.start()
    if not process.waitForStarted(5000):
        return False
    if not process.waitForFinished(10000):
        process.kill()
        return False
    if process.exitCode() != 0:
        return False
    output = bytes(process.readAllStandardOutput()).decode(errors="replace").strip()
    return output == _RUNNING_VERSION


def resolve_python_executable() -> tuple[str | None, list[str]]:
    """(verified interpreter path or None, every candidate that was tried)."""
    tried: list[str] = []
    for candidate in _candidate_interpreters():
        tried.append(candidate)
        if _matches_running_python(candidate):
            return candidate, tried
    return None, tried


def _run_pip_subprocess(python_exe: str, pip_args: list[str]) -> tuple[bool, str]:
    process = QProcess()
    process.setProgram(python_exe)
    process.setArguments(["-m", "pip", "install", "--disable-pip-version-check", *pip_args])
    process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

    state = {"done": False, "code": -1, "error": ""}

    def _on_finished(code, _status):
        state["done"] = True
        state["code"] = code

    def _on_error(_error):
        # Only terminal failures (e.g. failed to start) end the wait; a
        # crash/read error while still running is followed by `finished`.
        if process.state() == QProcess.ProcessState.NotRunning:
            state["done"] = True
            state["error"] = process.errorString()

    process.finished.connect(_on_finished)
    process.errorOccurred.connect(_on_error)
    process.start()
    while not state["done"]:
        process.waitForFinished(200)
        QApplication.processEvents()

    output = bytes(process.readAllStandardOutput()).decode(errors="replace")
    if state["error"]:
        output += f"\n[process error] {state['error']}"
    return state["code"] == 0, output


class _InProcessPipThread(QThread):
    """Runs pip from QGIS's own embedded Python, for machines where no
    separate interpreter could be located."""

    def __init__(self, pip_args: list[str], parent=None):
        super().__init__(parent)
        self._pip_args = pip_args
        self.code = -1
        self.output = ""

    def run(self):
        buffer = io.StringIO()
        try:
            from pip._internal.cli.main import main as pip_main

            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                self.code = int(
                    pip_main(["install", "--disable-pip-version-check", *self._pip_args]) or 0
                )
        except (Exception, SystemExit) as exc:
            buffer.write(f"\n[in-process pip error] {exc!r}")
        self.output = buffer.getvalue()


def _run_pip_in_process(pip_args: list[str]) -> tuple[bool, str]:
    thread = _InProcessPipThread(pip_args)
    thread.start()
    while not thread.isFinished():
        thread.wait(200)
        QApplication.processEvents()
    return thread.code == 0, thread.output


def _diagnostics(tried: list[str], pip_log: str) -> str:
    return "\n".join(
        [
            f"sys.executable: {sys.executable!r}",
            f"sys.prefix: {sys.prefix!r}",
            f"python: {sys.version}",
            f"platform: {sys.platform}",
            f"QGIS prefix: {QgsApplication.prefixPath()!r}",
            f"interpreters tried: {tried if tried else 'none found on disk'}",
            f"pip module importable in-process: {importlib.util.find_spec('pip') is not None}",
            "",
            "--- pip output ---",
            pip_log[-3000:] or "(none)",
        ]
    )


def _show_failure(parent, tried: list[str], pip_log: str) -> None:
    box = QMessageBox(
        QMessageBox.Icon.Critical,
        "Bhoonidhi Downloader — dependency install failed",
        f"The '{REQUIRED_PACKAGE}' package couldn't be installed automatically.\n\n"
        "Please install it manually: open the OSGeo4W Shell (Windows) or a "
        "terminal that uses QGIS's Python, then run:\n\n"
        f"  python -m pip install --user {REQUIRED_PACKAGE}\n\n"
        "Then restart QGIS. If it still fails, click 'Show Details' and send "
        "the text to the plugin author.",
        QMessageBox.StandardButton.Ok,
        parent,
    )
    box.setDetailedText(_diagnostics(tried, pip_log))
    box.exec()


def ensure_installed(parent=None) -> bool:
    """Return True if bhoonidhi_downloader is importable, prompting to
    install it into QGIS's Python if it's missing. Blocking (modal)."""
    if is_installed():
        return True

    reply = QMessageBox.question(
        parent,
        "Bhoonidhi Downloader — dependency missing",
        f"The '{REQUIRED_PACKAGE}' package isn't installed in QGIS's Python "
        "environment yet.\n\nInstall it now with pip (into your user Python "
        "packages folder -- no administrator rights needed)?\n\n"
        "This is a one-time download (a few MB, needs an internet connection) "
        "and can take anywhere from a few seconds to a minute or so.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        return False

    progress = QProgressDialog(
        f"Downloading and installing {REQUIRED_PACKAGE} from PyPI "
        "(one-time, may take a minute)...",
        None,
        0,
        0,
        parent,
    )
    progress.setWindowTitle("Bhoonidhi Downloader")
    progress.setMinimumDuration(0)
    progress.show()
    QApplication.processEvents()

    python_exe, tried = resolve_python_executable()
    can_run_in_process = importlib.util.find_spec("pip") is not None

    pip_log = ""
    if python_exe is None and not can_run_in_process:
        pip_log = "No Python interpreter found and pip is not importable in-process."
    else:
        for extra_args in _PIP_ATTEMPTS:
            args = [*extra_args, REQUIRED_PACKAGE]
            if python_exe is not None:
                _ok, output = _run_pip_subprocess(python_exe, args)
            else:
                _ok, output = _run_pip_in_process(args)
            pip_log += f"\n$ pip install {' '.join(args)}\n{output}"
            if is_installed():
                break

    progress.close()

    if is_installed():
        QMessageBox.information(
            parent, "Bhoonidhi Downloader", f"'{REQUIRED_PACKAGE}' installed successfully."
        )
        return True

    _show_failure(parent, tried, pip_log)
    return False
