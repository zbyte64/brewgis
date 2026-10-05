MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel physical activity from walking and cycling trips: MET-hours and the active share.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    walk_met_hours = 'Walking MET-hours from walk trips at the mean walk trip distance, its walk speed and the MET value.',
    bike_met_hours = 'Cycling MET-hours from bike trips at the mean bike trip distance, its bike speed and the MET value.',
    total_met_hours = 'Walking plus cycling metabolic equivalent hours.',
    walk_trips = 'Walking trips attributed to the parcel (trips).',
    bike_trips = 'Cycling trips attributed to the parcel (trips).',
    active_trip_share = 'Walking plus cycling trips as a share of all trips (0-1).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('physical_activity'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- H1 — Physical Activity (MET-hours)
--
-- Computes metabolic equivalent (MET) hours from active transportation
-- (walking and cycling) using mode choice trip data and each mode's own mean
-- one-way trip distance.
--
-- Formula:
--   MET-hours = trips x (mode_trip_length_km / mode_speed_kmh) x MET
--
-- Walk and bike distances are *not* the region's vehicle trip length: a walking
-- trip is an order of magnitude shorter than a car trip, so scaling walk/bike
-- trips by ``trip_lengths.avg_trip_length_km`` (SACOG: 6.4 km, the SACSIM
-- reference length) modelled the average walk trip as ~80 minutes and inflated
-- walk MET-hours ~7x. Each active mode carries its own mean instead.
--
-- Variables:
--   @blueprint_var('health_walk_met'): Walking MET value (default: 3.5).
--   @blueprint_var('health_bike_met'): Biking MET value (default: 6.0).
--   @blueprint_var('health_walk_speed_kmh'): Walking speed in km/h (default: 4.8).
--   @blueprint_var('health_bike_speed_kmh'): Biking speed in km/h (default: 16.0).
--   @blueprint_var('health_walk_trip_length_km'): Mean walk trip distance (default: 0.8).
--   @blueprint_var('health_bike_trip_length_km'): Mean bike trip distance (default: 3.2).

WITH mode_data AS (
    SELECT
        mc.parcel_id,
        mc.trips_walk AS walk_trips,
        mc.trips_bike AS bike_trips,
        mc.trips_auto AS auto_trips,
        mc.trips_transit AS transit_trips,
        es.geometry
    FROM @{scenario_schema}.mode_choice AS mc
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON mc.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- Walking MET-hours: walk_trips x (walk_trip_length_km / walk_speed_kmh) x MET
    COALESCE(walk_trips * (@blueprint_var('health_walk_trip_length_km') / @blueprint_var('health_walk_speed_kmh')) * @blueprint_var('health_walk_met'), 0.0)
        AS walk_met_hours,

    -- Biking MET-hours: bike_trips x (bike_trip_length_km / bike_speed_kmh) x MET
    COALESCE(bike_trips * (@blueprint_var('health_bike_trip_length_km') / @blueprint_var('health_bike_speed_kmh')) * @blueprint_var('health_bike_met'), 0.0)
        AS bike_met_hours,

    -- Total MET-hours
    COALESCE(walk_trips * (@blueprint_var('health_walk_trip_length_km') / @blueprint_var('health_walk_speed_kmh')) * @blueprint_var('health_walk_met'), 0.0)
    + COALESCE(bike_trips * (@blueprint_var('health_bike_trip_length_km') / @blueprint_var('health_bike_speed_kmh')) * @blueprint_var('health_bike_met'), 0.0)
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

    geometry
FROM mode_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_physical_activity_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_physical_activity_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
