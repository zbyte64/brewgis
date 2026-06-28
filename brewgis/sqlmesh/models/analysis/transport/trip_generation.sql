MODEL (
  name brewgis.analysis.trip_generation,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
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
--   @transport_pass_by_pct: Pass-by reduction fraction (default: 0.0).
--   @transport_hbw_pct: Home-based work share (default: 0.18).
--   @transport_hbo_pct: Home-based other share (default: 0.42).
--   @transport_nhb_pct: Non-home-based share (default: 0.40).

WITH parcel_base AS (
    SELECT
        es.parcel_id,
        es.gross_acres,
        es.dwelling_units_total,
        es.building_sqft_total,
        es.built_form_id,
        es.land_dev_category,
        es.intersection_density,
        es.population,
        es.employment_total,
        es.geom,
        bf.trip_rate_override,
        bf.pass_by_trip_pct
    FROM brewgis.analysis.core_end_state AS es
    LEFT JOIN public.built_forms AS bf
        ON es.built_form_id = bf.key
),

trip_rates AS (
    SELECT
        parcel_id,
        gross_acres,
        dwelling_units_total,
        building_sqft_total,
        geom,

        -- Residential trips: dwelling_units * trip_rate_override
        -- (trip_rate_override is trips/dwelling_unit for residential)
        COALESCE(dwelling_units_total * trip_rate_override, 0.0)
            AS trips_res,

        -- Non-residential trips: (building_sqft_total / 1000) * nonres_rate
        COALESCE((building_sqft_total / 1000.0) * @transport_nonres_trip_rate, 0.0)
            AS trips_nonres_raw,

        COALESCE(pass_by_trip_pct, 0.0) AS pass_by_trip_pct
    FROM parcel_base
)

SELECT
    parcel_id,
    gross_acres,
    -- Total primary trips with pass-by reduction
    trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct) AS trips_total,
    trips_res,
    -- Non-residential trips after pass-by reduction
    trips_nonres_raw * (1.0 - pass_by_trip_pct) AS trips_nonres,
    -- Trip purpose split
    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct)) * @transport_hbw_pct AS trips_hbw,
    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct)) * @transport_hbo_pct AS trips_hbo,
    (trips_res + trips_nonres_raw * (1.0 - pass_by_trip_pct)) * @transport_nhb_pct AS trips_nhb,
    geom
FROM trip_rates;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_trip_generation_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_trip_generation_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
