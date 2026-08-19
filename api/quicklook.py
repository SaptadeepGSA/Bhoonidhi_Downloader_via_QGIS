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


def _cache_dir(slug: str) -> str:
    import tempfile

    path = os.path.join(tempfile.gettempdir(), "bhoonidhi_quicklooks", slug)
    os.makedirs(path, exist_ok=True)
    return path


def fetch_and_georeference(scene: dict[str, Any], slug: str) -> str | None:
    """Download + georeference one scene's quicklook. Returns the output
    GeoTIFF path, or None on any failure (network, missing corners, bad
    image) -- the caller surfaces that as a status message, not a crash."""
    import requests
    from osgeo import gdal

    scene_id = str(scene.get("ID") or "unknown")
    cache_dir = _cache_dir(slug)
    tif_path = os.path.join(cache_dir, f"{scene_id}.tif")
    if os.path.exists(tif_path):
        return tif_path

    url = quicklook_url(scene)
    if not url:
        return None

    jpeg_path = os.path.join(cache_dir, f"{scene_id}_raw.jpg")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(jpeg_path, "wb") as f:
            f.write(response.content)
    except Exception:
        return None

    try:
        gdal.UseExceptions()
        src = gdal.Open(jpeg_path)
        if src is None:
            return None
        gcps = _corner_gcps(scene, src.RasterXSize, src.RasterYSize)
        if not gcps:
            return None

        vrt_path = os.path.join(cache_dir, f"{scene_id}.vrt")
        gdal.Translate(
            vrt_path, src, format="VRT", GCPs=gcps, outputSRS="EPSG:4326"
        )
        src = None
        gdal.Warp(tif_path, vrt_path, dstSRS="EPSG:4326")
    except Exception:
        return None
    finally:
        for temp in (jpeg_path, os.path.join(cache_dir, f"{scene_id}.vrt")):
            try:
                if os.path.exists(temp):
                    os.remove(temp)
            except OSError:
                pass

    return tif_path if os.path.exists(tif_path) else None
