MODEL (
  name duckdb.staging.overture_land_use,
  kind VIEW,
  gateway duckdb,
  dialect duckdb
);

-- Overture Maps land use for Sacramento County, CA.
-- DuckDB reads GeoParquet directly from S3 via httpfs extension.
-- Land use contains polygons with subtype (agriculture, residential, industrial, etc.)
-- and optional class fields (farmland, commercial, retail, etc.).
-- Row-group filter pushdown on the bbox struct column ensures only
-- Sacramento-relevant row groups are fetched from S3.
-- Post-statements materialize the result in public.overture_land_use in
-- PostGIS via the postgres_scanner-attached pg catalog.

SELECT
  ST_Transform(geometry, 'EPSG:' || @VAR('local_srid', 3310)::text) AS local_geometry,
  ST_Transform(geometry, 'EPSG:4326') AS geometry,
  subtype::VARCHAR AS subtype,
  class::VARCHAR AS class
FROM read_parquet(@overture_land_use_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;
