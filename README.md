# LandCap Assessment Tool - QGIS plugin

QGIS port of the standalone LandCap Assessment desktop tool. Runs the same
land capability classification workflow (R/K/LS/SEP/SEI factors, thematic
buffer layers, final classification with despeckle cleanup) as a Processing
algorithm and a guided dialog inside QGIS.

## Installing

Download the latest release zip from this repo's
[Releases](https://github.com/leobarua/LandCapTool_for_QGIS/releases) page,
then in QGIS: Plugins -> Manage and Install Plugins -> Install from ZIP.

## Layout

- `core/geoprocessor.py` - the workflow itself, ported onto native QGIS/GDAL
  Processing calls (no rasterio/geopandas dependency).
- `core/soil_match.py` - stdlib-only fuzzy text matching (replaces `thefuzz`).
- `core/whitebox_runner.py` - the one remaining bundled dependency: depression
  filling and D8 flow accumulation still run on WhiteboxTools, since no
  stock QGIS/GRASS tool reproduces its flow-accumulation output on the
  drainage network (see that file's docstring for what was tested).
- `processing/` - `QgsProcessingProvider`/`QgsProcessingAlgorithm` for the
  Processing Toolbox / batch / model-builder entry point.
- `gui/` - the guided dialog (`main_dialog.py`) plus the interactive
  soil-texture-match and forest-class-selection popups, for users who want
  to review/correct those matches instead of the algorithm's automatic
  fuzzy/exact matching.

## Setup (Linux/macOS only)

The packaged plugin already bundles a Windows WhiteboxTools binary in
`vendor/whitebox/`, so Windows users have nothing extra to install - just
install the plugin zip and go.

On Linux/macOS, swap in the matching-platform WhiteboxTools binary before
packaging: download it and replace the contents of `vendor/whitebox/` per
`vendor/whitebox/SETUP.md`.
