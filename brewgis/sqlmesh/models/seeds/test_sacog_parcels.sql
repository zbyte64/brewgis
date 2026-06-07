MODEL (
  name brewgis.seeds.test_sacog_parcels,
  kind SEED (
    path '../../seeds/test_sacog_parcels.csv'
  ),
  columns (
    parcel_id TEXT,
    geometry geometry(Geometry,4326),
    acres DOUBLE PRECISION,
    du DOUBLE PRECISION,
    emp DOUBLE PRECISION,
    land_use TEXT,
    assessor TEXT,
    ret DOUBLE PRECISION,
    off DOUBLE PRECISION,
    pub DOUBLE PRECISION,
    ind DOUBLE PRECISION,
    other DOUBLE PRECISION,
    jurisdiction TEXT,
    gp TEXT,
    gluc TEXT,
    census_blockgroup TEXT,
    census_block TEXT,
    notes TEXT
  )
);
