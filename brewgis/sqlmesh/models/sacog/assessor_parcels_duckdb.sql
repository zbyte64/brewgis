MODEL (
  name duckdb.sacog.assessor_parcels,
  kind VIEW,
  description 'DuckDB staging VIEW reading the Sacramento County parcel MapServer (PARCELS/MapServer/8) through arcgis_query, one row per APN.',
  column_descriptions (
    apn = 'Assessor parcel number (APN, the layer''s PARCEL_NUMBER) of the parcel.',
    landuse = 'Assessor land-use code (LANDUSE) of the parcel.',
    zone = 'Assessor zoning code (ZONE_) of the parcel.',
    lotsize = 'Raw assessor lot size of the parcel (LOTSIZE, sq ft).',
    jurisdiction = 'Jurisdiction the parcel sits in (JURISDICTION).',
    geometry = 'Parcel geometry transformed from EPSG:4326 to EPSG:3857 (Web Mercator).',
    wgs84_geometry = 'Parcel polygon returned by arcgis_query in EPSG:4326 lon/lat.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    apn VARCHAR,
    landuse VARCHAR,
    zone VARCHAR,
    lotsize DOUBLE,
    jurisdiction VARCHAR,
    geometry GEOMETRY,
    wgs84_geometry GEOMETRY
  )
);

-- Sacramento County assessor parcels — DuckDB VIEW over the county's Active GIS
-- Parcel Base (PARCELS/MapServer/8, ~508K parcels). arcgis_query (the arcgis
-- extension) pages through the whole layer and returns its fields as typed
-- columns plus an EPSG:4326 geometry (the layer's native SR 2226 is
-- reprojected by the server). ST_Transform with always_xy=true keeps the
-- (lon,lat) input axis order.
--
-- The layer can carry several features per PARCEL_NUMBER; the parcel key is
-- the APN, so the largest LOTSIZE wins (OBJECTID breaks ties
-- deterministically). Rows without a PARCEL_NUMBER are not identifiable
-- parcels and are dropped.

SELECT
  PARCEL_NUMBER AS apn,
  LANDUSE AS landuse,
  ZONE_ AS zone,
  LOTSIZE AS lotsize,
  JURISDICTION AS jurisdiction,
  ST_Transform(geometry, 'EPSG:4326', 'EPSG:3857', true) AS geometry,
  geometry AS wgs84_geometry
FROM arcgis_query('https://mapservices.gis.saccounty.net/arcgis/rest/services/PARCELS/MapServer/8')
WHERE length(trim(PARCEL_NUMBER)) > 0
QUALIFY row_number() OVER (
  PARTITION BY PARCEL_NUMBER
  ORDER BY LOTSIZE DESC NULLS LAST, OBJECTID
) = 1;
