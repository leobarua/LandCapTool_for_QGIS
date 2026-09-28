from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessing,
)

from ..core.geoprocessor import GeoProcessor
from ..core.soil_match import build_k_value_map


class LandCapAlgorithm(QgsProcessingAlgorithm):
    DEM = "DEM"
    WATERSHED = "WATERSHED"
    RAINFALL = "RAINFALL"
    SOIL = "SOIL"
    SOIL_TEXTURE_FIELD = "SOIL_TEXTURE_FIELD"
    K_LOOKUP_TABLE = "K_LOOKUP_TABLE"
    RIVER = "RIVER"
    LAND_COVER = "LAND_COVER"
    LAND_COVER_FIELD = "LAND_COVER_FIELD"
    FOREST_CLASS_VALUES = "FOREST_CLASS_VALUES"
    PROTECTED_AREA = "PROTECTED_AREA"
    SIEVE_SIZE = "SIEVE_SIZE"
    HOLE_FILL_SIZE = "HOLE_FILL_SIZE"
    ITERATIONS = "ITERATIONS"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def createInstance(self):
        return LandCapAlgorithm()

    def name(self):
        return "landcap_full_analysis"

    def displayName(self):
        return "Run Full Land Capability Analysis"

    def group(self):
        return "LandCap Assessment"

    def groupId(self):
        return "landcap_assessment"

    def shortHelpString(self):
        return (
            "Runs the full land capability classification workflow: R/K/LS/SEP/SEI "
            "factors, thematic buffer layers, and final classification with despeckle "
            "cleanup.\n\n"
            "The soil-texture-to-K-value match and the forest class selection are "
            "resolved automatically (fuzzy text match / exact value match) rather than "
            "interactively — use the LandCap Assessment dialog (Plugins menu) instead "
            "of this algorithm if you want to review and correct those matches by hand "
            "before running."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(self.DEM, "DEM"))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.WATERSHED, "Watershed boundary", [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.RAINFALL, "Monthly rainfall rasters", QgsProcessing.SourceType.TypeRaster))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.SOIL, "Soil vector", [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.SOIL_TEXTURE_FIELD, "Soil texture field", parentLayerParameterName=self.SOIL))
        self.addParameter(QgsProcessingParameterFile(
            self.K_LOOKUP_TABLE, "K-factor lookup table (CSV, columns: 'Soil Texture', 'Kvalue')",
            extension="csv"))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.RIVER, "River network", [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.LAND_COVER, "Land cover vector", [QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.LAND_COVER_FIELD, "Land cover class field", parentLayerParameterName=self.LAND_COVER))
        self.addParameter(QgsProcessingParameterString(
            self.FOREST_CLASS_VALUES,
            "Land cover values that count as forest (comma-separated, exact match)"))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROTECTED_AREA, "Protected area vector (optional)",
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.SIEVE_SIZE, "Despeckle sieve size (pixels)",
            type=QgsProcessingParameterNumber.Type.Integer, defaultValue=2, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.HOLE_FILL_SIZE, "Despeckle hole-fill size (pixels)",
            type=QgsProcessingParameterNumber.Type.Integer, defaultValue=10, minValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.ITERATIONS, "Despeckle iterations",
            type=QgsProcessingParameterNumber.Type.Integer, defaultValue=1, minValue=1))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, "Output folder"))

    def processAlgorithm(self, parameters, context, feedback):
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        watershed_layer = self.parameterAsVectorLayer(parameters, self.WATERSHED, context)
        rainfall_layers = self.parameterAsLayerList(parameters, self.RAINFALL, context)
        soil_layer = self.parameterAsVectorLayer(parameters, self.SOIL, context)
        soil_field = self.parameterAsString(parameters, self.SOIL_TEXTURE_FIELD, context)
        k_lookup_path = self.parameterAsFile(parameters, self.K_LOOKUP_TABLE, context)
        river_layer = self.parameterAsVectorLayer(parameters, self.RIVER, context)
        land_cover_layer = self.parameterAsVectorLayer(parameters, self.LAND_COVER, context)
        land_cover_field = self.parameterAsString(parameters, self.LAND_COVER_FIELD, context)
        forest_values = [
            v.strip() for v in
            self.parameterAsString(parameters, self.FOREST_CLASS_VALUES, context).split(",")
            if v.strip()
        ]
        protected_area_layer = self.parameterAsVectorLayer(parameters, self.PROTECTED_AREA, context)
        sieve_size = self.parameterAsInt(parameters, self.SIEVE_SIZE, context)
        hole_fill_size = self.parameterAsInt(parameters, self.HOLE_FILL_SIZE, context)
        iterations = self.parameterAsInt(parameters, self.ITERATIONS, context)
        output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)

        feedback.pushInfo("Matching soil texture values to K-factor lookup table...")
        soil_map = build_k_value_map(soil_layer, soil_field, k_lookup_path)

        inputs = {
            "dem": dem_layer.source(),
            "watershed": watershed_layer.source(),
            "rainfall": [lyr.source() for lyr in rainfall_layers],
            "soil": soil_layer.source(),
            "soil_field": soil_field,
            "soil_map": soil_map,
            "river": river_layer.source(),
            "land_cover": land_cover_layer.source(),
            "land_cover_field": land_cover_field,
            "forest_values": forest_values,
            "protected_area": protected_area_layer.source() if protected_area_layer else None,
        }

        processor = GeoProcessor(logger_callback=feedback.pushInfo, feedback=feedback)
        success = processor.run_full_analysis(
            inputs, output_folder,
            sieve_size=sieve_size, hole_fill_size=hole_fill_size, iterations=iterations)

        if not success:
            raise RuntimeError("Land capability analysis failed - see log for details.")

        return {self.OUTPUT_FOLDER: output_folder}
