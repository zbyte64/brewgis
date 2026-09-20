AUDIT (
  name assert_acs_block_group_coverage,
  dialect postgres
);

-- Assert that every block group the region's ACS source provides — restricted to
-- block groups that TIGER/Line knows — is present in @this_model.
--
-- The model joins ACS rows to TIGER block groups at a single vintage (@bg_vintage).
-- An ACS release is published on one TIGER vintage, so a vintage that does not match
-- the release drops every block group whose geoid is absent from the older TIGER
-- release, silently shrinking the region's ACS coverage. The expectation below is
-- therefore derived from the raw source against TIGER at ANY vintage: a vintage
-- mismatch fails the audit instead of quietly removing block groups.
--
-- Measured 2026-09-20 (fresno, ACS 2022 joined to TIGER 2013): 174 of the source's
-- 637 block groups for county 019 were dropped, covering 52,382 canvas parcels,
-- which is what this audit exists to catch.
--
-- Returns at most 10 geographies so logs stay readable.

WITH source_block_groups AS (
  SELECT DISTINCT
    b.state || b.county || b.tract || b.block_group AS geoid
  FROM brewgis.@{region}.acs_bridge b
  JOIN brewgis.census.tiger_block_groups t
    ON t.geoid = b.state || b.county || b.tract || b.block_group
  WHERE b.year = @acs_year
    AND b.state = @state_fips
    AND b.county = ANY(STRING_TO_ARRAY(@county_fips, ','))
),
missing AS (
  SELECT s.geoid
  FROM source_block_groups s
  WHERE NOT EXISTS (
    SELECT 1
    FROM @this_model m
    WHERE m.geoid = s.geoid
  )
)
SELECT
  geoid,
  'ACS block group present in the source but missing from this model — check bg_vintage against acs_year' AS reason
FROM missing
LIMIT 10
