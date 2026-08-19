"""Small reusable Qt widget tweaks."""

from __future__ import annotations

from qgis.PyQt.QtCore import QPoint
from qgis.PyQt.QtWidgets import QComboBox


class DownwardComboBox(QComboBox):
    """A QComboBox whose popup always opens directly below it.

    Qt's default popup placement flips the list above the combo box when
    there isn't enough room below on screen -- disorienting inside a
    scrollable dock panel, where a combo near the bottom of the visible
    area would otherwise have its dropdown jump to a different spot each
    time depending on scroll position.
    """

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        popup.move(self.mapToGlobal(QPoint(0, self.height())))
