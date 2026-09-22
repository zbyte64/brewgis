MODEL (
  name brewgis.fresno.city_boundary_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Fresno city limits fetch, one boundary row.',
  column_descriptions (
    objectid = 'Feature ID (FID) of the city limits record, as fetched from the FeatureServer.',
    agency_cod = 'AGENCY_COD code of the agency that publishes the boundary.',
    agency_nam = 'AGENCY_NAM agency name of the boundary record.',
    geometry = 'City limits geometry in EPSG:4326, ST_SetCRS-tagged so the FDW keeps the SRID.'
  ),
  gateway duckdb
);

-- Fresno City Boundary Bridge — materializes the DuckDB fetch VIEW into
-- PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat). ST_SetCRS
-- records the SRID explicitly because the DuckDB→PostGIS FDW drops SRID
-- metadata (all geometries arrive as SRID 0), mirroring
-- staging/fresno_parcels_bridge.sql.

SELECT
    objectid,
    agency_cod,
    agency_nam,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.city_boundary;
