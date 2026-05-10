{#
    VMT Mitigation Fee Calculator (ROADMAP_2 Phase 2b)

    Multiplies scenario VMT by configurable fee rates ($/VMT) and tracks
    exempt VMT and forgone revenue. Implements SB 743 VMT mitigation fee
    programs (e.g. Fresno's $295/VMT fee with partial exemptions).

    Config vars:
        vmt_fee_rate_dollars_per_vmt: Fee rate per VMT (default: 295.0)
        vmt_exempt_pct: Percentage of VMT exempt from fee (default: 0.0)

    Source table: {{ ref('vmt') }}

    Output columns:
        parcel_id, gross_acres, population, households,
        vmt_total, fee_rate_dollars_per_vmt, vmt_exempt,
        fee_revenue_total, revenue_forgone, net_revenue, geom

    Materialized as: {{ var('target_schema') }}.vmt_fee_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='vmt_fee_' ~ scenario_id) }}

{%- set fee_rate = var('vmt_fee_rate_dollars_per_vmt', 295.0) -%}
{%- set exempt_pct = var('vmt_exempt_pct', 0.0) -%}

WITH vmt_data AS (
    SELECT
        v.parcel_id,
        v.gross_acres,
        v.population,
        v.households,
        v.vmt_total,
        v.vmt_per_capita,
        v.geom
    FROM {{ ref('vmt') }} AS v
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    vmt_total,
    {{ fee_rate }} AS fee_rate_dollars_per_vmt,
    ROUND((vmt_total * {{ exempt_pct }} / 100.0)::numeric, 2) AS vmt_exempt,
    -- Fee revenue on non-exempt VMT
    ROUND((vmt_total * (1.0 - {{ exempt_pct }} / 100.0) * {{ fee_rate }})::numeric, 2) AS fee_revenue_total,
    -- Forgone revenue from exempt VMT
    ROUND((vmt_total * {{ exempt_pct }} / 100.0 * {{ fee_rate }})::numeric, 2) AS revenue_forgone,
    -- Net revenue after exemption
    ROUND((vmt_total * (1.0 - {{ exempt_pct }} / 100.0) * {{ fee_rate }})::numeric, 2) AS net_revenue,
    geom
FROM vmt_data
