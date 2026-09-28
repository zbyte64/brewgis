MODEL (
  name brewgis.fresno.floodplains_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB FEMA flood zone fetch, one zone per row.',
  column_descriptions (
    fld_zone = 'FEMA flood hazard zone code (FLD_ZONE) of the polygon.',
    sfha_tf = 'SFHA_TF Special Flood Hazard Area flag from the NFHL record.',
    static_bfe = 'STATIC_BFE static base flood elevation from the NFHL record.',
    geometry = 'Flood zone geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.fresno.floodplains for the re-tagged column.'
  ),
  gateway duckdb
);

-- FEMA NFHL Flood Zones Bridge — materializes the DuckDB fetch VIEW into
-- PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    fld_zone,
    sfha_tf,
    static_bfe,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.floodplains;
