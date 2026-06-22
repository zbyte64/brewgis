"""Unit tests for parcel_bft_classification model.

Tests the built_form_key 6-tier derivation:
  - Tier 0: landuse prefix → built_form_key mapping
  - Tier 1: sales records → built_form_key (overrides landuse)
  - Tier 2: Overture building footprints
  - Tier 3b: footprint ratio filter (lot>3ac, ratio<0.02 → agricultural)
  - Tier 4: area heuristic (lot>10ac → ag, 3-10ac+zone%A% → ag)
  - Priority: Tier1 > Tier0 > Tier2 > Tier3 > Tier4

Run with: sqlmesh test
"""


def test_landuse_A1_small_lot_returns_detsf_sl(context):
    """A1% + lot<0.15 → detsf_sl"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A1_SL",
                    "lot_size_acres": 0.10,
                    "landuse": "A1",
                    "zone": "R-1",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ]
        },
    )
    df = result[0].df
    assert df["built_form_key"].iloc[0] == "detsf_sl", (
        f"Expected detsf_sl, got {df['built_form_key'].iloc[0]}"
    )


def test_landuse_A1_large_lot_returns_detsf_ll(context):
    """A1% + lot≥0.15 → detsf_ll"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A1_LL",
                    "lot_size_acres": 0.25,
                    "landuse": "A1",
                    "zone": "R-1",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ]
        },
    )
    df = result[0].df
    assert df["built_form_key"].iloc[0] == "detsf_ll", (
        f"Expected detsf_ll, got {df['built_form_key'].iloc[0]}"
    )


def test_a2_landuse_not_classified_at_tier0(context):
    """A2% → NOT classified at Tier 0 (falls through to Tier 3b+/Tier4)"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_FT",
                    "lot_size_acres": 5.0,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ]
        },
    )
    df = result[0].df
    # A2 should NOT get classified by Tier0 — falls through to Tier4 mf2to4 fallback
    row = df.iloc[0]
    assert row["built_form_key"] == "mf2to4", (
        f"A2 landuse should be mf2to4 from tier4, got {row['built_form_key']}"
    )
    assert row["built_form_key_source"] == "tier4", (
        f"A2 should be tier4, got {row['built_form_key_source']}"
    )


def test_landuse_AE_returns_commercial(context):
    """AE% → commercial"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_AE",
                    "lot_size_acres": 1.0,
                    "landuse": "AE",
                    "zone": "C-1",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ]
        },
    )
    df = result[0].df
    assert df["built_form_key"].iloc[0] == "commercial", (
        f"Expected commercial, got {df['built_form_key'].iloc[0]}"
    )


def test_sales_sfr_overrides_landuse(context):
    """Tier1 (Sales SFR) > Tier0 (landuse A1)

    A parcel with landuse=AG (agricultural) but SFR sales should get detsf_sl.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_SFR_OVERRIDE",
                    "lot_size_acres": 0.10,
                    "landuse": "AG",
                    "zone": "A-2",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "public.sacog_assessor_sales_raw": [
                {
                    "apn": "TEST_SFR_OVERRIDE",
                    "property_type": "SFR",
                    "lot_size_acres": 0.10,
                    "units": 1,
                    "living_area": 1500,
                    "building_sf": 1800,
                    "year_built": 2005,
                }
            ],
        },
    )
    df = result[0].df
    # SFR + lot<0.15 → detsf_sl, overriding landuse AG → agricultural
    assert df["built_form_key"].iloc[0] == "detsf_sl", (
        f"Expected detsf_sl (SFR overrides AG), got {df['built_form_key'].iloc[0]}"
    )


def test_tier3b_footprint_ratio_filter(context):
    """lot>3ac + footprint_ratio<0.02 → agricultural (Tier 3b)"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_3B",
                    "lot_size_acres": 5.0,
                    "landuse": "A1",
                    "zone": "R-1",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "brewgis.assessor.parcel_building_sqft_by_type": [
                {
                    "apn": "TEST_3B",
                    "total_footprint_sqft": 500.0,
                    "building_count": 1,
                    "footprint_ratio": 0.005,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "max_levels": 1,
                }
            ],
        },
    )
    df = result[0].df
    assert df["built_form_key"].iloc[0] == "agricultural", (
        f"Expected agricultural (footprint ratio < 0.02), got {df['built_form_key'].iloc[0]}"
    )
