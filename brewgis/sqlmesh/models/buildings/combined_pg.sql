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
-- DuckDB buildings_combined model with GiST indexes for performant spatial
-- joins in parcel_building_footprints and downstream models.
--
-- This exists because buildings_combined is a DuckDB-gateway FULL model whose
-- geometry column cannot be GiST-indexed from DuckDB. By materializing a PG
-- copy with proper indexes, ST_Intersects spatial joins run as index scans
-- instead of sequential scans (~302K buildings).
--
-- geometry (EPSG:3857) comes pre-projected from DuckDB; wgs84_geometry
-- (EPSG:4326) provides geographic coords; local_geometry (local_srid) is
-- needed for area computation but DuckDB cannot project it due to PROJ
-- constraints — transform here in PostGIS instead.

SELECT
  ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)) AS wgs84_geometry,
  ST_SetSRID(geometry, @VAR('wm_srid', 3857)) AS geometry,
  ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid')) AS local_geometry,
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
  @local_area_sqm(ST_Area(ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid')))) * 10.7639 AS footprint_sqft
FROM brewgis.@{region}.buildings_combined;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_buildings_combined_pg_wgs84_geometry_')
  ON @this_model USING GIST (wgs84_geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_buildings_combined_pg_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_buildings_combined_pg_local_geometry_')
  ON @this_model USING GIST (local_geometry);
ANALYZE @this_model;
