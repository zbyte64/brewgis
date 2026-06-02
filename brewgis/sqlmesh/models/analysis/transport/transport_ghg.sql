MODEL (
  name brewgis.analysis.transport_ghg,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- G1 — Transportation GHG
--
-- Computes greenhouse gas emissions (CO2e) from vehicle miles traveled.
-- VMT x emission factor (kg CO2e per mile), with optional speed adjustment.
--
-- Variables:
--   @transport_ghg_co2_per_mile: CO2e per mile (default: 0.411 kg/mi — EPA fleet avg).
--   @transport_ghg_speed_adjust: Enable speed-based emission adjustment (bool, default: false).

WITH vmt_data AS (
    SELECT
        v.parcel_id,
        v.vmt_total,
        v.avg_trip_length_mi,
        v.auto_trips,
        es.population,
        es.geom
    FROM brewgis.analysis.vmt AS v
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON v.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- CO2e total (kg): VMT x emission factor, with optional speed adjustment
    vmt_total * @transport_ghg_co2_per_mile
    * CASE WHEN @transport_ghg_speed_adjust THEN 1.15 ELSE 1.0 END
        AS co2e_total_kg,

    -- CO2e per capita
    CASE
        WHEN population > 0
        THEN (
            vmt_total * @transport_ghg_co2_per_mile
            * CASE WHEN @transport_ghg_speed_adjust THEN 1.15 ELSE 1.0 END
        ) / population
        ELSE 0.0
    END AS co2e_per_capita_kg,

    vmt_total,
    avg_trip_length_mi,
    auto_trips,
    geom
FROM vmt_data
