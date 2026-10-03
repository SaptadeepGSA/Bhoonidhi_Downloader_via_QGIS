"""Georeferenced scene quicklooks ("Quick View", req #3).

bhoonidhi_downloader's core/search/utils.py already builds the portal's
quicklook JPEG URL from a scene's DIRPATH/FILENAME/TABLETYPE
(get_quicklook_url) -- no auth needed, same as the CLI's own preview link.
What doesn't exist anywhere is georeferencing it: this fetches the JPEG and
assigns GDAL ground-control-points from the scene's own Crn* corner fields
(the same four corners the footprint layer already draws), then warps it
into a real GeoTIFF in EPSG:4326. The output is only ever handed to a
QgsRasterLayer for the map canvas -- nothing here opens a browser or an
external image viewer.
"""

from __future__ import annotations

import os
from typing import Any


def quicklook_url(scene: dict[str, Any]) -> str | None:
    from bhoonidhi_downloader.core.search.utils import get_quicklook_url

    try:
        return get_quicklook_url(scene)
    except (KeyError, TypeError):
        return None


def _corner_gcps(scene: dict[str, Any], width: int, height: int):
    """GCPs mapping the JPEG's 4 pixel corners to their real-world lon/lat.

    Corner fields are always NW/NE/SE/SW regardless of any along-track
    rotation, so pairing them with the image's actual (0,0)/(w,0)/(w,h)/(0,h)
    pixel corners is correct even for a skewed/rotated footprint -- a
    first-order polynomial warp over these 4 points reproduces it exactly.
    """
    from osgeo import gdal

    try:
        corners = [
            (float(scene["CrnNWLon"]), float(scene["CrnNWLat"]), 0, 0),
            (float(scene["CrnNELon"]), float(scene["CrnNELat"]), width, 0),
            (float(scene["CrnSELon"]), float(scene["CrnSELat"]), width, height),
            (float(scene["CrnSWLon"]), float(scene["CrnSWLat"]), 0, height),
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return [gdal.GCP(lon, lat, 0, px, py) for lon, lat, px, py in corners]


_HEADERS = {"User-Agent": "Mozilla/5.0 BhoonidhiQGIS"}
_MAX_RETRIES = 2  # extra attempts after the first one
_RETRY_WAIT_SECONDS = 2
_JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])


def _cache_dir(slug: str) -> str:
    """Per-query cache folder. Falls back to the user's home folder if the
    system temp folder is locked, full or blocked."""
    import tempfile

    bases = [tempfile.gettempdir(), os.path.join(os.path.expanduser("~"), ".bhoonidhi")]
    last_error: Exception | None = None
    for base in bases:
        path = os.path.join(base, "bhoonidhi_quicklooks", slug)
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write_test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return path
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"no writable folder for quicklooks ({last_error})")


def _download_with_requests(url: str) -> bytes:
    import requests

    response = requests.get(url, timeout=30, headers=_HEADERS)
    response.raise_for_status()
    return response.content


def _download_with_qgis(url: str) -> bytes:
    """Same download through QGIS's own network stack, which honours the
    proxy and certificate settings configured in QGIS."""
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest

    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"User-Agent", _HEADERS["User-Agent"].encode())
    blocking = QgsBlockingNetworkRequest()
    error = blocking.get(request)
    if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise RuntimeError(blocking.errorMessage() or f"QGIS network error {error}")
    return bytes(blocking.reply().content())


def _download_jpeg(url: str) -> bytes:
    """Download and check that the answer really is a JPEG (the portal can
    answer 200 with an HTML error page)."""
    errors = []
    for fetch in (_download_with_requests, _download_with_qgis):
        try:
            data = fetch(url)
        except Exception as exc:
            errors.append(f"{fetch.__name__.replace('_download_with_', '')}: {exc}")
            continue
        if data[:3] == _JPEG_MAGIC:
            return data
        errors.append(
            f"{fetch.__name__.replace('_download_with_', '')}: not a JPEG "
            f"({len(data)} bytes, portal returned something else)"
        )
    raise RuntimeError("download failed (" + " | ".join(errors) + f") from {url}")


def _cached_tif_ok(path: str) -> bool:
    """A cached GeoTIFF is only reused if it still opens cleanly."""
    if not os.path.exists(path):
        return False
    try:
        from osgeo import gdal

        gdal.UseExceptions()
        ds = gdal.Open(path)
        ok = ds is not None and ds.RasterXSize > 0
        ds = None
        if ok:
            return True
    except Exception:  # nosec B110
        pass
    try:
        os.remove(path)
    except OSError:
        pass
    return False


def _fetch_once(scene: dict[str, Any], cache_dir: str, scene_id: str, tif_path: str) -> str:
    from osgeo import gdal

    url = quicklook_url(scene)
    if not url:
        raise RuntimeError("scene has no quicklook location (DIRPATH/FILENAME missing)")

    data = _download_jpeg(url)
    jpeg_path = os.path.join(cache_dir, f"{scene_id}_raw.jpg")
    vrt_path = os.path.join(cache_dir, f"{scene_id}.vrt")
    part_path = os.path.join(cache_dir, f"{scene_id}.part.tif")
    src = None
    try:
        with open(jpeg_path, "wb") as f:
            f.write(data)
        gdal.UseExceptions()
        src = gdal.Open(jpeg_path)
        gcps = _corner_gcps(scene, src.RasterXSize, src.RasterYSize)
        if not gcps:
            raise ValueError("scene has no valid corner coordinates (Crn* fields)")
        gdal.Translate(vrt_path, src, format="VRT", GCPs=gcps, outputSRS="EPSG:4326")
        src = None
        gdal.Warp(part_path, vrt_path, dstSRS="EPSG:4326")
        os.replace(part_path, tif_path)  # never leave a half-written GeoTIFF behind
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        raise RuntimeError(f"georeferencing failed: {exc}") from exc
    finally:
        src = None  # release GDAL's handle so the temp files can be deleted
        for temp in (jpeg_path, vrt_path, part_path):
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except OSError:
                pass
    return tif_path


def fetch_and_georeference(scene: dict[str, Any], slug: str) -> str:
    """Download + georeference one scene's quicklook and return the GeoTIFF
    path. A failed attempt is retried up to _MAX_RETRIES more times. Raises
    RuntimeError with the exact reason if every attempt fails; missing
    corner data is not retried because it cannot succeed."""
    import time

    scene_id = str(scene.get("ID") or "unknown")
    cache_dir = _cache_dir(slug)
    tif_path = os.path.join(cache_dir, f"{scene_id}.tif")
    if _cached_tif_ok(tif_path):
        return tif_path

    last_error = "unknown error"
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return _fetch_once(scene, cache_dir, scene_id, tif_path)
        except RuntimeError as exc:
            last_error = str(exc)
            if "corner coordinates" in last_error or "no quicklook location" in last_error:
                break
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_WAIT_SECONDS)
    tries = f" (after {attempt + 1} attempt{'s' if attempt else ''})"
    raise RuntimeError(last_error + tries)
