"""Makes sure the `bhoonidhi-downloader` library is usable inside QGIS's Python,
installing it automatically (with pip) when it isn't.

Design notes -- each item below is a real failure mode seen on user machines
or found while reviewing the plugin on Windows / QGIS 3.44 and 4.2:

- "Installed" means the SDK really imports (`bhoonidhi_downloader.sdk`, which
  pulls in pydantic/requests/rich/typer) *and* its version is in the range
  this plugin was tested against. The package's own __init__ is empty, so
  importing just the top-level name would report success even when a
  dependency is missing or broken.
- The library needs Python >= 3.10. QGIS builds that bundle Python 3.9
  (e.g. Windows QGIS <= 3.28) can never install it; that is detected up
  front and explained instead of surfacing a confusing pip error.
- On Windows a running QGIS reports sys.executable as the QGIS binary itself
  (qgis-bin.exe) -- https://github.com/qgis/QGIS/issues/45646. Launching it
  with "-m pip" just opens another QGIS window. So the real interpreter is
  searched for (beside sys.executable, in the Python prefixes and QGIS's own
  bin/), every candidate is verified to be the same Python major.minor as
  the one running QGIS, and only executables whose name contains "python"
  are ever launched.
- If no interpreter can be found, pip runs in-process in a worker thread.
  pip is always told --only-binary=:all: so it never tries to build a source
  package: a build would spawn subprocesses using sys.executable and, in
  QGIS, that means more QGIS windows. sys.executable is also neutralised
  while pip runs in-process, as a second guard.
- Install goes to the per-user site-packages (--user): no admin rights and
  survives QGIS upgrades. Python only puts that folder on sys.path at
  startup if it already existed then, so it is added explicitly afterwards.
- pip failures are translated into a plain-language reason plus what to do
  (offline/proxy, locked file, PEP 668, missing pip, no wheel, ...). The
  check re-runs every time QGIS starts, so "fix it, restart QGIS" works.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import importlib.util
import io
import os
import re
import site
import sys
import time

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import QProcess, Qt, QThread
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QProgressDialog

DIST_NAME = "bhoonidhi-downloader"
IMPORT_NAME = "bhoonidhi_downloader"
# Tested range of the library (its SDK API is what the plugin is written against).
MIN_VERSION = (0, 5, 2)
MAX_VERSION_EXCLUSIVE = (0, 6, 0)
REQUIREMENT = f"{DIST_NAME}>=0.5.2,<0.6"
MIN_PYTHON = (3, 10)

_WINDOWS = os.name == "nt"
_RUNNING_VERSION = "%d.%d" % sys.version_info[:2]
_PIP_TIMEOUT_SECONDS = 15 * 60

# Tried in order until the dependency imports. The plain (no --user) attempt is
# for environments that forbid --user; --break-system-packages is only reached
# on distros whose system Python refuses pip (PEP 668) and is combined with
# --user so it can only ever write to the user's own folder.
_PIP_ATTEMPTS = (
    ["--user"],
    [],
    ["--user", "--break-system-packages"],
)

_installing = False


# ---------------------------------------------------------------------------
# Is the dependency usable right now?
# ---------------------------------------------------------------------------
def _add_user_site_to_path() -> None:
    """Make a freshly created per-user site-packages importable.

    Python only adds that folder at startup if it already existed. It must go
    *before* the interpreter's own site-packages (as Python itself orders them):
    appending it (what site.addsitedir does on its own) lets QGIS's bundled,
    older copies of shared packages such as pydantic_core shadow the newer ones
    pip just installed, which then fail to import together.
    """
    try:
        user_site = site.getusersitepackages()
    except (AttributeError, OSError):
        return
    if not user_site or not os.path.isdir(user_site) or user_site in sys.path:
        return
    system_index = len(sys.path)
    for index, entry in enumerate(sys.path):
        if os.path.basename(os.path.normpath(entry)) in ("site-packages", "dist-packages"):
            system_index = index
            break
    sys.path.insert(system_index, user_site)
    site.addsitedir(user_site)  # already on sys.path, so this only processes .pth files


def _parse_version(text: str) -> tuple[int, ...] | None:
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups(default="0"))


def _version_in_range(text: str | None) -> bool:
    if text is None:
        return True  # no metadata (e.g. a source checkout): trust the import
    parsed = _parse_version(text)
    if parsed is None:
        return True
    return MIN_VERSION <= parsed < MAX_VERSION_EXCLUSIVE


def check_dependency() -> tuple[str, str]:
    """(state, detail). state is one of:
    ok | missing | broken (present but won't import) | wrong_version."""
    _add_user_site_to_path()
    importlib.invalidate_caches()
    try:
        importlib.import_module(f"{IMPORT_NAME}.sdk")
    except Exception as exc:  # ImportError, or a clash raising something else
        if importlib.util.find_spec(IMPORT_NAME) is None:
            return "missing", ""
        return "broken", f"{type(exc).__name__}: {exc}"
    try:
        version = importlib.metadata.version(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        version = None
    if not _version_in_range(version):
        return "wrong_version", version or "unknown"
    return "ok", version or ""


def is_installed() -> bool:
    return check_dependency()[0] == "ok"


def is_installing() -> bool:
    return _installing


# ---------------------------------------------------------------------------
# Finding a real Python interpreter to run pip with
# ---------------------------------------------------------------------------
def _candidate_interpreters() -> list[str]:
    """Existing files that might be QGIS's Python interpreter, best first."""
    major, minor = sys.version_info[:2]
    if _WINDOWS:
        names = ("python.exe", "python3.exe")
    else:
        names = ("python3", f"python{major}.{minor}", "python")

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
        # Windows standalone/OSGeo4W: <root>/apps/qgis*/ beside <root>/bin/
        directories.append(os.path.normpath(os.path.join(qgis_prefix, "..", "..", "bin")))
        # macOS app bundle / Linux prefix: <prefix>/bin
        directories.append(os.path.join(qgis_prefix, "bin"))

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
    """True if `path` runs and is the same major.minor Python as QGIS's, so
    what it installs is importable here."""
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


# ---------------------------------------------------------------------------
# Running pip
# ---------------------------------------------------------------------------
def _pip_args(extra: list[str]) -> list[str]:
    return [
        "install",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--retries",
        "2",
        "--timeout",
        "15",
        *extra,
        REQUIREMENT,
    ]


def _run_pip_subprocess(python_exe: str, extra: list[str]) -> tuple[bool, str]:
    process = QProcess()
    process.setProgram(python_exe)
    process.setArguments(["-m", "pip", *_pip_args(extra)])
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
    deadline = time.monotonic() + _PIP_TIMEOUT_SECONDS
    while not state["done"]:
        process.waitForFinished(200)
        QApplication.processEvents()
        if time.monotonic() > deadline:
            process.kill()
            state["error"] = f"pip did not finish within {_PIP_TIMEOUT_SECONDS // 60} minutes"
            break

    output = bytes(process.readAllStandardOutput()).decode(errors="replace")
    if state["error"]:
        output += f"\n[process error] {state['error']}"
    return state["code"] == 0 and not state["error"], output


class _InProcessPipThread(QThread):
    """pip run from QGIS's own embedded Python, for machines where no separate
    interpreter could be located."""

    def __init__(self, extra: list[str], parent=None):
        super().__init__(parent)
        self._extra = extra
        self.code = -1
        self.output = ""

    def run(self):
        buffer = io.StringIO()
        try:
            from pip._internal.cli.main import main as pip_main

            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                self.code = int(pip_main(_pip_args(self._extra)) or 0)
        except (Exception, SystemExit) as exc:
            buffer.write(f"\n[in-process pip error] {exc!r}")
        self.output = buffer.getvalue()


def _run_pip_in_process(extra: list[str]) -> tuple[bool, str]:
    # If pip ever did spawn a subprocess from sys.executable it would launch
    # another QGIS. --only-binary already prevents builds; this makes any
    # remaining attempt fail fast instead of opening windows.
    original_executable = sys.executable
    if "python" not in os.path.basename(original_executable or "").lower():
        sys.executable = os.devnull
    thread = _InProcessPipThread(extra)
    try:
        thread.start()
        deadline = time.monotonic() + _PIP_TIMEOUT_SECONDS
        while not thread.isFinished():
            thread.wait(200)
            QApplication.processEvents()
            if time.monotonic() > deadline:
                return False, "pip did not finish within the time limit"
    finally:
        sys.executable = original_executable
    return thread.code == 0, thread.output


# ---------------------------------------------------------------------------
# Explaining failures
# ---------------------------------------------------------------------------
_NETWORK_MARKERS = (
    "connection", "getaddrinfo", "name resolution", "timed out", "max retries",
    "proxyerror", "ssl", "certificate", "temporary failure", "network is unreachable",
    "read timed out",
)
# Failures that trying different pip flags cannot fix -- stop retrying at once.
_NOT_FIXABLE_BY_FLAGS = _NETWORK_MARKERS + (
    "no module named pip", "requires a different python", "no space left", "errno 28",
)


def _retry_is_pointless(pip_log: str) -> bool:
    text = (pip_log or "").lower()
    return any(marker in text for marker in _NOT_FIXABLE_BY_FLAGS)


def explain_failure(pip_log: str, state: str, detail: str) -> tuple[str, str]:
    """(why it failed, what to do) in plain language."""
    text = (pip_log or "").lower()

    if state == "broken" and ("successfully installed" in text or "already satisfied" in text):
        return (
            f"The package is installed, but it can't be loaded in this QGIS session ({detail}).",
            "Restart QGIS -- this usually means another plugin already loaded a different "
            "version of a shared library (pydantic, requests, rich) in this session. "
            "If it still fails after a restart, tell the plugin author.",
        )
    if "externally-managed-environment" in text:
        return (
            "Your operating system manages this Python and refuses pip installs (PEP 668).",
            "Run the manual command below (it adds --break-system-packages, which only "
            "writes to your own user folder), or install pipx/venv tooling from your "
            "package manager.",
        )
    if "no module named pip" in text or "pip is not importable" in text:
        return (
            "pip isn't installed for QGIS's Python.",
            "Install it first: Linux -- 'sudo apt install python3-pip' (Debian/Ubuntu) or "
            "'sudo dnf install python3-pip' (Fedora); macOS/Windows -- run "
            "'python -m ensurepip --user' in a terminal / OSGeo4W Shell.",
        )
    if any(marker in text for marker in _NETWORK_MARKERS):
        return (
            "Couldn't reach the Python package index (pypi.org).",
            "Check your internet connection. Behind a proxy or firewall, set the HTTPS_PROXY "
            "environment variable (or configure pip) and restart QGIS; on networks that "
            "inspect HTTPS traffic, pip may need your organisation's certificate.",
        )
    if "winerror 5" in text or "access is denied" in text or "permission denied" in text \
            or "errno 13" in text:
        if ".pyd" in text or ".dll" in text or ".so" in text or "being used" in text:
            return (
                "A file the install needs to replace is locked by a program that is running "
                "(often another QGIS plugin, or a second QGIS window, has it loaded).",
                "Close other QGIS windows and restart QGIS -- the install is retried "
                "automatically on the next start, before other plugins load it.",
            )
        return (
            "No permission to write to the Python packages folder.",
            "Run the manual command below (it uses --user, which needs no administrator "
            "rights), then restart QGIS.",
        )
    if "requires a different python" in text or "requires-python" in text:
        return (
            f"This QGIS's Python ({sys.version.split()[0]}) is too old for the library.",
            "Upgrade QGIS to a build that bundles Python 3.10 or newer (QGIS 3.34+ on "
            "Windows and macOS).",
        )
    if "no matching distribution" in text or "no binary" in text or "only-binary" in text:
        return (
            "No ready-made (binary) package exists for this Python / operating-system "
            "combination, and the plugin deliberately never compiles code inside QGIS.",
            "Use an official QGIS build (64-bit, Python 3.10-3.13), or install the library "
            "yourself with the manual command below from a terminal that has a compiler.",
        )
    if "no space left" in text or "errno 28" in text:
        return ("The disk is full.", "Free some disk space and restart QGIS.")
    if state == "wrong_version":
        return (
            f"An incompatible version of the library is installed ({detail}).",
            f"Run the manual command below to install a supported version ({REQUIREMENT}).",
        )
    return (
        "pip failed for a reason this plugin doesn't recognise.",
        "Click 'Show Details' for the exact pip output and send it to the plugin author.",
    )


def _manual_command() -> str:
    python = "python" if _WINDOWS else "python3"
    return f'{python} -m pip install --user "{REQUIREMENT}"'


def _diagnostics(tried: list[str], pip_log: str, state: str, detail: str) -> str:
    return "\n".join(
        [
            f"QGIS: {Qgis.QGIS_VERSION}",
            f"python: {sys.version}",
            f"platform: {sys.platform}",
            f"sys.executable: {sys.executable!r}",
            f"sys.prefix: {sys.prefix!r}",
            f"QGIS prefix: {QgsApplication.prefixPath()!r}",
            f"dependency state: {state} {detail}",
            f"interpreters tried: {tried if tried else 'none found on disk'}",
            f"pip importable in-process: {importlib.util.find_spec('pip') is not None}",
            "",
            "--- pip output ---",
            (pip_log or "(none)")[-4000:],
        ]
    )


def _show_failure(parent, reason: str, advice: str, diagnostics: str) -> None:
    box = QMessageBox(
        QMessageBox.Icon.Warning,
        "Bhoonidhi Downloader -- setup needs your attention",
        f"Bhoonidhi Downloader couldn't finish setting up its dependency "
        f"('{DIST_NAME}').\n\nWhy: {reason}\n\nWhat to do: {advice}\n\n"
        "To install it manually, run this in a terminal (OSGeo4W Shell on Windows) "
        f"that uses QGIS's Python:\n\n    {_manual_command()}\n\n"
        "Then restart QGIS. The plugin checks again every time QGIS starts, so nothing "
        "else is needed.",
        QMessageBox.StandardButton.Ok,
        parent,
    )
    box.setDetailedText(diagnostics)
    box.exec()


def _notify_success(parent, version: str) -> None:
    text = f"'{DIST_NAME}' {version} is installed. Click the toolbar icon to start."
    try:
        from qgis.utils import iface

        if iface is not None:
            iface.messageBar().pushMessage(
                "Bhoonidhi Downloader", text, level=Qgis.MessageLevel.Success, duration=10
            )
            return
    # Purely cosmetic: fall back to a dialog if the message bar isn't available.
    except Exception:  # nosec B110
        pass
    QMessageBox.information(parent, "Bhoonidhi Downloader", text)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def ensure_installed(parent=None) -> bool:
    """Return True if the library is usable, installing it automatically if
    needed. Blocking, but keeps the QGIS UI responsive while pip runs."""
    global _installing

    state, detail = check_dependency()
    if state == "ok":
        return True
    if _installing:
        return False  # another call is already installing (re-entered via processEvents)

    if sys.version_info < MIN_PYTHON:
        _show_failure(
            parent,
            f"This QGIS bundles Python {sys.version.split()[0]}, but the "
            f"'{DIST_NAME}' library needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
            "Upgrade QGIS to a build that bundles Python 3.10+ (QGIS 3.34 or newer on "
            "Windows and macOS; on Linux use a distribution release with Python 3.10+).",
            _diagnostics([], "", state, detail),
        )
        return False

    _installing = True
    progress = None
    try:
        progress = QProgressDialog(
            "Bhoonidhi Downloader is installing the library it needs "
            f"('{DIST_NAME}', one-time, needs internet)...\nThis can take up to a minute.",
            None,
            0,
            0,
            parent,
        )
        progress.setWindowTitle("Bhoonidhi Downloader")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        python_exe, tried = resolve_python_executable()
        can_run_in_process = importlib.util.find_spec("pip") is not None

        pip_log = ""
        if python_exe is None and not can_run_in_process:
            pip_log = "No Python interpreter found and pip is not importable in-process."
        else:
            for extra in _PIP_ATTEMPTS:
                if python_exe is not None:
                    _ok, output = _run_pip_subprocess(python_exe, extra)
                else:
                    _ok, output = _run_pip_in_process(extra)
                pip_log += f"\n$ pip {' '.join(_pip_args(extra))}\n{output}"
                state, detail = check_dependency()
                if state == "ok" or _retry_is_pointless(output):
                    break
    finally:
        _installing = False
        if progress is not None:
            progress.close()

    if state == "ok":
        _notify_success(parent, detail)
        return True

    reason, advice = explain_failure(pip_log, state, detail)
    _show_failure(parent, reason, advice, _diagnostics(tried, pip_log, state, detail))
    return False
