# Bhoonidhi Downloader — QGIS Plugin

A QGIS front-end for [bhoonidhi-downloader](https://github.com/geovicco-dev/bhoonidhi-downloader) (MIT license), letting you search, preview, and download open-access satellite imagery from ISRO's [Bhoonidhi](https://bhoonidhi.nrsc.gov.in) portal without leaving QGIS.

## Features

- Login with your Bhoonidhi portal credentials — kept in memory only for the current QGIS session, never written to disk, and discarded when QGIS closes.
- Satellite/sensor pickers restricted to direct-download (open-access) products, refreshed live from the portal's archive on each session.
- Date range and spatial filter (manual bounding box or draw-on-map) driven search.
- Results table with pagination, select-all, and per-scene availability status.
- Georeferenced quicklook previews rendered directly on the QGIS map canvas.
- Session-scoped saved "queries" (slugs) you can revisit, rename, fork, or refresh within the same QGIS session — automatically deleted when QGIS closes.
- Straightforward per-scene download to a folder of your choice.

## Requirements

- **QGIS 3.34 or newer, including QGIS 4.x** (Qt5 and Qt6 builds). The `bhoonidhi-downloader` library needs Python 3.10+, which is what QGIS 3.34+ bundles on Windows and macOS (older QGIS builds ship Python 3.9 and cannot run it).
- Windows, macOS or Linux, with an internet connection the first time (to download the library).
- A Bhoonidhi portal account ([register here](https://bhoonidhi.nrsc.gov.in)).

### Automatic dependency install

The first time QGIS starts with this plugin, it installs [`bhoonidhi-downloader`](https://pypi.org/project/bhoonidhi-downloader/) (version 0.5.x) for you with `pip install --user` — into your own user Python folder, so **no administrator rights are needed**. It never compiles code inside QGIS and never opens extra QGIS windows.

If it can't finish, a dialog explains *why* (no internet / proxy, a file locked by another plugin, pip missing, PEP 668 on some Linux distros, ...) and shows the one command to run manually:

    python -m pip install --user "bhoonidhi-downloader>=0.5.2,<0.6"

(use the *OSGeo4W Shell* on Windows, or a terminal that uses QGIS's Python on macOS/Linux), then restart QGIS (or click the toolbar icon again). The plugin re-checks its dependency every time QGIS starts and every time you click its icon, and tries the automatic install again, so once the problem is fixed there is nothing else to do. When the install succeeds you'll see an **"All dependencies resolved"** message listing what was installed.

## Installation

From the QGIS Plugin Repository: **Plugins → Manage and Install Plugins → All**, search for "Bhoonidhi Downloader", install.

From a zip: **Plugins → Manage and Install Plugins → Install from ZIP**.

## Usage

1. Click the Bhoonidhi Downloader toolbar icon.
2. Log in with your Bhoonidhi credentials when prompted.
3. Pick a satellite and sensor, a date range, and a spatial filter (type in a bounding box, or draw one on the map).
4. Click **Search** — results appear both in the table and as footprint polygons on the map.
5. Check the scenes you want, optionally toggle **Quick View** to preview a georeferenced thumbnail on the map.
6. Click **Export / Download selected...**, pick an output folder, and download.

## Notes on scope

Downloaded scene archives (`.zip`) can contain several single-band product rasters. This plugin intentionally does **not** attempt to clip or mosaic them automatically — each raster found inside a downloaded scene is added to the QGIS project as its own layer, untouched.

## License

The plugin's own code is licensed under [GPL-3.0-or-later](LICENSE). It depends on [`bhoonidhi-downloader`](https://github.com/geovicco-dev/bhoonidhi-downloader), which is MIT-licensed.

## Issues

Please report bugs and feature requests via the issue tracker linked in the plugin metadata.
