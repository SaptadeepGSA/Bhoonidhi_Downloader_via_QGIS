"""QThread workers so network calls into Bhoonidhi never block the QGIS UI
thread."""

from __future__ import annotations

from qgis.PyQt.QtCore import QThread, pyqtSignal


class SearchWorker(QThread):
    finished_ok = pyqtSignal(object)  # SearchResult
    failed = pyqtSignal(str)

    def __init__(self, params: dict, parent=None):
        super().__init__(parent)
        self.params = params

    def run(self):
        try:
            from ..api import query as query_api

            result = query_api.search_and_save(**self.params)
            self.finished_ok.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))


class RefreshWorker(QThread):
    finished_ok = pyqtSignal(object)  # RefreshResult
    failed = pyqtSignal(str)

    def __init__(self, slug: str, parent=None):
        super().__init__(parent)
        self.slug = slug

    def run(self):
        try:
            from ..api import query as query_api

            result = query_api.refresh_query(self.slug)
            self.finished_ok.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))


class QuicklookWorker(QThread):
    finished_ok = pyqtSignal(str, str)  # scene_id, georeferenced tif path
    failed = pyqtSignal(str, str)  # scene_id, message

    def __init__(self, scene: dict, slug: str, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.slug = slug

    def run(self):
        scene_id = str(self.scene.get("ID") or "unknown")
        try:
            from ..api import quicklook as quicklook_api

            path = quicklook_api.fetch_and_georeference(self.scene, self.slug)
            if path:
                self.finished_ok.emit(scene_id, path)
            else:
                self.failed.emit(scene_id, "Could not fetch/georeference quicklook.")
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(scene_id, str(exc))


class DownloadWorker(QThread):
    progress = pyqtSignal(str, int, object)  # scene_id, downloaded, total
    finished_ok = pyqtSignal(object)  # DownloadRunResult
    failed = pyqtSignal(str)

    def __init__(self, slug: str, scenes: list, out_dir: str, parallel: int, parent=None):
        super().__init__(parent)
        self.slug = slug
        self.scenes = scenes
        self.out_dir = out_dir
        self.parallel = parallel

    def run(self):
        try:
            from ..api import download as download_api

            def on_progress(scene_id, downloaded, total):
                self.progress.emit(scene_id, downloaded, total)

            result = download_api.download_scenes(
                self.slug,
                self.scenes,
                self.out_dir,
                parallel=self.parallel,
                on_progress=on_progress,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(str(exc))
