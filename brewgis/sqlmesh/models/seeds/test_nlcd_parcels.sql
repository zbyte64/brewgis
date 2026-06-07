MODEL (
  name brewgis.seeds.test_nlcd_parcels,
  kind SEED (
    path '../../seeds/test_nlcd_parcels.csv'
  ),
  columns (
    parcel_id TEXT,
    land_development_category TEXT,
    impervious_fraction DOUBLE PRECISION
  )
);
