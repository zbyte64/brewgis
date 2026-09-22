MODEL (
  name brewgis.sacog.assessor_parcels_raw,
  kind FULL,
  description 'Assessor parcels bridge: materializes the DuckDB staging view duckdb.sacog.assessor_parcels.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the parcel.',
    geometry = 'Parcel geometry set to EPSG:3857 (Web Mercator) from the DuckDB staging view.',
    wgs84_geometry = 'Parcel geometry set to EPSG:4326 (WGS84 lon/lat) from the DuckDB staging view.',
    lotsize = 'Raw assessor lot size of the parcel (sq ft).',
    landuse = 'Assessor land-use code (LANDUSE) of the parcel.',
    zone = 'Assessor zoning code (ZONE_) of the parcel.',
    jurisdiction = 'Jurisdiction the parcel sits in (JURISDICTION).'
  ),
  gateway duckdb
);

-- Assessor Parcels Bridge — materializes the DuckDB VIEW into PostGIS.

SELECT
  apn,
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  lotsize,
  landuse,
  zone,
  jurisdiction
FROM duckdb.sacog.assessor_parcels;
