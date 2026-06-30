MODEL (
  name brewgis.analysis.core_increment,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    number_of_rows(threshold := 1)
  )
);

-- Core Increment Model — Scenario Builder Delta
--
-- Computes the delta between the end-state allocation and the existing
-- (base canvas) condition for each attribute. This shows the change
-- from baseline for every output metric.
--
-- The increment is computed as:
--     increment = COALESCE(end_state.value, 0) - COALESCE(base.value, 0)

WITH end_state AS (
    SELECT * FROM brewgis.analysis.core_end_state
),

base AS (
    SELECT * FROM @base_canvas_table
)

SELECT
    COALESCE(es.parcel_id, b.parcel_id) AS parcel_id,
    b.gross_acres,
    es.acres_developable,
    es.acres_developed,
    es.land_dev_category,

    -- Dwelling units
    COALESCE(es.dwelling_units_total, 0.0) - COALESCE(b.dwelling_units_total, 0.0) AS dwelling_units_total,
    COALESCE(es.dwelling_units_sf_ll, 0.0) - COALESCE(b.dwelling_units_sf_ll, 0.0) AS dwelling_units_sf_ll,
    COALESCE(es.dwelling_units_sf_sl, 0.0) - COALESCE(b.dwelling_units_sf_sl, 0.0) AS dwelling_units_sf_sl,
    COALESCE(es.dwelling_units_attached_sf, 0.0) - COALESCE(b.dwelling_units_attached_sf, 0.0) AS dwelling_units_attached_sf,
    COALESCE(es.dwelling_units_mf_2_4, 0.0) - COALESCE(b.dwelling_units_mf_2_4, 0.0) AS dwelling_units_mf_2_4,
    COALESCE(es.dwelling_units_mf_5p, 0.0) - COALESCE(b.dwelling_units_mf_5p, 0.0) AS dwelling_units_mf_5p,

    -- Population and households
    COALESCE(es.population, 0.0) - COALESCE(b.population, 0.0) AS population,
    COALESCE(es.households, 0.0) - COALESCE(b.households, 0.0) AS households,

    -- Employment
    COALESCE(es.employment_total, 0.0) - COALESCE(b.employment_total, 0.0) AS employment_total,

    -- Building square footage
    COALESCE(es.building_sqft_total, 0.0) - COALESCE(b.building_sqft_total, 0.0) AS building_sqft_total,
    COALESCE(es.building_sqft_residential, 0.0) - COALESCE(b.building_sqft_residential, 0.0) AS building_sqft_residential,
    COALESCE(es.building_sqft_commercial, 0.0) - COALESCE(b.building_sqft_commercial, 0.0) AS building_sqft_commercial,
    COALESCE(es.building_sqft_office, 0.0) - COALESCE(b.building_sqft_office, 0.0) AS building_sqft_office,
    COALESCE(es.building_sqft_industrial, 0.0) - COALESCE(b.building_sqft_industrial, 0.0) AS building_sqft_industrial,
    COALESCE(es.building_sqft_public, 0.0) - COALESCE(b.building_sqft_public, 0.0) AS building_sqft_public,
    COALESCE(es.building_sqft_retail, 0.0) - COALESCE(b.building_sqft_retail, 0.0) AS building_sqft_retail,
    COALESCE(es.building_sqft_wholesale, 0.0) - COALESCE(b.building_sqft_wholesale, 0.0) AS building_sqft_wholesale,
    COALESCE(es.building_sqft_education, 0.0) - COALESCE(b.building_sqft_education, 0.0) AS building_sqft_education,
    COALESCE(es.building_sqft_healthcare, 0.0) - COALESCE(b.building_sqft_healthcare, 0.0) AS building_sqft_healthcare,
    COALESCE(es.building_sqft_hotel_lodging, 0.0) - COALESCE(b.building_sqft_hotel_lodging, 0.0) AS building_sqft_hotel_lodging,
    COALESCE(es.building_sqft_entertainment, 0.0) - COALESCE(b.building_sqft_entertainment, 0.0) AS building_sqft_entertainment,
    COALESCE(es.building_sqft_other, 0.0) - COALESCE(b.building_sqft_other, 0.0) AS building_sqft_other,

    -- Irrigation
    COALESCE(es.res_irrigated_sqft, 0.0) - COALESCE(b.res_irrigated_sqft, 0.0) AS res_irrigated_sqft,
    COALESCE(es.com_irrigated_sqft, 0.0) - COALESCE(b.com_irrigated_sqft, 0.0) AS com_irrigated_sqft,

    -- Parcel acres
    COALESCE(es.parcel_acres_developed, 0.0) - COALESCE(b.parcel_acres_developed, 0.0) AS parcel_acres_developed,
    COALESCE(es.parcel_acres_agriculture, 0.0) - COALESCE(b.parcel_acres_agriculture, 0.0) AS parcel_acres_agriculture,
    COALESCE(es.parcel_acres_open_space, 0.0) - COALESCE(b.parcel_acres_open_space, 0.0) AS parcel_acres_open_space,
    COALESCE(es.parcel_acres_vacant, 0.0) - COALESCE(b.parcel_acres_vacant, 0.0) AS parcel_acres_vacant,

    -- Intersection density
    COALESCE(es.intersection_density, 0.0) - COALESCE(b.intersection_density, 0.0) AS intersection_density,

    -- Geometry
    COALESCE(es.geom, b.geom) AS geom
FROM end_state AS es
FULL OUTER JOIN base AS b ON es.parcel_id = b.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_core_increment_geom_@snapshot_hash
  ON @this_model USING GIST (geom);

  CREATE INDEX IF NOT EXISTS idx_core_increment_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
