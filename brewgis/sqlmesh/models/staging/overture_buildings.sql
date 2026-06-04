MODEL (
  name brewgis.staging.overture_buildings,
  kind FULL,
  gateway duckdb,
  dialect duckdb
);

-- Overture Maps building footprints for Sacramento County, CA.
-- DuckDB reads GeoParquet directly from S3 via httpfs extension.
-- Row-group filter pushdown on the bbox struct column ensures only
-- Sacramento-relevant row groups are fetched from S3.
-- Post-statements materialize the result in public.overture_buildings in
-- PostGIS via the postgres_scanner-attached pg catalog.

SELECT
  geometry,
  CASE WHEN NOT is_nan(height) THEN height END AS height,
  CASE WHEN NOT is_nan(num_floors::DOUBLE) THEN num_floors::INTEGER END AS levels,
  class::VARCHAR AS class
FROM read_parquet(@overture_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;

DROP TABLE IF EXISTS pg.public.overture_buildings CASCADE;
CREATE TABLE pg.public.overture_buildings AS
SELECT
  geometry,
  CASE WHEN NOT is_nan(height) THEN height END AS height,
  CASE WHEN NOT is_nan(num_floors::DOUBLE) THEN num_floors::INTEGER END AS levels,
  class::VARCHAR AS class
FROM read_parquet(@overture_parquet_glob)
WHERE bbox.xmin < @overture_bbox_max_x
  AND bbox.xmax > @overture_bbox_min_x
  AND bbox.ymin < @overture_bbox_max_y
  AND bbox.ymax > @overture_bbox_min_y;
CREATE INDEX IF NOT EXISTS idx_overture_buildings_geometry
ON pg.public.overture_buildings USING GIST (geometry);
ANALYZE pg.public.overture_buildings;
