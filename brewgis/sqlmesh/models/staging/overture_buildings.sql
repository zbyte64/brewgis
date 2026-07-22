MODEL (
  name duckdb.staging.overture_buildings,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
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
