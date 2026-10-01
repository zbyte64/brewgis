MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level residential and non-residential water demand in litres per year from end-state inputs, with outdoor use at the parcel''s reference evapotranspiration.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developed = 'Developed acres from the end state (acres).',
    water_demand_res_indoor = 'Residential indoor demand (litres per year) from population and the built form''s indoor rate.',
    water_demand_res_outdoor = 'Residential outdoor demand (litres per year): irrigated area at the parcel''s ETo-zone reference evapotranspiration depth.',
    water_demand_nonres_indoor = 'Non-residential indoor demand (litres per year) from employment.',
    water_demand_nonres_outdoor = 'Non-residential outdoor demand (litres per year): irrigated area at the parcel''s ETo-zone reference evapotranspiration depth.',
    water_demand_total = 'Total water demand, indoor plus outdoor (litres per year).',
    water_demand_per_unit = 'Total demand per resident plus job (litres per year); zero when both are zero.',
    pop = 'Population allocated to the parcel (people).',
    emp = 'Employment allocated to the parcel (jobs).',
    du = 'Dwelling units allocated to the parcel (units).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('water_demand'),
);

-- Water Demand — per-parcel litres/year.
--
-- Indoor demand is unchanged: population and employment at the built form's
-- indoor rates. Outdoor demand is no longer a flat depth: it is the parcel's
-- irrigated area at the reference evapotranspiration of the CIMIS ETo zone its
-- centroid falls in (core_end_state.annual_eto_mm, an inches -> mm depth, so
-- numerically litres per square metre), which is the ET replacement depth the
-- irrigation has to make up. ETo replaces the previous flat built-form
-- outdoor_water_rate of 100 L/m²/yr — on the SACOG parcels that flat rate
-- implied 89 mm/yr against the ETo zones' 1449 mm/yr.
--
-- The depth is resolved once in the `end_state` CTE as
-- COALESCE(annual_eto_mm, outdoor_water_rate): a parcel in no ETo zone (outside
-- California) keeps the built-form rate it had before, and an indoor term is
-- never affected.
--
-- Source (dbt): brewgis/dbt_project/models/water_demand.sql

WITH end_state AS (
    SELECT
        parcel_id,
        area_gross_acres,
        acres_developed,
        pop,
        emp,
        du,
        geometry,
        indoor_water_rate,
        residential_irrigated_area,
        commercial_irrigated_area,
        -- Outdoor depth (L/m²/yr = mm/yr): the parcel's ETo zone where it has
        -- one, else the built form's flat outdoor rate.
        COALESCE(annual_eto_mm, outdoor_water_rate) AS outdoor_depth_mm
    FROM @{scenario_schema}.core_end_state
)

SELECT
    es.parcel_id,
    es.area_gross_acres,
    es.acres_developed,

    -- Residential indoor (L/yr): population * indoor_water_rate * 365
    es.pop * es.indoor_water_rate * 365.0 AS water_demand_res_indoor,

    -- Residential outdoor (L/yr): irrigated acres -> m2 * outdoor depth (L/m2/yr)
    es.residential_irrigated_area * 4046.8564224 * es.outdoor_depth_mm AS water_demand_res_outdoor,

    -- Non-residential indoor (L/yr): employment * default_rate * 365
    es.emp * @blueprint_var('nonres_indoor_water_rate') * 365.0 AS water_demand_nonres_indoor,

    -- Non-residential outdoor (L/yr): irrigated acres -> m2 * outdoor depth
    es.commercial_irrigated_area * 4046.8564224 * es.outdoor_depth_mm AS water_demand_nonres_outdoor,

    -- Total water demand (L/yr)
    (es.pop * es.indoor_water_rate * 365.0)
      + (es.residential_irrigated_area * 4046.8564224 * es.outdoor_depth_mm)
      + (es.emp * @blueprint_var('nonres_indoor_water_rate') * 365.0)
      + (es.commercial_irrigated_area * 4046.8564224 * es.outdoor_depth_mm)
    AS water_demand_total,

    -- Per-unit water demand (L/person+job/yr)
    CASE WHEN (es.pop + es.emp) > 0
        THEN ((es.pop * es.indoor_water_rate * 365.0)
              + (es.residential_irrigated_area * 4046.8564224 * es.outdoor_depth_mm)
              + (es.emp * @blueprint_var('nonres_indoor_water_rate') * 365.0)
              + (es.commercial_irrigated_area * 4046.8564224 * es.outdoor_depth_mm))
             / (es.pop + es.emp)
        ELSE 0.0
    END AS water_demand_per_unit,

    es.pop,
    es.emp,
    es.du,
    es.geometry
FROM end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_water_demand_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_water_demand_parcel_id_')
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
