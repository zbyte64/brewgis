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
-- Computes vehicle miles traveled (VMT) directly from trip generation,
-- using a fixed auto mode share and average trip length (sketch-level
-- planning approximation — no mode choice / trip distribution sub-models).
--
-- VMT = total trips x auto mode share x avg trip length (mi) x circuity factor.
--
-- Variables:
--   @transport_mode_share_auto: Fraction of trips made by auto (default: 0.85).
--   @transport_avg_trip_length_mi: Average one-way trip length in miles (default: 5.0).
--   @transport_circuity_factor: Road network directness adjustment (default: 1.2).

WITH auto_trips AS (
    SELECT
        tg.parcel_id,
        tg.trips_total * @transport_mode_share_auto AS auto_trips,
        es.pop,
        es.geometry,
        tg.trips_total * @transport_mode_share_auto
            * @transport_avg_trip_length_mi * @transport_circuity_factor
            AS vmt_total
    FROM brewgis.analysis.trip_generation AS tg
    LEFT JOIN brewgis.analysis.core_end_state AS es
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
    @transport_avg_trip_length_mi AS avg_trip_length_mi,
    geometry
FROM auto_trips;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_vmt_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_vmt_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
