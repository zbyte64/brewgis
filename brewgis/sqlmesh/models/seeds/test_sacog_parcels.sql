MODEL (
  name brewgis.seeds.test_sacog_parcels,
  kind SEED (
    path '../../seeds/test_sacog_parcels.csv'
  ),
  description 'Test fixture: 1 SACOG parcel row with acres, dwelling units, employment, land use and census ids.',
  column_descriptions (
    parcel_id = 'SACOG parcel identifier (text).',
    geometry = 'Parcel polygon geometry in EPSG:4326 (WGS 84).',
    acres = 'Parcel area (acres).',
    du = 'Dwelling units on the parcel.',
    emp = 'Employment on the parcel (jobs).',
    land_use = 'SACOG land use label of the parcel.',
    assessor = 'Assessor use code of the parcel (SACOG field, text).',
    ret = 'Retail employment on the parcel (jobs).',
    off = 'Office employment on the parcel (jobs).',
    pub = 'Public employment on the parcel (jobs).',
    ind = 'Industrial employment on the parcel (jobs).',
    other = 'Other employment on the parcel (jobs).',
    jurisdiction = 'Jurisdiction the parcel lies in (SACOG field).',
    gp = 'SACOG parcel source field gp, carried through unchanged (text).',
    gluc = 'SACOG parcel source field gluc, carried through unchanged (text).',
    census_blockgroup = 'Census block group GEOID (12-digit FIPS) containing the parcel.',
    census_block = 'Census block GEOID (15-digit FIPS) containing the parcel.',
    notes = 'Free-text notes on the fixture parcel.'
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
