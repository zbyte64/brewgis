MODEL (
  name brewgis.seeds.test_overture_land_use,
  kind SEED (
    path '../../seeds/test_overture_land_use.csv'
  ),
  description 'Test fixture: 6 Overture land use polygons matching the overture_land_use schema.',
  column_descriptions (
    geometry = 'Overture land use polygon in EPSG:4326 (WGS 84).',
    subtype = 'Overture land use subtype code (e.g. residential, agriculture).',
    class = 'Overture land use class code (empty when the polygon carries no class).'
  ),
  columns (
    geometry geometry(Geometry,4326),
    subtype TEXT,
    class TEXT
  )
);
