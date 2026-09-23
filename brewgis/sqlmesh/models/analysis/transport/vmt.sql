MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Daily vehicle miles travelled per parcel from trip generation, auto mode share and trip length.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    vmt_total = 'Vehicle miles travelled per day for the parcel: trips x auto share x trip length x circuity.',
    vmt_per_capita = 'Vehicle miles travelled per resident per day, zero where population is zero.',
    auto_trips = 'Trips made by automobile per day (count): total trips x the auto mode share.',
    avg_trip_length_mi = 'Average one-way trip length assumed by the model (miles).',
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
-- Computes vehicle miles traveled (VMT) directly from trip generation,
-- using a fixed auto mode share and average trip length (sketch-level
-- planning approximation — no mode choice / trip distribution sub-models).
--
-- VMT = total trips x auto mode share x avg trip length (mi) x circuity factor.
--
-- Variables:
--   @blueprint_var('transport_mode_share_auto'): Fraction of trips made by auto (default: 0.85).
--   @blueprint_var('transport_avg_trip_length_mi'): Average one-way trip length in miles (default: 5.0).
--   @blueprint_var('transport_circuity_factor'): Road network directness adjustment (default: 1.2).

WITH auto_trips AS (
    SELECT
        tg.parcel_id,
        tg.trips_total * @blueprint_var('transport_mode_share_auto') AS auto_trips,
        es.pop,
        es.geometry,
        tg.trips_total * @blueprint_var('transport_mode_share_auto')
            * @blueprint_var('transport_avg_trip_length_mi') * @blueprint_var('transport_circuity_factor')
            AS vmt_total
    FROM @{scenario_schema}.trip_generation AS tg
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON tg.parcel_id = es.parcel_id
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
    @blueprint_var('transport_avg_trip_length_mi') AS avg_trip_length_mi,
    geometry
FROM auto_trips;

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
