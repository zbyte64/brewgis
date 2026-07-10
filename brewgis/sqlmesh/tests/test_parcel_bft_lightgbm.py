"""Unit tests for parcel_bft_lightgbm model.

Tests:
- Training produces predictions with 100+ synthetic samples
- High-confidence predictions match expected class
- Edge case: all-NULL features returns empty
- Integration: resolved chain includes LightGBM predictions

Run with: sqlmesh test
"""

from __future__ import annotations

from typing import Any

import pytest


def _make_parcel(
    apn: str,
    lot_size_acres: float = 0.2,
    landuse: str = "A1000A",
    zone: str = "R-3",
    built_form_key: str | None = None,
    residential_sqft: float = 0.0,
    commercial_sqft: float = 0.0,
    industrial_sqft: float = 0.0,
    other_sqft: float = 0.0,
    total_footprint_sqft: float = 0.0,
    building_count: int = 0,
    footprint_ratio: float = 0.0,
    max_levels: int = 1,
    intersection_density: float = 0.0,
    geometry: str | None = None,
) -> dict[str, Any]:
    """Create a synthetic parcel dict for test inputs."""
    if geometry is None:
        geometry = (
            "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))"
        )
    row: dict[str, Any] = {
        "apn": apn,
        "lot_size_acres": lot_size_acres,
        "landuse": landuse,
        "zone": zone,
        "geometry": geometry,
        "residential_building_sqft": residential_sqft,
        "commercial_building_sqft": commercial_sqft,
        "industrial_building_sqft": industrial_sqft,
        "other_building_sqft": other_sqft,
        "total_footprint_sqft": total_footprint_sqft,
        "building_count": building_count,
        "footprint_ratio": footprint_ratio,
        "max_levels": max_levels,
        "intersection_density": intersection_density,
    }
    if built_form_key is not None:
        row["built_form_key"] = built_form_key
    return row


def _generate_tier1_data(
    count: int, built_form_key: str, **overrides: Any
) -> list[dict[str, Any]]:
    """Generate synthetic tier1 training parcels."""
    parcels = []
    for i in range(count):
        apn = f"TEST_LGBM_{built_form_key}_{i:04d}"
        row = _make_parcel(apn, built_form_key=built_form_key, **overrides)
        parcels.append(row)
    return parcels


# -- Common geometry for test parcels
BASE_GEOM = "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))"


def test_lightgbm_training_produces_predictions(context):
    """120 synthetic tier1 samples across 2 classes → predictions for 5 inference parcels."""
    # Training data: 60 detsf_sl + 60 mf5p with distinct features
    train_parcels = _generate_tier1_data(
        60,
        "detsf_sl",
        lot_size_acres=0.15,
        residential_sqft=1200.0,
        total_footprint_sqft=800.0,
        building_count=1,
        footprint_ratio=0.12,
        max_levels=1,
        intersection_density=15.0,
    ) + _generate_tier1_data(
        60,
        "mf5p",
        lot_size_acres=0.4,
        residential_sqft=5000.0,
        total_footprint_sqft=2000.0,
        building_count=1,
        footprint_ratio=0.08,
        max_levels=3,
        intersection_density=80.0,
    )

    # Inference-only parcels (5, with no tier1 label)
    inference_apns = [f"TEST_LGBM_INF_{i:04d}" for i in range(5)]
    inference_parcels = [
        _make_parcel(
            apn,
            lot_size_acres=0.5,
            residential_sqft=6000.0,
            total_footprint_sqft=2200.0,
            building_count=2,
            footprint_ratio=0.07,
            max_levels=4,
            intersection_density=100.0,
        )
        for apn in inference_apns
    ]

    # All parcels (training + inference) must be in sacog_assessor_parcels + feature tables
    all_apns = [p["apn"] for p in train_parcels + inference_parcels]
    all_feature_rows = []
    for apn in all_apns:
        matching = [p for p in train_parcels + inference_parcels if p["apn"] == apn]
        if matching:
            p = matching[0]
            all_feature_rows.append(
                {
                    "apn": apn,
                    "residential_building_sqft": p["residential_building_sqft"],
                    "commercial_building_sqft": p["commercial_building_sqft"],
                    "industrial_building_sqft": p["industrial_building_sqft"],
                    "other_building_sqft": p["other_building_sqft"],
                    "total_footprint_sqft": p["total_footprint_sqft"],
                    "building_count": p["building_count"],
                    "footprint_ratio": p["footprint_ratio"],
                    "max_levels": p["max_levels"],
                    "lot_size_acres": p["lot_size_acres"],
                }
            )

    # tier1_sales input — only training parcels have labels
    tier1_rows = [
        {"apn": p["apn"], "built_form_key": p["built_form_key"]} for p in train_parcels
    ]

    # Intersection density
    id_rows = [
        {"apn": p["apn"], "intersection_density": p["intersection_density"]}
        for p in train_parcels + inference_parcels
    ]

    # Parcel rows for the assessor table
    parcel_rows = []
    for p in train_parcels + inference_parcels:
        parcel_rows.append(
            {
                "apn": p["apn"],
                "lot_size_acres": p["lot_size_acres"],
                "landuse": p["landuse"],
                "zone": p["zone"],
                "geometry": BASE_GEOM,
            }
        )

    result = context.evaluate(
        "brewgis.assessor.parcel_bft_lightgbm",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_bft_tier1_sales": tier1_rows,
            "brewgis.assessor.sacog_assessor_parcels": parcel_rows,
            "brewgis.assessor.parcel_building_sqft_by_type": all_feature_rows,
            "brewgis.assessor.overture_intersection_density": id_rows,
        },
    )
    df = result[0].df

    # Should have 125 rows (120 training + 5 inference)
    assert len(df) == 125, f"Expected 125 total parcels, got {len(df)}"

    # All rows should have non-NULL built_form_key
    null_predictions = df["built_form_key"].isna().sum()
    assert null_predictions == 0, f"Expected 0 null predictions, got {null_predictions}"

    # All built_form_keys should be valid classes
    valid_classes = {
        "detsf_sl",
        "detsf_ll",
        "attsf",
        "mf2to4",
        "mf5p",
        "commercial",
        "industrial",
        "civic",
        "agricultural",
    }
    invalid = set(df["built_form_key"].unique()) - valid_classes
    assert not invalid, f"Invalid built_form_key values: {invalid}"

    # Inference parcels should have predictions (known features → mf5p)
    inf_results = df[df["apn"].isin(inference_apns)]
    for _, row in inf_results.iterrows():
        assert row["built_form_key"] in ("mf5p",), (
            f"Inference parcel {row['apn']}: expected mf5p, got {row['built_form_key']}"
        )


def test_lightgbm_empty_training_returns_empty(context):
    """Empty training data (no tier1 rows) → model returns NULL predictions."""
    parcel_rows = [_make_parcel("TEST_EMPTY_001", lot_size_acres=0.3)]
    feature_rows = [
        {
            "apn": "TEST_EMPTY_001",
            "residential_building_sqft": 1500.0,
            "commercial_building_sqft": 0.0,
            "industrial_building_sqft": 0.0,
            "other_building_sqft": 0.0,
            "total_footprint_sqft": 800.0,
            "building_count": 1,
            "footprint_ratio": 0.05,
            "max_levels": 2,
            "lot_size_acres": 0.3,
        }
    ]
    id_rows = [{"apn": "TEST_EMPTY_001", "intersection_density": 20.0}]

    result = context.evaluate(
        "brewgis.assessor.parcel_bft_lightgbm",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_bft_tier1_sales": [],
            "brewgis.assessor.sacog_assessor_parcels": parcel_rows,
            "brewgis.assessor.parcel_building_sqft_by_type": feature_rows,
            "brewgis.assessor.overture_intersection_density": id_rows,
        },
    )
    df = result[0].df

    assert len(df) == 1, f"Expected 1 row, got {len(df)}"
    assert df["built_form_key"].iloc[0] is None, (
        f"Expected NULL built_form_key with no training data, "
        f"got {df['built_form_key'].iloc[0]}"
    )
    assert df["probability"].iloc[0] is None, (
        f"Expected NULL probability, got {df['probability'].iloc[0]}"
    )


def test_resolved_chain_includes_lightgbm(context):
    """parcel_bft_resolved should use LightGBM when tier1/tier0 miss.

    A parcel with no tier1/tier0 match but a LightGBM prediction should
    get built_form_key_source = 'lightgbm'.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_resolved",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_LGBM_RESOLVED_001",
                    "lot_size_acres": 0.5,
                    "landuse": "A1000A",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "brewgis.assessor.parcel_bft_tier1_sales": [],
            "brewgis.assessor.parcel_bft_tier0_landuse": [],
            "brewgis.assessor.parcel_bft_lightgbm": [
                {
                    "apn": "TEST_LGBM_RESOLVED_001",
                    "built_form_key": "mf5p",
                    "probability": 0.92,
                },
            ],
            "brewgis.assessor.parcel_bft_tier3b_agricultural": [],
            "brewgis.assessor.parcel_bft_tier4_catchall": [],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["built_form_key"] == "mf5p", (
        f"Expected mf5p from LightGBM, got {row['built_form_key']}"
    )
    assert row["built_form_key_source"] == "lightgbm", (
        f"Expected source 'lightgbm', got {row['built_form_key_source']}"
    )
    assert row["is_residential"] == 1, (
        f"mf5p should be residential, got is_residential={row['is_residential']}"
    )
    assert row["du_subtype"] == "mf5p", (
        f"Expected du_subtype mf5p, got {row['du_subtype']}"
    )


def test_resolved_chain_lightgbm_fallback_to_tier3b(context):
    """Parcel without LightGBM prediction → falls through to tier3b → tier4."""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_resolved",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_FALLBACK_001",
                    "lot_size_acres": 15.0,
                    "landuse": "A1",
                    "zone": "A-2",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                    "land_development_category": "rural",
                }
            ],
            "brewgis.assessor.parcel_bft_tier1_sales": [],
            "brewgis.assessor.parcel_bft_tier0_landuse": [],
            "brewgis.assessor.parcel_bft_lightgbm": [],
            "brewgis.assessor.parcel_bft_tier3b_agricultural": [
                {"apn": "TEST_FALLBACK_001", "built_form_key": "agricultural"},
            ],
            "brewgis.assessor.parcel_bft_tier4_catchall": [],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["built_form_key"] == "agricultural", (
        f"Expected agricultural from tier3b, got {row['built_form_key']}"
    )
    assert row["built_form_key_source"] == "tier3b", (
        f"Expected source 'tier3b', got {row['built_form_key_source']}"
    )


@pytest.mark.skip(
    reason="Full integration requires PostGIS and LightGBM (>120s runtime)"
)
def test_lightgbm_full_integration(context):
    """End-to-end: tier1_sales sourced from SQL + full training + classification.

    This test is a system-level validation that the LightGBM model trains
    correctly against real data. Skipped by default due to runtime.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_lightgbm",
        start="2024-01-01",
        end="2024-01-01",
    )
    df = result[0].df
    assert len(df) > 0, "Expected non-empty predictions"
    assert df["built_form_key"].notna().sum() > 0, (
        "Expected at least some non-null predictions"
    )
    assert df["probability"].notna().sum() > 0, (
        "Expected at least some non-null probabilities"
    )
