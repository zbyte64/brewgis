"""Unit tests for parcel_dasymetric_weights model — non-negative weight invariants.

Tests that pop_dasym_weight and emp_dasym_weight are always non-negative,
even when authoritative source data contains incoherent (negative) values.
"""


def test_emp_weight_non_negative_with_negative_authoritative(context):
    """Negative authoritative_non_residential_sqft → GREATEST(0, ...) clamps to 0"""
    result = context.evaluate(
        "brewgis.assessor.parcel_dasymetric_weights",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_bft_classification": [
                {
                    "apn": "TEST_EMP_NEG",
                    "built_form_key": "commercial",
                    "built_form_key_source": "tier0",
                    "du_subtype": None,
                    "is_residential": 0,
                    "landuse": "AE",
                    "lot_size_acres": 1.0,
                    "zone": "C-1",
                    "land_development_category": "urban",
                    "actual_living_sqft": 0.0,
                    "actual_building_sqft": 0.0,
                    "property_type": None,
                    "sales_lot_size_acres": None,
                    "units": None,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 0.0,
                    "building_count": 0,
                    "footprint_ratio": 0.0,
                    "max_levels": 0,
                    "intersection_density": 0.0,
                }
            ],
            "brewgis.assessor.authoritative_residential_area": [
                {
                    "apn": "TEST_EMP_NEG",
                    "authoritative_residential_sqft": None,
                    "authoritative_non_residential_sqft": -100.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["emp_dasym_weight"] >= 0, (
        f"emp_dasym_weight should be >= 0 even with negative authoritative data, "
        f"got {row['emp_dasym_weight']}"
    )
    # authoritative_non_residential_sqft = -100 → GREATEST(0, -100) = 0
    # Multiplier: (1.0 + 0.0/200) = 1.0
    # Expected: 0 * 1.0 = 0
    assert row["emp_dasym_weight"] == 0.0, (
        f"emp_dasym_weight should be 0 (clamped from -100), got {row['emp_dasym_weight']}"
    )


def test_pop_weight_non_negative_with_negative_authoritative(context):
    """Negative authoritative_residential_sqft → GREATEST(0, ...) clamps to 0"""
    result = context.evaluate(
        "brewgis.assessor.parcel_dasymetric_weights",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_bft_classification": [
                {
                    "apn": "TEST_POP_NEG",
                    "built_form_key": "detsf_ll",
                    "built_form_key_source": "tier0",
                    "du_subtype": "detsf_ll",
                    "is_residential": 1,
                    "landuse": "A1",
                    "lot_size_acres": 0.5,
                    "zone": "R-1",
                    "land_development_category": "urban",
                    "actual_living_sqft": 0.0,
                    "actual_building_sqft": 0.0,
                    "property_type": None,
                    "sales_lot_size_acres": None,
                    "units": None,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 0.0,
                    "building_count": 0,
                    "footprint_ratio": 0.0,
                    "max_levels": 0,
                    "intersection_density": 0.0,
                }
            ],
            "brewgis.assessor.authoritative_residential_area": [
                {
                    "apn": "TEST_POP_NEG",
                    "authoritative_residential_sqft": -200.0,
                    "authoritative_non_residential_sqft": None,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["pop_dasym_weight"] >= 0, (
        f"pop_dasym_weight should be >= 0 even with negative authoritative data, "
        f"got {row['pop_dasym_weight']}"
    )
    # authoritative_residential_sqft = -200 → GREATEST(0, -200) = 0
    # Expected: 0
    assert row["pop_dasym_weight"] == 0.0, (
        f"pop_dasym_weight should be 0 (clamped from -200), got {row['pop_dasym_weight']}"
    )


def test_emp_weight_positive_with_normal_data(context):
    """Normal positive data → emp_dasym_weight > 0"""
    result = context.evaluate(
        "brewgis.assessor.parcel_dasymetric_weights",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_bft_classification": [
                {
                    "apn": "TEST_EMP_POS",
                    "built_form_key": "commercial",
                    "built_form_key_source": "tier0",
                    "du_subtype": None,
                    "is_residential": 0,
                    "landuse": "AE",
                    "lot_size_acres": 1.0,
                    "zone": "C-1",
                    "land_development_category": "urban",
                    "actual_living_sqft": 0.0,
                    "actual_building_sqft": 0.0,
                    "property_type": None,
                    "sales_lot_size_acres": None,
                    "units": None,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 500.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 500.0,
                    "building_count": 1,
                    "footprint_ratio": 0.02,
                    "max_levels": 1,
                    "intersection_density": 10.0,
                }
            ],
        },
    )
    df = result[0].df
    row = df.iloc[0]
    assert row["emp_dasym_weight"] >= 0, (
        f"emp_dasym_weight should be >= 0 with normal data, "
        f"got {row['emp_dasym_weight']}"
    )
    # commercial_building_sqft = 500 (no authoritative, no intersection_density adjustment)
    # GREATEST(0, COALESCE(NULL, 500+0+0, ...)) = 500
    # Multiplier: (1.0 + 10.0/200) = 1.05
    # Expected: 500 * 1.05 = 525
    assert row["emp_dasym_weight"] == 525.0, (
        f"emp_dasym_weight should be 525, got {row['emp_dasym_weight']}"
    )
