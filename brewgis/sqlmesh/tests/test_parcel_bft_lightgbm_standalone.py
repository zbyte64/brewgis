"""Standalone unit tests for parcel_bft_lightgbm helper functions.

These tests validate the feature encoding, mapping, and training logic WITHOUT any
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


# ── Mock context helpers ──────────────────────────────────────────────────


def _make_mock_context():
    """Create a minimal mock ExecutionContext that supports _discover_env_view.

    The _discover_env_view helper calls context.engine_adapter.fetchdf() to
    query information_schema. If that fails (no DB), it raises RuntimeError.
    _fetch_reference_training_data now fails hard — it doesn't catch.
    """

    class MockEngineAdapter:
        @staticmethod
        def fetchdf(*args, **kwargs):
            raise RuntimeError("no database in standalone test — expected")

        @staticmethod
        def execute(*args, **kwargs):
            pass

    class MockContext:
        engine_adapter = MockEngineAdapter()

        @staticmethod
        def resolve_table(name):
            raise RuntimeError(f"no database in standalone test — resolve({name})")

        @staticmethod
        def fetchdf(*args, **kwargs):
            raise RuntimeError("no database in standalone test — fetchdf")

    return MockContext()


# ── Synthetic data generators ─────────────────────────────────────────────


def _make_training_data(mod, n_per_class=105):
    """Create synthetic data with the 9-class old labels + land_development_category."""
    classes_9 = ["detsf_sl", "detsf_ll", "commercial"]
    ldev_cats = ["standard", "standard", "compact"]
    # Lot sizes chosen so _map_tier1_to_39class produces classes matching
    # _make_reference_data: detsf_sl (lot>=0.15) → bt__medium_high,
    # detsf_ll (lot<1.0) → bt__low_density, commercial → bt__communityneighborhood
    rows = []
    for i, cls in enumerate(classes_9):
        for j in range(n_per_class):
            idx = i * n_per_class + j
            rows.append(
                {
                    "apn": f"APN{idx:06d}",
                    "built_form_key": cls,
                    "land_development_category": ldev_cats[i],
                    "lot_size_acres": 0.5,
                    "landuse": ["RC100A", "A1000A", "A2000A"][i],
                    "zone": ["R-3", "C-2", "M-1"][i],
                    "centroid_x": 6500000.0 + i * 1000.0 + j * 10.0,
                    "centroid_y": 2000000.0 + i * 500.0 + j * 10.0,
                    "residential_building_sqft": 2000.0 - i * 500.0 + (j % 10) * 100.0,
                    "commercial_building_sqft": float(i * 1000 + (j % 5) * 200),
                    "industrial_building_sqft": float(
                        max(0, (i - 1) * 2000 + (j % 3) * 100)
                    ),
                    "other_building_sqft": float((j % 20) * 50),
                    "total_footprint_sqft": 1500.0 + i * 500.0 + (j % 10) * 100.0,
                    "building_count": 1 + (j % 5),
                    "footprint_ratio": 0.15 + i * 0.05 + (j % 10) * 0.01,
                    "max_levels": 1 + (j % 3),
                    "intersection_density": 50.0 + i * 30.0 + (j % 10) * 5.0,
                }
            )
    return pd.DataFrame(rows)


def _make_reference_data(mod, n_per_class=210):
    """Create synthetic reference data with bt__ classes that match mapped
    assessor output: the mapping from detsf_sl (lot>=0.15) → bt__medium_high,
    detsf_ll (lot<1.0) → bt__low_density, and commercial → bt__communityneighborhood_retail."""
    classes_40 = [
        "bt__medium_high_density_detached_residential",
        "bt__low_density_detached_residential",
        "bt__communityneighborhood_retail",
    ]
    ldev_cats = ["standard", "standard", "compact"]
    rows = []
    for i, cls in enumerate(classes_40):
        ld = ldev_cats[i]
        for j in range(n_per_class):
            idx = i * n_per_class + j
            rows.append(
                {
                    "built_form_key": cls,
                    "land_development_category": ld,
                    "lot_size_acres": 0.25 + i * 0.5 + (j % 5) * 0.1,
                    "landuse": ["RC100A", "A1000A", "A2000A"][i],
                    "zone": ["R-3", "C-2", "M-1"][i],
                    "centroid_x": 6500000.0 + i * 1000.0 + j * 10.0,
                    "centroid_y": 2000000.0 + i * 500.0 + j * 10.0,
                    "residential_building_sqft": 2000.0 - i * 500.0 + (j % 10) * 100.0,
                    "commercial_building_sqft": float(i * 1000 + (j % 5) * 200),
                    "industrial_building_sqft": float(
                        max(0, (i - 1) * 2000 + (j % 3) * 100)
                    ),
                    "other_building_sqft": float((j % 20) * 50),
                    "total_footprint_sqft": 1500.0 + i * 500.0 + (j % 10) * 100.0,
                    "building_count": 1 + (j % 5),
                    "footprint_ratio": 0.15 + i * 0.05 + (j % 10) * 0.01,
                    "max_levels": 1 + (j % 3),
                    "intersection_density": 50.0 + i * 30.0 + (j % 10) * 5.0,
                }
            )
    return pd.DataFrame(rows)


def _make_inference_data(n=50):
    """Create synthetic inference parcels (no built_form_key)."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "apn": f"INF{i:06d}",
                "land_development_category": [
                    "standard",
                    "compact",
                    "standard",
                    "compact",
                ][i % 4],
                "lot_size_acres": 0.25 + (i % 10) * 0.1,
                "landuse": ["RC100A", "A1000A", "A2000A", "ATB00A"][i % 4],
                "zone": ["R-3", "C-2", "M-1", "A-1"][i % 4],
                "centroid_x": 6500000.0 + i * 100.0,
                "centroid_y": 2000000.0 + i * 100.0,
                "residential_building_sqft": 1500.0 + (i % 10) * 100.0,
                "commercial_building_sqft": float((i % 5) * 500),
                "industrial_building_sqft": 0.0,
                "other_building_sqft": float((i % 20) * 50),
                "total_footprint_sqft": 1500.0 + (i % 10) * 100.0,
                "building_count": 1 + (i % 5),
                "footprint_ratio": 0.15 + (i % 10) * 0.01,
                "max_levels": 1 + (i % 3),
                "intersection_density": 50.0 + (i % 10) * 5.0,
            }
        )
    return pd.DataFrame(rows)


# ── Tests ─────────────────────────────────────────────────────────────────


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
    ldev_cats = ["standard", "compact"]

    df = pd.DataFrame(
        {
            "apn": ["T1", "T2", "T3"],
            "land_development_category": ["standard", "compact", "standard"],
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

    result = mod._feature_matrix(df, landuse_prefixes, zone_prefixes, ldev_cats)

    # All numeric features must be present
    for col in mod.NUMERIC_FEATURES:
        assert col in result.columns, f"Missing numeric feature: {col}"

    # All one-hot columns must be present
    for p in landuse_prefixes:
        assert f"lu_{p}" in result.columns, f"Missing landuse one-hot: lu_{p}"
    for p in zone_prefixes:
        assert f"zone_{p}" in result.columns, f"Missing zone one-hot: zone_{p}"
    for c in ldev_cats:
        assert f"ldc_{c}" in result.columns, f"Missing ldc one-hot: ldc_{c}"

    # Shape: 3 rows × (12 numeric + 3 landuse + 3 zone + 2 ldc) = 20 columns
    assert result.shape == (3, 20), f"Expected (3, 20), got {result.shape}"


def test_feature_matrix_handles_missing_zone_and_landuse():
    """NULL landuse/zone must not crash — fillna with XX/X."""
    mod = _import_model()

    landuse_prefixes = ["A1", "XX"]
    zone_prefixes = ["R", "X"]
    ldev_cats = ["standard"]

    df = pd.DataFrame(
        {
            "apn": ["T1"],
            "land_development_category": ["standard"],
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

    result = mod._feature_matrix(df, landuse_prefixes, zone_prefixes, ldev_cats)
    assert result.shape[0] == 1, "Should still produce 1 row with NULL inputs"


def test_class_to_idx_roundtrip():
    """Each class must map to a unique index and back."""
    mod = _import_model()

    assert len(mod.CLASSES) == 40, f"Expected 40 classes, got {len(mod.CLASSES)}"
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


def test_clean_bft_key():
    """_clean_bft_key must keep bt__ prefix and strip _sacog suffix."""
    mod = _import_model()

    assert (
        mod._clean_bft_key("bt__low_density_detached_residential")
        == "bt__low_density_detached_residential"
    )
    assert mod._clean_bft_key("bt__agriculture_sacog") == "bt__agriculture"
    assert (
        mod._clean_bft_key("bt__park_andor_open_space_sacog")
        == "bt__park_andor_open_space"
    )
    assert mod._clean_bft_key("bt__rural_residential_sacog") == "bt__rural_residential"


def test_9_to_39_mapping_correct():
    """_map_tier1_to_39class must map 9-class labels to correct bt__ classes."""
    mod = _import_model()

    df = pd.DataFrame(
        {
            "built_form_key": [
                "detsf_sl",
                "detsf_ll",
                "commercial",
                "agricultural",
                "mf5p",
                "attsf",
                "civic",
                "industrial",
            ],
            "lot_size_acres": [0.1, 2.0, 0.5, 10.0, 0.3, 0.2, 0.5, 1.0],
            "intersection_density": [100.0, 10.0, 200.0, 5.0, 150.0, 30.0, 50.0, 20.0],
        }
    )

    result = mod._map_tier1_to_39class(df)

    # detsf_sl with lot < 0.15 → bt__medium_density_detached_residential
    assert result.iloc[0]["built_form_key"] == "bt__medium_density_detached_residential"
    # detsf_ll with lot 1.0-5.0 → bt__very_low_density_detached_residential
    assert (
        result.iloc[1]["built_form_key"] == "bt__very_low_density_detached_residential"
    )
    # commercial → default bt__communityneighborhood_retail
    assert result.iloc[2]["built_form_key"] == "bt__communityneighborhood_retail"
    # agricultural → bt__agriculture
    assert result.iloc[3]["built_form_key"] == "bt__agriculture"
    # mf5p with int_density >= 100 → bt__urban_mid_rise_residential
    assert result.iloc[4]["built_form_key"] == "bt__urban_mid_rise_residential"
    # attsf with int_density < 50 → bt__medium_density_attached_residential
    assert result.iloc[5]["built_form_key"] == "bt__medium_density_attached_residential"


def test_reference_fetch_raises_when_tables_missing():
    """_fetch_reference_training_data must raise RuntimeError when no DB.

    It no longer silently returns empty — the silent fallback was removed.
    """
    mod = _import_model()
    ctx = _make_mock_context()

    import pytest

    with pytest.raises(RuntimeError):
        mod._fetch_reference_training_data(ctx)


def test_two_stage_trains_on_reference_and_assessor():
    """Classifier trains on reference data and fine-tunes on mapped assessor labels."""
    mod = _import_model()
    ctx = _make_mock_context()

    ref_df = _make_reference_data(mod, n_per_class=210)
    inference_df = _make_inference_data()
    train_df = _make_training_data(mod, n_per_class=210)

    results = mod._train_and_predict(ctx, ref_df, inference_df, assessor_df=train_df)

    assert isinstance(results, pd.DataFrame), "Must return a DataFrame"
    assert "apn" in results.columns, "Must have apn column"
    assert "built_form_key" in results.columns, "Must have built_form_key column"
    assert "probability" in results.columns, "Must have probability column"
    assert len(results) == len(inference_df), "Must predict for all inference parcels"
    assert results["built_form_key"].notna().sum() > 0, (
        "At least some parcels should be predicted"
    )
    assert results["built_form_key"].isin(mod.CLASSES).all(), (
        "All predictions must be valid bt__ classes"
    )


def test_reference_only_when_assessor_empty():
    """With assessor_df=None, classifier trains on reference data only."""
    mod = _import_model()
    ctx = _make_mock_context()

    ref_df = _make_reference_data(mod, n_per_class=210)
    inference_df = _make_inference_data()

    results = mod._train_and_predict(ctx, ref_df, inference_df, assessor_df=None)

    assert isinstance(results, pd.DataFrame), "Must return a DataFrame"
    assert "apn" in results.columns, "Must have apn column"
    assert "built_form_key" in results.columns, "Must have built_form_key column"
    assert "probability" in results.columns, "Must have probability column"
    assert len(results) == len(inference_df), "Must predict for all inference parcels"
    assert results["built_form_key"].notna().sum() > 0, (
        "At least some parcels should be predicted"
    )
