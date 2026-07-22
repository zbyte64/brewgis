MODEL (
  name duckdb.staging.osm_intersection_density,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  columns (
    parcel_id VARCHAR,
    intersection_density DOUBLE,
    geometry GEOMETRY
  )
);

-- Source CRS: EPSG:4326 (lon/lat). Local GeoParquet from OSM intersection analysis.

SELECT
  parcel_id,
  intersection_density,
  ST_Transform(geometry, 'EPSG:4326', 'EPSG:3857', true) AS geometry,
  geometry AS wgs84_geometry
FROM read_parquet('/app/planning/osm/osm_intersection_density.parquet');
