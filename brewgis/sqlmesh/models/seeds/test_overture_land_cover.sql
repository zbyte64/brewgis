MODEL (
  name brewgis.seeds.test_overture_land_cover,
  kind SEED (
    path '../../seeds/test_overture_land_cover.csv'
  ),
  description 'Test fixture: 6 Overture land cover polygons matching the overture_land_cover schema.',
  column_descriptions (
    geometry = 'Overture land cover polygon in EPSG:4326 (WGS 84).',
    subtype = 'Overture land cover subtype code (e.g. forest, crop).'
  ),
  columns (
    geometry geometry(Geometry,4326),
    subtype TEXT
  )
);
