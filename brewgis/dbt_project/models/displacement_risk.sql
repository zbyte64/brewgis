{#
    Displacement Risk / Gentrification Typology

    Computes per-parcel displacement risk using the Urban Displacement
    Project (UDP) methodology adapted for scenario analysis. Uses four
    equity indicators from the base canvas to assign a risk category:
    Equity data (median_income, rent_burden_pct, pct_minority, pct_college_educated)
    is provided by the ACS Equity Data Wrapper preprocessor (Phase 1c).

        1. Median income below threshold         → +1 vulnerability point
        2. Percent minority above threshold      → +1 vulnerability point
        3. Rent burden percent above threshold   → +1 vulnerability point
        4. Percent college-educated below threshold → +1 vulnerability point

    Risk categories (by vulnerability score):
        0  → stable
        1–2 → vulnerable
        3   → at_risk
        4   → displacement_pressure

    Config vars:
        displacement_income_threshold:      Median income below this = vulnerable (default: 50000).
        displacement_minority_threshold:    Pct minority above this = vulnerable (default: 50.0).
        displacement_rent_burden_threshold: Rent burden pct above this = vulnerable (default: 30.0).
        displacement_college_education_threshold: Pct college-educated below this = vulnerable (default: 25.0).

    Source tables:
        {{ ref('core_end_state') }}
        {{ var('target_schema') }}.{{ var('base_canvas_table', 'base_canvas') }}

    Output columns:
        parcel_id, gross_acres, population, households,
        median_income, rent_burden_pct, pct_minority, pct_college_educated,
        vulnerability_score, displacement_risk_category, geom

    Materialized as: {{ var('target_schema') }}.displacement_risk_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='displacement_risk_' ~ scenario_id) }}

{%- set income_threshold = var('displacement_income_threshold', 50000) -%}
{%- set minority_threshold = var('displacement_minority_threshold', 50.0) -%}
{%- set rent_burden_threshold = var('displacement_rent_burden_threshold', 30.0) -%}
{%- set college_education_threshold = var('displacement_college_education_threshold', 25.0) -%}

WITH parcel_equity AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        bc.median_income,
        bc.rent_burden_pct,
        bc.pct_minority,
        bc.pct_college_educated,
        es.geom,
        -- Vulnerability indicators (each TRUE adds 1 point)
        CASE WHEN COALESCE(bc.median_income, 0) < {{ income_threshold }} THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_minority, 0) > {{ minority_threshold }} THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.rent_burden_pct, 0) > {{ rent_burden_threshold }} THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_college_educated, 0) < {{ college_education_threshold }} THEN 1 ELSE 0 END
        AS vulnerability_score
    FROM {{ ref('core_end_state') }} AS es
    LEFT JOIN {{ var('target_schema') }}.{{ var('base_canvas_table', 'base_canvas') }} AS bc
        ON es.parcel_id = bc.id
)

SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    median_income,
    rent_burden_pct,
    pct_minority,
    pct_college_educated,
    vulnerability_score,
    -- Displacement risk category
    CASE
        WHEN vulnerability_score = 0 THEN 'stable'
        WHEN vulnerability_score BETWEEN 1 AND 2 THEN 'vulnerable'
        WHEN vulnerability_score = 3 THEN 'at_risk'
        WHEN vulnerability_score = 4 THEN 'displacement_pressure'
    END AS displacement_risk_category,
    geom
FROM parcel_equity
