MODEL (
  name brewgis.seeds.test_overture_land_cover,
  kind SEED (
    path '../../seeds/test_overture_land_cover.csv'
  ),
  columns (
    geometry geometry(Geometry,4326),
    subtype TEXT
  )
);
