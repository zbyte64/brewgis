"""Unit tests for base_canvas_combined model.

Tests (merged from demographics + employment):
  - Population is DU-weighted from Census 2020 blocks
  - Σ(pop per parcel in block) ≈ total block population
  - Non-residential parcels get zero population
  - ACS demographics are area-weighted from block groups
  - Employment is sector-constrained by building sqft type (Section 7)
  - Commercial sectors → commercial_building_sqft
  - Industrial sectors → industrial_building_sqft
  - Other sectors → other_building_sqft
  - Σ(emp per parcel in block) ≈ WAC block total

Run with: sqlmesh test
"""


def test_population_conservation(context):
    """2 parcels in one block should split pop proportionally by DU weight"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "P1",
                    "geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_sl",
                    "intersection_density": 12.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 1.0,
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
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
                    "local_geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                },
                {
                    "parcel_id": "P2",
                    "geometry": "POLYGON((-121.50 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.50 38.50))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "detsf_sl",
                    "intersection_density": 10.0,
                    "area_gross": 8.0,
                    "area_gross_acres": 8.0,
                    "area_parcel_acres": 7.5,
                    "area_dev_condition_acres": 7.0,
                    "area_row_acres": 0.8,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
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
                    "local_geometry": "POLYGON((-121.50 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.50 38.50))",
                },
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 3000.0,
                    "total_housing_units": 1200.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    total_pop = df["pop"].sum()
    # With du weights 1 and 2 in same block with pop 3000:
    # P1 gets 3000 * 1/3 = 1000, P2 gets 3000 * 2/3 = 2000
    assert abs(total_pop - 3000.0) < 1.0, f"Expected total pop ~3000, got {total_pop}"


def test_non_residential_pop_zero(context):
    """Non-residential parcels get zero population"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "P3",
                    "geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "county": "Sacramento",
                    "land_development_category": "industrial",
                    "built_form_key": "industrial",
                    "intersection_density": 5.0,
                    "area_gross": 20.0,
                    "area_gross_acres": 20.0,
                    "area_parcel_acres": 19.0,
                    "area_dev_condition_acres": 18.0,
                    "area_row_acres": 2.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 0.0,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "commercial_building_sqft": 10000.0,
                    "industrial_building_sqft": 50000.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 60000.0,
                    "building_count": 2,
                    "footprint_ratio": 0.1,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.5,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 1.0,
                    "hh_size": 0.0,
                    "vacancy_rate": 0.05,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                    "local_geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 3000.0,
                    "total_housing_units": 1200.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
        },
    )
    df = result[0].df
    assert df["pop"].iloc[0] == 0.0, (
        f"Expected pop=0 (industrial), got {df['pop'].iloc[0]}"
    )


def test_commercial_sqft_routes_retail_jobs(context):
    """Parcel with commercial sqft gets retail/office jobs"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
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
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 0.0,
                    "is_residential": False,
                    "residential_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.02,
                    "max_levels": 2,
                    "dasym_impervious_fraction": 0.5,
                    "pop_dasym_weight": 0.0,
                    "emp_dasym_weight": 1.0,
                    "hh_size": 0.0,
                    "vacancy_rate": 0.05,
                    "du_pop_dasym_weight": 0.0,
                    "hh_dasym_weight": 0.0,
                    "hh_estimated": 0.0,
                    "local_geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 3000.0,
                    "total_housing_units": 1200.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.staging.wac_block_projected": [
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
    # Gets all retail jobs and all office+medical jobs
    assert df["emp_retail_services"].iloc[0] > 0, (
        f"Expected retail jobs > 0 with commercial sqft, got {df['emp_retail_services'].iloc[0]}"
    )
    assert df["emp_office_services"].iloc[0] > 0, (
        f"Expected office jobs > 0 with commercial sqft, got {df['emp_office_services'].iloc[0]}"
    )


def test_no_commercial_sqft_no_retail_jobs(context):
    """Parcel with zero commercial sqft gets zero retail/office jobs"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
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
                    "hh": 40.0,
                    "du": 42.0,
                    "du_estimated": 1.0,
                    "is_residential": True,
                    "residential_building_sqft": 1800.0,
                    "total_footprint_sqft": 1800.0,
                    "building_count": 1,
                    "footprint_ratio": 0.02,
                    "max_levels": 1,
                    "dasym_impervious_fraction": 0.3,
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
                    "local_geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                }
            ],
            "brewgis.staging.census_2020_block_projected": [
                {
                    "geoid": "060670011001001",
                    "total_population": 3000.0,
                    "total_housing_units": 1200.0,
                    "geometry": "POLYGON((-121.51 38.49,-121.48 38.49,-121.48 38.52,-121.51 38.52,-121.51 38.49))",
                }
            ],
            "brewgis.staging.wac_block_projected": [
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


def test_null_subtype_res_sqft_recovered_to_mf(context):
    """Parcel with NULL du_subtype + residential_sqft → bldg_area_mf gets the sqft"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "NULLDU1",
                    "geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "local_geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 8.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 1.0,
                    "is_residential": True,
                    "residential_building_sqft": 5000.0,
                    "commercial_building_sqft": 0.0,
                    "industrial_building_sqft": 0.0,
                    "other_building_sqft": 0.0,
                    "total_footprint_sqft": 5000.0,
                    "building_count": 1,
                    "footprint_ratio": 0.02,
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
        },
    )
    df = result[0].df
    # du_subtype is NULL → 4th COALESCE term recovers residential_building_sqft
    assert df["bldg_area_mf"].iloc[0] == 5000.0, (
        f"Expected bldg_area_mf=5000 (NULL du_subtype + 5000 res sqft), got {df['bldg_area_mf'].iloc[0]}"
    )
    # Other res bldg_area columns should be 0
    assert df["bldg_area_detsf_sl"].iloc[0] == 0.0, (
        f"Expected bldg_area_detsf_sl=0, got {df['bldg_area_detsf_sl'].iloc[0]}"
    )
    assert df["bldg_area_detsf_ll"].iloc[0] == 0.0, (
        f"Expected bldg_area_detsf_ll=0, got {df['bldg_area_detsf_ll'].iloc[0]}"
    )
    assert df["bldg_area_attsf"].iloc[0] == 0.0, (
        f"Expected bldg_area_attsf=0, got {df['bldg_area_attsf'].iloc[0]}"
    )


def test_null_subtype_no_res_sqft_zero_bldg_area(context):
    """Parcel with NULL du_subtype + 0 residential_sqft → all bldg_area = 0"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_combined",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "brewgis.base_canvas.base_canvas_geometry": [
                {
                    "parcel_id": "NULLDU2",
                    "geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "local_geometry": "POLYGON((-121.5 38.49,-121.49 38.49,-121.49 38.50,-121.50 38.50,-121.5 38.49))",
                    "county": "Sacramento",
                    "land_development_category": "urban",
                    "built_form_key": "commercial",
                    "intersection_density": 8.0,
                    "area_gross": 10.0,
                    "area_gross_acres": 10.0,
                    "area_parcel_acres": 9.5,
                    "area_dev_condition_acres": 9.0,
                    "area_row_acres": 1.0,
                    "pop": 0.0,
                    "hh": 0.0,
                    "du": 0.0,
                    "du_estimated": 1.0,
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
                    "pop_dasym_weight": 1.0,
                    "emp_dasym_weight": 0.0,
                    "hh_size": 2.5,
                    "vacancy_rate": 0.025,
                    "du_pop_dasym_weight": 1.0,
                    "hh_dasym_weight": 0.975,
                    "hh_estimated": 0.975,
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
        },
    )
    df = result[0].df
    # No residential sqft → no recovery, and NULL du_subtype means no subtype match
    assert df["bldg_area_mf"].iloc[0] == 0.0, (
        f"Expected bldg_area_mf=0 (NULL du_subtype + 0 res sqft), got {df['bldg_area_mf'].iloc[0]}"
    )
    assert df["bldg_area_detsf_sl"].iloc[0] == 0.0, (
        f"Expected bldg_area_detsf_sl=0, got {df['bldg_area_detsf_sl'].iloc[0]}"
    )
    assert df["bldg_area_detsf_ll"].iloc[0] == 0.0, (
        f"Expected bldg_area_detsf_ll=0, got {df['bldg_area_detsf_ll'].iloc[0]}"
    )
    assert df["bldg_area_attsf"].iloc[0] == 0.0, (
        f"Expected bldg_area_attsf=0, got {df['bldg_area_attsf'].iloc[0]}"
    )
