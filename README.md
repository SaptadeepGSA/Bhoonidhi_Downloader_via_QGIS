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

- QGIS ≥ 3.28
- The [`bhoonidhi-downloader`](https://pypi.org/project/bhoonidhi-downloader/) PyPI package, installed automatically into QGIS's own Python the first time the plugin runs (you'll be asked to confirm before anything is installed).
- A Bhoonidhi portal account ([register here](https://bhoonidhi.nrsc.gov.in)).

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
