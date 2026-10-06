MODEL (
  name brewgis.fresno.city_boundary_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Fresno city limits fetch, one boundary row.',
  column_descriptions (
    objectid = 'Feature ID (FID) of the city limits record, as fetched from the FeatureServer.',
    agency_cod = 'AGENCY_COD code of the agency that publishes the boundary.',
    agency_nam = 'AGENCY_NAM agency name of the boundary record.',
    geometry = 'City limits geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.fresno.city_boundary for the re-tagged column.'
  ),
  gateway duckdb
);

-- Fresno City Boundary Bridge — materializes the DuckDB fetch VIEW into
-- PostGIS.
--
-- arcgis_query emits EPSG:4326 geometry (lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    objectid,
    agency_cod,
    agency_nam,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.city_boundary;
