MODEL (
  name duckdb.@{region}.overture_buildings,
  kind VIEW,
  description 'Overture Maps building footprints for the region (release 2026-08-19.0 GeoParquet read from S3 by DuckDB via httpfs), reprojected to 3857, 4326 and the local CRS.',
  column_descriptions (
    geometry = 'Building footprint polygon reprojected from Overture CRS84 to Web Mercator (EPSG:3857).',
    wgs84_geometry = 'Building footprint polygon reprojected from Overture CRS84 to EPSG:4326 (lon/lat).',
    local_geometry = 'Building footprint polygon reprojected from Overture CRS84 to the region local CRS (EPSG:3310).',
    height = 'Overture building height, NULL when the source value is NaN (meters).',
    levels = 'Overture floor count from num_floors, NULL when the source value is NaN (levels).',
    class = 'Overture building class, cast to VARCHAR.'
  ),
  gateway duckdb,
  dialect duckdb,
  blueprints @region_blueprints()
);

-- Overture Maps building footprints for Sacramento County, CA.
-- DuckDB reads GeoParquet directly from S3 via httpfs extension.
-- Row-group filter pushdown on the bbox struct column ensures only
-- Sacramento-relevant row groups are fetched from S3.
-- Post-statements materialize the result in public.overture_buildings in
-- PostGIS via the postgres_scanner-attached pg catalog.
--
-- Source CRS: CRS84 (lon/lat axis). Overture Maps GeoParquet via S3 httpfs.
-- ST_Transform with always_xy=true ensures (lon,lat) input axis order.

-- Increase the maximum number of network retries (Default is usually 3)
SET http_retries = 10;

-- Change the network timeout limit (e.g., to 30 seconds)
SET http_timeout = 30;
SET http_retry_wait_ms = 1000;
SET httpfs_connection_caching = true;

SELECT
  ST_Transform(geometry, 'CRS84', 'EPSG:3857', true) AS geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:4326', true) AS wgs84_geometry,
  ST_Transform(geometry, 'CRS84', 'EPSG:' || @VAR('local_srid', 3310)::text, true) AS local_geometry,
  CASE WHEN NOT is_nan(height) THEN height END AS height,
  CASE WHEN NOT is_nan(num_floors::DOUBLE) THEN num_floors::INTEGER END AS levels,
  class::VARCHAR AS class
FROM read_parquet(@overture_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;
