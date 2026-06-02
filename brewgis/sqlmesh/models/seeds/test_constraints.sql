MODEL (
  name brewgis.seeds.test_constraints,
  kind SEED (
    path '../../seeds/test_constraints.csv'
  ),
  columns (
    constraint_id TEXT,
    geometry TEXT,
    constraint_type TEXT,
    buffer_distance TEXT
  )
);
