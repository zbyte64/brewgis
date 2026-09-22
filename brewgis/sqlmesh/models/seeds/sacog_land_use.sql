MODEL (
  name brewgis.seeds.sacog_land_use,
  kind SEED (
    path '../../seeds/sacog_land_use.csv'
  ),
  description 'SACOG land use label to land development category lookup used by the base canvas model.',
  column_descriptions (
    land_use_label = 'SACOG land use label to match against the parcel land_use value.',
    category = 'Land development category assigned to the label.'
  ),
  columns (
    land_use_label TEXT,
    category TEXT
  )
);
