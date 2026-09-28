MODEL (
  name brewgis.fresno.parcels_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Fresno parcel fetch, one row per parcel feature.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel feature, as fetched from the FeatureServer.',
    apn = 'Assessor parcel number (APN), identical to parcel_id on this feature-grain fetch.',
    agency_cod = 'AGENCY_COD agency code of the parcel feature.',
    roll_year = 'ROLL_YEAR assessor roll year of the parcel feature.',
    shape_area = 'SHAPE_AREA attribute of the parcel feature as published by the FeatureServer (source units).',
    geometry = 'Parcel feature geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.fresno.parcels for the re-tagged column.'
  ),
  gateway duckdb
);

-- Fresno Parcels Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).
--
-- PostGIS models should use brewgis.fresno.parcels (the PostGIS VIEW
-- wrapping this table) rather than referencing this model directly, to get
-- proper SRID column metadata.

SELECT
    parcel_id,
    apn,
    agency_cod,
    roll_year,
    shape_area,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.parcels;
