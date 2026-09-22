MODEL (
  name brewgis.seeds.overture_land_use_map,
  kind SEED (
    path '../../seeds/overture_land_use_map.csv'
  ),
  description 'Overture land use subtype and class to land development category lookup.',
  column_descriptions (
    subtype = 'Overture land use subtype code to match (e.g. agriculture, developed).',
    class = 'Overture land use class code to match (empty when the rule keys on subtype only).',
    category = 'Land development category the matched subtype and class map to.'
  ),
  columns (
    subtype TEXT,
    class TEXT,
    category TEXT
  )
);
