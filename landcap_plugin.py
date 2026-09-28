import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .processing.provider import LandCapProvider


class LandCapPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.provider = None
        self.action = None
        self.dialog = None

    def initGui(self):
        self.provider = LandCapProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        icon = QIcon(os.path.join(self.plugin_dir, "icon.png"))
        self.action = QAction(icon, "LandCap Assessment Tool", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&LandCap Assessment", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        QgsApplication.processingRegistry().removeProvider(self.provider)
        self.iface.removePluginMenu("&LandCap Assessment", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()

    def run(self):
        from .gui.main_dialog import MainDialog
        if self.dialog is None:
            self.dialog = MainDialog(self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
