{#
    Housing Cost Burden Model

    Computes housing cost burden per parcel using configurable ACS-derived
    cost-burden rates applied to household counts.

    Formula:
    Equity data (median_income, rent_burden_pct, pct_minority, pct_college_educated)
    is provided by the ACS Equity Data Wrapper preprocessor (Phase 1c).
        cost_burdened_hh = households × cost_burden_rate
        severely_cost_burdened_hh = households × severe_burden_rate
        cost_burden_pct = cost_burdened_hh / NULLIF(households, 0) × 100

    Category thresholds:
        low_burden:            cost_burden_pct < 30%
        cost_burdened:         30% ≤ cost_burden_pct ≤ 50%
        severely_cost_burdened: cost_burden_pct > 50%

    Config vars:
        housing_cost_burden_rate:     Fraction of households cost-burdened (default: 0.32 — ~32% per ACS national avg).
        housing_severe_burden_rate:   Fraction of households severely cost-burdened (default: 0.14 — ~14% per ACS national avg).
        housing_median_rent:          Median rent in $/month (default: 1200 — placeholder).
        housing_median_income:        Median household income in $/year (default: 75000 — placeholder).

    Source table: {{ ref('core_end_state') }}

    Output columns:
        parcel_id, gross_acres, population, households, dwelling_units_total,
        cost_burdened_hh, severely_cost_burdened_hh,
        cost_burden_pct, cost_burden_category, geom

    Materialized as: {{ var('target_schema') }}.housing_cost_burden_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='housing_cost_burden_' ~ scenario_id) }}

{%- set cost_burden_rate = var('housing_cost_burden_rate', 0.32) -%}
{%- set severe_burden_rate = var('housing_severe_burden_rate', 0.14) -%}
{%- set median_rent = var('housing_median_rent', 1200) -%}
{%- set median_income = var('housing_median_income', 75000) -%}

SELECT
    es.parcel_id,
    es.gross_acres,
    es.population,
    es.households,
    es.dwelling_units_total,
    -- Cost-burdened households
    COALESCE(es.households * {{ cost_burden_rate }}, 0.0) AS cost_burdened_hh,
    -- Severely cost-burdened households
    COALESCE(es.households * {{ severe_burden_rate }}, 0.0) AS severely_cost_burdened_hh,
    -- Cost burden percentage
    COALESCE(
        (es.households * {{ cost_burden_rate }}) / NULLIF(es.households, 0) * 100.0,
        0.0
    ) AS cost_burden_pct,
    -- Cost burden category
    CASE
        WHEN COALESCE(es.households, 0) = 0 THEN 'low_burden'
        WHEN (es.households * {{ cost_burden_rate }}) / NULLIF(es.households, 0) * 100.0 < 30.0
            THEN 'low_burden'
        WHEN (es.households * {{ cost_burden_rate }}) / NULLIF(es.households, 0) * 100.0 <= 50.0
            THEN 'cost_burdened'
        ELSE 'severely_cost_burdened'
    END AS cost_burden_category,
    es.geom
FROM {{ ref('core_end_state') }} AS es
