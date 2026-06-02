MODEL (
  name brewgis.seeds.test_tiger_block_groups,
  kind SEED (
    path '../../seeds/test_tiger_block_groups.csv'
  ),
  columns (
    geoid TEXT,
    geometry geometry(Geometry,4326),
    vintage TEXT
  )
);
