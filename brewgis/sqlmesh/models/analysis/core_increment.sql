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
    SELECT * FROM @ref_model(@base_canvas_table)
)

SELECT
    COALESCE(es.parcel_id, b.parcel_id) AS parcel_id,
    b.area_gross_acres,
    -- Scenario-only quantities (no existing-condition analog in base_canvas)
    -- pass through from the end-state alone rather than diffing.
    es.acres_developable,
    es.acres_developed,
    es.land_development_category,

    -- Dwelling units
    COALESCE(es.du, 0.0) - COALESCE(b.du, 0.0) AS du,
    COALESCE(es.du_detsf_ll, 0.0) - COALESCE(b.du_detsf_ll, 0.0) AS du_detsf_ll,
    COALESCE(es.du_detsf_sl, 0.0) - COALESCE(b.du_detsf_sl, 0.0) AS du_detsf_sl,
    COALESCE(es.du_attsf, 0.0) - COALESCE(b.du_attsf, 0.0) AS du_attsf,
    COALESCE(es.du_mf2to4, 0.0) - COALESCE(b.du_mf2to4, 0.0) AS du_mf2to4,
    COALESCE(es.du_mf5p, 0.0) - COALESCE(b.du_mf5p, 0.0) AS du_mf5p,

    -- Population and households
    COALESCE(es.pop, 0.0) - COALESCE(b.pop, 0.0) AS pop,
    COALESCE(es.hh, 0.0) - COALESCE(b.hh, 0.0) AS hh,

    -- Employment
    COALESCE(es.emp, 0.0) - COALESCE(b.emp, 0.0) AS emp,

    -- Building square footage: base_canvas has no floor-area equivalent for
    -- these (only building *footprint*, a different physical quantity), so
    -- pass through the end-state value rather than diffing against it.
    es.building_sqft_total,
    es.building_sqft_residential,
    es.building_sqft_commercial,
    es.building_sqft_industrial,
    es.building_sqft_other,

    -- Building square footage by use type (base_canvas bldg_area_* — same
    -- floor-area concept on both sides, so these diff cleanly)
    COALESCE(es.bldg_area_office_services, 0.0) - COALESCE(b.bldg_area_office_services, 0.0) AS bldg_area_office_services,
    COALESCE(es.bldg_area_public_admin, 0.0) - COALESCE(b.bldg_area_public_admin, 0.0) AS bldg_area_public_admin,
    COALESCE(es.bldg_area_retail_services, 0.0) - COALESCE(b.bldg_area_retail_services, 0.0) AS bldg_area_retail_services,
    COALESCE(es.bldg_area_wholesale, 0.0) - COALESCE(b.bldg_area_wholesale, 0.0) AS bldg_area_wholesale,
    COALESCE(es.bldg_area_education, 0.0) - COALESCE(b.bldg_area_education, 0.0) AS bldg_area_education,
    COALESCE(es.bldg_area_medical_services, 0.0) - COALESCE(b.bldg_area_medical_services, 0.0) AS bldg_area_medical_services,
    COALESCE(es.bldg_area_accommodation, 0.0) - COALESCE(b.bldg_area_accommodation, 0.0) AS bldg_area_accommodation,
    COALESCE(es.bldg_area_arts_entertainment, 0.0) - COALESCE(b.bldg_area_arts_entertainment, 0.0) AS bldg_area_arts_entertainment,

    -- Irrigation (acres, matching base_canvas's own units)
    COALESCE(es.residential_irrigated_area, 0.0) - COALESCE(b.residential_irrigated_area, 0.0) AS residential_irrigated_area,
    COALESCE(es.commercial_irrigated_area, 0.0) - COALESCE(b.commercial_irrigated_area, 0.0) AS commercial_irrigated_area,

    -- Parcel acres by land classification — no base_canvas analog, pass
    -- through from the end-state alone.
    es.parcel_acres_developed,
    es.parcel_acres_agriculture,
    es.parcel_acres_open_space,
    es.parcel_acres_vacant,

    -- Intersection density
    COALESCE(es.intersection_density, 0.0) - COALESCE(b.intersection_density, 0.0) AS intersection_density,

    -- Geometry
    COALESCE(es.geometry, b.geometry) AS geometry
FROM end_state AS es
FULL OUTER JOIN base AS b ON es.parcel_id = b.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_increment_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_increment_parcel_id_')
  ON @this_model USING btree (parcel_id);
