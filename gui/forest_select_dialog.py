from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QCheckBox,
    QScrollArea, QWidget,
)


class ForestSelectDialog(QDialog):
    """Lets the user pick which land-cover class values count as forest,
    mirroring the desktop tool's ForestSelectPopup. Checkboxes default to
    checked when the value's text contains "forest".
    """

    def __init__(self, parent, land_cover_path):
        super().__init__(parent)
        self.setWindowTitle("Select Forest Classes")
        self.resize(600, 400)

        self.lc_layer = QgsVectorLayer(land_cover_path, "land_cover", "ogr")
        self.result = None
        self._checkboxes = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("1. Select Land Cover column (text columns only):"))

        self.field_combo = QComboBox()
        string_fields = [f.name() for f in self.lc_layer.fields() if f.type() == QVariant.String]
        self.field_combo.addItems(string_fields)
        self.field_combo.currentTextChanged.connect(self._populate_values)
        layout.addWidget(self.field_combo)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        scroll.setWidget(self._scroll_content)
        layout.addWidget(scroll)

        confirm_btn = QPushButton("Confirm Selection")
        confirm_btn.clicked.connect(self._confirm)
        layout.addWidget(confirm_btn)

        if string_fields:
            self._populate_values(string_fields[0])

    def _populate_values(self, field_name):
        while self._scroll_layout.count():
            item = self._scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes = {}

        idx = self.lc_layer.fields().indexFromName(field_name)
        distinct_values = sorted({f[idx] for f in self.lc_layer.getFeatures() if f[idx] is not None},
                                  key=str)
        for value in distinct_values:
            cb = QCheckBox(str(value))
            cb.setChecked("forest" in str(value).lower())
            self._scroll_layout.addWidget(cb)
            self._checkboxes[value] = cb

    def _confirm(self):
        self.result = {
            "field": self.field_combo.currentText(),
            "values": [value for value, cb in self._checkboxes.items() if cb.isChecked()],
        }
        self.accept()
