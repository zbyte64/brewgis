MODEL (
  name brewgis.@{region}.buildings_combined_pg,
  kind FULL,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
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
-- (EPSG:4326) provides geographic coords; local_geometry (EPSG:3310) is
-- needed for area computation but DuckDB cannot project it due to PROJ
-- constraints — transform here in PostGIS instead.

SELECT
  ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)) AS wgs84_geometry,
  ST_SetSRID(geometry, @VAR('wm_srid', 3857)) AS geometry,
  ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid', 3310)) AS local_geometry,
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
  ST_Area(ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid', 3310))) * 10.7639 AS footprint_sqft
FROM brewgis.@{region}.buildings_combined;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_buildings_combined_pg_wgs84_geometry_@snapshot_hash
  ON @this_model USING GIST (wgs84_geometry);
  CREATE INDEX IF NOT EXISTS idx_@{region}_buildings_combined_pg_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_@{region}_buildings_combined_pg_local_geometry_@snapshot_hash
  ON @this_model USING GIST (local_geometry);
ANALYZE @this_model;
