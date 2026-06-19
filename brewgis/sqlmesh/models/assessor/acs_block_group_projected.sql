MODEL (
  name brewgis.assessor.acs_block_group_projected,
  kind FULL,
  audits (
    not_null(columns := (geoid)),
    unique_values(columns := (geoid,))
  )
);

-- ACS Block Group Projected — pre-projected geometry for indexed spatial joins.
--
-- Reads ACS block group data from staging, transforms geometry to local_srid
-- (California Albers, 3310), and applies a GiST index on the projected geometry.
--
-- The staging model (brewGIS.staging.acs_block_group) is executed on DuckDB,
-- which does not support PostgreSQL post_statements GiST indexes. Without an
-- index, spatial joins against brewGIS.assessor.sacog_assessor_parcels fall
-- back to unindexed nested loops (~2.4B cost).
--
-- This intermediate model runs on PostgreSQL, allows a GiST index, and is
-- kind FULL (~900 rows) — cheap to rebuild on every plan.

SELECT
    a.geoid,
    a.hh,
    a.du,
    ST_Transform(a.geometry, @VAR('local_srid', 3310)) AS geometry
FROM brewgis.staging.acs_block_group a
WHERE a.du > 0
  AND a.geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_acs_block_group_projected_geometry
  ON brewgis.assessor.acs_block_group_projected USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_acs_block_group_projected_geoid
  ON brewgis.assessor.acs_block_group_projected (geoid);
ANALYZE brewgis.assessor.acs_block_group_projected;
