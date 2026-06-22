"""Unit tests for parcel_du_estimation model — non-residential du=0 invariant.

Tests that assert_du_non_residential_zero audit is correctly scoped:
- Non-residential built_form_key (commercial/industrial/civic/agricultural) → du=0
- Residential built_form_key overrides non-residential land_development_category → du>0
"""


def test_residential_bft_in_industrial_ldc_has_positive_du(context):
    """A2/mf2to4 in industrial LDC → du > 0 (residential bft overrides LDC)"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_MF_IND_LDC",
                    "built_form_key": "mf2to4",
                    "du_subtype": "mf2to4",
                    "is_residential": True,
                    "lot_size_acres": 0.50,
                    "land_development_category": "industrial",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 10.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # Residential built_form_key (mf2to4) → tier4 → du = 2
    # Even though land_development_category = 'industrial'
    assert row["du"] > 0, (
        f"Residential bft (mf2to4) in industrial LDC expected du>0, got {row['du']}"
    )
    assert row["du"] == 2.0, f"mf2to4 no sqft expected du=2 (tier4), got {row['du']}"


def test_agricultural_bft_has_zero_du(context):
    """agricultural built_form_key → du=0"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_AGR",
                    "built_form_key": "agricultural",
                    "du_subtype": None,
                    "is_residential": False,
                    "lot_size_acres": 5.0,
                    "land_development_category": "agricultural",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 0.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["du"] == 0.0, f"agricultural bft expected du=0, got {row['du']}"


def test_industrial_ldc_with_null_bft_has_zero_du(context):
    """NULL built_form_key + undeveloped LDC → du = 0"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_NULL",
                    "built_form_key": None,
                    "du_subtype": None,
                    "is_residential": False,
                    "lot_size_acres": 10.0,
                    "land_development_category": "undeveloped",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 0.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["du"] == 0.0, (
        f"NULL bft + undeveloped LDC expected du=0, got {row['du']}"
    )


def test_detsf_in_agricultural_ldc_still_one_du(context):
    """detsf_ll built_form_key + agricultural LDC → du = 1"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_AG_RES",
                    "built_form_key": "detsf_ll",
                    "du_subtype": "detsf_ll",
                    "is_residential": True,
                    "lot_size_acres": 5.0,
                    "land_development_category": "agricultural",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 2.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # Residential bft (detsf_ll) → tier2 → du = 1
    assert row["du"] == 1.0, (
        f"detsf_ll in agricultural LDC expected du=1, got {row['du']}"
    )


def test_commercial_urban_ldc_tier5_default_du(context):
    """Commercial bft + urban LDC + no assessor units → du=1 (tier5 urban default)

    Tier5 fires before tier6 in the COALESCE priority, intentionally
    giving du=1 for non-residential bft in urban/mixed-use LDC.
    The audit should NOT flag this case.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_COMM_URBAN",
                    "built_form_key": "commercial",
                    "du_subtype": None,
                    "is_residential": False,
                    "lot_size_acres": 1.0,
                    "land_development_category": "urban",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 8.0,
                    "actual_living_sqft": 0.0,
                    "actual_building_sqft": 0.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    # du should be 1.0 from tier5 (urban default) despite commercial bft
    assert row["du"] == 1.0, (
        f"Commercial bft + urban LDC expected du=1.0 (tier5), got {row['du']}"
    )


def test_commercial_industrial_ldc_du_zero(context):
    """Commercial bft + industrial LDC + no assessor units → du=0 (tier6)

    Tier6 catches non-residential bft/LDC, giving du=0.
    The audit SHOULD pass for this case.
    """
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_COMM_IND",
                    "built_form_key": "commercial",
                    "du_subtype": None,
                    "is_residential": False,
                    "lot_size_acres": 5.0,
                    "land_development_category": "industrial",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 0.0,
                    "actual_living_sqft": 0.0,
                    "actual_building_sqft": 0.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["du"] == 0.0, (
        f"Commercial bft + industrial LDC expected du=0 (tier6), got {row['du']}"
    )
