"""Satellite/sensor listing, restricted to direct-download-only archive records.

Uses BhoonidhiClient().archive.list() (SDK), which returns the raw archive
records unchanged from the portal (satName, priced, sensors[senName], ...).
The plugin only ever wants "OpenData_DirectDownload" satellites (req #2).

archive_records() is the one function that actually hits the network/cache
(refresh=True bypasses the on-disk ~/.bhoonidhi/archive.json cache, which
can otherwise go stale for months). Callers fetch the records once per
"session" (dock-widget open, or an explicit Refresh click) and pass them
into the *_from() filters below, rather than each dropdown re-fetching --
that was the actual bug behind "sensors are incomplete": the dropdowns
were silently reading a stale cache, not a filtering error.
"""

from __future__ import annotations

DIRECT_DOWNLOAD = "OpenData_DirectDownload"


def archive_records(refresh: bool = False) -> list[dict]:
    from .client_state import get_client

    return get_client().archive.list(refresh=refresh)


def direct_download_satellites_from(records: list[dict]) -> list[str]:
    """Satellite names whose archive record is priced == OpenData_DirectDownload."""
    return sorted(
        {
            record.get("satName")
            for record in records
            if record.get("priced") == DIRECT_DOWNLOAD and record.get("satName")
        }
    )


def sensors_for_satellite_from(records: list[dict], satellite: str) -> list[str]:
    """Sensor names available for a given (direct-download) satellite."""
    sensors: set[str] = set()
    for record in records:
        if record.get("satName") != satellite:
            continue
        if record.get("priced") != DIRECT_DOWNLOAD:
            continue
        for sensor in record.get("sensors", []):
            sen_name = sensor.get("senName")
            if sen_name:
                sensors.add(sen_name)
    return sorted(sensors)


def direct_download_satellites(refresh: bool = False) -> list[str]:
    """Convenience one-shot: fetch + filter in one call."""
    return direct_download_satellites_from(archive_records(refresh=refresh))


def sensors_for_satellite(satellite: str, refresh: bool = False) -> list[str]:
    """Convenience one-shot: fetch + filter in one call."""
    return sensors_for_satellite_from(archive_records(refresh=refresh), satellite)
