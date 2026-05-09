{#
    F2 — Sales Tax Revenue

    Computes sales tax revenue from retail employment.

    Formula:
        retail_sales = employment_total × retail_share_pct / 100 × sales_per_employee
        sales_tax_revenue = retail_sales × sales_tax_rate / 100

    Config vars:
        retail_share_pct: Percentage of employment that is retail (default: 15).
        sales_per_employee: Average sales per retail employee (default: 100000).
        sales_tax_rate: Sales tax rate in percent (default: 1.0).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, retail_sales, sales_tax_revenue, geom

    Materialized as: {{ var('target_schema') }}.fiscal_sales_tax_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='fiscal_sales_tax_' ~ scenario_id) }}

{%- set retail_share = var('retail_employment_share', 15) -%}
{%- set sales_per_emp = var('sales_per_employee', 100000) -%}
{%- set sales_tax = var('sales_tax_rate', 1.0) -%}

SELECT
    es.parcel_id,
    -- Estimated retail sales
    COALESCE(
        es.employment_total * {{ retail_share }} / 100.0 * {{ sales_per_emp }},
        0.0
    ) AS retail_sales,
    -- Sales tax revenue
    COALESCE(
        es.employment_total * {{ retail_share }} / 100.0 * {{ sales_per_emp }}
        * {{ sales_tax }} / 100.0,
        0.0
    ) AS sales_tax_revenue,
    es.geom
FROM {{ ref('core_end_state') }} AS es
