MODEL (
  name brewgis.nlcd.overture_road_impervious,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Overture Road Impervious — per-parcel road surface statistics.
--
-- Computes paved and unpaved road area within each parcel using Overture
-- transportation segments (roads). Road impervious fraction is the share
-- of parcel area covered by paved road surfaces, complementing the NLCD-based
-- impervious fraction metric.
--
-- Road classification:
--   Paved: surface IN ('paved', 'asphalt', 'concrete') or NULL (assumed paved)
--   Unpaved: surface IN ('unpaved', 'gravel', 'dirt', 'earth', 'ground')
--
-- All areas are in acres. Parcel geometry is in LOCAL_SRID (3310, California Albers).

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
    WHERE geometry IS NOT NULL
),

-- Categorize by paved/unpaved and compute intersection area per parcel
road_intersections AS (
    SELECT
        p.parcel_id,
        t.road_surface_class,
        ST_Area(ST_Intersection(p.geometry, t.local_geometry)) AS area_sqm
    FROM parcels p
    JOIN transport t
        ON ST_Intersects(p.geometry, t.local_geometry)
),

-- Aggregate to one row per parcel
road_summary AS (
    SELECT
        parcel_id,
        COALESCE(SUM(CASE WHEN road_surface_class = 'paved' THEN area_sqm END), 0) AS paved_sqm,
        COALESCE(SUM(CASE WHEN road_surface_class = 'unpaved' THEN area_sqm END), 0) AS unpaved_sqm,
        COALESCE(SUM(CASE WHEN road_surface_class = 'other' THEN area_sqm END), 0) AS other_sqm,
        COALESCE(SUM(area_sqm), 0) AS total_sqm
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
    COALESCE(rs.paved_sqm / 4046.86, 0.0) AS road_paved_area,
    COALESCE(rs.unpaved_sqm / 4046.86, 0.0) AS road_unpaved_area,
    COALESCE(rs.other_sqm / 4046.86, 0.0) AS road_other_area,
    COALESCE(rs.total_sqm / 4046.86, 0.0) AS road_total_area,
    COALESCE(
        (rs.paved_sqm / 4046.86) / NULLIF(ap.area_gross_acres, 0.0),
        0.0
    ) AS road_impervious_fraction,
    ap.area_gross_acres AS parcel_area_gross
FROM all_parcels ap
LEFT JOIN road_summary rs ON ap.parcel_id = rs.parcel_id;

-- post_statements
-- (overture_transport is DuckDB gateway, so indexes must live here)
  CREATE INDEX IF NOT EXISTS idx_overture_transport_geometry
  ON brewgis.staging.overture_transport USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_overture_road_impervious_parcel_id
  ON brewgis.nlcd.overture_road_impervious (parcel_id);
