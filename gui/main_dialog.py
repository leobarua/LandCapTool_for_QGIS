import os

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QThread, QObject, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QPlainTextEdit, QSpinBox,
    QMessageBox, QTextBrowser,
)

from ..core.geoprocessor import GeoProcessor
from .soil_match_dialog import SoilMatchDialog
from .forest_select_dialog import ForestSelectDialog

_IDLE_STYLE = "background-color: gray; color: white; padding: 4px;"
_DONE_STYLE = "background-color: #21a452; color: white; padding: 4px;"


class AnalysisWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)
    outputs_ready = pyqtSignal(str, str)  # final_path, simplified_path

    def __init__(self, inputs, output_folder, sieve_size, hole_fill_size, iterations):
        super().__init__()
        self.inputs = inputs
        self.output_folder = output_folder
        self.sieve_size = sieve_size
        self.hole_fill_size = hole_fill_size
        self.iterations = iterations

    def run(self):
        processor = GeoProcessor(logger_callback=self.log.emit)
        success = processor.run_full_analysis(
            self.inputs, self.output_folder,
            sieve_size=self.sieve_size, hole_fill_size=self.hole_fill_size, iterations=self.iterations)
        if success:
            self.outputs_ready.emit(
                processor.last_final_path or "", processor.last_simplified_path or "")
        self.finished.emit(bool(success))


class ResimplifyWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)
    outputs_ready = pyqtSignal(str)  # simplified_path

    def __init__(self, output_folder, sieve_size, hole_fill_size, iterations):
        super().__init__()
        self.output_folder = output_folder
        self.sieve_size = sieve_size
        self.hole_fill_size = hole_fill_size
        self.iterations = iterations

    def run(self):
        processor = GeoProcessor(logger_callback=self.log.emit)
        try:
            ok = processor.recompute_simplified_classification(
                self.output_folder, sieve_size=self.sieve_size,
                hole_fill_size=self.hole_fill_size, iterations=self.iterations)
            self.log.emit("Simplified classification updated." if ok else "Simplified classification failed.")
            if ok:
                self.outputs_ready.emit(processor.last_simplified_path or "")
        except Exception as e:
            self.log.emit(f"ERROR during re-simplification: {e}")
            ok = False
        self.finished.emit(bool(ok))


class MainDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LandCap Assessment Tool by Leonardo Barua")
        self.resize(900, 700)

        self.inputs = {}
        self._entries = {}
        self._thread = None
        self._worker = None
        self._resimplify_thread = None
        self._resimplify_worker = None

        self.default_sieve_size = 2
        self.default_hole_fill_size = 10
        self.default_iterations = 1
        self.last_run_success = False

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.setup_tab = QWidget()
        self.run_tab = QWidget()
        self.about_tab = QWidget()
        self.tabs.addTab(self.setup_tab, "Input and Setup")
        self.tabs.addTab(self.run_tab, "Calculation and Log")
        self.tabs.addTab(self.about_tab, "About")

        self._build_setup_tab()
        self._build_run_tab()
        self._build_about_tab()

    # ---------- about tab ----------

    def _build_about_tab(self):
        layout = QVBoxLayout(self.about_tab)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)

        readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                text = f.read()
            if hasattr(browser, "setMarkdown"):
                browser.setMarkdown(text)
            else:
                browser.setPlainText(text)
        except OSError as e:
            browser.setPlainText(f"Could not load README.md: {e}")

        layout.addWidget(browser)

    # ---------- setup tab ----------

    def _add_file_row(self, layout, label, key, file_filter, multi=False):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        entry = QLineEdit()
        self._entries[key] = entry
        row.addWidget(entry)
        browse_btn = QPushButton("Browse...")

        def browse():
            if multi:
                files, _ = QFileDialog.getOpenFileNames(self, f"Select {label}", "", file_filter)
            else:
                path, _ = QFileDialog.getOpenFileName(self, f"Select {label}", "", file_filter)
                files = [path] if path else []
            if files:
                entry.setText(";".join(files))
                self.inputs[key] = files if multi else files[0]

        browse_btn.clicked.connect(browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

    def _add_folder_row(self, layout, label, key):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        entry = QLineEdit()
        self._entries[key] = entry
        row.addWidget(entry)
        browse_btn = QPushButton("Browse...")

        def browse():
            folder = QFileDialog.getExistingDirectory(self, f"Select {label}")
            if folder:
                entry.setText(folder)
                self.inputs[key] = folder

        browse_btn.clicked.connect(browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

    def _build_setup_tab(self):
        layout = QVBoxLayout(self.setup_tab)

        raster_ft = "GeoTIFF (*.tif);;All files (*)"
        vector_ft = "Vector files (*.shp *.gpkg);;All files (*)"
        csv_ft = "CSV files (*.csv);;All files (*)"

        layout.addWidget(QLabel("<b>A. Core Inputs</b>"))
        self._add_file_row(layout, "DEM (any resolution)", "dem", raster_ft)
        self._add_file_row(layout, "Watershed Vector (for Extent)", "watershed", vector_ft)
        self._add_file_row(layout, "Monthly Total Rainfall (any resolution)", "rainfall", raster_ft, multi=True)

        layout.addWidget(QLabel("<b>B. Thematic Layer Inputs</b>"))
        self._add_file_row(layout, "Soil Vector", "soil", vector_ft)
        self._add_file_row(layout, "K Factor Lookup (.csv)", "k_lookup", csv_ft)
        self._add_file_row(layout, "River Vector", "river", vector_ft)
        self._add_file_row(layout, "Land Cover Vector", "land_cover", vector_ft)
        self._add_file_row(layout, "Protected Area Vector (Optional)", "protected_area", vector_ft)

        layout.addWidget(QLabel("<b>Output Folder</b>"))
        self._add_folder_row(layout, "Select Output Folder", "output_folder")

        layout.addWidget(QLabel("<b>C. Pre-Computation Setup</b>"))
        setup_row = QHBoxLayout()
        soil_btn = QPushButton("Setup Soil Matches")
        soil_btn.clicked.connect(self._setup_soil_matches)
        setup_row.addWidget(soil_btn)
        forest_btn = QPushButton("Setup Forest Selection")
        forest_btn.clicked.connect(self._setup_forest_selection)
        setup_row.addWidget(forest_btn)
        layout.addLayout(setup_row)

        layout.addStretch()

    # ---------- run tab ----------

    def _build_run_tab(self):
        layout = QHBoxLayout(self.run_tab)

        log_col = QVBoxLayout()
        self.run_button = QPushButton("Run Full Analysis")
        self.run_button.clicked.connect(self._start_analysis)
        log_col.addWidget(self.run_button)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        log_col.addWidget(self.log_box)
        layout.addLayout(log_col, 3)

        status_col = QVBoxLayout()
        status_col.addWidget(QLabel("<b>Processing Status</b>"))
        self.steps = ["R Factor", "K Factor", "LS & SLT Factors", "SEP & SEI", "Thematic Layers",
                      "Final Classification"]
        self.status_labels = {}
        for i, step in enumerate(self.steps):
            lbl = QLabel(f"Module {i + 1}: {step}")
            lbl.setStyleSheet(_IDLE_STYLE)
            status_col.addWidget(lbl)
            self.status_labels[i + 1] = lbl

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        status_col.addWidget(reset_btn)

        status_col.addWidget(QLabel("<b>Simplification</b>"))
        grid = QGridLayout()
        grid.addWidget(QLabel("Sieve size:"), 0, 0)
        self.sieve_size_spin = QSpinBox()
        self.sieve_size_spin.setRange(1, 1000)
        self.sieve_size_spin.setValue(self.default_sieve_size)
        grid.addWidget(self.sieve_size_spin, 0, 1)
        grid.addWidget(QLabel("Hole fill size:"), 1, 0)
        self.hole_fill_spin = QSpinBox()
        self.hole_fill_spin.setRange(1, 1000)
        self.hole_fill_spin.setValue(self.default_hole_fill_size)
        grid.addWidget(self.hole_fill_spin, 1, 1)
        grid.addWidget(QLabel("Iterations:"), 2, 0)
        self.iterations_spin = QSpinBox()
        self.iterations_spin.setRange(1, 20)
        self.iterations_spin.setValue(self.default_iterations)
        grid.addWidget(self.iterations_spin, 2, 1)
        status_col.addLayout(grid)

        self.resimplify_button = QPushButton("Recalculate Simplified Map")
        self.resimplify_button.setEnabled(False)
        self.resimplify_button.clicked.connect(self._recalculate_simplified_only)
        status_col.addWidget(self.resimplify_button)

        status_col.addStretch()
        layout.addLayout(status_col, 1)

    # ---------- setup dialogs ----------

    def _setup_soil_matches(self):
        if not self.inputs.get("soil") or not self.inputs.get("k_lookup"):
            QMessageBox.critical(self, "Error", "Please select the Soil Vector and K Factor Lookup CSV first.")
            return
        dialog = SoilMatchDialog(self, self.inputs["soil"], self.inputs["k_lookup"])
        if dialog.exec_() and dialog.result:
            self.inputs["soil_field"] = dialog.result["field"]
            self.inputs["soil_map"] = dialog.build_soil_map()
            QMessageBox.information(self, "Success", "Soil matching is configured.")

    def _setup_forest_selection(self):
        if not self.inputs.get("land_cover"):
            QMessageBox.critical(self, "Error", "Please select the Land Cover Vector file first.")
            return
        dialog = ForestSelectDialog(self, self.inputs["land_cover"])
        if dialog.exec_() and dialog.result:
            self.inputs["land_cover_field"] = dialog.result["field"]
            self.inputs["forest_values"] = dialog.result["values"]
            QMessageBox.information(self, "Success", "Forest selection is configured.")

    # ---------- run ----------

    def _start_analysis(self):
        required = ["dem", "watershed", "rainfall", "soil", "k_lookup", "river", "land_cover",
                    "output_folder", "soil_field", "soil_map", "land_cover_field", "forest_values"]
        if not all(k in self.inputs for k in required):
            QMessageBox.critical(
                self, "Error",
                "Missing required inputs. Please fill all fields and complete both "
                "'Setup Soil Matches' and 'Setup Forest Selection'.")
            return

        for lbl in self.status_labels.values():
            lbl.setStyleSheet(_IDLE_STYLE)
        self.run_button.setEnabled(False)
        self.run_button.setText("Running...")
        self.tabs.setCurrentWidget(self.run_tab)

        self._thread = QThread(self)
        self._worker = AnalysisWorker(
            dict(self.inputs), self.inputs["output_folder"],
            self.sieve_size_spin.value(), self.hole_fill_spin.value(), self.iterations_spin.value())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._on_log)
        self._worker.outputs_ready.connect(self._on_analysis_outputs_ready)
        self._worker.finished.connect(self._on_analysis_complete)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_log(self, message):
        if message.startswith("MODULE_COMPLETE:"):
            module_num = int(message.split(":")[1])
            if module_num in self.status_labels:
                self.status_labels[module_num].setStyleSheet(_DONE_STYLE)
        else:
            self.log_box.appendPlainText(message)

    def _on_analysis_complete(self, success):
        self.last_run_success = success
        self.run_button.setEnabled(True)
        self.run_button.setText("Run Full Analysis")
        self.resimplify_button.setEnabled(success)

    def _load_raster_layer(self, path, name):
        if not path or not os.path.exists(path):
            return
        layer = QgsRasterLayer(path, name)
        if not layer.isValid():
            self.log_box.appendPlainText(f"WARNING: could not load {path} as a layer.")
            return
        qml_path = os.path.splitext(path)[0] + ".qml"
        if os.path.exists(qml_path):
            layer.loadNamedStyle(qml_path)
            layer.triggerRepaint()
        QgsProject.instance().addMapLayer(layer)

    def _on_analysis_outputs_ready(self, final_path, simplified_path):
        self._load_raster_layer(final_path, "Land Capability Classes")
        self._load_raster_layer(simplified_path, "Land Capability Classes (simplified)")

    def _on_resimplify_outputs_ready(self, simplified_path):
        self._load_raster_layer(simplified_path, os.path.basename(simplified_path))

    def _recalculate_simplified_only(self):
        output_folder = self.inputs.get("output_folder")
        if not output_folder:
            QMessageBox.critical(
                self, "Error", "Output folder is not set. Run the full analysis at least once first.")
            return

        sieve_size = self.sieve_size_spin.value()
        hole_fill_size = self.hole_fill_spin.value()
        iterations = self.iterations_spin.value()
        self.log_box.appendPlainText(
            f"Recalculating simplified classification "
            f"(sieve={sieve_size}, holes={hole_fill_size}, iter={iterations})...")

        self._resimplify_thread = QThread(self)
        self._resimplify_worker = ResimplifyWorker(output_folder, sieve_size, hole_fill_size, iterations)
        self._resimplify_worker.moveToThread(self._resimplify_thread)
        self._resimplify_thread.started.connect(self._resimplify_worker.run)
        self._resimplify_worker.log.connect(self._on_log)
        self._resimplify_worker.outputs_ready.connect(self._on_resimplify_outputs_ready)
        self._resimplify_worker.finished.connect(self._resimplify_thread.quit)
        self._resimplify_thread.start()

    def _reset(self):
        self.inputs.clear()
        for entry in self._entries.values():
            entry.clear()
        self.log_box.clear()
        for lbl in self.status_labels.values():
            lbl.setStyleSheet(_IDLE_STYLE)
        self.sieve_size_spin.setValue(self.default_sieve_size)
        self.hole_fill_spin.setValue(self.default_hole_fill_size)
        self.iterations_spin.setValue(self.default_iterations)
        self.last_run_success = False
        self.resimplify_button.setEnabled(False)
        self.tabs.setCurrentWidget(self.setup_tab)
        self.log_box.appendPlainText("--- Application Reset ---")
        self.run_button.setEnabled(True)
        self.run_button.setText("Run Full Analysis")
