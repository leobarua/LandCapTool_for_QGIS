import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .landcap_algorithm import LandCapAlgorithm


class LandCapProvider(QgsProcessingProvider):
    def id(self):
        return "landcap"

    def name(self):
        return "LandCap Assessment"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), "..", "icon.png")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return super().icon()

    def loadAlgorithms(self):
        self.addAlgorithm(LandCapAlgorithm())
