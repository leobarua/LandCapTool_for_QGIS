"""Plain-pytest tests for core/soil_match.py - no PyQGIS import, so these run
with an ordinary Python interpreter (unlike core/geoprocessor.py, which needs
a headless QGIS / qgis.testing environment to import at all, since it imports
qgis.core and the Processing framework).
"""

import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.soil_match import best_match, read_k_lookup  # noqa: E402


def test_best_match_exact():
    assert best_match("Clay Loam", ["Clay Loam", "Sandy Loam", "Silt"]) == "Clay Loam"


def test_best_match_typo():
    assert best_match("Clay Laom", ["Clay Loam", "Sandy Loam", "Silt"]) == "Clay Loam"


def test_best_match_no_close_match_still_returns_something():
    result = best_match("xyz", ["Clay Loam", "Sandy Loam"])
    assert result in ("Clay Loam", "Sandy Loam")


def test_read_k_lookup(tmp_path=None):
    path = tempfile.mktemp(suffix=".csv")
    try:
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Soil Texture", "Kvalue"])
            writer.writerow(["Clay Loam", "0.30"])
            writer.writerow(["Sandy Loam", "0.15"])
        lookup = read_k_lookup(path)
        assert lookup == {"Clay Loam": 0.30, "Sandy Loam": 0.15}
    finally:
        os.remove(path)
