"""Export/download dialog: output dir, parallel count, plain per-scene
download. No clip or mosaic step (removed by request) -- a scene's zip can
contain several single-band product tifs, and both clipping and
mosaicking need to know which of those belong together and in what band
order, which the plugin can't infer generically. Individual, unmodified
downloads only; each raster file found in a downloaded scene is added to
the project as its own layer, untouched.
"""

from __future__ import annotations

import os

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ..api import rasters as rasters_api
from .workers import DownloadWorker


class ExportDialog(QDialog):
    def __init__(self, iface, slug: str, scenes: list, aoi_bbox, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.slug = slug
        self.scenes = scenes
        self.aoi_bbox = aoi_bbox
        self._download_worker: DownloadWorker | None = None

        self.setWindowTitle(f"Export — query '{slug}'")
        self.resize(520, 460)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"{len(self.scenes)} scene(s) selected for download."))

        form = QFormLayout()
        out_row = QHBoxLayout()
        self.out_dir_edit = QLineEdit(os.path.expanduser("~"))
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_out_dir)
        out_row.addWidget(self.out_dir_edit)
        out_row.addWidget(browse_btn)
        form.addRow("Output directory", out_row)

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 8)
        self.parallel_spin.setValue(4)
        form.addRow("Parallel downloads", self.parallel_spin)
        layout.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(200)
        layout.addWidget(self.log_view)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Download")
        buttons.accepted.connect(self._on_download_clicked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._buttons = buttons

    def _browse_out_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Choose output directory", self.out_dir_edit.text()
        )
        if directory:
            self.out_dir_edit.setText(directory)

    def _on_download_clicked(self):
        out_dir = self.out_dir_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "Bhoonidhi Downloader", "Choose an output directory.")
            return
        os.makedirs(out_dir, exist_ok=True)

        self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.progress_bar.setVisible(True)
        self.log_view.append(f"Downloading {len(self.scenes)} scene(s) to {out_dir}...")

        self._download_worker = DownloadWorker(
            self.slug, self.scenes, out_dir, self.parallel_spin.value()
        )
        self._download_worker.finished_ok.connect(self._on_download_finished)
        self._download_worker.failed.connect(self._on_download_failed)
        self._download_worker.start()

    def _on_download_failed(self, message: str):
        self.progress_bar.setVisible(False)
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        self.log_view.append(f"Download failed: {message}")

    def _on_download_finished(self, result):
        self.progress_bar.setVisible(False)
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(True)

        if not result.ok:
            if result.needs_reauth:
                self.log_view.append("Session expired — please log in again and retry.")
                self.parent_needs_reauth = True
                self.reject()
                return
            self.log_view.append(result.error or "Download failed.")
            return

        outcomes = result.outcomes or []
        for outcome in outcomes:
            self.log_view.append(f"{outcome.scene_id}: {outcome.status}")

        downloaded = [o for o in outcomes if o.status in ("downloaded", "already_downloaded")]
        added_layers = 0
        for outcome in downloaded:
            for raster_path in rasters_api.find_rasters(outcome.path):
                layer = QgsRasterLayer(raster_path, os.path.basename(raster_path))
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    added_layers += 1
        if added_layers:
            self.log_view.append(f"Added {added_layers} raster layer(s) to the project.")

        self.log_view.append("Done.")
