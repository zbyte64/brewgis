MODEL (
  name brewgis.seeds.test_assessor_parcels,
  kind SEED (
    path '../../seeds/test_assessor_parcels.csv'
  ),
  description 'Test fixture: 35 assessor parcels for the assessor parcel, census and intersection density tests.',
  column_descriptions (
    apn = 'Assessor parcel number (APN).',
    geometry = 'Parcel polygon geometry in EPSG:4326 (WGS 84).',
    lotsize = 'Parcel lot size (acres).',
    landuse = 'Assessor land use code of the parcel (text).',
    zone = 'Assessor zoning code of the parcel (e.g. R-1).',
    jurisdiction = 'Jurisdiction the parcel lies in.'
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
