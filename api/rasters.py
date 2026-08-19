"""Scene footprint math + locating raster files inside a downloaded scene.

None of this exists in bhoonidhi_downloader itself -- the library only
downloads the raw scene archive. Scenes are delivered as a .zip (or .h5 for
NISAR SSAR) containing the actual raster product; the internal layout
varies by satellite/sensor, so rather than hard-code per-product paths this
just extracts the archive and lists whatever georeferenced raster file(s)
it finds inside.

No clip/mosaic step lives here (removed by request): a scene's zip can
contain several single-band product tifs (e.g. separate per-band files),
and both clipping and mosaicking need to know which of those belong
together and in what band order -- something this plugin can't infer
generically across satellites/sensors without risking a wrong/misleading
merge. Individual, unmodified downloads only.
"""

from __future__ import annotations

import glob
import os
import zipfile
from typing import Any

RASTER_EXTS = (".tif", ".tiff", ".img", ".h5", ".dat", ".jp2")


def scene_bbox(scene: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """(minx, miny, maxx, maxy) footprint of a scene from its Crn* corners."""
    try:
        lons = [
            float(scene[k]) for k in ("CrnNWLon", "CrnNELon", "CrnSELon", "CrnSWLon")
        ]
        lats = [
            float(scene[k]) for k in ("CrnNWLat", "CrnNELat", "CrnSELat", "CrnSWLat")
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _extract_if_archive(path: str) -> str:
    """Extract a .zip download next to itself; return the extraction dir
    (or the original file's directory if it isn't a zip)."""
    if not path.lower().endswith(".zip"):
        return os.path.dirname(path)
    extract_dir = path[: -len(".zip")] + "_extracted"
    if not os.path.isdir(extract_dir):
        with zipfile.ZipFile(path) as zf:
            zf.extractall(extract_dir)
    return extract_dir


def find_rasters(path: str) -> list[str]:
    """Rasters found for a downloaded scene: the file itself if it's
    already a raster, or every candidate raster inside its extracted zip."""
    if not path.lower().endswith(".zip"):
        return [path] if path.lower().endswith(RASTER_EXTS) else []
    extract_dir = _extract_if_archive(path)
    found = []
    for ext in RASTER_EXTS:
        found.extend(glob.glob(os.path.join(extract_dir, "**", f"*{ext}"), recursive=True))
    return sorted(found)
