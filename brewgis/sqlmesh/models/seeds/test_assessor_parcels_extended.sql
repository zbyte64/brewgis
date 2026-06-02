MODEL (
  name brewgis.seeds.test_assessor_parcels_extended,
  kind SEED (
    path '../../seeds/test_assessor_parcels_extended.csv'
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
