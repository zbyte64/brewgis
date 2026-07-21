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

SELECT * FROM read_parquet('/app/planning/osm/osm_intersection_density.parquet');
