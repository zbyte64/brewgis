{#
    F1 — Property Tax Revenue

    Computes property tax revenue from assessed value of residential and
    non-residential development.

    Formula:
        assessed_value_res = dwelling_units_total × res_assessed_value_per_du
        assessed_value_nonres = building_sqft_total × nonres_assessed_value_per_sqft
        property_tax_revenue = (assessed_value_res + assessed_value_nonres)
                               × property_tax_rate / 100

    Config vars:
        res_assessed_value_per_du: Assessed value per dwelling unit (default: 350000).
        nonres_assessed_value_per_sqft: Assessed value per sqft non-res (default: 150).
        property_tax_rate: Property tax rate in percent (default: 1.0).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, assessed_value_res, assessed_value_nonres,
        property_tax_revenue, geom

    Materialized as: {{ var('target_schema') }}.fiscal_property_tax_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='fiscal_property_tax_' ~ scenario_id) }}

{%- set res_assessed_value = var('res_assessed_value_per_du', 350000) -%}
{%- set nonres_assessed_value = var('nonres_assessed_value_per_sqft', 150) -%}
{%- set tax_rate = var('property_tax_rate', 1.0) -%}

SELECT
    es.parcel_id,
    -- Residential assessed value
    COALESCE(es.dwelling_units_total * {{ res_assessed_value }}, 0.0) AS assessed_value_res,
    -- Non-residential assessed value
    COALESCE(es.building_sqft_total * {{ nonres_assessed_value }}, 0.0) AS assessed_value_nonres,
    -- Property tax revenue
    COALESCE(
        (es.dwelling_units_total * {{ res_assessed_value }}
         + es.building_sqft_total * {{ nonres_assessed_value }})
        * {{ tax_rate }} / 100.0,
        0.0
    ) AS property_tax_revenue,
    es.geom
FROM {{ ref('core_end_state') }} AS es
