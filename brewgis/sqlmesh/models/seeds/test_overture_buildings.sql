MODEL (
  name brewgis.seeds.test_overture_buildings,
  kind SEED (
    path '../../seeds/test_overture_buildings.csv'
  ),
  description 'Test fixture: 21 Overture building footprints for the building footprint staging test.',
  column_descriptions (
    geometry = 'Building footprint polygon in EPSG:4326 (WGS 84).',
    height = 'Building height reported by the Overture source (metres).',
    levels = 'Number of building levels reported by the Overture source.',
    class = 'Overture building class (e.g. house, commercial, industrial, mixed).',
    source = 'Source dataset the footprint came from (e.g. OSM).',
    id = 'Overture building identifier (text).'
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
