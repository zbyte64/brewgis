MODEL (
  name brewgis.california.eto_zones_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Reference Evapotranspiration Zones fetch, one zone polygon per row.',
  column_descriptions (
    eto_zone = 'Reference Evapotranspiration Zone number (1-18) the polygon belongs to.',
    annual_eto_in = 'Annual reference evapotranspiration of the zone: sum of the zone''s twelve monthly average ETo depths (inches per year).',
    geometry = 'Zone geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.california.eto_zones for the re-tagged column.'
  ),
  gateway duckdb
);

-- California Reference Evapotranspiration Zones Bridge — materializes the
-- DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_GeomFromGeoJSON emits EPSG:4326 geometry (GeoJSON lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    eto_zone,
    annual_eto_in,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.california.eto_zones;
