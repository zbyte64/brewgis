MODEL (
  name brewgis.seeds.test_vida_buildings,
  kind SEED (
    path '../../seeds/test_vida_buildings.csv'
  ),
  columns (
    geometry TEXT,
    confidence TEXT,
    bf_source TEXT,
    area_in_meters TEXT
  )
);
