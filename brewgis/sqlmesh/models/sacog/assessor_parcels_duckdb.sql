MODEL (
  name duckdb.sacog.assessor_parcels,
  kind VIEW,
  description 'DuckDB staging view of Sacramento County assessor parcels read from the local GeoParquet cache.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the parcel.',
    landuse = 'Assessor land-use code (LANDUSE) of the parcel.',
    zone = 'Assessor zoning code (ZONE_) of the parcel.',
    lotsize = 'Raw assessor lot size of the parcel (sq ft).',
    jurisdiction = 'Jurisdiction the parcel sits in (JURISDICTION).',
    geometry = 'Parcel geometry transformed from EPSG:4326 to EPSG:3857 (Web Mercator).'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    apn VARCHAR,
    landuse VARCHAR,
    zone VARCHAR,
    lotsize DOUBLE,
    jurisdiction VARCHAR,
    geometry GEOMETRY
  )
);

-- Sacramento County assessor parcels — DuckDB reads from local GeoParquet.
--
-- Source CRS: EPSG:4326 (GeoParquet native lon/lat). Parcel geometries from
-- ArcGIS REST export written by assessor_fetcher. DuckDB preserves (lon,lat)
-- axis from GeoParquet metadata. ST_Transform with always_xy=true ensures
-- (lon,lat) input axis order.

SELECT
  apn,
  landuse,
  zone,
  lotsize,
  jurisdiction,
  ST_Transform(geometry, 'EPSG:4326', 'EPSG:3857', true) AS geometry,
  geometry AS wgs84_geometry
FROM read_parquet('/app/planning/assessor/assessor_parcels.parquet');
