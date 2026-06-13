MODEL (
  name brewgis.seeds.overture_land_cover_map,
  kind SEED (
    path '../../seeds/overture_land_cover_map.csv'
  ),
  columns (
    subtype TEXT,
    class TEXT,
    category TEXT
  )
);
