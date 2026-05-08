{#
    F3 — Service Costs

    Computes public service costs from dwelling units, population, and
    employment. Covers schools, public safety, roads/transit.

    Formula:
        service_cost_schools = dwelling_units_total × cost_per_du
        service_cost_public_safety = population × cost_per_capita
        service_cost_roads = employment_total × cost_per_employee
        service_cost_total = sum of all three

    Config vars:
        cost_per_du: Annual cost per dwelling unit (default: 5000) — schools, infrastructure.
        cost_per_capita: Annual cost per capita (default: 2000) — police, fire, libraries.
        cost_per_employee: Annual cost per employee (default: 1500) — roads, transit.

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, service_cost_schools, service_cost_public_safety,
        service_cost_roads, service_cost_total, geom

    Materialized as: {{ var('target_schema') }}.fiscal_service_costs_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='fiscal_service_costs_' ~ scenario_id) }}

{%- set cost_per_du = var('cost_per_du', 5000) -%}
{%- set cost_per_capita = var('cost_per_capita', 2000) -%}
{%- set cost_per_employee = var('cost_per_employee', 1500) -%}

SELECT
    es.parcel_id,
    -- Schools and infrastructure
    COALESCE(es.dwelling_units_total * {{ cost_per_du }}, 0.0) AS service_cost_schools,
    -- Police, fire, libraries
    COALESCE(es.population * {{ cost_per_capita }}, 0.0) AS service_cost_public_safety,
    -- Roads and transit
    COALESCE(es.employment_total * {{ cost_per_employee }}, 0.0) AS service_cost_roads,
    -- Total service cost
    COALESCE(es.dwelling_units_total * {{ cost_per_du }}, 0.0)
    + COALESCE(es.population * {{ cost_per_capita }}, 0.0)
    + COALESCE(es.employment_total * {{ cost_per_employee }}, 0.0)
    AS service_cost_total,
    es.geom
FROM {{ var('target_schema') }}.end_state_{{ var('scenario_id') }} AS es
