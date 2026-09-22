MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel annual public service costs for schools, public safety and roads and transit.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    service_cost_schools = 'Annual schools and infrastructure cost per dwelling unit ($ per year).',
    service_cost_public_safety = 'Annual police, fire and library cost per resident ($ per year).',
    service_cost_roads = 'Annual roads and transit cost per employee ($ per year).',
    service_cost_total = 'Sum of the schools, public safety and roads costs ($ per year).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('fiscal_service_costs'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- F3 — Service Costs
--
-- Computes public service costs from dwelling units, population, and
-- employment. Covers schools, public safety, roads/transit.
--
-- Formula:
--   service_cost_schools = dwelling_units_total x cost_per_du
--   service_cost_public_safety = population x cost_per_capita
--   service_cost_roads = employment_total x cost_per_employee
--   service_cost_total = sum of all three
--
-- Variables:
--   @cost_per_du: Annual cost per dwelling unit (default: 5000).
--   @cost_per_capita: Annual cost per capita (default: 2000).
--   @cost_per_employee: Annual cost per employee (default: 1500).

SELECT
    es.parcel_id,
    -- Schools and infrastructure
    COALESCE(es.du * @cost_per_du, 0.0) AS service_cost_schools,
    -- Police, fire, libraries
    COALESCE(es.pop * @cost_per_capita, 0.0) AS service_cost_public_safety,
    -- Roads and transit
    COALESCE(es.emp * @cost_per_employee, 0.0) AS service_cost_roads,
    -- Total service cost
    COALESCE(es.du * @cost_per_du, 0.0)
    + COALESCE(es.pop * @cost_per_capita, 0.0)
    + COALESCE(es.emp * @cost_per_employee, 0.0)
    AS service_cost_total,
    es.geometry
FROM @{scenario_schema}.core_end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_service_costs_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_service_costs_parcel_id_')
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
