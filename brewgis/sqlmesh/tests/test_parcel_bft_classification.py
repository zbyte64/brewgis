"""Unit tests for parcel_bft_classification model — A2 landuse path.

Tests that A2% (multi-family) landuse parcels correctly fall through tier0
and are classified as mf2to4 or mf5p by downstream tiers.

Key invariants:
- A2 parcels NOT caught by tier1 must never get non-mf classifications
- Tier2 building data → mf2to4/mf5p (NOT detsf_sl)
- Tier4 fallback → mf2to4 (NOT agricultural/detsf_ll/detsf_sl/attsf)
- Tier3b must NOT intercept A2 parcels as agricultural
"""


def test_a2_no_sales_no_buildings_small_lot_tier4(context):
    """A2% + small lot + no data → tier4 → mf2to4"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T4_SM",
                    "lot_size_acres": 0.10,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["built_form_key"].iloc[0] == "mf2to4", (
        f"A2 small lot (0.1ac) expected mf2to4 from tier4, got {df['built_form_key'].iloc[0]}"
    )


def test_a2_no_sales_no_buildings_medium_lot_tier4(context):
    """A2% + medium lot (0.4-3ac) + no data → tier4 → mf2to4"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T4_MD",
                    "lot_size_acres": 0.50,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["built_form_key"].iloc[0] == "mf2to4", (
        f"A2 medium lot (0.5ac) expected mf2to4 from tier4, got {df['built_form_key'].iloc[0]}"
    )


def test_a2_no_sales_no_buildings_large_lot_tier4(context):
    """A2% + large lot (>3ac) + no data → skips tier3b → tier4 → mf2to4

    Before the fix, tier3b would intercept this parcel as 'agricultural'
    because footprint_ratio defaults to 0 (no building data).
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T4_LG",
                    "lot_size_acres": 5.0,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["built_form_key"] == "mf2to4", (
        f"A2 large lot (5ac) expected mf2to4 from tier4, got {row['built_form_key']}"
    )


def test_a2_no_sales_no_buildings_very_large_lot_tier4(context):
    """A2% + very large lot (>10ac) + no data → tier4 → mf2to4

    A2 landuse takes priority over area-based agricultural heuristic.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T4_VL",
                    "lot_size_acres": 15.0,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["built_form_key"] == "mf2to4", (
        f"A2 very large lot (15ac) expected mf2to4 from tier4, got {row['built_form_key']}"
    )


def test_a2_with_building_data_tier2(context):
    """A2% + residential building sqft + max_levels<3 → tier2 → mf2to4"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T2_LOW",
                    "lot_size_acres": 0.20,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "brewgis.assessor.parcel_building_sqft_by_type": [
                {
                    "apn": "TEST_A2_T2_LOW",
                    "total_footprint_sqft": 2000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.05,
                    "residential_building_sqft": 1500.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "max_levels": 1,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["built_form_key"] == "mf2to4", (
        f"A2 with residential bldg (<3 levels) expected mf2to4 from tier2, got {row['built_form_key']}"
    )


def test_a2_with_building_data_tier2_mf5p(context):
    """A2% + residential building sqft + max_levels>=3 → tier2 → mf5p"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T2_HI",
                    "lot_size_acres": 0.30,
                    "landuse": "A2",
                    "zone": "R-4",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "brewgis.assessor.parcel_building_sqft_by_type": [
                {
                    "apn": "TEST_A2_T2_HI",
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.10,
                    "residential_building_sqft": 4000.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "max_levels": 3,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["built_form_key"] == "mf5p", (
        f"A2 with residential bldg (>=3 levels) expected mf5p from tier2, got {row['built_form_key']}"
    )


def test_a2_with_large_lot_and_building_data(context):
    """A2% + large lot with building data → tier3b should NOT catch (landuse check)"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_3B_NO",
                    "lot_size_acres": 5.0,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "brewgis.assessor.parcel_building_sqft_by_type": [
                {
                    "apn": "TEST_A2_3B_NO",
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
    row = df.iloc[0]
    # A2 + large lot + low footprint → should NOT be agricultural (tier3b blocked)
    # Falls to tier4 A2 check → mf2to4
    assert row["built_form_key"] == "mf2to4", (
        f"A2 large lot w/ building data expected mf2to4 from tier4, got {row['built_form_key']}"
    )


def test_a2_null_landuse_not_affected(context):
    """NULL landuse parcels should not be affected by A2 filters"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_NULL_LU",
                    "lot_size_acres": 0.10,
                    "landuse": None,
                    "zone": "R-1",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # NULL landuse → no tier0 match → falls to unknown_parcels
    # landuse_prefix is NULL → tier3 filter: NULL NOT LIKE 'A2' is NULL (falsy)
    # → no KNN neighbors → tier3b (lot 0.1 < 3, so no) → tier4 → small lot → mf2to4 (even APN parity)
    assert row["built_form_key"] is not None, (
        "NULL landuse parcel should get some classification"
    )


def test_a1_large_lot_still_agricultural(context):
    """Non-A2 parcels >3ac with low footprint should still be agricultural (tier3b unaffected)"""
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_AGR_3B",
                    "lot_size_acres": 5.0,
                    "landuse": "A1",
                    "zone": "R-1",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # A1 + large lot + no building data → tier3b → agricultural
    assert row["built_form_key"] == "agricultural", (
        f"A1 large lot (5ac) expected agricultural from tier3b, got {row['built_form_key']}"
    )


def test_a2_large_lot_explicit_low_footprint_tier3b_excluded(context):
    """A2% + large lot + explicit low footprint ratio → skips tier3b → tier4 → mf2to4

    This test explicitly provides building data with low footprint_ratio to exercise
    the tier3b exclusion path. Before the fix, tier3b would classify as agricultural.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_3B_EX",
                    "lot_size_acres": 5.0,
                    "landuse": "A2",
                    "zone": "R-3",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
            "brewgis.assessor.parcel_building_sqft_by_type": [
                {
                    "apn": "TEST_A2_3B_EX",
                    "total_footprint_sqft": 100.0,
                    "building_count": 1,
                    "footprint_ratio": 0.001,
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
    row = df.iloc[0]
    # A2 + large lot + low footprint → NOT agricultural (tier3b excluded A2)
    # Falls to tier4 A2 check → mf2to4
    assert row["built_form_key"] == "mf2to4", (
        f"A2 large lot + low footprint expected mf2to4 from tier4, "
        f"got {row['built_form_key']} (source={row['built_form_key_source']})"
    )
    # Verify the source is NOT tier3b (would have been before fix)
    assert row["built_form_key_source"] != "tier3b", (
        f"A2 should NOT be tier3b, got {row['built_form_key_source']}"
    )


def test_a2_very_large_lot_tier4_overrides_agricultural(context):
    """A2% + very large lot (>10ac) → tier4 → mf2to4 (NOT agricultural)

    This test specifically exercises the assert_bft_tier4_area_heuristic audit path.
    Before the fix, tier4 would classify A2 >10ac as 'agricultural'.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_A2_T4_AG",
                    "lot_size_acres": 20.0,
                    "landuse": "A2",
                    "zone": "A-2",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # A2 + very large lot with A-zone → should still be mf2to4 (landuse trumps zone)
    assert row["built_form_key"] == "mf2to4", (
        f"A2 very large lot (20ac, zone A-2) expected mf2to4 from tier4, "
        f"got {row['built_form_key']} (source={row['built_form_key_source']})"
    )
    assert row["built_form_key_source"] == "tier4", (
        f"A2 very large lot should be tier4, got {row['built_form_key_source']}"
    )


def test_non_a2_large_lot_zone_a_still_agricultural_tier4(context):
    """Non-A2 + large lot + A-zone → still agricultural from tier4

    Verifies that the tier4 agricultural heuristic still works for non-A2 parcels.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_bft_classification",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.sacog_assessor_parcels": [
                {
                    "apn": "TEST_NON_A2_AG",
                    "lot_size_acres": 15.0,
                    "landuse": "A1",
                    "zone": "A-2",
                    "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # Non-A2 + very large lot + A-zone → agricultural
    assert row["built_form_key"] == "agricultural", (
        f"Non-A2 large lot (A-zone) expected agricultural from tier4, "
        f"got {row['built_form_key']} (source={row['built_form_key_source']})"
    )
