MODEL (
  name brewgis.seeds.test_nlcd_parcels,
  kind SEED (
    path '../../seeds/test_nlcd_parcels.csv'
  ),
  description 'Test fixture: 7 parcels with NLCD impervious fractions matching the NLCD parcel stats schema.',
  column_descriptions (
    parcel_id = 'Identifier of the parcel the impervious fraction applies to.',
    land_development_category = 'Land development category of the parcel.',
    impervious_fraction = 'NLCD impervious surface fraction of the parcel (0-1).'
  ),
  columns (
    parcel_id TEXT,
    land_development_category TEXT,
    impervious_fraction DOUBLE PRECISION
  )
);
