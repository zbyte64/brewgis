MODEL (
  name brewgis.nlcd.overture_road_impervious,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id)),
    assert_road_area_valid
  )
);

-- pre hooks
-- (overture_transport is DuckDB gateway, so indexes must live here)
  CREATE INDEX IF NOT EXISTS idx_overture_transport_geometry_@snapshot_hash
  ON brewgis.staging.overture_transport USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_overture_transport_local_geometry_@snapshot_hash
  ON brewgis.staging.overture_transport USING GIST (local_geometry);

-- Overture Road Surface — per-parcel road intersection statistics.
--
-- Computes paved and unpaved road metrics within each parcel using Overture
-- transportation segments (roads). Overture roads are ST_LineString, so
-- ST_Area of the intersection is always 0. Instead, we compute:
--   - road_length_m: length of road within the parcel (meters)
--   - road_total_area: kept for backward compat (always 0 for linestrings)
--
-- Road classification:
--   Paved: surface IN ('paved', 'asphalt', 'concrete') or NULL (assumed paved)
--   Unpaved: surface IN ('unpaved', 'gravel', 'dirt', 'earth', 'ground')
--
-- Road length is in meters. Parcel geometry is in LOCAL_SRID (3310, California Albers).

WITH parcels AS (
    SELECT
        geography_id AS parcel_id,
        geometry
    FROM public.sacog_comparison_parcels
    WHERE geometry IS NOT NULL
),

transport AS (
    SELECT
        ST_Transform(ST_SetSRID(geometry, @VAR('default_srid', 4326)), @VAR('local_srid', 3310)) AS local_geometry,
        CASE
            WHEN surface IS NULL
                 OR surface IN ('paved', 'asphalt', 'concrete') THEN 'paved'
            WHEN surface IN ('unpaved', 'gravel', 'dirt', 'earth', 'ground') THEN 'unpaved'
            ELSE 'other'
        END AS road_surface_class
    FROM brewgis.staging.overture_transport
    WHERE local_geometry IS NOT NULL
),

-- Categorize by paved/unpaved and compute intersection geometry per parcel
-- Overture roads are ST_LineString, so we use ST_Length not ST_Area.
road_intersections AS (
    SELECT
        p.parcel_id,
        t.road_surface_class,
        ST_Length(ST_Intersection(p.geometry, t.local_geometry)) AS length_m
    FROM parcels p
    JOIN transport t
        ON ST_Intersects(p.geometry, t.local_geometry)
),

-- Aggregate to one row per parcel
road_summary AS (
    SELECT
        parcel_id,
        COALESCE(SUM(CASE WHEN road_surface_class = 'paved' THEN length_m END), 0) AS paved_length_m,
        COALESCE(SUM(CASE WHEN road_surface_class = 'unpaved' THEN length_m END), 0) AS unpaved_length_m,
        COALESCE(SUM(CASE WHEN road_surface_class = 'other' THEN length_m END), 0) AS other_length_m,
        COALESCE(SUM(length_m), 0) AS road_length_m
    FROM road_intersections
    GROUP BY parcel_id
),

-- Include all parcels (even those with no road intersection)
all_parcels AS (
    SELECT
        geography_id AS parcel_id,
        ST_Area(geometry) / 4046.86 AS area_gross_acres  -- sq meters → acres
    FROM public.sacog_comparison_parcels
    WHERE geometry IS NOT NULL
)

SELECT
    ap.parcel_id,
    COALESCE(rs.paved_length_m, 0.0) AS road_paved_area,
    COALESCE(rs.unpaved_length_m, 0.0) AS road_unpaved_area,
    COALESCE(rs.other_length_m, 0.0) AS road_other_area,
    COALESCE(rs.road_length_m, 0.0) AS road_total_area,
    COALESCE(
        rs.paved_length_m / NULLIF(rs.road_length_m, 0.0),
        0.0
    ) AS road_impervious_fraction,
    ap.area_gross_acres AS parcel_area_gross
FROM all_parcels ap
LEFT JOIN road_summary rs ON ap.parcel_id = rs.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_road_impervious_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
