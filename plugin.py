"""Plugin entry point: toolbar/menu wiring, dockwidget lifecycle,
dependency install, session-slug cleanup, and login-session purging.

- req #6/#7: slugs created this session are deleted on unload, not left in
  ~/.bhoonidhi/queries forever.
- req #4: login is in-memory only (see api/client_state.py) -- this module
  purges any on-disk session both at plugin load (in case an older version
  of this plugin, or another tool, left one behind) and again at unload /
  QGIS close, so nothing about a login ever survives past this session.
- req #5: dependencies are installed as soon as the plugin loads (deferred
  via QTimer so initGui() itself stays fast), not only when the user first
  opens the dock -- covers installing straight from the QGIS Plugin
  Repository, where bhoonidhi-downloader isn't bundled.
"""

from __future__ import annotations

import os

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

PLUGIN_DIR = os.path.dirname(__file__)


class BhoonidhiPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action: QAction | None = None
        self.dock_widget = None
        self._session_slugs: set[str] = set()

    # ------------------------------------------------------------------
    def initGui(self):
        icon = QIcon(os.path.join(PLUGIN_DIR, "icon.png"))
        self.action = QAction(icon, "Bhoonidhi Downloader", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self._toggle_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Bhoonidhi Downloader", self.action)

        from .api.client_state import reset_client

        reset_client()  # purge any pre-existing on-disk session (req #4)

        QTimer.singleShot(0, self._ensure_dependencies_ready)

    def _ensure_dependencies_ready(self):
        from .dependency_check import ensure_installed

        ensure_installed(self.iface.mainWindow())

    def unload(self):
        if self.dock_widget is not None:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&Bhoonidhi Downloader", self.action)
            self.action = None

        self._cleanup_session_slugs()

        from .api.client_state import reset_client

        reset_client()  # drop the in-memory session + purge the disk file (req #4)

    # ------------------------------------------------------------------
    def _toggle_dock(self, checked: bool):
        if not checked:
            if self.dock_widget is not None:
                self.dock_widget.hide()
            return

        from .dependency_check import ensure_installed

        if not ensure_installed(self.iface.mainWindow()):
            self.action.setChecked(False)
            return

        from .ui.login_dialog import LoginDialog

        if not LoginDialog.ensure_logged_in(self.iface.mainWindow()):
            self.action.setChecked(False)
            return

        if self.dock_widget is None:
            self._create_dock_widget()
        self.dock_widget.show()
        self.dock_widget.raise_()

    def _create_dock_widget(self):
        from .ui.main_dock_widget import BhoonidhiDockWidget

        self.dock_widget = BhoonidhiDockWidget(self.iface, self.iface.mainWindow())
        self.dock_widget.querySlugCreated.connect(self._on_slug_created)
        self.dock_widget.querySlugDeleted.connect(self._on_slug_deleted)
        self.dock_widget.exportRequested.connect(self._on_export_requested)
        self.dock_widget.visibilityChanged.connect(self._on_dock_visibility_changed)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)

    def _on_dock_visibility_changed(self, visible: bool):
        if self.action is not None:
            self.action.setChecked(visible)

    # ------------------------------------------------------------------
    # Session-scoped slug tracking (req #6/#7)
    # ------------------------------------------------------------------
    def _on_slug_created(self, slug: str):
        self._session_slugs.add(slug)

    def _on_slug_deleted(self, slug: str):
        self._session_slugs.discard(slug)

    def _cleanup_session_slugs(self):
        if not self._session_slugs:
            return
        from .api import query as query_api

        for slug in list(self._session_slugs):
            try:
                query_api.delete_query(slug)
            except Exception:
                pass
        self._session_slugs.clear()

    # ------------------------------------------------------------------
    # Export flow
    # ------------------------------------------------------------------
    def _on_export_requested(self, slug: str, scenes: list, aoi_bbox):
        from .ui.export_dialog import ExportDialog

        dialog = ExportDialog(self.iface, slug, scenes, aoi_bbox, self.iface.mainWindow())
        dialog.exec_()

        if getattr(dialog, "parent_needs_reauth", False):
            from .ui.login_dialog import LoginDialog

            if LoginDialog.ensure_logged_in(self.iface.mainWindow()):
                retry_dialog = ExportDialog(
                    self.iface, slug, scenes, aoi_bbox, self.iface.mainWindow()
                )
                retry_dialog.exec_()
