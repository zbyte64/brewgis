MODEL (
  name brewgis.analysis.fiscal_service_costs,
  kind FULL,
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
    COALESCE(es.dwelling_units_total * @cost_per_du, 0.0) AS service_cost_schools,
    -- Police, fire, libraries
    COALESCE(es.population * @cost_per_capita, 0.0) AS service_cost_public_safety,
    -- Roads and transit
    COALESCE(es.employment_total * @cost_per_employee, 0.0) AS service_cost_roads,
    -- Total service cost
    COALESCE(es.dwelling_units_total * @cost_per_du, 0.0)
    + COALESCE(es.population * @cost_per_capita, 0.0)
    + COALESCE(es.employment_total * @cost_per_employee, 0.0)
    AS service_cost_total,
    es.geom
FROM brewgis.analysis.core_end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fiscal_service_costs_geom_@snapshot_hash
  ON @this_model USING GIST (geom);

  CREATE INDEX IF NOT EXISTS idx_fiscal_service_costs_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
