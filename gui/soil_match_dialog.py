from qgis.core import QgsVectorLayer
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QScrollArea, QWidget,
)

from ..core.soil_match import best_match, read_k_lookup


class SoilMatchDialog(QDialog):
    """Lets the user review/override the fuzzy soil-texture-to-K-value match
    before a run, mirroring the desktop tool's SoilMatchPopup.
    """

    def __init__(self, parent, soil_path, k_lookup_path):
        super().__init__(parent)
        self.setWindowTitle("Match Soil Types")
        self.resize(600, 400)

        self.soil_layer = QgsVectorLayer(soil_path, "soil", "ogr")
        self.k_lookup = read_k_lookup(k_lookup_path)
        self.texture_labels = list(self.k_lookup.keys())
        self.result = None
        self._match_boxes = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("1. Select soil texture field from vector file:"))

        self.field_combo = QComboBox()
        field_names = [f.name() for f in self.soil_layer.fields() if f.name().lower() != "geometry"]
        self.field_combo.addItems(field_names)
        self.field_combo.currentTextChanged.connect(self._populate_matches)
        layout.addWidget(self.field_combo)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        scroll.setWidget(self._scroll_content)
        layout.addWidget(scroll)

        confirm_btn = QPushButton("Confirm Matches")
        confirm_btn.clicked.connect(self._confirm)
        layout.addWidget(confirm_btn)

        if field_names:
            self._populate_matches(field_names[0])

    def _populate_matches(self, field_name):
        while self._scroll_layout.count():
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._match_boxes = {}

        idx = self.soil_layer.fields().indexFromName(field_name)
        distinct_values = sorted({f[idx] for f in self.soil_layer.getFeatures() if f[idx] is not None},
                                  key=str)
        for value in distinct_values:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.addWidget(QLabel(str(value)))
            combo = QComboBox()
            combo.addItems(self.texture_labels)
            combo.setCurrentText(best_match(str(value), self.texture_labels))
            row_layout.addWidget(combo)
            self._scroll_layout.addWidget(row)
            self._match_boxes[value] = combo

    def _confirm(self):
        self.result = {
            "field": self.field_combo.currentText(),
            "matches": {value: combo.currentText() for value, combo in self._match_boxes.items()},
            "k_lookup": self.k_lookup,
        }
        self.accept()

    def build_soil_map(self):
        """Returns {field_value: k_value}, ready for GeoProcessor.run_module2_k_factor."""
        if self.result is None:
            return None
        return {
            value: self.result["k_lookup"][label]
            for value, label in self.result["matches"].items()
        }
