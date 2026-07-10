"""Standalone unit tests for parcel_bft_lightgbm helper functions.

These tests validate the feature encoding and training logic WITHOUT any
SQLMesh or database infrastructure — pure pandas/numpy validation.

Run with: python3 -m pytest brewgis/sqlmesh/tests/test_parcel_bft_lightgbm_standalone.py -v
"""

from __future__ import annotations

from pathlib import Path

_MODEL_FILE = (
    Path(__file__).resolve().parent.parent
    / "models"
    / "python"
    / "parcel_bft_lightgbm.py"
)

import pandas as pd


def _import_model():
    """Import the model module."""
    import importlib

    spec = importlib.util.spec_from_file_location(
        "parcel_bft_lightgbm",
        _MODEL_FILE,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_top_landuse_prefixes():
    """landuse_prefix column must be present and top prefixes returned."""
    mod = _import_model()

    train = pd.DataFrame({"landuse_prefix": ["A1", "A1", "A1", "A2", "A2", "AT", "XX"]})
    inference = pd.DataFrame({"landuse_prefix": ["A1", "A2", "AT", "RC", "XX"]})

    prefixes = mod._extract_top_landuse_prefixes(train, inference, n=3)
    prefixes.sort()

    assert "A1" in prefixes, "A1 should be in top prefixes"
    assert "A2" in prefixes, "A2 should be in top prefixes"
    assert "XX" in prefixes or "AT" in prefixes, (
        "Should include at least one more prefix"
    )
    assert "RC" in prefixes, "RC is in inference only and should be included"


def test_feature_matrix_produces_expected_columns():
    """_feature_matrix must produce all numeric features plus one-hot columns."""
    mod = _import_model()

    landuse_prefixes = ["A1", "A2", "AT"]
    zone_prefixes = ["R", "C", "M"]

    df = pd.DataFrame(
        {
            "apn": ["T1", "T2", "T3"],
            "lot_size_acres": [0.1, 0.5, 1.0],
            "landuse": ["A1000A", "A2000A", "ATB00A"],
            "zone": ["R-3", "C-2", "M-1"],
            "centroid_x": [100.0, 200.0, 300.0],
            "centroid_y": [400.0, 500.0, 600.0],
            "residential_building_sqft": [1000.0, 2000.0, 0.0],
            "commercial_building_sqft": [0.0, 500.0, 3000.0],
            "industrial_building_sqft": [0.0, 0.0, 5000.0],
            "other_building_sqft": [0.0, 0.0, 1000.0],
            "total_footprint_sqft": [500.0, 1200.0, 4500.0],
            "building_count": [1, 2, 5],
            "footprint_ratio": [0.1, 0.05, 0.08],
            "max_levels": [1, 2, 3],
            "intersection_density": [10.0, 50.0, 100.0],
        }
    )

    result = mod._feature_matrix(df, landuse_prefixes, zone_prefixes)

    # All numeric features must be present
    for col in mod.NUMERIC_FEATURES:
        assert col in result.columns, f"Missing numeric feature: {col}"

    # All one-hot columns must be present
    for p in landuse_prefixes:
        assert f"lu_{p}" in result.columns, f"Missing landuse one-hot: lu_{p}"
    for p in zone_prefixes:
        assert f"zone_{p}" in result.columns, f"Missing zone one-hot: zone_{p}"

    # Shape: 3 rows × (12 numeric + 3 landuse + 3 zone) = 18 columns
    assert result.shape == (3, 18), f"Expected (3, 18), got {result.shape}"


def test_feature_matrix_handles_missing_zone_and_landuse():
    """NULL landuse/zone must not crash — fillna with XX/X."""
    mod = _import_model()

    landuse_prefixes = ["A1", "XX"]
    zone_prefixes = ["R", "X"]

    df = pd.DataFrame(
        {
            "apn": ["T1"],
            "lot_size_acres": [0.2],
            "landuse": [None],
            "zone": [None],
            "centroid_x": [100.0],
            "centroid_y": [200.0],
            "residential_building_sqft": [1500.0],
            "commercial_building_sqft": [0.0],
            "industrial_building_sqft": [0.0],
            "other_building_sqft": [0.0],
            "total_footprint_sqft": [800.0],
            "building_count": [1],
            "footprint_ratio": [0.1],
            "max_levels": [2],
            "intersection_density": [20.0],
        }
    )

    result = mod._feature_matrix(df, landuse_prefixes, zone_prefixes)
    assert result.shape[0] == 1, "Should still produce 1 row with NULL inputs"


def test_class_to_idx_roundtrip():
    """Each class must map to a unique index and back."""
    mod = _import_model()

    assert len(mod.CLASSES) == 9, f"Expected 9 classes, got {len(mod.CLASSES)}"
    assert set(mod.CLASS_TO_IDX.keys()) == set(mod.CLASSES), (
        "CLASS_TO_IDX keys must match CLASSES"
    )
    assert len(mod.CLASS_TO_IDX) == len(mod.CLASSES), (
        "CLASS_TO_IDX must have unique entries"
    )

    for cls in mod.CLASSES:
        idx = mod.CLASS_TO_IDX[cls]
        assert mod.IDX_TO_CLASS[idx] == cls, (
            f"Roundtrip failed for {cls} -> {idx} -> {mod.IDX_TO_CLASS[idx]}"
        )


def test_compute_data_hash_invariant():
    """Same data must produce same hash; different data must produce different hash."""
    mod = _import_model()

    df1 = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    df2 = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    df3 = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 99.0]})

    assert mod._compute_data_hash(df1) == mod._compute_data_hash(df2), (
        "Identical data must hash identically"
    )
    assert mod._compute_data_hash(df1) != mod._compute_data_hash(df3), (
        "Different data must hash differently"
    )
