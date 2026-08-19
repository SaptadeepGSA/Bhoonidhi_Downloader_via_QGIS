"""Login/logout for the plugin's single in-memory BhoonidhiClient (req #4).

No credentials or session token are ever persisted to disk -- every login
uses save=False, so the token lives only in the shared client instance
(client_state.py) for the lifetime of this QGIS session, and reset_client()
drops it entirely on unload / QGIS close. That means the user is asked to
log in again every fresh QGIS session, by design.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LoginResult:
    ok: bool
    username: str | None = None
    user_email: str | None = None
    error: str | None = None


def login(username: str, password: str) -> LoginResult:
    """Authenticate and hold the session in memory only (save=False)."""
    from .client_state import get_client

    if not username or not password:
        return LoginResult(ok=False, error="Username and password cannot be empty.")

    try:
        client = get_client()
        session = client.login(username, password, save=False)
        return LoginResult(ok=True, username=session.username, user_email=session.user_email)
    except Exception as exc:  # BhoonidhiError, requests errors, etc.
        return LoginResult(ok=False, error=str(exc))


def has_valid_session() -> bool:
    """True if this QGIS session already holds a logged-in client. Purely
    in-memory -- never reads ~/.bhoonidhi/session, so a stale file left
    over from another tool (or an older version of this plugin) can never
    silently authenticate the user."""
    from .client_state import is_logged_in

    return is_logged_in()


def logout() -> bool:
    from .client_state import reset_client

    reset_client()
    return True


def whoami() -> str | None:
    from .client_state import get_client, is_logged_in

    if not is_logged_in():
        return None
    account = get_client().account
    return account.username if account else None
