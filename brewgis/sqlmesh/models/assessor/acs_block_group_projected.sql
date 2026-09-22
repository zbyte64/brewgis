MODEL (
  name brewgis.@{region}.acs_block_group_projected,
  kind FULL,
  description 'ACS block group demographics reprojected to local_srid (3310), one row per block group with homes.',
  column_descriptions (
    geoid = 'Census block group GEOID (12-digit FIPS) from the ACS staging model.',
    hh = 'Households in the block group from ACS table B25003 (count).',
    du = 'Dwelling units from ACS table B25024 (count); block groups with none are dropped.',
    median_income = 'Median household income of the block group from ACS table B19013 ($ per year).',
    rent_burden_pct = 'Share of renter households paying over 30% of income on rent (ACS B25070, % as 0-100).',
    pct_minority = 'Share of the population that is not white alone (ACS B03002, % as 0-100).',
    pct_college_educated = 'Share of adults with a bachelors degree or higher (ACS B15003, % as 0-100).',
    cost_burden_pct = 'Share of households cost-burdened in rent or owner costs (ACS B25070, B25091; % as 0-100).',
    geometry = 'Block group polygon reprojected to local_srid (3310) for indexed spatial joins.',
    local_envelope = 'Bounding box of the reprojected polygon, used to clip parcel geometries quickly.',
    bg_area = 'Area of the reprojected polygon in square metres, floored at 1e-10 for safe division.'
  ),
  audits (
    not_null(columns := (geoid)),
    unique_values(columns := (geoid,))
  ),
  blueprints @region_blueprints()
);

-- ACS Block Group Projected — pre-projected geometry for indexed spatial joins.
--
-- Reads ACS block group data from staging, transforms geometry to local_srid
-- (California Albers, 3310), and applies a GiST index on the projected geometry.
--
-- The staging model (brewgis.@{region}.acs_block_group) is executed on DuckDB,
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
    a.median_income,
    a.rent_burden_pct,
    a.pct_minority,
    a.pct_college_educated,
    a.cost_burden_pct,
    ST_Transform(a.geometry, @VAR('local_srid', 3310)) AS geometry,
    ST_Envelope(ST_Transform(a.geometry, @VAR('local_srid', 3310))) AS local_envelope,
    GREATEST(ST_Area(ST_Transform(a.geometry, @VAR('local_srid', 3310))), 1e-10) AS bg_area
FROM brewgis.@{region}.acs_block_group a
WHERE a.du > 0
  AND a.geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_acs_block_group_projected_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_acs_block_group_projected_geoid_')
  ON @this_model USING btree (geoid);
ANALYZE @this_model;
