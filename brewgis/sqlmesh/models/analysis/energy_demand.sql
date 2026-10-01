MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level residential and non-residential energy demand in kWh per year from end-state floor area.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developed = 'Developed acres from the end state (acres).',
    energy_electricity_res = 'Residential electricity demand (kWh per year) from residential floor area and EUI.',
    energy_gas_res = 'Residential gas demand (kWh per year) from residential floor area and EUI.',
    energy_electricity_nonres = 'Non-residential electricity demand (kWh per year) from commercial floor area and EUI.',
    energy_gas_nonres = 'Non-residential gas demand (kWh per year) from commercial floor area and EUI.',
    energy_total = 'Total energy demand, residential plus non-residential (kWh per year).',
    energy_intensity_kwh_per_sqft = 'Energy demand per unit floor area (kWh per sq ft per year); zero without area.',
    du = 'Dwelling units from the end state (units).',
    building_sqft_total = 'Total building floor area from the end state (sq ft).',
    pop = 'Population allocated to the parcel (people).',
    emp = 'Employment allocated to the parcel (jobs).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('energy_demand'),
);

WITH demand AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.acres_developed,
        es.du,
        es.building_sqft_total,
        es.pop,
        es.emp,
        es.geometry,

        -- Residential electric (kWh/yr): residential floor area (sq ft) -> m2 * EUI (kWh/m2/yr)
        COALESCE(es.building_sqft_residential * 0.092903 * es.electricity_eui, 0.0)
            AS energy_electricity_res,

        -- Residential gas (kWh/yr)
        COALESCE(es.building_sqft_residential * 0.092903 * es.gas_eui, 0.0)
            AS energy_gas_res,

        -- Non-residential electric (kWh/yr): commercial floor area -> m2 * EUI
        COALESCE(es.building_sqft_commercial * 0.092903 * es.electricity_eui, 0.0)
            AS energy_electricity_nonres,

        -- Non-residential gas (kWh/yr)
        COALESCE(es.building_sqft_commercial * 0.092903 * es.gas_eui, 0.0)
            AS energy_gas_nonres
    FROM @{scenario_schema}.core_end_state AS es
)

SELECT
    parcel_id,
    area_gross_acres,
    acres_developed,
    energy_electricity_res,
    energy_gas_res,
    energy_electricity_nonres,
    energy_gas_nonres,

    -- Total energy (kWh/yr): each fuel's residential plus non-residential demand.
    (energy_electricity_res + energy_gas_res + energy_electricity_nonres + energy_gas_nonres)
        AS energy_total,

    -- Energy intensity (kWh/sqft of total floor area)
    CASE WHEN building_sqft_total > 0
        THEN (energy_electricity_res + energy_gas_res + energy_electricity_nonres + energy_gas_nonres)
            / building_sqft_total
        ELSE 0.0
    END AS energy_intensity_kwh_per_sqft,

    du,
    building_sqft_total,
    pop,
    emp,
    geometry
FROM demand;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_energy_demand_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_energy_demand_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
