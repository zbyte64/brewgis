MODEL (
  name brewgis.seeds.test_overture_buildings,
  kind SEED (
    path '../../seeds/test_overture_buildings.csv'
  ),
  columns (
    geometry geometry(Geometry,4326),
    height DOUBLE PRECISION,
    levels INTEGER,
    class TEXT,
    source TEXT,
    id TEXT
  )
);
