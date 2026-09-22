MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  blueprints @analysis_blueprints('fiscal_net_impact'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- F4 — Net Fiscal Impact
--
-- Computes net fiscal impact per parcel by summing property tax and
-- sales tax revenue, then subtracting service costs.
--
-- Formula:
--   net_fiscal_impact = property_tax_revenue + sales_tax_revenue - service_cost_total
--
-- Dependencies: fiscal_property_tax (F1), fiscal_sales_tax (F2), fiscal_service_costs (F3)

SELECT
    f1.parcel_id,
    COALESCE(f1.property_tax_revenue, 0.0) AS property_tax_revenue,
    COALESCE(f2.sales_tax_revenue, 0.0) AS sales_tax_revenue,
    COALESCE(f3.service_cost_total, 0.0) AS service_cost_total,
    -- Net fiscal impact: revenue - costs
    COALESCE(f1.property_tax_revenue, 0.0)
    + COALESCE(f2.sales_tax_revenue, 0.0)
    - COALESCE(f3.service_cost_total, 0.0)
    AS net_fiscal_impact,
    COALESCE(f1.geometry, f2.geometry, f3.geometry) AS geometry
FROM @{scenario_schema}.fiscal_property_tax AS f1
FULL OUTER JOIN @{scenario_schema}.fiscal_sales_tax AS f2
    ON f1.parcel_id = f2.parcel_id
FULL OUTER JOIN @{scenario_schema}.fiscal_service_costs AS f3
    ON f1.parcel_id = f3.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_net_impact_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_net_impact_parcel_id_')
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
