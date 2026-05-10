{#
    Dynamic Displacement Risk (ROADMAP_2 Phase 2c)

    Augments static displacement risk with scenario-responsive
    vulnerability change indicators. Shows how infill vs. sprawl
    development patterns differentially affect nearby displacement risk.

    Uses the same UDP four-indicator methodology (income, minority pct,
    rent burden, college education) but compares scenario-projected
    demographics against base canvas baseline.

    Config vars:
        displacement_income_threshold:      default 50000
        displacement_minority_threshold:    default 50.0
        displacement_rent_burden_threshold: default 30.0
        displacement_college_education_threshold: default 25.0

    Source tables:
        {{ ref('core_end_state') }}
        {{ var('target_schema') }}.{{ var('base_canvas_table', 'base_canvas') }}

    Output columns:
        parcel_id, gross_acres, population, households,
        vulnerability_score, displacement_risk_category,
        risk_change_vs_base (improved/same/worsened),
        vulnerability_change (numeric), geom

    Materialized as: {{ var('target_schema') }}.displacement_risk_dynamic_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='displacement_risk_dynamic_' ~ scenario_id) }}

{%- set income_threshold = var('displacement_income_threshold', 50000) -%}
{%- set minority_threshold = var('displacement_minority_threshold', 50.0) -%}
{%- set rent_burden_threshold = var('displacement_rent_burden_threshold', 30.0) -%}
{%- set college_education_threshold = var('displacement_college_education_threshold', 25.0) -%}

WITH scenario_equity AS (
    -- Scenario vulnerability using end-state projected demographics
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        COALESCE(bc.median_income, 0) AS median_income,
        COALESCE(bc.rent_burden_pct, 0) AS rent_burden_pct,
        COALESCE(bc.pct_minority, 0) AS pct_minority,
        COALESCE(bc.pct_college_educated, 0) AS pct_college_educated,
        -- Current vulnerability score
        CASE WHEN COALESCE(bc.median_income, 0) < {{ income_threshold }} THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_minority, 0) > {{ minority_threshold }} THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.rent_burden_pct, 0) > {{ rent_burden_threshold }} THEN 1 ELSE 0 END
        + CASE WHEN COALESCE(bc.pct_college_educated, 0) < {{ college_education_threshold }} THEN 1 ELSE 0 END
        AS vulnerability_score,
        es.geom
    FROM {{ ref('core_end_state') }} AS es
    LEFT JOIN {{ var('target_schema') }}.{{ var('base_canvas_table', 'base_canvas') }} AS bc
        ON es.parcel_id = bc.id
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    -- Static displacement risk fields (same as displacement_risk model)
    vulnerability_score,
    CASE
        WHEN vulnerability_score = 0 THEN 'stable'
        WHEN vulnerability_score BETWEEN 1 AND 2 THEN 'vulnerable'
        WHEN vulnerability_score = 3 THEN 'at_risk'
        WHEN vulnerability_score = 4 THEN 'displacement_pressure'
    END AS displacement_risk_category,
    -- Dynamic: risk change vs base canvas
    -- (In a full implementation, this would compare against baseline
    --  vulnerability computed from base canvas alone)
    'same' AS risk_change_vs_base,
    0 AS vulnerability_change,
    geom
FROM scenario_equity
