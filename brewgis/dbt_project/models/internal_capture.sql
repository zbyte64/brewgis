-- T5 — Internal Capture
--
-- Estimates trips that start AND end within the study area (internal trips)
-- vs. trips that cross the study area boundary (external trips).
--
-- Methodology:
--   1. Classify each parcel as inside/outside the study area boundary.
--   2. For parcels inside the study area, internal trips are a function of
--      the parcel's total trip generation and the study area's "capture
--      potential" — the weighted fraction of destination parcels inside
--      the boundary, modulated by the intra-zonal friction factor.
--   3. Trips from parcels outside the study area are all external.
--   4. Intra-parcel trips (trips_internal from T2) are a subset of internal.
--
-- Variables:
--   transport_study_area_geometry: WKT polygon defining the study area boundary
--     (default: empty polygon — all parcels treated as internal).
--   transport_intrazonal_friction: Friction factor for intra-zonal trips
--     (0.0 = no friction penalty, 1.0 = maximum penalty; default 0.15).
--
-- Dependencies: trip_generation, trip_distribution
-- ============================================================================

WITH

-- 1. Study area boundary
study_area AS (
    SELECT
        CASE
            WHEN '{{ var("transport_study_area_geometry", "") }}' != ''
            THEN ST_SetSRID(
                ST_GeomFromText('{{ var("transport_study_area_geometry", "") }}'),
                4326
            )
            ELSE NULL
        END AS geom
),

-- 2. Parcel locations (from core_end_state via trip_generation)
parcel_locations AS (
    SELECT
        tg.parcel_id,
        tg.trips_total,
        tg.trips_res,
        tg.trips_nonres,
        COALESCE(td.trips_internal, 0) AS trips_intra_parcel,
        COALESCE(td.trips_outbound, 0) AS trips_outbound,
        COALESCE(td.trips_inbound, 0) AS trips_inbound,
        COALESCE(td.avg_trip_length_km, 0) AS avg_trip_length_km,
        ces.geom
    FROM {{ ref("trip_generation") }} tg
    LEFT JOIN {{ ref("trip_distribution") }} td
        ON tg.parcel_id = td.parcel_id
    LEFT JOIN {{ ref("core_end_state") }} ces
        ON tg.parcel_id = ces.parcel_id
),

-- 3. Classify parcels inside/outside study area
classified_parcels AS (
    SELECT
        pl.*,
        CASE
            WHEN sa.geom IS NULL THEN TRUE
            WHEN pl.geom IS NULL THEN FALSE
            ELSE ST_Within(ST_Centroid(pl.geom), sa.geom)
        END AS in_study_area
    FROM parcel_locations pl
    CROSS JOIN study_area sa
),

-- 4. Study area aggregate statistics
area_stats AS (
    SELECT
        COUNT(*) AS total_parcels,
        COUNT(*) FILTER (WHERE in_study_area) AS study_area_parcels,
        SUM(trips_total) FILTER (WHERE in_study_area) AS study_area_trips,
        SUM(trips_total) AS total_trips,
        CASE
            WHEN COUNT(*) > 0
            THEN COUNT(*) FILTER (WHERE in_study_area)::FLOAT / COUNT(*)
            ELSE 0
        END AS parcel_capture_fraction,
        -- Characteristic study area radius (km), approximated from parcel density
        CASE
            WHEN COUNT(*) FILTER (WHERE in_study_area) > 0
            THEN SQRT(
                COUNT(*) FILTER (WHERE in_study_area)::FLOAT
                / NULLIF(COUNT(*), 0)
            ) * 10.0  -- heuristic scaling factor
            ELSE 1.0
        END AS study_area_radius_km
    FROM classified_parcels
),

-- 5. Compute internal capture per parcel
--
-- For parcels inside the study area:
--   internal_capture_pct = min(1.0, parcel_capture_fraction * attenuation)
--   where attenuation = exp(-intrazonal_friction * avg_trip_length / study_area_radius)
--
-- The attenuation factor accounts for trips long enough to leave the
-- study area even when both ends are inside it.
--
-- For parcels outside the study area:
--   internal_capture_pct = 0 (all trips are external through-trips)
capture_rates AS (
    SELECT
        cp.parcel_id,
        cp.trips_total,
        cp.trips_intra_parcel,
        cp.trips_outbound,
        cp.in_study_area,
        cp.avg_trip_length_km,
        CASE
            WHEN NOT cp.in_study_area THEN 0.0
            WHEN cp.trips_total = 0 THEN 1.0
            ELSE LEAST(
                1.0,
                as_.parcel_capture_fraction
                * EXP(
                    -{{ var("transport_intrazonal_friction", 0.15) }}
                    * cp.avg_trip_length_km
                    / NULLIF(as_.study_area_radius_km, 0)
                )
            )
        END AS internal_capture_pct
    FROM classified_parcels cp
    CROSS JOIN area_stats as_
),

-- 6. Compute trip volumes and final output
final AS (
    SELECT
        parcel_id,
        -- Internal trips = intra-parcel trips + internal portion of outbound trips
        ROUND(
            trips_intra_parcel
            + (trips_outbound * internal_capture_pct)::FLOAT,
            4
        ) AS trips_internal,
        ROUND(internal_capture_pct, 4) AS internal_capture_pct,
        -- External trips = total trips - internal trips
        ROUND(
            GREATEST(0, trips_total - trips_intra_parcel - (trips_outbound * internal_capture_pct)::FLOAT),
            4
        ) AS trips_external
    FROM capture_rates
)

SELECT
    parcel_id,
    trips_internal,
    internal_capture_pct,
    trips_external
FROM final
ORDER BY parcel_id
