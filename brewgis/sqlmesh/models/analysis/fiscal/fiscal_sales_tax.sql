MODEL (
  name brewgis.analysis.fiscal_sales_tax,
  kind FULL,
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
        es.employment_total * @retail_employment_share / 100.0 * @sales_per_employee,
        0.0
    ) AS retail_sales,
    -- Sales tax revenue
    COALESCE(
        es.employment_total * @retail_employment_share / 100.0 * @sales_per_employee
        * @sales_tax_rate / 100.0,
        0.0
    ) AS sales_tax_revenue,
    es.geom
FROM brewgis.analysis.core_end_state AS es;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fiscal_sales_tax_geom_@snapshot_hash
  ON @this_model USING GIST (geom);

  CREATE INDEX IF NOT EXISTS idx_fiscal_sales_tax_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
