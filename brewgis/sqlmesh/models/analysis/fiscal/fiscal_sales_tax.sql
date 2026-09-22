MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel sales tax revenue estimated from the retail employment share and sales per employee.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    retail_sales = 'Retail sales from the configured employment share and spending ($ per year).',
    sales_tax_revenue = 'Sales tax on the estimated retail sales ($ per year).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('fiscal_sales_tax'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- F2 — Sales Tax Revenue
--
-- Computes sales tax revenue from retail employment.
--
-- Formula:
--   retail_sales = employment_total x retail_share_pct / 100 x sales_per_employee
--   sales_tax_revenue = retail_sales x sales_tax_rate / 100
--
-- Variables:
--   @retail_employment_share: Percentage of employment that is retail (default: 15).
--   @sales_per_employee: Average sales per retail employee (default: 100000).
--   @sales_tax_rate: Sales tax rate in percent (default: 1.0).

SELECT
    es.parcel_id,
    -- Estimated retail sales
    COALESCE(
        es.emp * @retail_employment_share / 100.0 * @sales_per_employee,
        0.0
    ) AS retail_sales,
    -- Sales tax revenue
    COALESCE(
        es.emp * @retail_employment_share / 100.0 * @sales_per_employee
        * @sales_tax_rate / 100.0,
        0.0
    ) AS sales_tax_revenue,
    es.geometry
FROM @{scenario_schema}.core_end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_sales_tax_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_fiscal_sales_tax_parcel_id_')
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
