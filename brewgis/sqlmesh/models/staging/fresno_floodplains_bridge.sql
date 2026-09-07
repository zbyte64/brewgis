MODEL (
  name brewgis.staging._fresno_floodplains_raw,
  kind FULL,
  gateway duckdb
);

-- FEMA NFHL Flood Zones Bridge — materializes the DuckDB fetch VIEW into
-- PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat). ST_SetCRS
-- records the SRID explicitly because the DuckDB→PostGIS FDW drops SRID
-- metadata (all geometries arrive as SRID 0), mirroring
-- staging/fresno_parcels_bridge.sql.

SELECT
    fld_zone,
    sfha_tf,
    static_bfe,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.staging.fresno_floodplains;
