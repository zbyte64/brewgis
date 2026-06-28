MODEL (
  name brewgis.analysis.fiscal_net_impact,
  kind FULL,
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
    COALESCE(f1.geom, f2.geom, f3.geom) AS geom
FROM brewgis.analysis.fiscal_property_tax AS f1
FULL OUTER JOIN brewgis.analysis.fiscal_sales_tax AS f2
    ON f1.parcel_id = f2.parcel_id
FULL OUTER JOIN brewgis.analysis.fiscal_service_costs AS f3
    ON f1.parcel_id = f3.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fiscal_net_impact_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_fiscal_net_impact_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
