AUDIT (
  name assert_pdb_block_group_coverage,
  dialect postgres
);

-- Assert that every block group the region's PDB source provides — restricted to
-- block groups that TIGER/Line knows — is present in @this_model.
--
-- The model joins PDB rows to TIGER block groups at a single vintage (@bg_vintage).
-- PDB's current release is ACS 2018-2022, i.e. 2020 block-group geography, so a
-- vintage that does not carry those geographies drops every block group the older
-- release does not have. The expectation below is derived from the raw source
-- against TIGER at ANY vintage, so a vintage mismatch fails the audit instead of
-- quietly removing block groups.
--
-- Measured 2026-09-20 (fresno, PDB joined to TIGER 2013): 174 of the source's 637
-- block groups for county 019 were dropped, covering 52,382 canvas parcels, which
-- is what this audit exists to catch.
--
-- Returns at most 10 geographies so logs stay readable.

WITH source_block_groups AS (
  SELECT DISTINCT p.gidbg AS geoid
  FROM brewgis.@{region}.pdb_bridge p
  JOIN brewgis.census.tiger_block_groups t
    ON t.geoid = p.gidbg
  WHERE p.state = @state_fips
    AND p.county = ANY(STRING_TO_ARRAY(@county_fips, ','))
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
  'PDB block group present in the source but missing from this model — check bg_vintage' AS reason
FROM missing
LIMIT 10
