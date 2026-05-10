{#
    Cost of Sprawl per Household (ROADMAP_2 Phase 2e)

    Divides scenario infrastructure costs (service costs + capital costs)
    by number of added households to compute cost per household.
    Directly answers whether 45,000 homes pay for their own infrastructure.

    Config vars:
        sprawl_infrastructure_cost_per_du: Annual infrastructure cost per DU (default: 15000)
        sprawl_capital_cost_per_du: One-time capital cost per DU (default: 50000)

    Source tables:
        {{ ref('core_end_state') }}
        {{ ref('fiscal_net_impact') }}  -- for fiscal_service_costs

    Output columns:
        parcel_id, gross_acres, population, households, dwelling_units_total,
        infrastructure_cost_per_du_annual, capital_cost_per_du,
        infrastructure_cost_total_annual, infrastructure_cost_per_hh_annual, geom

    Materialized as: {{ var('target_schema') }}.sprawl_cost_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='sprawl_cost_' ~ scenario_id) }}

{%- set infra_cost_per_du = var('sprawl_infrastructure_cost_per_du', 15000) -%}
{%- set capital_cost_per_du = var('sprawl_capital_cost_per_du', 50000) -%}

WITH parcel_data AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        es.dwelling_units_total,
        es.geom,
        es.land_dev_category,
        -- Infrastructure cost: annual service cost + amortized capital cost
        ROUND((es.dwelling_units_total * {{ infra_cost_per_du }})::numeric, 2) AS infrastructure_cost_annual,
        ROUND((es.dwelling_units_total * {{ capital_cost_per_du }})::numeric, 2) AS capital_cost
    FROM {{ ref('core_end_state') }} AS es
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    dwelling_units_total,
    {{ infra_cost_per_du }} AS infrastructure_cost_per_du_annual,
    {{ capital_cost_per_du }} AS capital_cost_per_du,
    infrastructure_cost_annual,
    capital_cost,
    -- Infrastructure cost per household (annual)
    ROUND(
        (infrastructure_cost_annual + capital_cost / 30.0)  -- 30-year amortization
        / NULLIF(households, 0)::numeric, 2
    ) AS infrastructure_cost_per_hh_annual,
    geom
FROM parcel_data
