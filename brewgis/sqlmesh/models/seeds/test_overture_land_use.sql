MODEL (
  name brewgis.seeds.test_overture_land_use,
  kind SEED (
    path '../../seeds/test_overture_land_use.csv'
  ),
  columns (
    geometry geometry(Geometry,4326),
    subtype TEXT,
    class TEXT
  )
);
