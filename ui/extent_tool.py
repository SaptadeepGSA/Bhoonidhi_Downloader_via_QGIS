"""Rubber-band rectangle draw tool for the "Draw bounding box" spatial
filter option (req #5, matches image 2's Draw/Clear buttons)."""

from __future__ import annotations

from qgis.core import QgsCoordinateTransform, QgsProject, QgsRectangle, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor


class ExtentDrawTool(QgsMapTool):
    """Click-drag-release to draw a rectangle; emits extentDrawn(QgsRectangle)
    in the canvas' own CRS -- caller is responsible for reprojecting to
    EPSG:4326."""

    extentDrawn = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0, 60))
        self.rubber_band.setStrokeColor(QColor(255, 0, 0, 200))
        self.rubber_band.setWidth(2)
        self._start_point = None
        self._dragging = False

    def canvasPressEvent(self, event):
        self._start_point = self.toMapCoordinates(event.pos())
        self._dragging = True
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)

    def canvasMoveEvent(self, event):
        if not self._dragging or self._start_point is None:
            return
        current = self.toMapCoordinates(event.pos())
        self._update_rubber_band(self._start_point, current)

    def canvasReleaseEvent(self, event):
        if not self._dragging or self._start_point is None:
            return
        end_point = self.toMapCoordinates(event.pos())
        self._update_rubber_band(self._start_point, end_point)
        self._dragging = False

        rect = QgsRectangle(self._start_point, end_point)
        rect.normalize()
        if rect.width() > 0 and rect.height() > 0:
            self.extentDrawn.emit(rect)

    def _update_rubber_band(self, p1, p2):
        rect = QgsRectangle(p1, p2)
        rect.normalize()
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        points = [
            rect.xMinimum(), rect.yMinimum(),
            rect.xMaximum(), rect.yMinimum(),
            rect.xMaximum(), rect.yMaximum(),
            rect.xMinimum(), rect.yMaximum(),
        ]
        from qgis.core import QgsPointXY

        self.rubber_band.addPoint(QgsPointXY(points[0], points[1]), False)
        self.rubber_band.addPoint(QgsPointXY(points[2], points[3]), False)
        self.rubber_band.addPoint(QgsPointXY(points[4], points[5]), False)
        self.rubber_band.addPoint(QgsPointXY(points[6], points[7]), True)

    def clear(self):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self._start_point = None
        self._dragging = False

    def deactivate(self):
        super().deactivate()


def rectangle_to_wgs84(rect: QgsRectangle, source_crs) -> tuple[float, float, float, float]:
    """Reproject a QgsRectangle from source_crs to EPSG:4326, returning
    (minx, miny, maxx, maxy)."""
    from qgis.core import QgsCoordinateReferenceSystem

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if source_crs == wgs84:
        return rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()
    transform = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
    transformed = transform.transformBoundingBox(rect)
    return (
        transformed.xMinimum(),
        transformed.yMinimum(),
        transformed.xMaximum(),
        transformed.yMaximum(),
    )
