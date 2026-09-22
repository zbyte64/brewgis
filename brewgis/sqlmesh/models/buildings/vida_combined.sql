MODEL (
  name duckdb.buildings.vida_combined,
  kind VIEW,
  description 'VIDA Google and Microsoft building footprints read from Source Cooperative GeoParquet in DuckDB.',
  column_descriptions (
    geometry = 'Building footprint projected from WGS84 to Web Mercator (EPSG:3857).',
    wgs84_geometry = 'Building footprint in source WGS84 coordinates (EPSG:4326).',
    confidence = 'VIDA confidence score for the building footprint.',
    bf_source = 'Building-footprint source provider: google or microsoft (OSM rows are filtered out).',
    area_in_meters = 'Footprint area reported by VIDA in square metres (m2).'
  ),
  gateway duckdb,
  dialect duckdb
);

-- VIDA Google + Microsoft building footprints from Source Cooperative S3.
-- Filters to Google and Microsoft sources only (OSM is redundant with Overture).
-- DuckDB reads GeoParquet directly via httpfs extension with row-group pushdown.
-- Post-statements materialize the result in public.vida_combined_buildings in
-- PostGIS via the postgres_scanner-attached pg catalog.
--
-- Source CRS: EPSG:4326 (GeoParquet native lon/lat). VIDA Google+Microsoft
-- building footprints from Source Cooperative S3.

SELECT
  ST_Transform(geometry, 'EPSG:4326', 'EPSG:3857', true) AS geometry,
  geometry AS wgs84_geometry,
  confidence,
  bf_source,
  area_in_meters
FROM read_parquet(@vida_parquet_glob)
WHERE bf_source IN ('google', 'microsoft');
