MODEL (
  name brewgis.staging.osm_intersection_density,
  kind FULL,
  gateway duckdb
);

SELECT
  parcel_id,
  intersection_density,
  ST_SetSRID(geometry, 3857) AS geometry,
  ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry
FROM duckdb.staging.osm_intersection_density;
