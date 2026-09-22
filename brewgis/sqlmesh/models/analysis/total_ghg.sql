MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel greenhouse gas summary combining transport with building and water emissions.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) from either emissions model.',
    co2e_transport = 'Transport CO2e from the transport GHG model (kg per year).',
    co2e_buildings = 'Building energy CO2e from the building and water GHG model (kg per year).',
    co2e_water = 'Water and wastewater CO2e from the building and water GHG model (kg per year).',
    co2e_total = 'Transport plus building and water CO2e (kg per year).'
  ),
  blueprints @analysis_blueprints('total_ghg'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- G3 — Total GHG Summary
--
-- Aggregates transportation (G1) and building/water (G2) emissions into
-- a per-parcel summary.
--
-- Dependencies: transport_ghg (G1), building_water_ghg (G2)

SELECT
    COALESCE(t.parcel_id, b.parcel_id) AS parcel_id,
    COALESCE(t.co2e_total_kg, 0.0) AS co2e_transport,
    COALESCE(b.co2e_energy_total_kg, 0.0) AS co2e_buildings,
    COALESCE(b.co2e_water_total_kg, 0.0) AS co2e_water,
    COALESCE(t.co2e_total_kg, 0.0)
    + COALESCE(b.co2e_total_kg, 0.0) AS co2e_total
FROM @{scenario_schema}.transport_ghg AS t
FULL OUTER JOIN @{scenario_schema}.building_water_ghg AS b
    ON t.parcel_id = b.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_total_ghg_parcel_id_')
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
