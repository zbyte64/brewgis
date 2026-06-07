MODEL (
  name brewgis.seeds.test_constraints,
  kind SEED (
    path '../../seeds/test_constraints.csv'
  ),
  columns (
    constraint_id INTEGER,
    geometry geometry(Geometry,4326),
    constraint_type TEXT,
    buffer_distance DOUBLE PRECISION
  )
);
