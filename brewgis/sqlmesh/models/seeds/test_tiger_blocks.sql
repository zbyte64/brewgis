MODEL (
  name brewgis.seeds.test_tiger_blocks,
  kind SEED (
    path '../../seeds/test_tiger_blocks.csv'
  ),
  description 'Test fixture: 2 TIGER block boundaries matching the tiger_blocks schema.',
  column_descriptions (
    geoid = 'Census block GEOID (15-digit FIPS).',
    geometry = 'Block boundary polygon in EPSG:4326 (WGS 84).',
    vintage = 'TIGER/Line vintage year of the boundary (text).'
  ),
  columns (
    geoid TEXT,
    geometry geometry(Geometry,4326),
    vintage TEXT
  )
);
