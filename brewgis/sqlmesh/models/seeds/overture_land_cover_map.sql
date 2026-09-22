MODEL (
  name brewgis.seeds.overture_land_cover_map,
  kind SEED (
    path '../../seeds/overture_land_cover_map.csv'
  ),
  description 'Overture land cover subtype and class to land development category lookup.',
  column_descriptions (
    subtype = 'Overture land cover subtype code to match (e.g. forest, crop).',
    class = 'Overture land cover class code to match (empty when the rule keys on subtype only).',
    category = 'Land development category the matched subtype and class map to.'
  ),
  columns (
    subtype TEXT,
    class TEXT,
    category TEXT
  )
);
