"""Unit tests for Base Canvas Calibration v2 changes.

Tests for:
  - Sector-specific sqft_per_emp (retail/office/public/industrial)
  - Reference sqft_per_du defaults (3,000 detsf, 1,500 attsf/MF)
  - Unified building-sqft-based employment allocation
"""


def test_retail_sqft_per_emp_formula_fallback(context):
    """Parcel with emp_retail_services > 0, no building sqft, no geometry bldg area
    → sqft_per_emp formula path fires → 5 emp × 706 sqft/emp = 3530"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_RETAIL_001",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 12.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 0.0,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 0.0,
                    "building_count": 0,
                    "footprint_ratio": 0.0,
                    "max_levels": 0,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 100.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                }
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 5.0,
                    "emp_retail_services": 5.0,
                    "emp_restaurant": 0.0,
                    "emp_accommodation": 0.0,
                    "emp_arts_entertainment": 0.0,
                    "emp_other_services": 0.0,
                    "emp_office_services": 0.0,
                    "emp_medical_services": 0.0,
                    "emp_public_admin": 0.0,
                    "emp_education": 0.0,
                    "emp_manufacturing": 0.0,
                    "emp_wholesale": 0.0,
                    "emp_transport_warehousing": 0.0,
                    "emp_utilities": 0.0,
                    "emp_construction": 0.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 0.0,
                    "emp_off": 0.0,
                    "emp_pub": 0.0,
                    "emp_ind": 0.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["bldg_area_retail_services_v"].iloc[0] == 3530.0, (
        f"Expected bldg_area_retail_services_v=3530 (5 emp × 706 sqft/emp), "
        f"got {df['bldg_area_retail_services_v'].iloc[0]}"
    )


def test_detsf_sl_sqft_per_du_3000(context):
    """Parcel with du=2, du_subtype=detsf_sl, no residential building sqft
    → formula: 2 × 3000 = 6000 sqft"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_DU_DETSF",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_sl",
                    "intersection_density": 10.0,
                    "area_gross": 5.0,
                    "area_gross_acres": 5.0,
                    "area_parcel_acres": 4.5,
                    "area_dev_condition_acres": 4.0,
                    "area_row_acres": 0.5,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 2.0,
                    "du_subtype": "detsf_sl",
                    "du_estimated": 2.0,
                    "is_residential": True,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 0.0,
                    "building_count": 0,
                    "footprint_ratio": 0.0,
                    "max_levels": 0,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 2.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 2.0,
                    "hh_dasym_weight": 1.95,
                    "hh_estimated": 1.95,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 0.0,
                    "emp_retail_services": 0.0,
                    "emp_restaurant": 0.0,
                    "emp_accommodation": 0.0,
                    "emp_arts_entertainment": 0.0,
                    "emp_other_services": 0.0,
                    "emp_office_services": 0.0,
                    "emp_medical_services": 0.0,
                    "emp_public_admin": 0.0,
                    "emp_education": 0.0,
                    "emp_manufacturing": 0.0,
                    "emp_wholesale": 0.0,
                    "emp_transport_warehousing": 0.0,
                    "emp_utilities": 0.0,
                    "emp_construction": 0.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 0.0,
                    "emp_off": 0.0,
                    "emp_pub": 0.0,
                    "emp_ind": 0.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
        },
    )
    df = result[0].df
    assert df["bldg_area_detsf_sl_v"].iloc[0] == 6000.0, (
        f"Expected bldg_area_detsf_sl_v=6000 (2 DU × 3000 sqft/DU), "
        f"got {df['bldg_area_detsf_sl_v'].iloc[0]}"
    )


def test_attsf_sqft_per_du_1500(context):
    """Parcel with du=3, du_subtype=attsf, no residential building sqft
    → GREATEST(3 × 1500, 3 × 600) = 4500 sqft"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_DU_ATTSF",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "attsf",
                    "intersection_density": 10.0,
                    "area_gross": 5.0,
                    "area_gross_acres": 5.0,
                    "area_parcel_acres": 4.5,
                    "area_dev_condition_acres": 4.0,
                    "area_row_acres": 0.5,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 3.0,
                    "du_subtype": "attsf",
                    "du_estimated": 3.0,
                    "is_residential": True,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 0.0,
                    "building_count": 0,
                    "footprint_ratio": 0.0,
                    "max_levels": 0,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 3.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 3.0,
                    "hh_dasym_weight": 2.85,
                    "hh_estimated": 2.85,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 0.0,
                    "emp_retail_services": 0.0,
                    "emp_restaurant": 0.0,
                    "emp_accommodation": 0.0,
                    "emp_arts_entertainment": 0.0,
                    "emp_other_services": 0.0,
                    "emp_office_services": 0.0,
                    "emp_medical_services": 0.0,
                    "emp_public_admin": 0.0,
                    "emp_education": 0.0,
                    "emp_manufacturing": 0.0,
                    "emp_wholesale": 0.0,
                    "emp_transport_warehousing": 0.0,
                    "emp_utilities": 0.0,
                    "emp_construction": 0.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 0.0,
                    "emp_off": 0.0,
                    "emp_pub": 0.0,
                    "emp_ind": 0.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
        },
    )
    df = result[0].df
    assert df["bldg_area_attsf_v"].iloc[0] == 4500.0, (
        f"Expected bldg_area_attsf_v=4500 (3 DU × 1500 sqft/DU), "
        f"got {df['bldg_area_attsf_v'].iloc[0]}"
    )


def test_proportional_emp_allocation(context):
    """Two parcels with equal building sqft in same block → 50/50 emp split"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_EMP_A",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 12.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 0.0,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 5000.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.5,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                },
                {
                    "parcel_id": "CAL_EMP_B",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 12.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 0.0,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 5000.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.5,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                },
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 100.0,
                    "emp_retail_services": 50.0,
                    "emp_restaurant": 20.0,
                    "emp_accommodation": 10.0,
                    "emp_arts_entertainment": 5.0,
                    "emp_other_services": 15.0,
                    "emp_office_services": 30.0,
                    "emp_medical_services": 10.0,
                    "emp_public_admin": 8.0,
                    "emp_education": 12.0,
                    "emp_manufacturing": 40.0,
                    "emp_wholesale": 20.0,
                    "emp_transport_warehousing": 15.0,
                    "emp_utilities": 5.0,
                    "emp_construction": 10.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 100.0,
                    "emp_off": 40.0,
                    "emp_pub": 20.0,
                    "emp_ind": 80.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    df_a = df[df["parcel_id"] == "CAL_EMP_A"]
    df_b = df[df["parcel_id"] == "CAL_EMP_B"]
    assert len(df_a) == 1, f"Expected 1 row for CAL_EMP_A, got {len(df_a)}"
    assert len(df_b) == 1, f"Expected 1 row for CAL_EMP_B, got {len(df_b)}"
    assert abs(df_a["emp_retail_services"].iloc[0] - 25.0) < 0.1, (
        f"Expected emp_retail_services~25 for CAL_EMP_A (50% of 50), "
        f"got {df_a['emp_retail_services'].iloc[0]}"
    )
    assert abs(df_b["emp_retail_services"].iloc[0] - 25.0) < 0.1, (
        f"Expected emp_retail_services~25 for CAL_EMP_B (50% of 50), "
        f"got {df_b['emp_retail_services'].iloc[0]}"
    )


def test_residential_parcel_zero_emp(context):
    """Residential parcel with no building sqft → gets zero employment"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_RES_EMP",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_sl",
                    "intersection_density": 10.0,
                    "area_gross": 5.0,
                    "area_gross_acres": 5.0,
                    "area_parcel_acres": 4.5,
                    "area_dev_condition_acres": 4.0,
                    "area_row_acres": 0.5,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 1.0,
                    "du_subtype": "detsf_sl",
                    "du_estimated": 1.0,
                    "is_residential": True,
                    "residential_building_sqft": 2000.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 2000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.2,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
                },
                {
                    "parcel_id": "CAL_COM_EMP",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 12.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 0.0,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 5000.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.5,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                },
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 100.0,
                    "emp_retail_services": 50.0,
                    "emp_restaurant": 20.0,
                    "emp_accommodation": 10.0,
                    "emp_arts_entertainment": 5.0,
                    "emp_other_services": 15.0,
                    "emp_office_services": 30.0,
                    "emp_medical_services": 10.0,
                    "emp_public_admin": 8.0,
                    "emp_education": 12.0,
                    "emp_manufacturing": 40.0,
                    "emp_wholesale": 20.0,
                    "emp_transport_warehousing": 15.0,
                    "emp_utilities": 5.0,
                    "emp_construction": 10.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 100.0,
                    "emp_off": 40.0,
                    "emp_pub": 20.0,
                    "emp_ind": 80.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    df_res = df[df["parcel_id"] == "CAL_RES_EMP"]
    df_com = df[df["parcel_id"] == "CAL_COM_EMP"]
    assert len(df_res) == 1, f"Expected 1 row for CAL_RES_EMP, got {len(df_res)}"
    assert len(df_com) == 1, f"Expected 1 row for CAL_COM_EMP, got {len(df_com)}"
    assert df_res["emp"].iloc[0] == 0.0, (
        f"Expected emp=0 for residential parcel (0 building sqft), "
        f"got {df_res['emp'].iloc[0]}"
    )
    assert abs(df_com["emp"].iloc[0] - 100.0) < 0.1, (
        f"Expected emp~100 for commercial parcel (all block emp), "
        f"got {df_com['emp'].iloc[0]}"
    )


def test_detsf_sl_assessor_over_formula(context):
    """Parcel with du=1, du_subtype=detsf_sl, assessor sqft 5000 > formula 3000
    → bldg_area_detsf_sl_v = 5000 (GREATEST picks assessor)"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_V3_DETSF",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_sl",
                    "intersection_density": 10.0,
                    "area_gross": 5.0,
                    "area_gross_acres": 5.0,
                    "area_parcel_acres": 4.5,
                    "area_dev_condition_acres": 4.0,
                    "area_row_acres": 0.5,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 1.0,
                    "du_subtype": "detsf_sl",
                    "du_estimated": 1.0,
                    "is_residential": True,
                    "residential_building_sqft": 5000.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.2,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
                }
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 0.0,
                    "emp_retail_services": 0.0,
                    "emp_restaurant": 0.0,
                    "emp_accommodation": 0.0,
                    "emp_arts_entertainment": 0.0,
                    "emp_other_services": 0.0,
                    "emp_office_services": 0.0,
                    "emp_medical_services": 0.0,
                    "emp_public_admin": 0.0,
                    "emp_education": 0.0,
                    "emp_manufacturing": 0.0,
                    "emp_wholesale": 0.0,
                    "emp_transport_warehousing": 0.0,
                    "emp_utilities": 0.0,
                    "emp_construction": 0.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 0.0,
                    "emp_off": 0.0,
                    "emp_pub": 0.0,
                    "emp_ind": 0.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["bldg_area_detsf_sl_v"].iloc[0] == 5000.0, (
        f"Expected bldg_area_detsf_sl_v=5000 (assessor 5000 > formula 3000), "
        f"got {df['bldg_area_detsf_sl_v'].iloc[0]}"
    )


def test_detsf_ll_formula_path(context):
    """Parcel with du=2, du_subtype=detsf_ll, no residential building sqft
    → bldg_area_detsf_ll_v = 2 × 3000 = 6000 (GREATEST formula path)"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_V3_DETSF_LL",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_ll",
                    "intersection_density": 10.0,
                    "area_gross": 5.0,
                    "area_gross_acres": 5.0,
                    "area_parcel_acres": 4.5,
                    "area_dev_condition_acres": 4.0,
                    "area_row_acres": 0.5,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 2.0,
                    "du_subtype": "detsf_ll",
                    "du_estimated": 2.0,
                    "is_residential": True,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 0.0,
                    "building_count": 0,
                    "footprint_ratio": 0.0,
                    "max_levels": 0,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 2.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 2.0,
                    "hh_dasym_weight": 1.95,
                    "hh_estimated": 1.95,
                }
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 0.0,
                    "emp_retail_services": 0.0,
                    "emp_restaurant": 0.0,
                    "emp_accommodation": 0.0,
                    "emp_arts_entertainment": 0.0,
                    "emp_other_services": 0.0,
                    "emp_office_services": 0.0,
                    "emp_medical_services": 0.0,
                    "emp_public_admin": 0.0,
                    "emp_education": 0.0,
                    "emp_manufacturing": 0.0,
                    "emp_wholesale": 0.0,
                    "emp_transport_warehousing": 0.0,
                    "emp_utilities": 0.0,
                    "emp_construction": 0.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 0.0,
                    "emp_off": 0.0,
                    "emp_pub": 0.0,
                    "emp_ind": 0.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["bldg_area_detsf_ll_v"].iloc[0] == 6000.0, (
        f"Expected bldg_area_detsf_ll_v=6000 (2 DU × 3000 sqft/DU), "
        f"got {df['bldg_area_detsf_ll_v'].iloc[0]}"
    )


def test_null_subtype_mf_assessor_recovery_greatest(context):
    """Parcel with NULL du_subtype + 5000 residential_building_sqft
    → bldg_area_mf_v = 5000 (GREATEST picks assessor via catch-all CASE)"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "CAL_V3_MF_NULL",
                    "geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "local_geometry": "POLYGON((-121.5 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.5 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "mf",
                    "intersection_density": 10.0,
                    "area_gross": 5.0,
                    "area_gross_acres": 5.0,
                    "area_parcel_acres": 4.5,
                    "area_dev_condition_acres": 4.0,
                    "area_row_acres": 0.5,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 1.0,
                    "du_subtype": None,
                    "du_estimated": 1.0,
                    "is_residential": True,
                    "residential_building_sqft": 5000.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.2,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
                }
            ],
            "brewgis.staging.wac_block_projected": [
                {
                    "geoid": "060670011001001",
                    "emp": 0.0,
                    "emp_retail_services": 0.0,
                    "emp_restaurant": 0.0,
                    "emp_accommodation": 0.0,
                    "emp_arts_entertainment": 0.0,
                    "emp_other_services": 0.0,
                    "emp_office_services": 0.0,
                    "emp_medical_services": 0.0,
                    "emp_public_admin": 0.0,
                    "emp_education": 0.0,
                    "emp_manufacturing": 0.0,
                    "emp_wholesale": 0.0,
                    "emp_transport_warehousing": 0.0,
                    "emp_utilities": 0.0,
                    "emp_construction": 0.0,
                    "emp_agriculture": 0.0,
                    "emp_extraction": 0.0,
                    "emp_military": 0.0,
                    "emp_ret": 0.0,
                    "emp_off": 0.0,
                    "emp_pub": 0.0,
                    "emp_ind": 0.0,
                    "emp_ag": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.seeds.calibration_parameters": [
                {
                    "land_development_category": "urban",
                    "sqft_per_du": 3000.0,
                    "sqft_per_emp_retail": 706.0,
                    "sqft_per_emp_office": 408.0,
                    "sqft_per_emp_public": 909.0,
                    "sqft_per_emp_industrial": 267.0,
                    "intersection_density": 25.0,
                    "res_irrigation_frac": 0.064,
                    "com_irrigation_frac": 0.035,
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 0.0,
                    "total_housing_units": 0.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["bldg_area_mf_v"].iloc[0] == 5000.0, (
        f"Expected bldg_area_mf_v=5000 (assessor 5000 via NULL-subtype catch-all in GREATEST), "
        f"got {df['bldg_area_mf_v'].iloc[0]}"
    )
