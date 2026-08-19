"""Search + saved-query ("slug") management via BhoonidhiClient.query.*.

Every function here maps 1:1 to the equivalent CLI command, which is what
lets the plugin's session-query-manager panel offer the same operations
(show/refresh/rename/fork/delete) the GitHub page documents (req #7). All
of it goes through the single shared client from client_state.py so a
login (in-memory only, never persisted) carries across these calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .client_state import get_client


@dataclass
class SearchResult:
    ok: bool
    query: Any = None  # QuerySchema
    error: str | None = None
    scene_count: int = 0


def search_and_save(
    minx: float,
    maxx: float,
    miny: float,
    maxy: float,
    start_date: datetime,
    end_date: datetime,
    satellite: str,
    sensor: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> SearchResult:
    """Run a search and save it as a new query. Mirrors `bhd query create`."""
    from bhoonidhi_downloader.sdk import BhoonidhiError

    try:
        query = get_client().query.create(
            start_date=start_date,
            end_date=end_date,
            satellite=satellite,
            sensor=sensor,
            minx=minx,
            maxx=maxx,
            miny=miny,
            maxy=maxy,
            name=name,
            description=description,
        )
    except BhoonidhiError as exc:
        return SearchResult(ok=False, error=str(exc))
    except Exception as exc:
        return SearchResult(ok=False, error=str(exc))

    if query is None:
        return SearchResult(ok=False, error="No scenes found for these parameters.")

    return SearchResult(ok=True, query=query, scene_count=len(query.scenes))


def list_queries():
    return get_client().query.list()


def load_query(slug: str):
    """Returns the QuerySchema, or None if the slug is unknown."""
    from bhoonidhi_downloader.sdk import BhoonidhiNotFoundError

    try:
        return get_client().query.show(slug)
    except BhoonidhiNotFoundError:
        return None


def delete_query(slug: str) -> bool:
    """Returns True if the slug existed and was deleted, False otherwise."""
    from bhoonidhi_downloader.sdk import BhoonidhiNotFoundError

    try:
        get_client().query.rm(slug)
        return True
    except BhoonidhiNotFoundError:
        return False


def rename_query(slug: str, name: str | None = None, description: str | None = None) -> bool:
    from bhoonidhi_downloader.sdk import BhoonidhiNotFoundError

    try:
        get_client().query.rename(slug, name=name, description=description)
        return True
    except BhoonidhiNotFoundError:
        return False


def fork_query(slug: str, name: str | None = None):
    """Clone a saved query under a new slug. Returns the new QuerySchema, or None."""
    from bhoonidhi_downloader.sdk import BhoonidhiNotFoundError

    try:
        return get_client().query.fork(slug, name=name)
    except BhoonidhiNotFoundError:
        return None


@dataclass
class RefreshResult:
    ok: bool
    query: Any = None
    added: int = 0
    error: str | None = None


def refresh_query(slug: str) -> RefreshResult:
    """Re-query the portal for scenes newer than the query's stored end_date."""
    from bhoonidhi_downloader.sdk import BhoonidhiError

    try:
        query, added = get_client().query.refresh(slug)
    except BhoonidhiError as exc:
        return RefreshResult(ok=False, error=str(exc))

    return RefreshResult(ok=True, query=query, added=added or 0)
