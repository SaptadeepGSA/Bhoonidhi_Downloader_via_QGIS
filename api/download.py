"""Scene download via the shared BhoonidhiClient.query.download.

client.query.download() requires an authenticated client. This checks
session.has_valid_session() (purely in-memory -- true once this QGIS
session has logged in, never touches disk) before handing off to the SDK,
and returns needs_reauth=True instead of surfacing a raw auth error, so the
plugin can pop the same login dialog it uses on startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .client_state import get_client


@dataclass
class DownloadRunResult:
    ok: bool
    outcomes: list = None  # list[DownloadOutcome]
    error: str | None = None
    needs_reauth: bool = False


def download_scenes(
    slug: str,
    scenes: list[dict[str, Any]],
    out_dir: str,
    parallel: int = 4,
    force: bool = False,
    on_progress: Callable[[str, int, int | None], None] | None = None,
) -> DownloadRunResult:
    """Download a specific list of scene dicts (already filtered/checked by
    the caller) from a saved query. Mirrors `bhd query download --select`."""
    from bhoonidhi_downloader.core.search.availability import is_downloadable
    from bhoonidhi_downloader.sdk import BhoonidhiAuthError, BhoonidhiError

    from . import session as session_api

    if not scenes:
        return DownloadRunResult(ok=False, error="No scenes selected.")

    if not session_api.has_valid_session():
        return DownloadRunResult(ok=False, needs_reauth=True, error="Not authenticated.")

    if not any(is_downloadable(s) for s in scenes):
        return DownloadRunResult(
            ok=False, error="None of the selected scenes are open-access/downloadable."
        )

    scene_ids = [s.get("ID") for s in scenes if s.get("ID")]

    try:
        outcomes = get_client().query.download(
            slug,
            out_dir,
            select=scene_ids,
            parallel=parallel,
            force=force,
            on_progress=on_progress,
        )
    except BhoonidhiAuthError:
        return DownloadRunResult(ok=False, needs_reauth=True, error="Not authenticated.")
    except BhoonidhiError as exc:
        return DownloadRunResult(ok=False, error=str(exc))

    return DownloadRunResult(ok=True, outcomes=outcomes)
