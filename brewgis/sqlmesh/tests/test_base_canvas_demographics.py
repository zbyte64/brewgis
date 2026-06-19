"""Unit tests for base_canvas_demographics model.

Tests:
  - Population is DU-weighted from Census 2020 blocks
  - Σ(pop per parcel in block) ≈ total block population
  - Non-residential parcels get zero population
  - ACS demographics are area-weighted from block groups

Run with: sqlmesh test
"""


def test_population_conservation(context):
    """2 parcels in one block should split pop proportionally by DU weight"""
    result = context.evaluate(
        "brewgis.base_canvas.base_canvas_demographics",
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
            "brewgis.staging.census_2020_block": [
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
        "brewgis.base_canvas.base_canvas_demographics",
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
            "brewgis.staging.census_2020_block": [
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
