"""Unit tests for parcel_du_estimation model.

Tests the 6-tier DU estimation cascade:
  - Tier 1: Direct assessor observation (units>0 → du = units)
  - Tier 2: SFR subtypes → du = 1
  - Tier 3: MF subtype + building sqft → estimated
  - Tier 4: MF subtype, no building data → min DU
  - Tier 5: urban/mixed_use default → du = 1
  - Tier 6: non-residential → du = 0

Also validates vacancy rates:
  - detsf_sl/ll → 2.5%
  - attsf/mf2to4 → 5.0%
  - mf5p → 8.0%

Run with: sqlmesh test
"""


def test_assessor_units_direct(context):
    """assessor.units>0 → du = assessor.units"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_T1",
                    "built_form_key": "mf5p",
                    "du_subtype": "mf5p",
                    "is_residential": True,
                    "lot_size_acres": 1.0,
                    "land_development_category": "urban",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 15.0,
                }
            ],
            "public.sacog_assessor_sales_raw": [
                {
                    "apn": "TEST_DU_T1",
                    "units": 12,
                    "property_type": "Multiple Family Residence",
                    "year_built": 2005,
                }
            ],
        },
    )
    df = result[0].df
    assert df["du"].iloc[0] == 12.0, f"Expected du=12, got {df['du'].iloc[0]}"


def test_sfr_du_equals_one(context):
    """detsf_sl/ll/attsf → du=1"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_T2",
                    "built_form_key": "detsf_sl",
                    "du_subtype": "detsf_sl",
                    "is_residential": True,
                    "lot_size_acres": 0.10,
                    "land_development_category": "urban",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 12.0,
                }
            ],
        },
    )
    df = result[0].df
    assert df["du"].iloc[0] == 1.0, f"Expected du=1 (SFR), got {df['du'].iloc[0]}"


def test_mf_with_sqft_estimated_du(context):
    """mf2to4 + res_sqft>0 → du ≥ 2"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_T3",
                    "built_form_key": "mf2to4",
                    "du_subtype": "mf2to4",
                    "is_residential": True,
                    "lot_size_acres": 0.50,
                    "land_development_category": "urban",
                    "residential_building_sqft": 5000.0,
                    "intersection_density": 15.0,
                }
            ],
        },
    )
    df = result[0].df
    assert df["du"].iloc[0] >= 2.0, (
        f"Expected du≥2 (MF with sqft), got {df['du'].iloc[0]}"
    )


def test_mf_no_sqft_uses_min_du(context):
    """mf2to4 + no res_sqft → du=2"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_T4",
                    "built_form_key": "mf2to4",
                    "du_subtype": "mf2to4",
                    "is_residential": True,
                    "lot_size_acres": 0.50,
                    "land_development_category": "urban",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 10.0,
                }
            ],
        },
    )
    df = result[0].df
    assert df["du"].iloc[0] == 2.0, (
        f"Expected du=2 (MF no sqft), got {df['du'].iloc[0]}"
    )


def test_non_residential_du_zero(context):
    """commercial → du=0"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_DU_T6",
                    "built_form_key": "commercial",
                    "du_subtype": None,
                    "is_residential": False,
                    "lot_size_acres": 1.0,
                    "land_development_category": "urban",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 8.0,
                }
            ],
        },
    )
    df = result[0].df
    assert df["du"].iloc[0] == 0.0, (
        f"Expected du=0 (commercial), got {df['du'].iloc[0]}"
    )


def test_vacancy_rate_detsf(context):
    """detsf_sl → vacancy_rate = 0.025"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_VAC_DETSF",
                    "built_form_key": "detsf_sl",
                    "du_subtype": "detsf_sl",
                    "is_residential": True,
                    "lot_size_acres": 0.10,
                    "land_development_category": "urban",
                    "residential_building_sqft": 0.0,
                    "intersection_density": 12.0,
                }
            ],
        },
    )
    df = result[0].df
    assert abs(df["vacancy_rate"].iloc[0] - 0.025) < 0.001, (
        f"Expected vacancy_rate=0.025, got {df['vacancy_rate'].iloc[0]}"
    )


def test_vacancy_rate_mf5p(context):
    """mf5p → vacancy_rate = 0.08"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TEST_VAC_MF5",
                    "built_form_key": "mf5p",
                    "du_subtype": "mf5p",
                    "is_residential": True,
                    "lot_size_acres": 1.0,
                    "land_development_category": "urban",
                    "residential_building_sqft": 10000.0,
                    "intersection_density": 20.0,
                }
            ],
        },
    )
    df = result[0].df
    assert abs(df["vacancy_rate"].iloc[0] - 0.080) < 0.001, (
        f"Expected vacancy_rate=0.080, got {df['vacancy_rate'].iloc[0]}"
    )


def test_min_sqft_per_unit_clamps_low_calibration(context):
    """@min_sqft_per_unit=400 → county avg of 100 gets clamped, DU drops"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TGT_CLAMP1",
                    "built_form_key": "mf5p",
                    "du_subtype": "mf5p",
                    "is_residential": True,
                    "lot_size_acres": 2.0,
                    "land_development_category": "urban",
                    "residential_building_sqft": 40000.0,
                    "intersection_density": 15.0,
                },
                {
                    "apn": "CAL_LOW",
                    "built_form_key": "mf5p",
                    "du_subtype": "mf5p",
                    "is_residential": True,
                    "lot_size_acres": 0.5,
                    "land_development_category": "urban",
                    "residential_building_sqft": 200.0,
                    "intersection_density": 15.0,
                },
            ],
            "public.sacog_assessor_sales_raw": [
                {
                    "apn": "CAL_LOW",
                    "units": 2,
                    "property_type": "Multiple Family Residence",
                    "year_built": 2000,
                },
            ],
        },
    )
    df = result[0].df
    _actual_sqft = df.loc[df["apn"] == "TGT_CLAMP1", "region_avg_sqft_per_unit"].iloc[0]
    assert _actual_sqft == 400.0, (
        f"Expected region_avg=400 (clamped from 100), got {_actual_sqft}"
    )
    _actual_du = df.loc[df["apn"] == "TGT_CLAMP1", "du"].iloc[0]
    assert _actual_du == 100.0, f"Expected du=100 (40000/400), got {_actual_du}"


def test_min_sqft_per_unit_passes_through_reasonable_calibration(context):
    """@min_sqft_per_unit=400 → county avg of 1000 passes through unchanged"""
    result = context.evaluate(
        "brewgis.assessor.parcel_du_estimation",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.assessor.parcel_dasymetric_weights": [
                {
                    "apn": "TGT_OK",
                    "built_form_key": "mf5p",
                    "du_subtype": "mf5p",
                    "is_residential": True,
                    "lot_size_acres": 2.0,
                    "land_development_category": "urban",
                    "residential_building_sqft": 40000.0,
                    "intersection_density": 15.0,
                },
                {
                    "apn": "CAL_OK",
                    "built_form_key": "mf5p",
                    "du_subtype": "mf5p",
                    "is_residential": True,
                    "lot_size_acres": 0.5,
                    "land_development_category": "urban",
                    "residential_building_sqft": 8000.0,
                    "intersection_density": 15.0,
                },
            ],
            "public.sacog_assessor_sales_raw": [
                {
                    "apn": "CAL_OK",
                    "units": 8,
                    "property_type": "Multiple Family Residence",
                    "year_built": 2000,
                },
            ],
        },
    )
    df = result[0].df
    _actual_sqft = df.loc[df["apn"] == "TGT_OK", "region_avg_sqft_per_unit"].iloc[0]
    assert _actual_sqft == 1000.0, (
        f"Expected region_avg=1000 (unclamped), got {_actual_sqft}"
    )
    _actual_du = df.loc[df["apn"] == "TGT_OK", "du"].iloc[0]
    assert _actual_du == 40.0, f"Expected du=40 (40000/1000), got {_actual_du}"
