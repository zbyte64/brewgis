MODEL (
  name brewgis.seeds.test_sacog_parcels,
  kind SEED (
    path '../../seeds/test_sacog_parcels.csv'
  ),
  columns (
    parcel_id TEXT,
    geometry geometry(Geometry,4326),
    acres TEXT,
    du TEXT,
    emp TEXT,
    land_use TEXT,
    assessor TEXT,
    ret TEXT,
    off TEXT,
    pub TEXT,
    ind TEXT,
    other TEXT,
    jurisdiction TEXT,
    gp TEXT,
    gluc TEXT,
    census_blockgroup TEXT,
    census_block TEXT,
    notes TEXT
  )
);
