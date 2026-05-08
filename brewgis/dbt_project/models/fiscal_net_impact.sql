{#
    F4 — Net Fiscal Impact

    Computes net fiscal impact per parcel by summing property tax and
    sales tax revenue, then subtracting service costs.

    Uses dbt ref() to express dependencies on F1–F3 so dbt resolves
    the correct execution order automatically.

    Formula:
        net_fiscal_impact = property_tax_revenue + sales_tax_revenue - service_cost_total

    Source models (dbt ref):
        fiscal_property_tax (F1), fiscal_sales_tax (F2), fiscal_service_costs (F3)

    Output columns:
        parcel_id, property_tax_revenue, sales_tax_revenue,
        service_cost_total, net_fiscal_impact, geom

    Materialized as: {{ var('target_schema') }}.fiscal_net_impact_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='fiscal_net_impact_' ~ scenario_id) }}

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
FROM {{ ref('fiscal_property_tax') }} AS f1
FULL OUTER JOIN {{ ref('fiscal_sales_tax') }} AS f2
    ON f1.parcel_id = f2.parcel_id
FULL OUTER JOIN {{ ref('fiscal_service_costs') }} AS f3
    ON f1.parcel_id = f3.parcel_id
