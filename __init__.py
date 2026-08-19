"""Plugin package entry point.

QGIS on Windows normally runs without an attached console, so
sys.stdout/sys.stderr are swapped for a stub ("NullWriter") that supports
write() but not flush(). bhoonidhi_downloader uses `rich` internally for
its search progress spinner, and rich calls file.flush() unconditionally
-- which crashes with "'NullWriter' object has no attribute 'flush'" the
moment a search runs. Patch the streams once, at import time (before
anything else in the plugin touches the library), so flush() becomes a
harmless no-op instead of an AttributeError.
"""

import sys


class _FlushSafeStream:
    """Wraps a stream that's missing flush() (or is None) so libraries
    that assume standard stdout/stderr behavior don't crash on it."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        if self._stream is None:
            return len(data) if isinstance(data, str) else 0
        try:
            return self._stream.write(data)
        except Exception:
            return len(data) if isinstance(data, str) else 0

    def flush(self):
        flush = getattr(self._stream, "flush", None)
        if callable(flush):
            try:
                flush()
            # Best-effort flush shim: must not crash the caller.
            except Exception:  # nosec B110
                pass

    def isatty(self):
        isatty = getattr(self._stream, "isatty", None)
        try:
            return bool(isatty()) if callable(isatty) else False
        except Exception:
            return False

    def __getattr__(self, name):
        if self._stream is None:
            raise AttributeError(name)
        return getattr(self._stream, name)


def _patch_std_streams():
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream is None or not hasattr(stream, "flush"):
            setattr(sys, attr, _FlushSafeStream(stream))


_patch_std_streams()


def classFactory(iface):
    from .plugin import BhoonidhiPlugin

    return BhoonidhiPlugin(iface)
