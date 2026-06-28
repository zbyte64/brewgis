MODEL (
  name brewgis.analysis.vmt,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- VMT Model — T4 Module
--
-- Computes vehicle miles traveled (VMT) from mode choice and trip distribution.
-- VMT = auto trips x avg trip length (km) x 0.621371 (km->mi) x circuity factor.
--
-- Variables:
--   @transport_circuity_factor: Road network directness adjustment (default: 1.2).
--   @transport_km_to_mi: Kilometer to mile conversion factor (default: 0.621371).

WITH mode_trips AS (
    SELECT
        mc.parcel_id,
        mc.trips_auto AS auto_trips,
        td.avg_trip_length_km,
        es.population,
        es.geom,
        mc.trips_auto * td.avg_trip_length_km * @transport_km_to_mi * @transport_circuity_factor
            AS vmt_total
    FROM brewgis.analysis.mode_choice AS mc
    LEFT JOIN brewgis.analysis.trip_distribution AS td
        ON mc.parcel_id = td.parcel_id
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON mc.parcel_id = es.parcel_id
)

SELECT
    parcel_id,
    vmt_total,
    -- VMT per capita
    CASE WHEN population > 0
        THEN vmt_total / population
        ELSE 0.0
    END AS vmt_per_capita,
    auto_trips,
    avg_trip_length_km * @transport_km_to_mi AS avg_trip_length_mi,
    geom
FROM mode_trips;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_vmt_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_vmt_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
