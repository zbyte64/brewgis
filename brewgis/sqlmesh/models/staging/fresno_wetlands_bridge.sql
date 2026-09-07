MODEL (
  name brewgis.staging._fresno_wetlands_raw,
  kind FULL,
  gateway duckdb
);

-- Fresno Wetlands Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat). ST_SetCRS
-- records the SRID explicitly because the DuckDB→PostGIS FDW drops SRID
-- metadata (all geometries arrive as SRID 0), mirroring
-- staging/fresno_parcels_bridge.sql.

SELECT
    attribute,
    wetland_type,
    acres,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.staging.fresno_wetlands;
