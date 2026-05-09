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

WITH input_data AS (
    SELECT
        pa.parcel_id,
        pa.total_met_hours,
        pa.walk_trips,
        pa.bike_trips,
        es.population,
        es.geom,
        COALESCE(tg.co2e_total_kg, 0.0) AS co2e_transport_kg
    FROM {{ ref('physical_activity') }} AS pa
    LEFT JOIN {{ ref('transport_ghg') }} AS tg
        ON pa.parcel_id = tg.parcel_id
    LEFT JOIN {{ ref('core_end_state') }} AS es
        ON pa.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- DALYs averted from physical activity
    -- Proportional mortality reduction: (MET-hrs/wk / baseline) × max_reduction
    -- Max reduction capped at mortality_reduction_pct of background mortality
    CASE
        WHEN population > 0 AND COALESCE(total_met_hours, 0.0) > 0
            THEN (
                {{ bg_death_rate }} * population
                * LEAST(
                    (total_met_hours / 52.0) / {{ baseline_met_hours }},
                    1.0
                )
                * ({{ mortality_reduction_pct }} / 100.0)
            )
            * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
        ELSE 0.0
    END AS dalys_averted_pa,

    -- DALYs added from air quality (transport emissions)
    -- Simplified: CO₂e as proxy for combustion → PM2.5 → population exposure → mortality
    -- Uses intake fraction × concentration-response × background mortality
    CASE
        WHEN population > 0 AND COALESCE(co2e_transport_kg, 0.0) > 0
            THEN (
                {{ bg_death_rate }} * population
                * LEAST(
                    (co2e_transport_kg / 1000.0) * {{ pm25_intake_fraction }}
                    * {{ pm25_conc_response }} * 100.0,
                    1.0
                )
            )
            * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
        ELSE 0.0
    END AS dalys_added_air_quality,

    -- Net DALYs (positive = health benefit)
    CASE
        WHEN population > 0
            THEN
                -- PA benefit
                CASE
                    WHEN COALESCE(total_met_hours, 0.0) > 0
                        THEN (
                            {{ bg_death_rate }} * population
                            * LEAST(
                                (total_met_hours / 52.0) / {{ baseline_met_hours }},
                                1.0
                            )
                            * ({{ mortality_reduction_pct }} / 100.0)
                        )
                        * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
                    ELSE 0.0
                END
                -- Air quality harm (subtracted)
                - CASE
                    WHEN COALESCE(co2e_transport_kg, 0.0) > 0
                        THEN (
                            {{ bg_death_rate }} * population
                            * LEAST(
                                (co2e_transport_kg / 1000.0) * {{ pm25_intake_fraction }}
                                * {{ pm25_conc_response }} * 100.0,
                                1.0
                            )
                        )
                        * ({{ bg_dalys_per_capita }} / {{ bg_death_rate }})
                    ELSE 0.0
                END
        ELSE 0.0
    END AS net_dalys,

    -- Deaths averted from physical activity
    CASE
        WHEN population > 0 AND COALESCE(total_met_hours, 0.0) > 0
            THEN
                {{ bg_death_rate }} * population
                * LEAST(
                    (total_met_hours / 52.0) / {{ baseline_met_hours }},
                    1.0
                )
                * ({{ mortality_reduction_pct }} / 100.0)
        ELSE 0.0
    END AS deaths_averted_pa,

    -- Deaths added from air quality
    CASE
        WHEN population > 0 AND COALESCE(co2e_transport_kg, 0.0) > 0
            THEN
                {{ bg_death_rate }} * population
                * LEAST(
                    (co2e_transport_kg / 1000.0) * {{ pm25_intake_fraction }}
                    * {{ pm25_conc_response }} * 100.0,
                    1.0
                )
        ELSE 0.0
    END AS deaths_added_air_quality,

    geom
FROM input_data
