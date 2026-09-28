# Changelog

## 0.1.1 - unreleased

Initial QGIS port of the desktop LandCap Assessment Tool. (0.1.0 was
submitted to plugins.qgis.org and blocked by their security validator;
0.1.1 is the same work with that fixed - see the WhiteboxTools trim entry
below.)

- Depression-filling and D8 flow accumulation stay on bundled WhiteboxTools
  (`vendor/whitebox/`), unchanged from the desktop tool - validated against
  GRASS's `r.fill.dir`/`r.watershed`/`r.terraflow`, which either matched
  closely (fill) or diverged substantially on the drainage network
  (accumulation); see `core/whitebox_runner.py` for details.
- Everything else (resampling/alignment, K-factor and forest/protected-area
  rasterization, buffers, despeckle cleanup, slope) moved off
  rasterio/geopandas onto native QGIS/GDAL Processing calls, so the plugin
  needs no packages beyond QGIS's bundled Python.
- `thefuzz`/`python-Levenshtein` replaced with stdlib `difflib`
  (`core/soil_match.py`).
- Fixed a data-integrity bug carried over from the desktop tool: aligning a
  raster to the watershed's bounding rectangle left out-of-coverage cells as
  uninitialized memory instead of a proper nodata value (see the
  corresponding fix in the desktop tool's `geoprocessing.py::_align_raster`).

## Verified against a running QGIS 3.44 instance

- All Processing algorithm IDs used in `core/geoprocessor.py`
  (`gdal:warpreproject`, `gdal:rasterize`, `native:buffer`,
  `native:dissolve`, `native:boundary`, `gdal:sieve`,
  `native:reprojectlayer`) exist with the parameter names used here.
- The enum values used (`RESAMPLING=1` for bilinear, `UNITS=1` for
  georeferenced units, `DATA_TYPE=0`/`5` for Byte/Float32 in `gdal:rasterize`,
  `END_CAP_STYLE=0`/`JOIN_STYLE=0` for round caps/joins) all matched the
  installed QGIS's actual enum option lists.
- Ran `_generate_reference_grid`'s and `_align_raster`'s `gdal:rasterize`/
  `gdal:warpreproject` calls live against the project's real DEM and
  watershed vector: output shapes agree between the two calls, and the
  aligned DEM correctly carries `nodata=-9999` with min/max matching the
  fixed desktop tool's output - the nodata-corruption fix reproduces
  correctly through the native API path.
- Ran `run_module5_thematic_layers` and `_clean_classification_array` (the
  actual plugin module, not a reimplementation) against the real land
  cover, watershed, river, and protected-area vectors in
  `data/LandCapability/InputData`. Forest/ridge/river buffer and forest/
  protected-area rasterization fractions are all physically plausible
  (13.25%/8.62%/1.26%/0.63%/4.98% of the grid respectively); the sieve-based
  cleanup conserves total cell count exactly before and after despeckling.
  No errors or warnings anywhere in the run.

- Ran a full `run_full_analysis` end-to-end (not module-by-module) against
  all real inputs in `data/LandCapability/InputData` - all 12 rainfall
  rasters, soil + K-factor lookup, land cover, river, watershed, protected
  areas. Completed successfully in ~114s. Checked the resulting factor
  rasters for NaN/Inf contamination (none), confirmed K-factor values land
  exactly in the lookup table's range, and traced the classification's heavy
  skew toward "Strict Protection" (~88% of in-watershed area) back to the
  SEI reclass thresholds - unchanged from the original tool, and consistent
  with this watershed's genuinely steep terrain (27% of area >=50% slope).
- Trimmed `vendor/whitebox/` from ~198MB to ~28MB by removing files
  confirmed unused by `whitebox_tools.py`'s subprocess wrapper (the `WBT/`
  subfolder, extension `plugins/`, the GUI runner exe, sample data) - see
  `vendor/whitebox/SETUP.md`. Re-ran the full analysis against the trimmed
  folder to confirm nothing broke.
- Fixed a real crash found via actual in-QGIS testing (not caught by any of
  the scripted verification above, since that ran through a console-attached
  `python-qgis-ltr.bat`, not the GUI runtime): `vendor/whitebox/
  whitebox_tools.py` calls `sys.stdout.flush()` unconditionally after every
  line of subprocess output, and QGIS's embedded Python has no attached
  console, so `sys.stdout`/`sys.stderr` are `None` there - crashing on the
  first `fill_depressions` call with `AttributeError: 'NoneType' object has
  no attribute 'flush'`. Same root cause the desktop tool's `main_app.py`
  already guards against with a dummy-stream fallback; `core/
  whitebox_runner.py` now installs the same guard before constructing
  `WhiteboxTools()`, without touching the vendored file. Verified the fix by
  forcing `sys.stdout = sys.stderr = None` and confirming `fill_depressions`
  completes cleanly.
- Fixed a second real crash, also only found via in-QGIS testing: the
  "Recalculate Simplified Map" button crashed with `expected str, bytes or
  os.PathLike object, not NoneType`. Root cause: `_save_raster` reads
  width/height/geotransform/crs off `self.ref_meta`, which is only
  populated by `_generate_reference_grid` during a full run - but
  `recompute_simplified_classification` runs on a *fresh* `GeoProcessor`
  with an empty `ref_meta` when triggered standalone from that button. The
  original desktop tool avoided this by reading georeferencing straight off
  the raster being cleaned rather than from separately-tracked state; added
  `_load_ref_meta_from_raster` to do the same here. Verified by reproducing
  the exact reported parameters (sieve=4, holes=12) against a fresh
  `GeoProcessor` instance - no crash, output written correctly.
- Both the full-run and re-simplify outputs are now automatically added to
  the QGIS map canvas with their `.qml` style applied
  (`MainDialog._load_raster_layer`, wired through new `outputs_ready`
  signals on both worker classes). Verified `loadNamedStyle` accepts our
  generated QML and produces a `QgsPalettedRasterRenderer` as expected.
- Dialog window title now reads "LandCap Assessment Tool by Leonardo
  Barua".
- Added an "About" tab that renders the plugin's own `README.md` (via
  `QTextBrowser.setMarkdown`) inside the dialog, so setup/usage notes are
  visible without leaving QGIS - edits to `README.md` show up next time the
  dialog opens. Verified live: 3 tabs present, markdown rendering confirmed
  available and working in this QGIS's Qt build.
- plugins.qgis.org's validator blocked v0.1.0 as a critical security risk
  (bandit findings against every `.py` file in the zip, including vendored
  code the plugin never calls). Trimmed `vendor/whitebox/whitebox_tools.py`
  from the full upstream API (~570 tool-wrapper methods, 10,701 lines) down
  to just `fill_depressions`/`d8_flow_accumulation` and the `run_tool`
  machinery they depend on (221 lines) - this removed the extension-
  installer/license-registration/self-updater code entirely, which is
  where the worst findings (`os.system` with string-concatenated shell
  commands, `urllib.request.urlopen`, partial executable paths) lived, none
  of it reachable from this plugin. Also fixed a real (if minor) issue in
  our own `test/test_soil_match.py`: `tempfile.mktemp()` has a documented
  TOCTOU race condition - switched to `tempfile.mkstemp()`. `test/` is now
  excluded from the packaged zip entirely (dev-only, not needed at
  runtime), which also drops bandit's routine `assert`-in-tests warnings
  from what ships. Result, scanning exactly what's in the zip: 24 findings
  (several Medium) -> 4 (all Low, all just "you imported subprocess" /
  "you called Popen with the already-safe shell=False"). Verified the
  trim didn't change behavior: reran the full analysis against the same
  real-world inputs and diffed the output raster against the pre-trim
  run - bit-for-bit identical.

## Not yet verified

- The guided dialog (`gui/main_dialog.py`) has since been confirmed working
  in real QGIS use (full run, re-simplify, auto-add-to-view, About tab).
- The Processing Toolbox entry point (`processing/landcap_algorithm.py`)
  has *not* been run yet - only the dialog path has real-world mileage so
  far.
