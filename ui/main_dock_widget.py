"""Main plugin panel: satellite/sensor pickers, date range, spatial filter,
search, results table, session query manager, and the export entry point.
"""

from __future__ import annotations

from datetime import datetime

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
)
from qgis.gui import QgsDateEdit
from qgis.PyQt.QtCore import QDate, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .extent_tool import ExtentDrawTool, rectangle_to_wgs84
from .scene_layer import replace_scene_footprint_layer
from .widgets import DownwardComboBox
from .workers import QuicklookWorker, RefreshWorker, SearchWorker

PAGE_SIZE = 10


class BhoonidhiDockWidget(QDockWidget):
    """Signals plugin.py listens to for cross-cutting concerns (slug
    lifecycle, export)."""

    querySlugCreated = pyqtSignal(str)  # new slug saved this session
    querySlugDeleted = pyqtSignal(str)
    exportRequested = pyqtSignal(str, list, object)  # slug, scenes, aoi_bbox
    reauthNeeded = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__("Bhoonidhi Downloader", parent)
        self.iface = iface
        self.setObjectName("BhoonidhiDownloaderDockWidget")

        self._archive_records: list[dict] = []
        self._current_aoi_bbox: tuple[float, float, float, float] | None = None
        self._current_query = None  # last saved QuerySchema
        self._session_queries: dict[str, object] = {}
        self._extent_tool: ExtentDrawTool | None = None
        self._search_worker: SearchWorker | None = None
        self._refresh_worker: RefreshWorker | None = None
        self._footprint_layer_id: str | None = None

        self._all_scenes: list[dict] = []
        self._checked_scene_ids: set[str] = set()
        self._current_page = 0
        self._quicklook_layer_ids: dict[str, str] = {}
        self._quicklook_workers: dict[str, QuicklookWorker] = {}

        self._build_ui()
        self._reload_archive(refresh=True)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        layout.addWidget(self._build_satellite_group())
        layout.addWidget(self._build_date_group())
        layout.addWidget(self._build_spatial_group())

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._on_search_clicked)
        layout.addWidget(self.search_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addLayout(self._build_selection_buttons_row())
        layout.addWidget(self._build_results_table())
        layout.addLayout(self._build_pagination_row())
        layout.addWidget(self._build_session_queries_group())
        layout.addWidget(self._build_query_details_group())

        self.export_button = QPushButton("Export / Download selected...")
        self.export_button.clicked.connect(self._on_export_clicked)
        self.export_button.setEnabled(False)
        layout.addWidget(self.export_button)

        container.setLayout(layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        self.setWidget(scroll)

    def _build_satellite_group(self) -> QGroupBox:
        box = QGroupBox("Satellite / Sensor")
        layout = QVBoxLayout()
        form = QFormLayout()
        self.satellite_combo = DownwardComboBox()
        self.satellite_combo.currentTextChanged.connect(self._on_satellite_changed)
        self.sensor_combo = DownwardComboBox()
        form.addRow("Satellite", self.satellite_combo)
        form.addRow("Sensor", self.sensor_combo)
        layout.addLayout(form)

        self.refresh_archive_button = QPushButton("⟳ Refresh archive")
        self.refresh_archive_button.clicked.connect(lambda: self._reload_archive(refresh=True))
        layout.addWidget(self.refresh_archive_button)

        box.setLayout(layout)
        return box

    def _build_date_group(self) -> QGroupBox:
        box = QGroupBox("Date Range")
        form = QFormLayout()
        self.start_date_edit = QgsDateEdit()
        self.end_date_edit = QgsDateEdit()
        today = datetime.now().date()

        self.start_date_edit.setDate(QDate(today.year - 1, today.month, today.day))
        self.end_date_edit.setDate(QDate(today.year, today.month, today.day))
        self.start_date_edit.setCalendarPopup(True)
        self.end_date_edit.setCalendarPopup(True)
        form.addRow("Start Date", self.start_date_edit)
        form.addRow("End Date", self.end_date_edit)
        box.setLayout(form)
        return box

    def _build_spatial_group(self) -> QGroupBox:
        box = QGroupBox("Spatial Filter")
        layout = QVBoxLayout()

        self.manual_filter_radio = QRadioButton("Enter bounding box")
        self.draw_filter_radio = QRadioButton("Draw bounding box")
        self.manual_filter_radio.setChecked(True)

        group = QButtonGroup(self)
        for rb in (self.manual_filter_radio, self.draw_filter_radio):
            group.addButton(rb)
        self._spatial_group = group

        layout.addWidget(self.manual_filter_radio)

        manual_form = QFormLayout()
        self.minx_spin = self._make_coord_spin(-180, 180)
        self.miny_spin = self._make_coord_spin(-90, 90)
        self.maxx_spin = self._make_coord_spin(-180, 180)
        self.maxy_spin = self._make_coord_spin(-90, 90)
        manual_form.addRow("minx", self.minx_spin)
        manual_form.addRow("miny", self.miny_spin)
        manual_form.addRow("maxx", self.maxx_spin)
        manual_form.addRow("maxy", self.maxy_spin)
        layout.addLayout(manual_form)

        self.fill_extent_button = QPushButton("Fill from current map extent")
        self.fill_extent_button.clicked.connect(self._on_fill_extent_clicked)
        layout.addWidget(self.fill_extent_button)

        layout.addWidget(self.draw_filter_radio)
        draw_row = QHBoxLayout()
        self.draw_button = QPushButton("Draw")
        self.clear_button = QPushButton("Clear")
        self.draw_button.clicked.connect(self._on_draw_clicked)
        self.clear_button.clicked.connect(self._on_clear_clicked)
        draw_row.addWidget(self.draw_button)
        draw_row.addWidget(self.clear_button)
        layout.addLayout(draw_row)

        self.aoi_label = QLabel("Drawn AOI: none")
        self.aoi_label.setWordWrap(True)
        layout.addWidget(self.aoi_label)

        box.setLayout(layout)
        return box

    @staticmethod
    def _make_coord_spin(minimum: float, maximum: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(minimum, maximum)
        return spin

    def _build_selection_buttons_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.clear_selection_button = QPushButton("Clear Selection")
        self.select_all_button.clicked.connect(self._on_select_all_clicked)
        self.clear_selection_button.clicked.connect(self._on_clear_selection_clicked)
        row.addWidget(self.select_all_button)
        row.addWidget(self.clear_selection_button)
        return row

    def _build_results_table(self) -> QTableWidget:
        self.results_table = QTableWidget(0, 6)
        self.results_table.setHorizontalHeaderLabels(
            ["Select to Download", "Quick View", "Scene ID", "Date", "Satellite/Sensor", "Availability"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.results_table.horizontalScrollBar().setEnabled(True)
        self.results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.itemChanged.connect(self._on_table_item_changed)
        return self.results_table

    def _build_pagination_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.prev_page_button = QPushButton("◀ Prev")
        self.page_label = QLabel("Page 0 of 0")
        self.next_page_button = QPushButton("Next ▶")
        self.prev_page_button.clicked.connect(self._on_prev_page)
        self.next_page_button.clicked.connect(self._on_next_page)
        row.addWidget(self.prev_page_button)
        row.addWidget(self.page_label)
        row.addWidget(self.next_page_button)
        return row

    def _build_session_queries_group(self) -> QGroupBox:
        box = QGroupBox("Session Queries (slugs)")
        layout = QVBoxLayout()

        self.toggle_footprints_button = QPushButton("Hide footprints on map")
        self.toggle_footprints_button.clicked.connect(self._on_toggle_footprints_clicked)
        layout.addWidget(self.toggle_footprints_button)

        self.query_list = QListWidget()
        self.query_list.currentItemChanged.connect(self._on_query_list_selection)
        layout.addWidget(self.query_list)

        button_row = QHBoxLayout()
        self.show_query_button = QPushButton("Show")
        self.refresh_query_button = QPushButton("Refresh")
        self.rename_query_button = QPushButton("Rename")
        self.fork_query_button = QPushButton("Fork")
        self.delete_query_button = QPushButton("Delete")
        for btn, handler in (
            (self.show_query_button, self._on_show_query),
            (self.refresh_query_button, self._on_refresh_query),
            (self.rename_query_button, self._on_rename_query),
            (self.fork_query_button, self._on_fork_query),
            (self.delete_query_button, self._on_delete_query),
        ):
            btn.clicked.connect(handler)
            button_row.addWidget(btn)
        layout.addLayout(button_row)

        box.setLayout(layout)
        return box

    def _build_query_details_group(self) -> QGroupBox:
        box = QGroupBox("Query Details")
        form = QFormLayout()

        self.details_slug_label = QLabel("—")
        self.details_name_edit = QLineEdit()
        self.details_description_edit = QTextEdit()
        self.details_description_edit.setMaximumHeight(60)
        form.addRow("Slug", self.details_slug_label)
        form.addRow("Name", self.details_name_edit)
        form.addRow("Description", self.details_description_edit)

        self.details_save_button = QPushButton("Save changes")
        self.details_save_button.clicked.connect(self._on_save_query_details)
        form.addRow("", self.details_save_button)

        self.details_selected_label = QLabel("0 of 0 scenes selected.")
        form.addRow("", self.details_selected_label)

        box.setLayout(form)
        return box

    # ------------------------------------------------------------------
    # Satellite / sensor population (req #1 -- always live, never a stale
    # on-disk cache)
    # ------------------------------------------------------------------
    def _reload_archive(self, refresh: bool):
        from ..api import archive as archive_api

        self.status_label.setText("Loading satellite archive...")
        try:
            self._archive_records = archive_api.archive_records(refresh=refresh)
        except Exception as exc:
            self.status_label.setText(f"Could not load satellite archive: {exc}")
            return

        self.satellite_combo.blockSignals(True)
        self.satellite_combo.clear()
        self.satellite_combo.addItems(
            archive_api.direct_download_satellites_from(self._archive_records)
        )
        self.satellite_combo.blockSignals(False)
        self._on_satellite_changed(self.satellite_combo.currentText())
        self.status_label.setText("Archive loaded.")

    def _on_satellite_changed(self, satellite: str):
        from ..api import archive as archive_api

        self.sensor_combo.clear()
        if not satellite:
            return
        sensors = archive_api.sensors_for_satellite_from(self._archive_records, satellite)
        self.sensor_combo.addItems(sensors)

    # ------------------------------------------------------------------
    # Spatial filter
    # ------------------------------------------------------------------
    def _on_fill_extent_clicked(self):
        canvas = self.iface.mapCanvas()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(
            canvas.mapSettings().destinationCrs(), wgs84, QgsProject.instance()
        )
        extent = transform.transformBoundingBox(canvas.extent())
        self.minx_spin.setValue(extent.xMinimum())
        self.miny_spin.setValue(extent.yMinimum())
        self.maxx_spin.setValue(extent.xMaximum())
        self.maxy_spin.setValue(extent.yMaximum())
        self.status_label.setText("Filled bounding box from the current map extent.")

    def _on_draw_clicked(self):
        self.draw_filter_radio.setChecked(True)
        canvas = self.iface.mapCanvas()
        self._extent_tool = ExtentDrawTool(canvas)
        self._extent_tool.extentDrawn.connect(self._on_extent_drawn)
        canvas.setMapTool(self._extent_tool)
        self.status_label.setText("Draw a rectangle on the map canvas.")

    def _on_extent_drawn(self, rect: QgsRectangle):
        canvas = self.iface.mapCanvas()
        bbox = rectangle_to_wgs84(rect, canvas.mapSettings().destinationCrs())
        self._current_aoi_bbox = bbox
        self.aoi_label.setText(
            f"Drawn AOI (EPSG:4326): minx={bbox[0]:.5f}, miny={bbox[1]:.5f}, "
            f"maxx={bbox[2]:.5f}, maxy={bbox[3]:.5f}"
        )
        self.status_label.setText("Bounding box captured.")

    def _on_clear_clicked(self):
        if self._extent_tool:
            self._extent_tool.clear()
        self._current_aoi_bbox = None
        self.aoi_label.setText("Drawn AOI: none")

    def _resolve_aoi_bbox(self) -> tuple[float, float, float, float] | None:
        if self.draw_filter_radio.isChecked():
            return self._current_aoi_bbox
        # manual_filter_radio
        minx, miny = self.minx_spin.value(), self.miny_spin.value()
        maxx, maxy = self.maxx_spin.value(), self.maxy_spin.value()
        if minx == 0 and miny == 0 and maxx == 0 and maxy == 0:
            return None
        return (minx, miny, maxx, maxy)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _on_search_clicked(self):
        satellite = self.satellite_combo.currentText()
        sensor = self.sensor_combo.currentText()
        if not satellite:
            QMessageBox.warning(self, "Bhoonidhi Downloader", "Pick a satellite first.")
            return

        aoi_bbox = self._resolve_aoi_bbox()
        if aoi_bbox is None:
            QMessageBox.warning(
                self,
                "Bhoonidhi Downloader",
                "Enter a bounding box (minx/miny/maxx/maxy) or draw one on the map first.",
            )
            return
        if aoi_bbox[0] >= aoi_bbox[2] or aoi_bbox[1] >= aoi_bbox[3]:
            QMessageBox.warning(
                self, "Bhoonidhi Downloader", "minx must be < maxx and miny must be < maxy."
            )
            return

        minx, miny, maxx, maxy = aoi_bbox
        start_dt = self.start_date_edit.date().toPyDate()
        end_dt = self.end_date_edit.date().toPyDate()

        params = dict(
            minx=minx,
            maxx=maxx,
            miny=miny,
            maxy=maxy,
            start_date=datetime(start_dt.year, start_dt.month, start_dt.day),
            end_date=datetime(end_dt.year, end_dt.month, end_dt.day),
            satellite=satellite,
            sensor=sensor or None,
        )

        self.search_button.setEnabled(False)
        self.status_label.setText("Searching Bhoonidhi...")

        self._search_worker = SearchWorker(params)
        self._search_worker.finished_ok.connect(self._on_search_finished)
        self._search_worker.failed.connect(self._on_search_failed)
        self._search_worker.start()

    def _on_search_failed(self, message: str):
        self.search_button.setEnabled(True)
        self.status_label.setText(f"Search failed: {message}")

    def _on_search_finished(self, result):
        self.search_button.setEnabled(True)
        if not result.ok:
            self.status_label.setText(result.error or "Search failed.")
            return

        query = result.query
        self._current_query = query
        self._session_queries[query.slug] = query
        self.querySlugCreated.emit(query.slug)

        self.status_label.setText(
            f"Found {result.scene_count} scene(s). Saved as query '{query.slug}'."
        )
        self._load_query_scenes(query)
        self._refresh_query_list()
        self.export_button.setEnabled(True)

    # ------------------------------------------------------------------
    # Results table: full scene list, pagination, footprints
    # ------------------------------------------------------------------
    def _load_query_scenes(self, query):
        """Full reset for a (newly shown/searched/refreshed) query: clears
        checked/quicklook state from any previous query and redraws
        everything from page 0."""
        self._clear_quicklook_layers()
        self._all_scenes = query.scenes
        self._checked_scene_ids = set()
        self._current_page = 0
        self._update_footprint_layer(self._all_scenes)
        self._render_current_page()
        self._refresh_query_details_panel()

    def _total_pages(self) -> int:
        if not self._all_scenes:
            return 0
        return (len(self._all_scenes) + PAGE_SIZE - 1) // PAGE_SIZE

    def _render_current_page(self):
        from bhoonidhi_downloader.core.search.availability import (
            AVAILABILITY_LABEL,
            availability_of,
            is_downloadable,
        )

        total_pages = self._total_pages()
        self.page_label.setText(f"Page {min(self._current_page + 1, total_pages)} of {total_pages}")
        self.prev_page_button.setEnabled(self._current_page > 0)
        self.next_page_button.setEnabled(self._current_page < total_pages - 1)

        start = self._current_page * PAGE_SIZE
        page_scenes = self._all_scenes[start : start + PAGE_SIZE]

        self.results_table.blockSignals(True)
        self.results_table.setRowCount(0)
        self._page_scenes = page_scenes

        for row, scene in enumerate(page_scenes):
            self.results_table.insertRow(row)
            scene_id = str(scene.get("ID", ""))

            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            downloadable = is_downloadable(scene)
            check_item.setCheckState(
                Qt.Checked if scene_id in self._checked_scene_ids else Qt.Unchecked
            )
            if not downloadable:
                check_item.setFlags(Qt.NoItemFlags)
            self.results_table.setItem(row, 0, check_item)

            quicklook_item = QTableWidgetItem()
            quicklook_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            quicklook_item.setCheckState(
                Qt.Checked if scene_id in self._quicklook_layer_ids else Qt.Unchecked
            )
            self.results_table.setItem(row, 1, quicklook_item)

            id_item = QTableWidgetItem(scene_id)
            self.results_table.setItem(row, 2, id_item)

            date_item = QTableWidgetItem(str(scene.get("DOP", "")))
            self.results_table.setItem(row, 3, date_item)

            satsen_item = QTableWidgetItem(
                f"{scene.get('SATELLITE', '')}/{scene.get('SENSOR', '')}"
            )
            self.results_table.setItem(row, 4, satsen_item)

            state = availability_of(scene)
            avail_item = QTableWidgetItem(AVAILABILITY_LABEL.get(state, str(state)))
            if not downloadable:
                avail_item.setToolTip(
                    "Not directly downloadable — request it on the Bhoonidhi portal."
                )
            self.results_table.setItem(row, 5, avail_item)

        self.results_table.blockSignals(False)

    def _on_prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

    def _on_next_page(self):
        if self._current_page < self._total_pages() - 1:
            self._current_page += 1
            self._render_current_page()

    def _update_footprint_layer(self, scenes: list):
        """Draw the search results' footprints on the map so they're visible
        alongside the results table, not just listed in it."""
        try:
            layer = replace_scene_footprint_layer(scenes, self._footprint_layer_id)
            self._footprint_layer_id = layer.id()
            # A freshly-added layer is always visible; reset the toggle
            # button to match instead of leaving it saying "Show" from a
            # previous query.
            self.toggle_footprints_button.setText("Hide footprints on map")
        except Exception as exc:
            self.status_label.setText(f"(Could not draw scene footprints: {exc})")

    def _on_toggle_footprints_clicked(self):
        if not self._footprint_layer_id:
            self.status_label.setText("No footprints on the map yet.")
            return
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(self._footprint_layer_id)
        if node is None:
            self.status_label.setText("Footprint layer not found (was it removed?).")
            return
        now_visible = not node.itemVisibilityChecked()
        node.setItemVisibilityChecked(now_visible)
        self.toggle_footprints_button.setText(
            "Hide footprints on map" if now_visible else "Show footprints on map"
        )

    def _on_table_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        page_scenes = getattr(self, "_page_scenes", [])
        if row >= len(page_scenes):
            return
        scene = page_scenes[row]
        scene_id = str(scene.get("ID", ""))

        if item.column() == 0:
            if item.checkState() == Qt.Checked:
                self._checked_scene_ids.add(scene_id)
            else:
                self._checked_scene_ids.discard(scene_id)
            self._refresh_query_details_panel()
        elif item.column() == 1:
            if item.checkState() == Qt.Checked:
                self._start_quicklook(scene)
            else:
                self._remove_quicklook_layer(scene_id)

    def checked_scenes(self) -> list:
        return [s for s in self._all_scenes if str(s.get("ID", "")) in self._checked_scene_ids]

    # ------------------------------------------------------------------
    # Select all / clear (req #7 -- whole result set, all pages)
    # ------------------------------------------------------------------
    def _on_select_all_clicked(self):
        from bhoonidhi_downloader.core.search.availability import is_downloadable

        self._checked_scene_ids = {
            str(s.get("ID", "")) for s in self._all_scenes if is_downloadable(s)
        }
        self._render_current_page()
        self._refresh_query_details_panel()

    def _on_clear_selection_clicked(self):
        self._checked_scene_ids = set()
        self._render_current_page()
        self._refresh_query_details_panel()

    # ------------------------------------------------------------------
    # Quick View (req #3): georeferenced quicklook rasters on the map
    # ------------------------------------------------------------------
    def _start_quicklook(self, scene: dict):
        scene_id = str(scene.get("ID", ""))
        if scene_id in self._quicklook_layer_ids or scene_id in self._quicklook_workers:
            return
        slug = self._current_query.slug if self._current_query else "adhoc"
        worker = QuicklookWorker(scene, slug)
        worker.finished_ok.connect(self._on_quicklook_ready)
        worker.failed.connect(self._on_quicklook_failed)
        self._quicklook_workers[scene_id] = worker
        self.status_label.setText(f"Fetching quicklook for {scene_id}...")
        worker.start()

    def _on_quicklook_ready(self, scene_id: str, tif_path: str):
        self._quicklook_workers.pop(scene_id, None)
        layer = QgsRasterLayer(tif_path, f"Quicklook: {scene_id}")
        if not layer.isValid():
            self.status_label.setText(f"Quicklook for {scene_id} failed to load as a raster.")
            return
        QgsProject.instance().addMapLayer(layer)
        self._quicklook_layer_ids[scene_id] = layer.id()
        self.status_label.setText(f"Quicklook added for {scene_id}.")

    def _on_quicklook_failed(self, scene_id: str, message: str):
        self._quicklook_workers.pop(scene_id, None)
        self.status_label.setText(f"Quicklook failed for {scene_id}: {message}")

    def _remove_quicklook_layer(self, scene_id: str):
        layer_id = self._quicklook_layer_ids.pop(scene_id, None)
        if layer_id and QgsProject.instance().mapLayer(layer_id) is not None:
            QgsProject.instance().removeMapLayer(layer_id)

    def _clear_quicklook_layers(self):
        for scene_id in list(self._quicklook_layer_ids):
            self._remove_quicklook_layer(scene_id)

    # ------------------------------------------------------------------
    # Query details panel (req #6)
    # ------------------------------------------------------------------
    def _refresh_query_details_panel(self):
        query = self._current_query
        if query is None:
            self.details_slug_label.setText("—")
            self.details_name_edit.setText("")
            self.details_description_edit.setPlainText("")
            self.details_selected_label.setText("0 of 0 scenes selected.")
            return

        self.details_slug_label.setText(query.slug)
        self.details_name_edit.setText(query.name)
        self.details_description_edit.setPlainText(query.description)
        self.details_selected_label.setText(
            f"{len(self._checked_scene_ids)} of {len(self._all_scenes)} scenes selected."
        )

    def _on_save_query_details(self):
        if not self._current_query:
            return
        from ..api import query as query_api

        name = self.details_name_edit.text().strip()
        description = self.details_description_edit.toPlainText().strip()
        if query_api.rename_query(self._current_query.slug, name=name or None, description=description or None):
            self._current_query.name = name or self._current_query.name
            self._current_query.description = description or self._current_query.description
            self.status_label.setText(f"Saved details for '{self._current_query.slug}'.")
        else:
            self.status_label.setText("Could not save — query not found.")

    # ------------------------------------------------------------------
    # Session query manager
    # ------------------------------------------------------------------
    def _refresh_query_list(self):
        self.query_list.clear()
        for slug in self._session_queries:
            self.query_list.addItem(QListWidgetItem(slug))

    def _selected_slug(self) -> str | None:
        item = self.query_list.currentItem()
        return item.text() if item else None

    def _on_query_list_selection(self, current, _previous):
        if current is None:
            return
        slug = current.text()
        query = self._session_queries.get(slug)
        if query:
            self._current_query = query
            self._current_aoi_bbox = (
                query.aoi.min_lon,
                query.aoi.min_lat,
                query.aoi.max_lon,
                query.aoi.max_lat,
            )
            self._load_query_scenes(query)
            self.export_button.setEnabled(True)

    def _on_show_query(self):
        slug = self._selected_slug()
        if not slug:
            return
        from ..api import query as query_api

        query = query_api.load_query(slug)
        if query:
            self._session_queries[slug] = query
            self._current_query = query
            self._load_query_scenes(query)

    def _on_refresh_query(self):
        slug = self._selected_slug()
        if not slug:
            return
        self.status_label.setText(f"Refreshing '{slug}'...")
        self._refresh_worker = RefreshWorker(slug)
        self._refresh_worker.finished_ok.connect(self._on_refresh_finished)
        self._refresh_worker.failed.connect(
            lambda msg: self.status_label.setText(f"Refresh failed: {msg}")
        )
        self._refresh_worker.start()

    def _on_refresh_finished(self, result):
        if not result.ok:
            self.status_label.setText(result.error or "Refresh failed.")
            return
        self._session_queries[result.query.slug] = result.query
        self.status_label.setText(f"Refreshed: {result.added} new scene(s).")
        if self._current_query and self._current_query.slug == result.query.slug:
            self._current_query = result.query
            self._load_query_scenes(result.query)

    def _on_rename_query(self):
        slug = self._selected_slug()
        if not slug:
            return
        from qgis.PyQt.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Rename query", "New name:")
        if not ok or not name:
            return
        from ..api import query as query_api

        query_api.rename_query(slug, name=name)
        self.status_label.setText(f"Renamed '{slug}'.")
        if self._current_query and self._current_query.slug == slug:
            self._current_query.name = name
            self._refresh_query_details_panel()

    def _on_fork_query(self):
        slug = self._selected_slug()
        if not slug:
            return
        from ..api import query as query_api

        fork = query_api.fork_query(slug)
        if fork:
            self._session_queries[fork.slug] = fork
            self.querySlugCreated.emit(fork.slug)
            self._refresh_query_list()
            self.status_label.setText(f"Forked '{slug}' -> '{fork.slug}'.")

    def _on_delete_query(self):
        slug = self._selected_slug()
        if not slug:
            return
        from ..api import query as query_api

        if query_api.delete_query(slug):
            self._session_queries.pop(slug, None)
            self.querySlugDeleted.emit(slug)
            self._refresh_query_list()
            self.status_label.setText(f"Deleted '{slug}'.")

    def forget_slug(self, slug: str):
        """Called by plugin.py after it has already deleted a slug (e.g. on
        unload) so the UI dict stays in sync."""
        self._session_queries.pop(slug, None)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _on_export_clicked(self):
        if not self._current_query:
            QMessageBox.warning(self, "Bhoonidhi Downloader", "Run a search first.")
            return
        checked = self.checked_scenes()
        if not checked:
            QMessageBox.warning(
                self, "Bhoonidhi Downloader", "Check at least one scene to export."
            )
            return
        self.exportRequested.emit(self._current_query.slug, checked, self._current_aoi_bbox)
