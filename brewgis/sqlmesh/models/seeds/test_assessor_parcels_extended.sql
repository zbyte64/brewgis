MODEL (
  name brewgis.seeds.test_assessor_parcels_extended,
  kind SEED (
    path '../../seeds/test_assessor_parcels_extended.csv'
  ),
  description 'Test fixture: 5 additional assessor parcels with the same schema as test_assessor_parcels.',
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
