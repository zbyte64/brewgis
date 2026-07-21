MODEL (
  name brewgis.staging.osm_intersection_density,
  kind FULL,
  gateway duckdb
);

SELECT
  parcel_id,
  intersection_density,
  ST_SetSRID(ST_FlipCoordinates(geometry), 4326) AS geometry
FROM duckdb.staging.osm_intersection_density;
