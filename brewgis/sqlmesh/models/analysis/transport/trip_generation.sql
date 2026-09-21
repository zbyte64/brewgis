MODEL (
  name brewgis.analysis.trip_generation,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,)),
    assert_column_non_negative(column_name := trips_total),
    assert_column_non_negative(column_name := trips_nonres)
  )
);

-- Trip Generation Model — T1 Module
--
-- Computes daily trip generation per parcel from ITE trip generation rates.
-- Uses BuildingType trip_rate_override (if set) or ITE default rates,
-- applies pass-by reduction for non-residential trips, and splits into
-- home-based work (HBW), home-based other (HBO), and non-home-based (NHB).
--
-- Variables:
--   @transport_nonres_trip_rate: Trips/1000 sqft/day (default: 42.94).
--   @transport_hbw_pct: Home-based work share (default: 0.18).
--   @transport_hbo_pct: Home-based other share (default: 0.42).
--   @transport_nhb_pct: Non-home-based share (default: 0.40).
--
-- Pass-by reduction comes from each built form's ``pass_by_trip_pct`` column
-- (``BuildingType.pass_by_trip_pct``), which is stored as a percentage
-- (0-100), not a fraction.

WITH parcel_base AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.du,
        es.building_sqft_total,
        es.built_form_key,
        es.land_development_category,
        es.intersection_density,
        es.pop,
        es.emp,
        es.geometry,
        bf.trip_rate_override,
        bf.pass_by_trip_pct
    FROM brewgis.analysis.core_end_state AS es
    LEFT JOIN @ref_model(@built_form_table) AS bf
        ON es.built_form_key = bf.key
),

trip_rates AS (
    SELECT
        parcel_id,
        area_gross_acres,
        du,
        building_sqft_total,
        geometry,

        -- Residential trips: dwelling_units * trip_rate_override
        -- (trip_rate_override is trips/dwelling_unit for residential)
        COALESCE(du * trip_rate_override, 0.0)
            AS trips_res,

        -- Non-residential trips: (building_sqft_total / 1000) * nonres_rate
        COALESCE((building_sqft_total / 1000.0) * @transport_nonres_trip_rate, 0.0)
            AS trips_nonres_raw,

        -- pass_by_trip_pct is a percentage (0-100) — normalise to a fraction
        -- before subtracting so the adjustment can never invert the sign.
        1.0 - COALESCE(pass_by_trip_pct, 0.0) / 100.0 AS pass_by_factor
    FROM parcel_base
)

SELECT
    parcel_id,
    area_gross_acres,
    -- Total primary trips with pass-by reduction
    trips_res + trips_nonres_raw * pass_by_factor AS trips_total,
    trips_res,
    -- Non-residential trips after pass-by reduction
    trips_nonres_raw * pass_by_factor AS trips_nonres,
    -- Trip purpose split
    (trips_res + trips_nonres_raw * pass_by_factor) * @transport_hbw_pct AS trips_hbw,
    (trips_res + trips_nonres_raw * pass_by_factor) * @transport_hbo_pct AS trips_hbo,
    (trips_res + trips_nonres_raw * pass_by_factor) * @transport_nhb_pct AS trips_nhb,
    geometry
FROM trip_rates;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_trip_generation_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_trip_generation_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
