MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Daily vehicle miles travelled per parcel from mode-choice auto trips and the parcel trip length, with the truck-adjusted and annual figures UrbanFootprint reports.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    vmt_total = 'Vehicle miles travelled per day for the parcel: auto trips x one-way trip length.',
    vmt_per_capita = 'Daily vehicle miles travelled per resident, zero where population is zero.',
    auto_trips = 'Trips made by automobile per day (count), from the mode-choice auto share.',
    avg_trip_length_mi = 'Average one-way trip length used by this model (miles).',
    geometry = 'Parcel geometry copied from the scenario end state (EPSG:4326).',
    vmt_daily_w_trucks = 'Daily vehicle miles travelled including the truck adjustment (miles per day).',
    vmt_per_hh = 'Daily vehicle miles travelled per household, zero where households are zero.',
    vmt_annual = 'Vehicle miles travelled per year at UrbanFootprint''s 347-day travel year (miles).',
    vmt_annual_w_trucks = 'Annual vehicle miles travelled including the truck adjustment (miles).',
    vmt_annual_per_capita = 'Annual vehicle miles travelled per resident, zero where population is zero.',
    vmt_annual_per_hh = 'Annual vehicle miles travelled per household, zero where households are zero.'
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
-- trips (T3) and the parcel's one-way trip length (trip_lengths):
--
--   VMT = auto trips x avg trip length (mi).
--
-- The trip length comes from the scenario's ``trip_lengths`` model, never from
-- the gravity model directly: a gravity-only trip length is an artifact of
-- parcel size and understates VMT several-fold (see that model). There is no
-- circuity factor on top — a reference length is already a network distance,
-- and the gravity fallback is scaled to a network-equivalent regional mean.
--
-- Trip lengths are measured in kilometres, so they are converted with the
-- km -> mi constant before they enter the VMT formula. ``vmt_daily_w_trucks``
-- applies UrbanFootprint's ``truck_adjustment_factor`` to the daily figure, and
-- the annual columns scale it by UrbanFootprint's 347-day travel year
-- (``vmt.csv``'s ``vmt_annual``).
--
-- Variables:
--   @blueprint_var('transport_truck_factor'): Truck adjustment applied to the daily VMT (default: 0.031).
--
-- Dependencies: mode_choice, trip_lengths, core_end_state

WITH mode_trips AS (
    SELECT
        mc.parcel_id,
        mc.trips_auto AS auto_trips,
        tl.avg_trip_length_km,
        es.pop,
        es.hh,
        es.geometry,
        mc.trips_auto * tl.avg_trip_length_km * 0.621371 AS vmt_total
    FROM @{scenario_schema}.mode_choice AS mc
    LEFT JOIN @{scenario_schema}.trip_lengths AS tl
        ON mc.parcel_id = tl.parcel_id
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
    geometry,
    -- Truck adjustment: UrbanFootprint adds the truck share on top of the
    -- passenger-car VMT rather than splitting the fleet out.
    vmt_total * (1.0 + @blueprint_var('transport_truck_factor')) AS vmt_daily_w_trucks,
    CASE WHEN hh > 0
        THEN vmt_total / hh
        ELSE 0.0
    END AS vmt_per_hh,
    vmt_total * 347.0 AS vmt_annual,
    vmt_total * (1.0 + @blueprint_var('transport_truck_factor')) * 347.0 AS vmt_annual_w_trucks,
    CASE WHEN pop > 0
        THEN vmt_total * 347.0 / pop
        ELSE 0.0
    END AS vmt_annual_per_capita,
    CASE WHEN hh > 0
        THEN vmt_total * 347.0 / hh
        ELSE 0.0
    END AS vmt_annual_per_hh
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
