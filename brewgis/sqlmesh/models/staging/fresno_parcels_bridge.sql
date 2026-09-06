MODEL (
  name brewgis.staging._fresno_parcels_raw,
  kind FULL,
  gateway duckdb
);

-- Fresno Parcels Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat). ST_SetCRS
-- records the SRID explicitly because the DuckDB→PostGIS FDW drops SRID
-- metadata (all geometries arrive as SRID 0), mirroring
-- staging/tiger_blocks_bridge.sql and assessor/overture_land_use_bridge.sql.
--
-- PostGIS models should use brewgis.staging.fresno_parcels (the PostGIS VIEW
-- wrapping this table) rather than referencing this model directly, to get
-- proper SRID column metadata.

SELECT
    parcel_id,
    apn,
    agency_cod,
    roll_year,
    shape_area,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.staging.fresno_parcels;
