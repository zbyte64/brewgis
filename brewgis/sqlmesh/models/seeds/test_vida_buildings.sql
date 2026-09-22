MODEL (
  name brewgis.seeds.test_vida_buildings,
  kind SEED (
    path '../../seeds/test_vida_buildings.csv'
  ),
  description 'Test fixture: 8 VIDA building footprints with source and confidence, matching the VIDA schema.',
  column_descriptions (
    geometry = 'Building footprint polygon in EPSG:4326 (WGS 84).',
    confidence = 'Detector confidence score of the VIDA footprint (0-1).',
    bf_source = 'Source that produced the footprint (google, microsoft or openstreetmap).',
    area_in_meters = 'Footprint area of the building (square metres).'
  ),
  columns (
    geometry geometry(Geometry,4326),
    confidence DOUBLE PRECISION,
    bf_source TEXT,
    area_in_meters DOUBLE PRECISION
  )
);
