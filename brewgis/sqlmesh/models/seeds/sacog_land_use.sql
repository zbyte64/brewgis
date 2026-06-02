MODEL (
  name brewgis.seeds.sacog_land_use,
  kind SEED (
    path '../../seeds/sacog_land_use.csv'
  ),
  columns (
    land_use_label TEXT,
    category TEXT
  )
);
