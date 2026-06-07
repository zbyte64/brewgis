MODEL (
  name brewgis.seeds.test_vida_buildings,
  kind SEED (
    path '../../seeds/test_vida_buildings.csv'
  ),
  columns (
    geometry geometry(Geometry,4326),
    confidence DOUBLE PRECISION,
    bf_source TEXT,
    area_in_meters DOUBLE PRECISION
  )
);
