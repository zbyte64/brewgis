AUDIT (
  name assert_fiscal_identity,
  dialect postgres
);
SELECT
  parcel_id,
  property_tax_revenue,
  sales_tax_revenue,
  service_cost_total,
  net_fiscal_impact,
  (property_tax_revenue + sales_tax_revenue - service_cost_total) AS computed_net_fiscal_impact,
  ABS(net_fiscal_impact - (property_tax_revenue + sales_tax_revenue - service_cost_total)) AS deviation
FROM @this_model
WHERE ABS(net_fiscal_impact - (property_tax_revenue + sales_tax_revenue - service_cost_total)) > 0.01
