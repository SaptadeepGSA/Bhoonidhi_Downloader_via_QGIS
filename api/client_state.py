"""Single BhoonidhiClient instance for this QGIS session, with in-memory-only
authentication: nothing about a login is ever written to disk.

BhoonidhiClient.login(..., save=False) keeps the session token only on this
one shared instance -- every api/ function reuses it via get_client() so a
login carries across searches/downloads for the rest of this QGIS session,
without ever touching ~/.bhoonidhi/session.

"Logged in" is tracked by our own flag, set only by a successful login()
through this plugin. The SDK's own is_authenticated would lazily read
~/.bhoonidhi/session, which would let a session created elsewhere (e.g. the
`bhd auth login` CLI in a terminal) silently authenticate the plugin.

reset_client() (called when the plugin loads -- to purge a session file left
by an older version of this plugin, which did persist one -- and again on
unload / QGIS close) drops the in-memory instance and deletes that file
directly by path, without importing bhoonidhi_downloader, so it works even
before the dependency is installed.
"""

from __future__ import annotations

_client = None
_logged_in = False


def get_client():
    global _client
    if _client is None:
        from bhoonidhi_downloader.sdk import BhoonidhiClient

        _client = BhoonidhiClient()
    return _client


def mark_logged_in() -> None:
    global _logged_in
    _logged_in = True


def is_logged_in() -> bool:
    return _client is not None and _logged_in


def reset_client() -> None:
    """Drop the in-memory session and delete any on-disk session file."""
    global _client, _logged_in
    _client = None
    _logged_in = False

    import os
    from pathlib import Path

    session_file = Path(os.path.expanduser("~")) / ".bhoonidhi" / "session"
    try:
        session_file.unlink(missing_ok=True)
    except OSError:
        pass
