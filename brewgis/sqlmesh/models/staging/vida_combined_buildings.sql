MODEL (
  name brewgis.staging.vida_combined_buildings,
  kind FULL,
  gateway duckdb,
  dialect duckdb
);

-- VIDA Google + Microsoft building footprints from Source Cooperative S3.
-- Filters to Google and Microsoft sources only (OSM is redundant with Overture).
-- DuckDB reads GeoParquet directly via httpfs extension with row-group pushdown.
-- Post-statements materialize the result in public.vida_combined_buildings in
-- PostGIS via the postgres_scanner-attached pg catalog.

SELECT
  geometry,
  confidence,
  bf_source,
  area_in_meters
FROM read_parquet(@vida_parquet_glob)
WHERE bf_source IN ('google', 'microsoft');

DROP TABLE IF EXISTS pg.public.vida_combined_buildings CASCADE;
CREATE TABLE pg.public.vida_combined_buildings AS
SELECT geometry, confidence, bf_source, area_in_meters
FROM read_parquet(@vida_parquet_glob)
WHERE bf_source IN ('google', 'microsoft');
CREATE INDEX IF NOT EXISTS idx_vida_combined_buildings_geometry
ON pg.public.vida_combined_buildings USING GIST (geometry);
ANALYZE pg.public.vida_combined_buildings;
