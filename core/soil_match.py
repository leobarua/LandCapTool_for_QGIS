"""Fuzzy text matching for soil-texture labels.

Replaces the desktop tool's dependency on thefuzz/python-Levenshtein with
Python's stdlib difflib, since neither thefuzz nor Levenshtein ships with
QGIS's bundled Python interpreter.
"""

import csv
import difflib


def best_match(value, choices):
    """Return the choice in `choices` most similar to `value`."""
    matches = difflib.get_close_matches(value, choices, n=1, cutoff=0.0)
    if matches:
        return matches[0]
    return max(choices, key=lambda c: difflib.SequenceMatcher(None, value, c).ratio())


def read_k_lookup(csv_path):
    """Reads the K-factor lookup CSV into {soil_texture_label: k_value}."""
    lookup = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lookup[row["Soil Texture"]] = float(row["Kvalue"])
    return lookup


def build_k_value_map(soil_layer, field_name, k_lookup_csv_path):
    """Fuzzy-matches each distinct value of `field_name` on `soil_layer`
    against the K-factor lookup CSV's 'Soil Texture' column, returning
    {field_value: k_value}.
    """
    k_lookup = read_k_lookup(k_lookup_csv_path)
    texture_labels = list(k_lookup.keys())

    idx = soil_layer.fields().indexFromName(field_name)
    distinct_values = {f[idx] for f in soil_layer.getFeatures() if f[idx] is not None}

    return {
        value: k_lookup[best_match(str(value), texture_labels)]
        for value in distinct_values
    }
