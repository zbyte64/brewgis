MODEL (
  name brewgis.staging.buildings_combined_pg,
  kind FULL
);

-- Combined Building Footprints (PG copy) — PostgreSQL materialization of the
-- DuckDB buildings_combined model with GiST indexes for performant spatial
-- joins in parcel_building_footprints and downstream models.
--
-- This exists because buildings_combined is a DuckDB-gateway FULL model whose
-- geometry column cannot be GiST-indexed from DuckDB. By materializing a PG
-- copy with proper indexes, ST_Intersects spatial joins run as index scans
-- instead of sequential scans (~302K buildings).

SELECT
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
  ST_Area(local_geometry) * 10.7639 AS footprint_sqft
FROM brewgis.staging.buildings_combined;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_buildings_combined_pg_geometry
  ON brewgis.staging.buildings_combined_pg USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_buildings_combined_pg_local_geometry
  ON brewgis.staging.buildings_combined_pg USING GIST (local_geometry);
ANALYZE brewgis.staging.buildings_combined_pg;
