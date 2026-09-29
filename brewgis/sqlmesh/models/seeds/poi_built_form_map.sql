MODEL (
  name brewgis.seeds.poi_built_form_map,
  kind SEED (
    path '../../seeds/poi_built_form_map.csv'
  ),
  description 'OpenStreetMap POI category to built form key lookup for the base canvas POI override: the built form a parcel takes when a point of that category falls inside it.',
  column_descriptions (
    poi_category = 'POI category from the Overpass taxonomy (macros/overpass_fetch.py POI_CATEGORIES).',
    built_form_key = 'Built form key assigned to a parcel containing a point of this category; a key of the seeded default built forms library.',
    priority = 'Tie-break when one parcel contains points of several categories: the lowest priority wins (most informative first).'
  ),
  columns (
    poi_category TEXT,
    built_form_key TEXT,
    priority INT
  )
);
