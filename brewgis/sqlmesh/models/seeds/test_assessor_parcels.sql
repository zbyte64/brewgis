MODEL (
  name brewgis.seeds.test_assessor_parcels,
  kind SEED (
    path '../../seeds/test_assessor_parcels.csv'
  ),
  columns (
    apn TEXT,
    geometry geometry(Geometry,4326),
    lotsize DOUBLE PRECISION,
    landuse TEXT,
    zone TEXT,
    jurisdiction TEXT
  )
);
