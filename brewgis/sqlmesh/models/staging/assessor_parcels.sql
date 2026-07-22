MODEL (
  name duckdb.staging.assessor_parcels,
  kind VIEW,
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
