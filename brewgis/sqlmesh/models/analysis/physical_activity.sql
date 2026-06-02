MODEL (
  name brewgis.analysis.physical_activity,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- H1 — Physical Activity (MET-hours)
--
-- Computes metabolic equivalent (MET) hours from active transportation
-- (walking and cycling) using mode choice trip data and trip distribution
-- distances.
--
-- Formula:
--   MET-hours = trips x (distance_km / speed_kmh) x MET
--
-- Variables:
--   @health_walk_met: Walking MET value (default: 3.5).
--   @health_bike_met: Biking MET value (default: 6.0).
--   @health_walk_speed_kmh: Walking speed in km/h (default: 4.8).
--   @health_bike_speed_kmh: Biking speed in km/h (default: 16.0).

WITH mode_data AS (
    SELECT
        mc.parcel_id,
        mc.trips_walk AS walk_trips,
        mc.trips_bike AS bike_trips,
        mc.trips_auto AS auto_trips,
        mc.trips_transit AS transit_trips,
        td.avg_trip_length_km,
        es.population,
        es.geom
    FROM brewgis.analysis.mode_choice AS mc
    LEFT JOIN brewgis.analysis.trip_distribution AS td
        ON mc.parcel_id = td.parcel_id
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON mc.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- Walking MET-hours: walk_trips x (avg_trip_length_km / walk_speed_kmh) x MET
    COALESCE(walk_trips * (avg_trip_length_km / @health_walk_speed_kmh) * @health_walk_met, 0.0)
        AS walk_met_hours,

    -- Biking MET-hours: bike_trips x (avg_trip_length_km / bike_speed_kmh) x MET
    COALESCE(bike_trips * (avg_trip_length_km / @health_bike_speed_kmh) * @health_bike_met, 0.0)
        AS bike_met_hours,

    -- Total MET-hours
    COALESCE(walk_trips * (avg_trip_length_km / @health_walk_speed_kmh) * @health_walk_met, 0.0)
    + COALESCE(bike_trips * (avg_trip_length_km / @health_bike_speed_kmh) * @health_bike_met, 0.0)
        AS total_met_hours,

    walk_trips,
    bike_trips,

    -- Active trip share (walk + bike / total trips)
    COALESCE(
        (COALESCE(walk_trips, 0.0) + COALESCE(bike_trips, 0.0))
        / NULLIF(
            COALESCE(walk_trips, 0.0) + COALESCE(bike_trips, 0.0)
            + COALESCE(auto_trips, 0.0) + COALESCE(transit_trips, 0.0),
            0.0
        ),
        0.0
    ) AS active_trip_share,

    geom
FROM mode_data
