MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level change from base canvas to scenario end state per attribute (end state minus base).',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area from the base canvas (acres).',
    acres_developable = 'Developable acres from the end state (acres); passed through.',
    acres_developed = 'Developed acres from the end state (acres); passed through.',
    land_development_category = 'Land development category from the scenario end state.',
    du = 'Change in total dwelling units from base canvas to end state (units).',
    du_detsf_ll = 'Change in detached single-family large-lot units (units).',
    du_detsf_sl = 'Change in detached single-family small-lot units (units).',
    du_attsf = 'Change in attached single-family dwelling units (units).',
    du_mf2to4 = 'Change in multi-family 2-4 unit dwelling units (units).',
    du_mf5p = 'Change in multi-family 5 or more unit dwelling units (units).',
    pop = 'Change in population from base canvas to end state (people).',
    hh = 'Change in households from base canvas to end state (households).',
    emp = 'Change in employment from base canvas to end state (jobs).',
    building_sqft_total = 'Total floor area from the end state (sq ft); passed through, not diffed.',
    building_sqft_residential = 'Residential floor area from the end state (sq ft); passed through.',
    building_sqft_commercial = 'Commercial floor area from the end state (sq ft); passed through.',
    building_sqft_industrial = 'Industrial floor area from the end state (sq ft); passed through.',
    building_sqft_other = 'Other non-residential floor area from the end state (sq ft).',
    bldg_area_office_services = 'Change in office services floor area (sq ft).',
    bldg_area_public_admin = 'Change in public administration floor area (sq ft).',
    bldg_area_retail_services = 'Change in retail services floor area (sq ft).',
    bldg_area_wholesale = 'Change in wholesale floor area (sq ft).',
    bldg_area_education = 'Change in education floor area (sq ft).',
    bldg_area_medical_services = 'Change in medical services floor area (sq ft).',
    bldg_area_accommodation = 'Change in accommodation floor area (sq ft).',
    bldg_area_arts_entertainment = 'Change in arts and entertainment floor area (sq ft).',
    residential_irrigated_area = 'Change in residential irrigated area (acres).',
    commercial_irrigated_area = 'Change in non-residential irrigated area (acres).',
    parcel_acres_developed = 'Developed parcel acres from the end state (acres); passed through.',
    parcel_acres_agriculture = 'Agricultural parcel acres from the end state (acres).',
    parcel_acres_open_space = 'Open-space parcel acres from the end state (acres); passed through.',
    parcel_acres_vacant = 'Vacant parcel acres from the end state (acres); passed through.',
    intersection_density = 'Change in intersection density (intersections per km2).',
    geometry = 'Parcel boundary geometry, from the end state or the base canvas (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('core_increment'),
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
    SELECT * FROM @{scenario_schema}.core_end_state
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


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
