"""Builds a temporary in-memory polygon layer of scene footprints (from
each scene's Crn* corner fields) so search results are visible on the map,
not just listed in the results table. Colored by availability, matching
the CLI's own Ready/Archived/OnOrder/Priced palette.
"""

from __future__ import annotations

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from ..api.rasters import scene_bbox

_AVAILABILITY_COLORS = {
    "Ready": QColor(34, 139, 34),
    "Archived": QColor(0, 150, 150),
    "OnOrder": QColor(230, 170, 0),
    "Priced": QColor(160, 0, 160),
}
_LAYER_NAME = "Bhoonidhi search results"


def _footprint_geometry(scene: dict) -> QgsGeometry | None:
    bbox = scene_bbox(scene)
    if bbox is None:
        return None
    minx, miny, maxx, maxy = bbox
    ring = [
        QgsPointXY(minx, maxy),
        QgsPointXY(maxx, maxy),
        QgsPointXY(maxx, miny),
        QgsPointXY(minx, miny),
        QgsPointXY(minx, maxy),
    ]
    return QgsGeometry.fromPolygonXY([ring])


def build_scene_footprint_layer(
    scenes: list[dict], layer_name: str = _LAYER_NAME
) -> QgsVectorLayer:
    from bhoonidhi_downloader.core.search.availability import AVAILABILITY_LABEL, availability_of

    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", layer_name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes(
        [
            QgsField("scene_id", QMetaType.Type.QString),
            QgsField("date", QMetaType.Type.QString),
            QgsField("satellite", QMetaType.Type.QString),
            QgsField("sensor", QMetaType.Type.QString),
            QgsField("availability", QMetaType.Type.QString),
        ]
    )
    layer.updateFields()

    features = []
    for scene in scenes:
        geom = _footprint_geometry(scene)
        if geom is None or geom.isEmpty():
            continue
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geom)
        state = availability_of(scene)
        feature.setAttributes(
            [
                str(scene.get("ID", "")),
                str(scene.get("DOP", "")),
                str(scene.get("SATELLITE", "")),
                str(scene.get("SENSOR", "")),
                AVAILABILITY_LABEL.get(state, str(state)),
            ]
        )
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()

    _apply_availability_style(layer)
    return layer


def _apply_availability_style(layer: QgsVectorLayer) -> None:
    categories = []
    for label, color in _AVAILABILITY_COLORS.items():
        symbol = QgsFillSymbol.createSimple(
            {
                "color": f"{color.red()},{color.green()},{color.blue()},60",
                "outline_color": f"{color.red()},{color.green()},{color.blue()},255",
                "outline_width": "0.6",
            }
        )
        categories.append(QgsRendererCategory(label, symbol, label))
    renderer = QgsCategorizedSymbolRenderer("availability", categories)
    layer.setRenderer(renderer)
    layer.setOpacity(0.85)


def replace_scene_footprint_layer(
    scenes: list[dict], previous_layer_id: str | None, layer_name: str = _LAYER_NAME
) -> QgsVectorLayer:
    """Add a fresh footprint layer to the project, removing a prior one
    this widget added (so re-searching doesn't pile up layers)."""
    project = QgsProject.instance()
    if previous_layer_id and project.mapLayer(previous_layer_id) is not None:
        project.removeMapLayer(previous_layer_id)

    layer = build_scene_footprint_layer(scenes, layer_name)
    project.addMapLayer(layer)
    return layer
