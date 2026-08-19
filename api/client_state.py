"""Single BhoonidhiClient instance for this QGIS session, with in-memory-only
authentication: nothing about a login is ever written to disk.

BhoonidhiClient.login(..., save=False) keeps the session token only on this
one shared instance -- every api/ function reuses it via get_client() so a
login carries across searches/downloads for the rest of this QGIS session,
without ever touching ~/.bhoonidhi/session. reset_client() (called both when
the plugin loads, to purge any pre-existing file from an older version of
this plugin or another tool like the bhd CLI, and again on unload/QGIS
close) drops the in-memory instance and deletes that file directly by path
-- without importing bhoonidhi_downloader, so the purge works even before
the dependency is installed.
"""

from __future__ import annotations

_client = None


def get_client():
    global _client
    if _client is None:
        from bhoonidhi_downloader.sdk import BhoonidhiClient

        _client = BhoonidhiClient()
    return _client


def is_logged_in() -> bool:
    return _client is not None and _client.is_authenticated


def reset_client() -> None:
    """Drop the in-memory session and delete any on-disk session file."""
    global _client
    _client = None

    import os
    from pathlib import Path

    session_file = Path(os.path.expanduser("~")) / ".bhoonidhi" / "session"
    try:
        session_file.unlink(missing_ok=True)
    except OSError:
        pass
