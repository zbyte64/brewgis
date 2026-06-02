MODEL (
  name brewgis.seeds.test_tiger_blocks,
  kind SEED (
    path '../../seeds/test_tiger_blocks.csv'
  ),
  columns (
    geoid TEXT,
    geometry geometry(Geometry,4326),
    vintage TEXT
  )
);
