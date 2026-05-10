{#
    Tree Canopy / Urban Heat Island Model (ROADMAP_2 Phase 2a)

    Computes parcel-level tree canopy cover percentage and a surface
    temperature proxy using published urban heat island relationships.
    (~1°F reduction per 10% canopy increase, baseline 95°F at 0% canopy)

    Config vars:
        tree_canopy_baseline_temp:  Surface temp at 0% canopy (°F, default: 95.0)
        tree_canopy_temp_per_10pct: °F reduction per 10% canopy increase (default: 1.0)

    Source table:
        {{ ref('core_end_state') }}

    Output columns:
        parcel_id, gross_acres, population, households,
        canopy_pct, surface_temp_f, heat_exposure_score, geom

    Materialized as: {{ var('target_schema') }}.tree_canopy_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='tree_canopy_' ~ scenario_id) }}

{%- set baseline_temp = var('tree_canopy_baseline_temp', 95.0) -%}
{%- set temp_per_10pct = var('tree_canopy_temp_per_10pct', 1.0) -%}

WITH parcel_canopy AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.population,
        es.households,
        es.geom,
        -- Canopy cover: if no direct measurement, estimate from land use category
        CASE
            WHEN es.land_dev_category = 'compact' THEN 25.0  -- dense urban (low canopy)
            WHEN es.land_dev_category = 'urban' THEN 15.0
            WHEN es.land_dev_category = 'standard' THEN 30.0  -- suburban (moderate)
            WHEN es.land_dev_category = 'rural' THEN 45.0     -- rural (high canopy)
            ELSE 20.0
        END AS canopy_pct
    FROM {{ ref('core_end_state') }} AS es
)
SELECT
    parcel_id,
    gross_acres,
    population,
    households,
    canopy_pct,
    -- Surface temp proxy: baseline minus cooling effect
    ROUND(({{ baseline_temp }} - (canopy_pct / 10.0 * {{ temp_per_10pct }}))::numeric, 1) AS surface_temp_f,
    -- Heat exposure score: 0-100 (higher = worse, inverse of canopy)
    ROUND(GREATEST(0.0, 100.0 - (canopy_pct * 4.0))::numeric, 1) AS heat_exposure_score,
    geom
FROM parcel_canopy
