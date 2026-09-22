MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level residential and non-residential water demand in litres per year from end-state inputs.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developed = 'Developed acres from the end state (acres).',
    water_demand_res_indoor = 'Residential indoor demand (litres per year) from households and rate.',
    water_demand_res_outdoor = 'Residential outdoor demand (litres per year) from irrigated area.',
    water_demand_nonres_indoor = 'Non-residential indoor demand (litres per year) from employment.',
    water_demand_nonres_outdoor = 'Non-residential outdoor demand (litres per year) from irrigated area.',
    water_demand_total = 'Total water demand, indoor plus outdoor (litres per year).',
    water_demand_per_unit = 'Total demand per resident plus job (litres per year); zero when both are zero.',
    pop = 'Population allocated to the parcel (people).',
    emp = 'Employment allocated to the parcel (jobs).',
    du = 'Dwelling units allocated to the parcel (units).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('water_demand'),
);

SELECT
    es.parcel_id,
    es.area_gross_acres,
    es.acres_developed,

    -- Residential indoor (L/yr): households * household_size * indoor_water_rate * 365
    es.hh * es.household_size * es.indoor_water_rate * 365.0 AS water_demand_res_indoor,

    -- Residential outdoor (L/yr): irrigated acres -> m2 * outdoor_water_rate (L/m2/yr)
    es.residential_irrigated_area * 4046.8564224 * es.outdoor_water_rate AS water_demand_res_outdoor,

    -- Non-residential indoor (L/yr): employment * default_rate * 365
    es.emp * @nonres_indoor_water_rate * 365.0 AS water_demand_nonres_indoor,

    -- Non-residential outdoor (L/yr): irrigated acres -> m2 * outdoor_water_rate
    es.commercial_irrigated_area * 4046.8564224 * es.outdoor_water_rate AS water_demand_nonres_outdoor,

    -- Total water demand (L/yr)
    (es.hh * es.household_size * es.indoor_water_rate * 365.0)
      + (es.residential_irrigated_area * 4046.8564224 * es.outdoor_water_rate)
      + (es.emp * @nonres_indoor_water_rate * 365.0)
      + (es.commercial_irrigated_area * 4046.8564224 * es.outdoor_water_rate)
    AS water_demand_total,

    -- Per-unit water demand (L/person+job/yr)
    CASE WHEN (es.pop + es.emp) > 0
        THEN ((es.hh * es.household_size * es.indoor_water_rate * 365.0)
              + (es.residential_irrigated_area * 4046.8564224 * es.outdoor_water_rate)
              + (es.emp * @nonres_indoor_water_rate * 365.0)
              + (es.commercial_irrigated_area * 4046.8564224 * es.outdoor_water_rate))
             / (es.pop + es.emp)
        ELSE 0.0
    END AS water_demand_per_unit,

    es.pop,
    es.emp,
    es.du,
    es.geometry
FROM @{scenario_schema}.core_end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_water_demand_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_water_demand_parcel_id_')
  ON @this_model USING btree (parcel_id);


-- ------------------------------------------------------------
-- Energy Demand
--   Residential and non-residential energy demand (kWh/year)
--   per parcel, using end-state allocation and BuildingType
--   energy use intensities (EUI).
-- Source (dbt): brewgis/dbt_project/models/energy_demand.sql
-- ------------------------------------------------------------


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
