MODEL (
  name brewgis.@{region}.buildings_combined_pg,
  kind FULL,
  description 'PostgreSQL copy of the DuckDB buildings_combined model with GiST indexes for spatial joins.',
  column_descriptions (
    wgs84_geometry = 'Building footprint in WGS84 (EPSG:4326) with lon/lat axis order.',
    geometry = 'Building footprint in Web Mercator (EPSG:3857).',
    local_geometry = 'Building footprint projected to the region local_srid.',
    height = 'Building height in metres from the source dataset.',
    levels = 'Number of building levels from the source dataset.',
    class = 'Source building class label (Overture or VIDA).',
    source = 'Origin dataset of the record: overture or vida.',
    bf_source = 'Building-footprint provider (google or microsoft); null for Overture rows.',
    confidence = 'VIDA confidence score for the building footprint; null for Overture rows.',
    class_category = 'Building class grouped into residential, commercial, industrial, mixed or other.',
    footprint_sqft = 'Building footprint area computed in local_srid and converted to square feet (sq ft).'
  ),
  blueprints @region_blueprints()
);

-- Combined Building Footprints (PG copy) — PostgreSQL materialization of the
-- buildings_combined VIEW with GiST indexes for performant spatial joins in
-- parcel_building_footprints and downstream models.
--
-- This exists because the DuckDB-gateway bridge underneath buildings_combined
-- cannot be GiST-indexed from DuckDB. By materializing a PG copy with proper
-- indexes, ST_Intersects spatial joins run as index scans instead of sequential
-- scans (~302K buildings).
--
-- All three CRSs come tagged from the published VIEW, and its local_geometry is
-- projected by DuckDB: that transform agreed with PostGIS's ``ST_Transform`` to
-- 0.000000 m across 1% samples of both regions' built tables (fresno 2834 rows,
-- sacog 6668 rows; 2026-09-27), so projecting it again here would be duplicated
-- work.

SELECT
  wgs84_geometry,
  geometry,
  local_geometry,
  height,
  levels,
  class,
  source,
  bf_source,
  confidence,
  CASE
      WHEN class IN ('cabin','dwelling_house','ger','houseboat','stilt_house','static_caravan',
                     'trullo','semi','residential','house','apartments','dormitory','detached',
                     'semidetached','terrace','bungalow') THEN 'residential'
      WHEN class = 'commercial' THEN 'commercial'
      WHEN class = 'industrial' THEN 'industrial'
      WHEN class IN ('mixed') OR class IS NULL THEN 'mixed'
      ELSE 'other'
  END AS class_category,
  @local_area_sqm(ST_Area(local_geometry)) * 10.7639 AS footprint_sqft
FROM brewgis.@{region}.buildings_combined;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_buildings_combined_pg_wgs84_geometry_')
  ON @this_model USING GIST (wgs84_geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_buildings_combined_pg_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_buildings_combined_pg_local_geometry_')
  ON @this_model USING GIST (local_geometry);
ANALYZE @this_model;
