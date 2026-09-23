MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Daily vehicle miles travelled per parcel from mode-choice auto trips and the trip-distribution average trip length.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    vmt_total = 'Vehicle miles travelled per day for the parcel: auto trips x trip length x circuity.',
    vmt_per_capita = 'Vehicle miles travelled per resident per day, zero where population is zero.',
    auto_trips = 'Trips made by automobile per day (count), from the mode-choice auto share.',
    avg_trip_length_mi = 'Average one-way trip length from trip distribution (miles).',
    geometry = 'Parcel geometry copied from the scenario end state (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('vmt'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,)),
    assert_column_non_negative(column_name := vmt_total),
    assert_column_non_negative(column_name := auto_trips)
  )
);

-- VMT Model — T4 Module
--
-- Computes vehicle miles traveled (VMT) per parcel from the mode-choice auto
-- trips (T3) and the trip-distribution average trip length (T2):
--
--   VMT = auto trips x avg trip length (mi) x circuity factor.
--
-- Trip distribution measures distance in projected units (km), so the trip
-- length is converted with the km -> mi constant before it enters the VMT
-- formula.
--
-- Variables:
--   @blueprint_var('transport_circuity_factor'): Road network directness adjustment (default: 1.2).
--
-- Dependencies: mode_choice, trip_distribution, core_end_state

WITH mode_trips AS (
    SELECT
        mc.parcel_id,
        mc.trips_auto AS auto_trips,
        td.avg_trip_length_km,
        es.pop,
        es.geometry,
        mc.trips_auto * td.avg_trip_length_km * 0.621371
            * @blueprint_var('transport_circuity_factor') AS vmt_total
    FROM @{scenario_schema}.mode_choice AS mc
    LEFT JOIN @{scenario_schema}.trip_distribution AS td
        ON mc.parcel_id = td.parcel_id
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON mc.parcel_id = es.parcel_id
)

SELECT
    parcel_id,
    vmt_total,
    -- VMT per capita
    CASE WHEN pop > 0
        THEN vmt_total / pop
        ELSE 0.0
    END AS vmt_per_capita,
    auto_trips,
    avg_trip_length_km * 0.621371 AS avg_trip_length_mi,
    geometry
FROM mode_trips;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_vmt_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_vmt_parcel_id_')
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
