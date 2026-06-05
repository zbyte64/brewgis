MODEL (
  name brewgis.staging.vida_combined_buildings,
  kind VIEW,
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
