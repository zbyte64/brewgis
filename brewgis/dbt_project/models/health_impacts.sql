{#
    H2 — Health Impacts (DALYs / Health Outcomes)

    Computes health impacts from physical activity (MET-hours) and air
    quality changes (transport emissions). Uses simplified dose-response
    functions appropriate for sketch-level planning — NOT a substitute
    for full health impact assessment (e.g., BenMAP, IHME methods).

    Physical Activity Benefit:
        Proportional reduction in all-cause mortality based on MET-hours
        per week above baseline. Uses WHO HEAT-based dose-response.

    Air Quality Impact:
        Simplified PM2.5 exposure model from vehicle emissions using
        intake fraction and concentration-response function.

    Config vars:
        health_heat_mortality_reduction_pct (default 8.0)
        health_heat_baseline_met_hours_per_week (default 11.25)
        health_pm25_intake_fraction (default 1.6e-6)
        health_pm25_concentration_response (default 0.0062)
        health_background_dalys_per_capita (default 0.013)
        health_background_death_rate (default 0.008)

    Output columns:
        parcel_id, dalys_averted_pa, dalys_added_air_quality, net_dalys,
        deaths_averted_pa, deaths_added_air_quality, geom

    Materialized as: {{ var('target_schema') }}.health_impacts_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='health_impacts_' ~ scenario_id) }}

{%- set mortality_reduction_pct = var('health_heat_mortality_reduction_pct', 8.0) -%}
{%- set baseline_met_hours = var('health_heat_baseline_met_hours_per_week', 11.25) -%}
{%- set pm25_intake_fraction = var('health_pm25_intake_fraction', 1.6e-6) -%}
{%- set pm25_conc_response = var('health_pm25_concentration_response', 0.0062) -%}
{%- set bg_dalys_per_capita = var('health_background_dalys_per_capita', 0.013) -%}
{%- set bg_death_rate = var('health_background_death_rate', 0.008) -%}
{%- set weeks_per_year = var('health_weeks_per_year', 52.0) -%}

WITH input_data AS (
    SELECT
        pa.parcel_id,
        pa.total_met_hours,
        pa.walk_trips,
        pa.bike_trips,
        es.population,
        es.geom,
        COALESCE(tg.co2e_total_kg, 0.0) AS co2e_transport_kg,
        -- PA benefit base: deaths averted from physical activity
        CASE
            WHEN es.population > 0 AND COALESCE(pa.total_met_hours, 0.0) > 0
            THEN {{ bg_death_rate }} * es.population
                * LEAST((pa.total_met_hours / {{ weeks_per_year }}) / {{ baseline_met_hours }}, 1.0)
                * ({{ mortality_reduction_pct }} / 100.0)
            ELSE 0.0
        END AS pa_death_reduction,
        -- AQ harm base: deaths added from air quality (transport emissions)
        CASE
            WHEN es.population > 0 AND COALESCE(tg.co2e_total_kg, 0.0) > 0
            THEN {{ bg_death_rate }} * es.population
                * LEAST(
                    (COALESCE(tg.co2e_total_kg, 0.0) / 1000.0) * {{ pm25_intake_fraction }}
                    * {{ pm25_conc_response }} * 100.0,
                    1.0
                )
            ELSE 0.0
        END AS aq_death_addition
    FROM {{ ref('physical_activity') }} AS pa
    LEFT JOIN {{ ref('transport_ghg') }} AS tg
        ON pa.parcel_id = tg.parcel_id
    LEFT JOIN {{ ref('core_end_state') }} AS es
        ON pa.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- DALYs averted from physical activity
    pa_death_reduction * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
        AS dalys_averted_pa,

    -- DALYs added from air quality (transport emissions)
    aq_death_addition * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
        AS dalys_added_air_quality,

    -- Net DALYs (positive = health benefit)
    CASE
        WHEN population > 0
        THEN (pa_death_reduction - aq_death_addition) * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
        ELSE 0.0
    END AS net_dalys,

    -- Deaths averted from physical activity
    pa_death_reduction AS deaths_averted_pa,

    -- Deaths added from air quality
    aq_death_addition AS deaths_added_air_quality,

    geom
FROM input_data
