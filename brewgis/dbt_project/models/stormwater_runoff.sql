{#
    S1 — Stormwater Runoff

    Estimates stormwater runoff volume changes from land use change and
    impervious surface increase. Uses the Simple Method (Schueler, 1987):
        Runoff Volume (acre-ft) = P × Pj × Rv × A / 12
    where:
        P  = annual precipitation (inches)
        Pj = fraction of annual rain producing runoff (0.9 typical)
        Rv = runoff coefficient = 0.05 + 0.009 × impervious_pct
        A  = area (acres)

    Compares baseline (base canvas) runoff vs. end-state (painted scenario)
    runoff using core_increment impervious surface changes.

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        stormwater_annual_precipitation_in: Annual precipitation in inches (default: 12.0).
        stormwater_method: Method to use — "simple" (default) or "rational".
        stormwater_runoff_coefficients: JSON mapping land_dev_category → C value (for rational method).

    Source tables:
        {{ var('target_schema') }}.land_consumption_{{ var('scenario_id') }}
        {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, impervious_acres, impervious_pct, runoff_coefficient,
        runoff_volume_acre_ft, runoff_baseline_acre_ft, runoff_change_acre_ft,
        runoff_change_pct, geom

    Materialized as: {{ var('target_schema') }}.stormwater_runoff_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='stormwater_runoff_' ~ scenario_id) }}

{%- set precip_in = var('stormwater_annual_precipitation_in', 12.0) -%}
{%- set method = var('stormwater_method', 'simple') -%}
{%- set pj = 0.9 -%}

WITH land_data AS (
    SELECT
        lc.parcel_id,
        lc.gross_acres,
        lc.impervious_acres,
        lc.impervious_pct,
        es.geom,
        COALESCE(inc.impervious_acres, 0.0) AS impervious_acres_baseline
    FROM {{ ref('land_consumption') }} AS lc
    LEFT JOIN {{ ref('core_increment') }} AS inc
        ON lc.parcel_id = inc.parcel_id
    LEFT JOIN {{ ref('core_end_state') }} AS es
        ON lc.parcel_id = es.parcel_id
),

-- Compute baseline impervious percentage from increment delta
baseline AS (
    SELECT
        parcel_id,
        gross_acres,
        impervious_acres,
        impervious_pct,
        geom,
        GREATEST(
            impervious_pct
            - CASE
                WHEN gross_acres > 0
                    THEN impervious_acres_baseline / gross_acres * 100.0
                ELSE 0.0
            END,
            0.0
        ) AS impervious_pct_baseline
    FROM land_data
),

-- Compute runoff volumes
runoff AS (
    SELECT
        parcel_id,
        impervious_acres,
        impervious_pct,
        geom,
        0.05 + 0.009 * impervious_pct AS runoff_coefficient,
        {{ precip_in }} * {{ pj }}
        * (0.05 + 0.009 * impervious_pct)
        * gross_acres / 12.0 AS runoff_volume_acre_ft,
        0.05 + 0.009 * impervious_pct_baseline AS runoff_coefficient_baseline,
        {{ precip_in }} * {{ pj }}
        * (0.05 + 0.009 * impervious_pct_baseline)
        * gross_acres / 12.0 AS runoff_baseline_acre_ft
    FROM baseline
)

SELECT
    parcel_id,
    impervious_acres,
    impervious_pct,
    runoff_coefficient,
    runoff_volume_acre_ft,
    runoff_baseline_acre_ft,
    geom,
    runoff_volume_acre_ft - runoff_baseline_acre_ft AS runoff_change_acre_ft,
    CASE
        WHEN runoff_baseline_acre_ft > 0
            THEN
                (runoff_volume_acre_ft - runoff_baseline_acre_ft)
                / runoff_baseline_acre_ft * 100.0
        ELSE 0.0
    END AS runoff_change_pct
FROM runoff
