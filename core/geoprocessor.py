"""Land capability classification workflow, ported from the desktop tool's
geoprocessing.py onto native QGIS/GDAL APIs instead of rasterio/geopandas,
so the plugin needs no packages beyond what QGIS's bundled Python ships.

NOTE ON VERIFICATION: all Processing algorithm IDs/parameter names/enum
values used below were checked against a running QGIS 3.44 instance
(algorithmDefinitions() + live parameter option lists), and
_generate_reference_grid/_align_raster's gdal:rasterize/gdal:warpreproject
calls were run end-to-end against the project's real DEM and watershed,
reproducing the nodata-corruption fix correctly. The native:buffer/
native:dissolve/native:boundary/gdal:sieve calls in modules 5-6 have only
had their parameter names confirmed to exist, not been run against real
data yet - see CHANGELOG.md's "Not yet verified" section.
"""

import csv
import os
import time

import numpy as np
from osgeo import gdal

import processing
from qgis.core import QgsVectorLayer, QgsRasterLayer, QgsField
from qgis.PyQt.QtCore import QVariant

from .whitebox_runner import get_whitebox_tools

gdal.UseExceptions()

_NUMPY_TO_GDAL = {
    "uint8": gdal.GDT_Byte,
    "int16": gdal.GDT_Int16,
    "uint16": gdal.GDT_UInt16,
    "int32": gdal.GDT_Int32,
    "uint32": gdal.GDT_UInt32,
    "float32": gdal.GDT_Float32,
    "float64": gdal.GDT_Float64,
}

_RESAMPLE_ENUM = {
    "near": 0, "bilinear": 1, "cubic": 2, "cubicspline": 3,
    "lanczos": 4, "average": 5, "mode": 6, "max": 7, "min": 8,
}

CLASS_ROWS = [
    (1, "Strict Protection"),
    (2, "Protection and Production Buffers"),
    (3, "Agroforestry Production"),
    (4, "Limited Production"),
    (5, "Unlimited Production"),
]
CLASS_COLORS = {1: "#0f7e00", 2: "#4bad05", 3: "#efef15", 4: "#eb9c34", 5: "#ea2121"}


class GeoProcessor:
    def __init__(self, logger_callback=print, feedback=None):
        self.logger = logger_callback
        self.feedback = feedback
        self.ref_meta = {}
        self._scratch_folder = None
        self.last_final_path = None
        self.last_simplified_path = None
        self.wbt = get_whitebox_tools()

    # ---------- raster I/O ----------

    def _get_unique_filepath(self, filepath):
        if not os.path.exists(filepath):
            return filepath
        base, ext = os.path.splitext(filepath)
        count = 1
        while True:
            candidate = f"{base}_{count}{ext}"
            if not os.path.exists(candidate):
                return candidate
            count += 1

    def _read_array(self, path):
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray().astype(np.float64)
        nodata = band.GetNoDataValue()
        ds = None
        return arr, nodata

    def _save_raster(self, data, path, nodata=None):
        unique_path = self._get_unique_filepath(path)
        gdal_dtype = _NUMPY_TO_GDAL.get(data.dtype.name, gdal.GDT_Float32)
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(unique_path, self.ref_meta["width"], self.ref_meta["height"], 1, gdal_dtype)
        ds.SetGeoTransform(self.ref_meta["geotransform"])
        ds.SetProjection(self.ref_meta["crs"].toWkt())
        band = ds.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.WriteArray(data)
        band.FlushCache()
        ds = None
        self.logger(f"SUCCESS: Saved raster to {unique_path}")
        return unique_path

    def _create_qml_style(self, qml_path, class_rows, color_map):
        self.logger("...creating QGIS style file (.qml).")
        lines = [
            "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>",
            '<qgis version="3.28.0-Firenze" styleCategories="AllStyleCategories">',
            "  <pipe>",
            '    <rasterrenderer renderer="paletted" nodataColor="" alphaBand="-1" band="1" type="paletted">',
            "      <rasterTransparency/>",
            "      <minMaxOrigin>",
            "        <limits>None</limits>",
            "        <extent>WholeRaster</extent>",
            "        <statAccuracy>Estimated</statAccuracy>",
            "        <cumulativeCutLower>0.02</cumulativeCutLower>",
            "        <cumulativeCutUpper>0.98</cumulativeCutUpper>",
            "        <stdDevFactor>2</stdDevFactor>",
            "      </minMaxOrigin>",
            "      <colorPalette>",
        ]
        for value, label in class_rows:
            color = color_map.get(value, "#000000")
            lines.append(f'        <paletteEntry value="{value}" label="{label}" color="{color}" alpha="255"/>')
        lines += ["      </colorPalette>", "    </rasterrenderer>", "  </pipe>", "</qgis>"]
        try:
            with open(qml_path, "w") as f:
                f.write("\n".join(lines))
            self.logger(f"SUCCESS: Saved QML style to {os.path.basename(qml_path)}")
        except Exception as e:
            self.logger(f"ERROR: Could not write QML file: {e}")

    # ---------- reference grid ----------

    def _get_raster_resolution(self, raster_path):
        ds = gdal.Open(raster_path)
        gt = ds.GetGeoTransform()
        return max(abs(gt[1]), abs(gt[5]))

    def _determine_reference_resolution(self, raster_paths):
        resolutions = {path: self._get_raster_resolution(path) for path in raster_paths}
        coarsest_path = max(resolutions, key=resolutions.get)
        coarsest_res = resolutions[coarsest_path]

        self.logger("...checking input raster resolutions:")
        for path, res in resolutions.items():
            self.logger(f"    - {os.path.basename(path)}: {res:.2f}m")
        self.logger(
            f"NOTICE: Final analysis resolution set to {coarsest_res:.2f}m "
            f"because '{os.path.basename(coarsest_path)}' has {coarsest_res:.2f}m "
            f"resolution, the coarsest among all input rasters."
        )
        return coarsest_res

    def _reproject_if_needed(self, layer):
        if layer.crs() != self.ref_meta["crs"]:
            return processing.run("native:reprojectlayer", {
                "INPUT": layer, "TARGET_CRS": self.ref_meta["crs"], "OUTPUT": "memory:",
            }, feedback=self.feedback)["OUTPUT"]
        return layer

    def _generate_reference_grid(self, dem_path, watershed_path, resolution, scratch_folder):
        self.logger("Step 0: Generating Reference Grid...")
        dem_layer = QgsRasterLayer(dem_path, "dem")
        dem_crs = dem_layer.crs()

        # ref_meta is populated incrementally here because _reproject_if_needed
        # and the rasterize call below both need it before the grid is fully built.
        self.ref_meta = {"crs": dem_crs, "resolution": resolution, "nodata": -9999}

        watershed_layer = self._reproject_if_needed(QgsVectorLayer(watershed_path, "watershed", "ogr"))
        extent = watershed_layer.extent()
        extent_str = (
            f"{extent.xMinimum()},{extent.xMaximum()},"
            f"{extent.yMinimum()},{extent.yMaximum()} [{dem_crs.authid()}]"
        )
        width = round((extent.xMaximum() - extent.xMinimum()) / resolution)
        height = round((extent.yMaximum() - extent.yMinimum()) / resolution)

        self.ref_meta.update({
            "extent": extent,
            "extent_str": extent_str,
            "geotransform": (extent.xMinimum(), resolution, 0, extent.yMaximum(), 0, -resolution),
            "width": width,
            "height": height,
        })

        mask_path = os.path.join(scratch_folder, "ref_mask.tif")
        processing.run("gdal:rasterize", {
            "INPUT": watershed_layer, "FIELD": None, "BURN": 1, "USE_Z": False,
            "UNITS": 1, "WIDTH": resolution, "HEIGHT": resolution,
            "EXTENT": extent_str, "NODATA": 0, "OPTIONS": "", "DATA_TYPE": 0,
            "INIT": None, "INVERT": False, "EXTRA": "", "OUTPUT": mask_path,
        }, feedback=self.feedback)

        ref_mask, _ = self._read_array(mask_path)
        self.logger(f"...Reference Grid generated successfully at {resolution:.2f}m resolution.")
        return ref_mask.astype("uint8")

    def _align_raster(self, raster_path, resample_alg="bilinear"):
        src_ds = gdal.Open(raster_path)
        src_nodata = src_ds.GetRasterBand(1).GetNoDataValue()
        src_ds = None

        result = processing.run("gdal:warpreproject", {
            "INPUT": raster_path,
            "TARGET_CRS": self.ref_meta["crs"],
            "RESAMPLING": _RESAMPLE_ENUM[resample_alg],
            "NODATA": src_nodata,
            "TARGET_RESOLUTION": self.ref_meta["resolution"],
            "OPTIONS": "",
            "TARGET_EXTENT": self.ref_meta["extent"],
            "TARGET_EXTENT_CRS": self.ref_meta["crs"],
            "MULTITHREADING": False,
            "EXTRA": f"-dstnodata {self.ref_meta['nodata']}",
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)

        arr, _ = self._read_array(result["OUTPUT"])
        return arr

    # ---------- vector helpers (buffers, rasterizing) ----------

    def _buffer_layer(self, layer, distance, dissolve=False):
        layer = self._reproject_if_needed(layer)
        result = processing.run("native:buffer", {
            "INPUT": layer, "DISTANCE": distance, "SEGMENTS": 8,
            "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "MITER_LIMIT": 2,
            "DISSOLVE": dissolve, "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)
        return result["OUTPUT"]

    def _buffer_boundary(self, layer, distance):
        """Dissolves `layer`, extracts its outer boundary, then buffers that
        boundary line - mirrors the desktop tool's
        dissolved.boundary.buffer(distance) for ridge/forest-edge buffers.
        """
        layer = self._reproject_if_needed(layer)
        dissolved = processing.run("native:dissolve", {
            "INPUT": layer, "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)["OUTPUT"]
        boundary = processing.run("native:boundary", {
            "INPUT": dissolved, "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)["OUTPUT"]
        return self._buffer_layer(boundary, distance)

    def _rasterize_binary(self, layer):
        result = processing.run("gdal:rasterize", {
            "INPUT": layer, "FIELD": None, "BURN": 1, "USE_Z": False,
            "UNITS": 1, "WIDTH": self.ref_meta["resolution"], "HEIGHT": self.ref_meta["resolution"],
            "EXTENT": self.ref_meta["extent_str"], "NODATA": 0, "OPTIONS": "",
            "DATA_TYPE": 0, "INIT": None, "INVERT": False, "EXTRA": "",
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)
        arr, _ = self._read_array(result["OUTPUT"])
        return arr.astype("uint8")

    def _sieve(self, path, threshold):
        result = processing.run("gdal:sieve", {
            "INPUT": path, "THRESHOLD": threshold, "EIGHT_CONNECTEDNESS": True,
            "NO_MASK": False, "MASK_LAYER": None, "EXTRA": "",
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)
        arr, _ = self._read_array(result["OUTPUT"])
        return arr

    # ---------- module 1: R factor ----------

    def run_module1_r_factor(self, rainfall_paths):
        self.logger("Module 1: Calculating R Factor...")
        p_total = np.zeros((self.ref_meta["height"], self.ref_meta["width"]), dtype=np.float64)
        sum_of_squares = np.zeros_like(p_total)
        for path in rainfall_paths:
            pi_array = self._align_raster(path)
            p_total += pi_array
            sum_of_squares += pi_array ** 2
        return np.where(p_total > 0, sum_of_squares / p_total, 0)

    # ---------- module 2: K factor ----------

    def run_module2_k_factor(self, soil_path, soil_field, soil_map):
        self.logger("Module 2: Calculating K Factor...")
        soil_layer = self._reproject_if_needed(QgsVectorLayer(soil_path, "soil", "ogr"))

        soil_layer.dataProvider().addAttributes([QgsField("Kvalue", QVariant.Double)])
        soil_layer.updateFields()
        field_idx = soil_layer.fields().indexFromName(soil_field)
        kvalue_idx = soil_layer.fields().indexFromName("Kvalue")

        soil_layer.startEditing()
        for feature in soil_layer.getFeatures():
            soil_layer.changeAttributeValue(feature.id(), kvalue_idx, soil_map.get(feature[field_idx], 0.0))
        soil_layer.commitChanges()

        result = processing.run("gdal:rasterize", {
            "INPUT": soil_layer, "FIELD": "Kvalue", "BURN": 0, "USE_Z": False,
            "UNITS": 1, "WIDTH": self.ref_meta["resolution"], "HEIGHT": self.ref_meta["resolution"],
            "EXTENT": self.ref_meta["extent_str"], "NODATA": 0, "OPTIONS": "",
            "DATA_TYPE": 5, "INIT": None, "INVERT": False, "EXTRA": "",
            "OUTPUT": "TEMPORARY_OUTPUT",
        }, feedback=self.feedback)

        k_factor, _ = self._read_array(result["OUTPUT"])
        return k_factor

    # ---------- module 3: LS & SLT factors ----------

    def run_module3_ls_slt_factors(self, dem_path, scratch_folder):
        self.logger("Module 3: Calculating Topographic Factors...")
        dem_aligned = self._align_raster(dem_path)

        temp_dem_path = os.path.join(scratch_folder, "wbt_dem.tif")
        self._save_raster(dem_aligned.astype("float32"), temp_dem_path, nodata=self.ref_meta["nodata"])

        self.logger("...filling pits using WhiteboxTools")
        temp_filled_dem_path = os.path.join(scratch_folder, "wbt_filled_dem.tif")
        self.wbt.fill_depressions(temp_dem_path, temp_filled_dem_path)
        time.sleep(1)

        self.logger("...calculating flow accumulation using WhiteboxTools")
        temp_flow_acc_path = os.path.join(scratch_folder, "wbt_flow_acc.tif")
        self.wbt.d8_flow_accumulation(temp_filled_dem_path, temp_flow_acc_path, out_type="cells")
        time.sleep(1)

        flow_acc_cells, _ = self._read_array(temp_flow_acc_path)
        pixel_area = self.ref_meta["resolution"] ** 2
        flow_acc_area = flow_acc_cells * pixel_area

        self.logger("...calculating slope using GDAL")
        temp_slope_path = os.path.join(scratch_folder, "gdal_slope.tif")
        gdal.DEMProcessing(temp_slope_path, temp_filled_dem_path, "slope", slopeFormat="percent")
        slope_pct, _ = self._read_array(temp_slope_path)

        slope_rad = np.arctan(slope_pct / 100.0)
        L = (flow_acc_area / 22.13) ** 0.4
        base_S = np.sin(slope_rad) / 0.0896
        S = np.where(slope_rad > 0, np.power(np.maximum(0, base_S), 1.4), 0)
        ls_factor = np.nan_to_num(L * S)
        conditions = [
            (slope_pct < 3), (slope_pct >= 3) & (slope_pct < 8), (slope_pct >= 8) & (slope_pct < 18),
            (slope_pct >= 18) & (slope_pct < 30), (slope_pct >= 30) & (slope_pct < 50), (slope_pct >= 50),
        ]
        values = [20, 15, 12, 10, 7, 5]
        slt_factor = np.select(conditions, values).astype("uint8")
        return ls_factor, slt_factor, slope_pct, dem_aligned

    # ---------- module 5: thematic layers ----------

    def run_module5_thematic_layers(self, sei_factor, dem_aligned, slope_pct,
                                     land_cover_path, land_cover_field, forest_values,
                                     watershed_path, river_path):
        self.logger("Module 5: Creating Thematic Layers...")
        outputs = {}

        self.logger("... (A) Reclassifying SEI Factor")
        conditions_sei = [
            (sei_factor < 1), (sei_factor >= 1) & (sei_factor < 2), (sei_factor >= 2) & (sei_factor < 3),
            (sei_factor >= 3) & (sei_factor < 4), (sei_factor >= 4),
        ]
        outputs["SEI_Reclass"] = np.select(conditions_sei, [1, 2, 3, 4, 5]).astype("uint8")

        self.logger("... (B) Reclassifying Elevation")
        outputs["Elev_Reclass"] = np.where(dem_aligned < 1000, 1, 2).astype("uint8")

        self.logger("... (C) Reclassifying Slope")
        outputs["Slope_Reclass"] = np.where(slope_pct < 50, 1, 2).astype("uint8")

        self.logger("... (F) Processing Forest Presence")
        lc_layer = QgsVectorLayer(land_cover_path, "land_cover", "ogr")
        quoted_values = ", ".join("'{}'".format(v.replace("'", "''")) for v in forest_values)
        lc_layer.setSubsetString(f'"{land_cover_field}" IN ({quoted_values})')
        outputs["Forest_Presence"] = self._rasterize_binary(lc_layer)

        self.logger("... (G) Generating Forest Buffer")
        outputs["Forest_Buffer"] = self._rasterize_binary(self._buffer_boundary(lc_layer, 50))

        self.logger("... (D & E) Generating Ridge and River Buffers")
        watershed_layer = QgsVectorLayer(watershed_path, "watershed", "ogr")
        outputs["Ridge_Buffer"] = self._rasterize_binary(self._buffer_boundary(watershed_layer, 50))

        river_layer = QgsVectorLayer(river_path, "river", "ogr")
        outputs["River_Buffer"] = self._rasterize_binary(self._buffer_layer(river_layer, 40, dissolve=True))

        return outputs

    # ---------- despeckle cleanup ----------

    def _load_protection_masks(self, output_folder):
        intermediate_folder = os.path.join(output_folder, "Intermediate Outputs")
        required = ["SEI_Reclass", "Forest_Presence", "Slope_Reclass", "Elev_Reclass",
                    "Forest_Buffer", "River_Buffer", "Ridge_Buffer", "Protected_Area"]
        paths = {name: os.path.join(intermediate_folder, f"{name}.tif") for name in required}
        if not all(os.path.exists(p) for p in paths.values()):
            self.logger("...intermediate layers not found; skipping buffer/protection re-stamping")
            return None

        def _read(name):
            arr, _ = self._read_array(paths[name])
            return arr

        buffer_mask = (_read("Forest_Buffer") == 1) | (_read("River_Buffer") == 1) | (_read("Ridge_Buffer") == 1)
        strict_mask = (
            (_read("SEI_Reclass") == 5) | (_read("Forest_Presence") == 1) |
            (_read("Slope_Reclass") == 2) | (_read("Elev_Reclass") == 2) | (_read("Protected_Area") == 1)
        )
        return buffer_mask, strict_mask

    def _clean_classification_array(self, class_array, sieve_size, hole_fill_size, iterations, protect_masks=None):
        self.logger(f"--- Cleaning classification ({iterations} iteration(s)) ---")
        nodata_mask = class_array == 0
        current = class_array.astype("uint8")
        tmp_path = os.path.join(self._scratch_folder, "sieve_in.tif")

        for i in range(iterations):
            self.logger(f"--- Cleaning Iteration {i+1}/{iterations}: sieve(size={sieve_size}) then sieve(size={hole_fill_size}) ---")
            self._save_raster(current, tmp_path, nodata=0)
            current = self._sieve(tmp_path, sieve_size).astype("uint8")
            self._save_raster(current, tmp_path, nodata=0)
            current = self._sieve(tmp_path, hole_fill_size).astype("uint8")

        if protect_masks is not None:
            self.logger("...re-applying buffer and strict-protection classes")
            buffer_mask, strict_mask = protect_masks
            current[buffer_mask] = 2
            current[strict_mask] = 1  # highest priority, applied last

        current[nodata_mask] = 0
        return current

    def _load_ref_meta_from_raster(self, path):
        """Populates self.ref_meta (crs/geotransform/width/height) from an
        existing raster's own georeferencing. _save_raster needs these, but
        a standalone recompute_simplified_classification call - e.g. from
        the "Recalculate Simplified Map" button, on a fresh GeoProcessor
        that never ran _generate_reference_grid - would otherwise have
        nothing to read them from.
        """
        from qgis.core import QgsCoordinateReferenceSystem
        ds = gdal.Open(path)
        crs = QgsCoordinateReferenceSystem()
        crs.createFromWkt(ds.GetProjection())
        self.ref_meta.update({
            "crs": crs,
            "geotransform": ds.GetGeoTransform(),
            "width": ds.RasterXSize,
            "height": ds.RasterYSize,
        })
        ds = None

    def recompute_simplified_classification(self, output_folder, sieve_size=2, hole_fill_size=10, iterations=1):
        base_path = os.path.join(output_folder, "Land_Capability_Classes.tif")
        if not os.path.exists(base_path):
            self.logger(f"ERROR: Base classification raster not found at {base_path}")
            return False

        self._load_ref_meta_from_raster(base_path)
        self._scratch_folder = os.path.join(output_folder, "scratch")
        os.makedirs(self._scratch_folder, exist_ok=True)

        class_array, _ = self._read_array(base_path)
        settings_tag = f"S{sieve_size}H{hole_fill_size}I{iterations}"
        simplified_path = os.path.join(output_folder, f"Land_Capability_Classes_simplified_{settings_tag}.tif")

        self.logger(
            f"Recomputing simplified classification "
            f"(sieve={sieve_size}, holes={hole_fill_size}, iter={iterations}) "
            f"-> {os.path.basename(simplified_path)}"
        )

        protect_masks = self._load_protection_masks(output_folder)
        cleaned = self._clean_classification_array(class_array, sieve_size, hole_fill_size, iterations, protect_masks)
        simplified_path = self._save_raster(cleaned, simplified_path, nodata=0)
        self.last_simplified_path = simplified_path

        qml_path = os.path.splitext(simplified_path)[0] + ".qml"
        self._create_qml_style(qml_path, CLASS_ROWS, CLASS_COLORS)
        return True

    # ---------- full workflow ----------

    def run_full_analysis(self, inputs, output_folder, sieve_size=2, hole_fill_size=10, iterations=1):
        try:
            self._scratch_folder = os.path.join(output_folder, "scratch")
            intermediate_folder = os.path.join(output_folder, "Intermediate Outputs")
            os.makedirs(intermediate_folder, exist_ok=True)
            os.makedirs(self._scratch_folder, exist_ok=True)

            raster_inputs = [inputs["dem"]] + list(inputs["rainfall"])
            resolution = self._determine_reference_resolution(raster_inputs)
            ref_mask = self._generate_reference_grid(
                inputs["dem"], inputs["watershed"], resolution, self._scratch_folder)

            r_factor = self.run_module1_r_factor(inputs["rainfall"])
            self._save_raster(r_factor * ref_mask, os.path.join(intermediate_folder, "R_Factor.tif"),
                               nodata=self.ref_meta["nodata"])
            self.logger("MODULE_COMPLETE:1")

            k_factor = self.run_module2_k_factor(inputs["soil"], inputs["soil_field"], inputs["soil_map"])
            self._save_raster(k_factor * ref_mask, os.path.join(intermediate_folder, "K_Factor.tif"),
                               nodata=self.ref_meta["nodata"])
            self.logger("MODULE_COMPLETE:2")

            ls_factor, slt_factor, slope_pct, dem_aligned = self.run_module3_ls_slt_factors(
                inputs["dem"], self._scratch_folder)
            self._save_raster(ls_factor * ref_mask, os.path.join(intermediate_folder, "LS_Factor.tif"),
                               nodata=self.ref_meta["nodata"])
            self._save_raster((slt_factor * ref_mask).astype("uint8"),
                               os.path.join(intermediate_folder, "SLT_Factor.tif"), nodata=0)
            self.logger("MODULE_COMPLETE:3")

            self.logger("Module 4: Calculating SEP and SEI Factors...")
            sep_factor = np.nan_to_num(r_factor * k_factor * ls_factor)
            sei_factor = np.where(slt_factor > 0, sep_factor / slt_factor, 0)
            self._save_raster(sep_factor * ref_mask, os.path.join(intermediate_folder, "SEP_Factor.tif"),
                               nodata=self.ref_meta["nodata"])
            self._save_raster(sei_factor * ref_mask, os.path.join(intermediate_folder, "SEI_Factor.tif"),
                               nodata=self.ref_meta["nodata"])
            self.logger("MODULE_COMPLETE:4")

            m5_outputs = self.run_module5_thematic_layers(
                sei_factor, dem_aligned, slope_pct,
                inputs["land_cover"], inputs["land_cover_field"], inputs["forest_values"],
                inputs["watershed"], inputs["river"])
            for name, data in m5_outputs.items():
                self._save_raster((data * ref_mask).astype("uint8"),
                                   os.path.join(intermediate_folder, f"{name}.tif"), nodata=0)
            self.logger("MODULE_COMPLETE:5")

            self.logger("Module 6: Final Land Capability Classification...")
            final_map = np.zeros_like(ref_mask, dtype="uint8")
            pa_raster = np.zeros_like(final_map)
            if inputs.get("protected_area"):
                pa_layer = QgsVectorLayer(inputs["protected_area"], "protected_area", "ogr")
                pa_raster = self._rasterize_binary(pa_layer)
            self._save_raster((pa_raster * ref_mask).astype("uint8"),
                               os.path.join(intermediate_folder, "Protected_Area.tif"), nodata=0)

            final_map[m5_outputs["SEI_Reclass"] == 1] = 5
            final_map[m5_outputs["SEI_Reclass"] == 4] = 4
            final_map[np.isin(m5_outputs["SEI_Reclass"], [2, 3])] = 3
            final_map[(m5_outputs["Forest_Buffer"] == 1) | (m5_outputs["River_Buffer"] == 1) |
                      (m5_outputs["Ridge_Buffer"] == 1)] = 2
            final_map[(m5_outputs["SEI_Reclass"] == 5) | (m5_outputs["Forest_Presence"] == 1) |
                      (m5_outputs["Slope_Reclass"] == 2) | (m5_outputs["Elev_Reclass"] == 2) |
                      (pa_raster == 1)] = 1

            final_map_masked = final_map * ref_mask
            final_output_path = self._save_raster(
                final_map_masked, os.path.join(output_folder, "Land_Capability_Classes.tif"), nodata=0)
            self.last_final_path = final_output_path

            csv_path = os.path.splitext(final_output_path)[0] + ".csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Value", "Class_Name"])
                writer.writerows(CLASS_ROWS)
            self.logger(f"SUCCESS: Saved attribute file to {os.path.basename(csv_path)}")

            qml_path = os.path.splitext(final_output_path)[0] + ".qml"
            self._create_qml_style(qml_path, CLASS_ROWS, CLASS_COLORS)

            self.logger("Module 6b: Generating default simplified classification...")
            self.recompute_simplified_classification(
                output_folder, sieve_size=sieve_size, hole_fill_size=hole_fill_size, iterations=iterations)

            self.logger("MODULE_COMPLETE:6")
            self.logger("--- WORKFLOW COMPLETED SUCCESSFULLY ---")
            return True

        except Exception as e:
            self.logger(f"ERROR: An exception occurred: {e}")
            import traceback
            self.logger(traceback.format_exc())
            return False
