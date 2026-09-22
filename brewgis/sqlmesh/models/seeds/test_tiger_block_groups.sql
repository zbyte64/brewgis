MODEL (
  name brewgis.seeds.test_tiger_block_groups,
  kind SEED (
    path '../../seeds/test_tiger_block_groups.csv'
  ),
  description 'Test fixture: 1 TIGER block group boundary matching the tiger_block_groups schema.',
  column_descriptions (
    geoid = 'Census block group GEOID (12-digit FIPS).',
    geometry = 'Block group boundary polygon in EPSG:4326 (WGS 84).',
    vintage = 'TIGER/Line vintage year of the boundary (text).'
  ),
  columns (
    geoid TEXT,
    geometry geometry(Geometry,4326),
    vintage TEXT
  )
);
