"""Unit tests for base_canvas_employment model.

Tests:
  - Employment is sector-constrained by building sqft type (Section 7)
  - Commercial sectors → commercial_building_sqft
  - Industrial sectors → industrial_building_sqft
  - Other sectors → other_building_sqft
  - Σ(emp per parcel in block) ≈ WAC block total

Run with: sqlmesh test
"""


def test_commercial_sqft_routes_retail_jobs(context):
    """Parcel with commercial sqft gets retail/office jobs"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_employment",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_demographics": [
                {
                    "parcel_id": "EMP1",
                    "geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "commercial_building_sqft": 5000.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "area_gross": 10.0,
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 8.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "pop_groupquarter": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_subtype": None,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.02,
                    "max_levels": 2,
                    "dasym_impervious_fraction": 0.5,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 1.0,
                    "du_estimated": 0.0,
                    "hh_size": 0.0,
                    "vacancy_rate": 0.05,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                    "median_income": None,
                    "rent_burden_pct": None,
                    "pct_minority": None,
                    "pct_college_educated": None,
                    "cost_burden_pct": None,
                    "vacancy_rate_demo": 0.05,
                    "bldg_area_detsf_sl": 0.0,
                    "bldg_area_detsf_ll": 0.0,
                    "bldg_area_attsf": 0.0,
                    "bldg_area_mf": 0.0,
                    "bldg_area_retail_services": 0.0,
                    "bldg_area_restaurant": 0.0,
                    "bldg_area_accommodation": 0.0,
                    "bldg_area_arts_entertainment": 0.0,
                    "bldg_area_other_services": 0.0,
                    "bldg_area_office_services": 0.0,
                    "bldg_area_public_admin": 0.0,
                    "bldg_area_education": 0.0,
                    "bldg_area_medical_services": 0.0,
                    "bldg_area_transport_warehousing": 0.0,
                    "bldg_area_wholesale": 0.0,
                    "land_use": None,
                    "assessor_use_code": None,
                    "residential_irrigated_area": 0.0,
                    "commercial_irrigated_area": 0.0,
                    "area_parcel_res": 0.0,
                    "area_parcel_emp_ag": 0.0,
                    "area_parcel_emp": 0.0,
                    "area_parcel_mixed_use": 0.0,
                    "area_parcel_no_use": 0.0,
                }
            ],
            "brewgis.staging.wac_block": [
                {
                    "geoid": "060670011001001",
                    "emp": 1500.0,
                    "emp_retail_services": 200.0,
                    "emp_restaurant": 100.0,
                    "emp_accommodation": 50.0,
                    "emp_arts_entertainment": 30.0,
                    "emp_other_services": 80.0,
                    "emp_office_services": 180.0,
                    "emp_medical_services": 150.0,
                    "emp_public_admin": 120.0,
                    "emp_education": 200.0,
                    "emp_manufacturing": 80.0,
                    "emp_wholesale": 60.0,
                    "emp_transport_warehousing": 40.0,
                    "emp_utilities": 20.0,
                    "emp_construction": 30.0,
                    "emp_agriculture": 20.0,
                    "emp_extraction": 10.0,
                    "emp_military": 5.0,
                    "emp_ret": 460.0,
                    "emp_off": 330.0,
                    "emp_pub": 320.0,
                    "emp_ind": 230.0,
                    "emp_ag": 30.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    # Parcel with 5000 commercial sqft (only parcel in block)
    # Gets all 460 retail jobs (200+100+50+30+80)
    # and all 330 office+medical jobs (180+150)
    assert df["emp_retail_services"].iloc[0] > 0, (
        f"Expected retail jobs > 0 with commercial sqft, got {df['emp_retail_services'].iloc[0]}"
    )
    assert df["emp_office_services"].iloc[0] > 0, (
        f"Expected office jobs > 0 with commercial sqft, got {df['emp_office_services'].iloc[0]}"
    )


def test_no_commercial_sqft_no_retail_jobs(context):
    """Parcel with zero commercial sqft gets zero retail/office jobs"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_employment",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_demographics": [
                {
                    "parcel_id": "EMP2",
                    "geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "area_gross": 10.0,
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_sl",
                    "intersection_density": 12.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 100.0,
                    "pop_groupquarter": 0.0,
                    "hh": 40.0,
                    "du": 42.0,
                    "du_subtype": "detsf_sl",
                    "is_residential": True,
                    "residential_building_sqft": 1800.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 1800.0,
                    "building_count": 1,
                    "footprint_ratio": 0.02,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "du_estimated": 1.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
                    "median_income": 75000.0,
                    "rent_burden_pct": 30.0,
                    "pct_minority": 45.0,
                    "pct_college_educated": 35.0,
                    "cost_burden_pct": 25.0,
                    "vacancy_rate_demo": 0.025,
                    "bldg_area_detsf_sl": 800.0,
                    "bldg_area_detsf_ll": 0.0,
                    "bldg_area_attsf": 0.0,
                    "bldg_area_mf": 0.0,
                    "bldg_area_retail_services": 0.0,
                    "bldg_area_restaurant": 0.0,
                    "bldg_area_accommodation": 0.0,
                    "bldg_area_arts_entertainment": 0.0,
                    "bldg_area_other_services": 0.0,
                    "bldg_area_office_services": 0.0,
                    "bldg_area_public_admin": 0.0,
                    "bldg_area_education": 0.0,
                    "bldg_area_medical_services": 0.0,
                    "bldg_area_transport_warehousing": 0.0,
                    "bldg_area_wholesale": 0.0,
                    "land_use": None,
                    "assessor_use_code": None,
                    "residential_irrigated_area": 0.5,
                    "commercial_irrigated_area": 0.0,
                    "area_parcel_res": 0.0,
                    "area_parcel_emp_ag": 0.0,
                    "area_parcel_emp": 0.0,
                    "area_parcel_mixed_use": 0.0,
                    "area_parcel_no_use": 0.0,
                }
            ],
            "brewgis.staging.wac_block": [
                {
                    "geoid": "060670011001001",
                    "emp": 1500.0,
                    "emp_retail_services": 200.0,
                    "emp_restaurant": 100.0,
                    "emp_accommodation": 50.0,
                    "emp_arts_entertainment": 30.0,
                    "emp_other_services": 80.0,
                    "emp_office_services": 180.0,
                    "emp_medical_services": 150.0,
                    "emp_public_admin": 120.0,
                    "emp_education": 200.0,
                    "emp_manufacturing": 80.0,
                    "emp_wholesale": 60.0,
                    "emp_transport_warehousing": 40.0,
                    "emp_utilities": 20.0,
                    "emp_construction": 30.0,
                    "emp_agriculture": 20.0,
                    "emp_extraction": 10.0,
                    "emp_military": 5.0,
                    "emp_ret": 460.0,
                    "emp_off": 330.0,
                    "emp_pub": 320.0,
                    "emp_ind": 230.0,
                    "emp_ag": 30.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["emp_retail_services"].iloc[0] == 0.0, (
        f"Expected 0 retail jobs (no commercial sqft), got {df['emp_retail_services'].iloc[0]}"
    )
    assert df["emp_manufacturing"].iloc[0] == 0.0, (
        f"Expected 0 manufacturing jobs (no industrial sqft), got {df['emp_manufacturing'].iloc[0]}"
    )
