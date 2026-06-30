MODEL (
  name brewgis.analysis.health_impacts,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- H2 — Health Impacts (DALYs / Health Outcomes)
--
-- Computes health impacts from physical activity (MET-hours) and air
-- quality changes (transport emissions). Uses simplified dose-response
-- functions appropriate for sketch-level planning.
--
-- Physical Activity Benefit:
--   Proportional reduction in all-cause mortality based on MET-hours
--   per week above baseline. Uses WHO HEAT-based dose-response.
--
-- Air Quality Impact:
--   Simplified PM2.5 exposure model from vehicle emissions using
--   intake fraction and concentration-response function.
--
-- Variables:
--   @health_heat_mortality_reduction_pct (default: 8.0)
--   @health_heat_baseline_met_hours_per_week (default: 11.25)
--   @health_pm25_intake_fraction (default: 1.6e-6)
--   @health_pm25_concentration_response (default: 0.0062)
--   @health_background_dalys_per_capita (default: 0.013)
--   @health_background_death_rate (default: 0.008)
--   @health_weeks_per_year (default: 52.0)

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
            THEN @health_background_death_rate * es.population
                * LEAST((pa.total_met_hours / @health_weeks_per_year) / @health_heat_baseline_met_hours_per_week, 1.0)
                * (@health_heat_mortality_reduction_pct / 100.0)
            ELSE 0.0
        END AS pa_death_reduction,
        -- AQ harm base: deaths added from air quality (transport emissions)
        CASE
            WHEN es.population > 0 AND COALESCE(tg.co2e_total_kg, 0.0) > 0
            THEN @health_background_death_rate * es.population
                * LEAST(
                    (COALESCE(tg.co2e_total_kg, 0.0) / 1000.0) * @health_pm25_intake_fraction
                    * @health_pm25_concentration_response * 100.0,
                    1.0
                )
            ELSE 0.0
        END AS aq_death_addition
    FROM brewgis.analysis.physical_activity AS pa
    LEFT JOIN brewgis.analysis.transport_ghg AS tg
        ON pa.parcel_id = tg.parcel_id
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON pa.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- DALYs averted from physical activity
    pa_death_reduction * (@health_background_dalys_per_capita / @health_background_death_rate)
        AS dalys_averted_pa,

    -- DALYs added from air quality (transport emissions)
    aq_death_addition * (@health_background_dalys_per_capita / @health_background_death_rate)
        AS dalys_added_air_quality,

    -- Net DALYs (positive = health benefit)
    CASE
        WHEN population > 0
        THEN (pa_death_reduction - aq_death_addition) * (@health_background_dalys_per_capita / @health_background_death_rate)
        ELSE 0.0
    END AS net_dalys,

    -- Deaths averted from physical activity
    pa_death_reduction AS deaths_averted_pa,

    -- Deaths added from air quality
    aq_death_addition AS deaths_added_air_quality,

    geom
FROM input_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_health_impacts_geom_@snapshot_hash
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_health_impacts_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
