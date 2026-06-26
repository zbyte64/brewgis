AUDIT (
  name assert_census_block_coverage,
  dialect postgres
);

-- Assert that every parcel with du_estimated > 0 has du > 0 after
-- the census block intersection join in base_canvas_demographics.
--
-- A parcel with du = 0 but du_estimated > 0 means the ST_Intersects
-- join to census_2020_block_projected found no matching block —
-- typically because census block geometry was under-fetched, has
-- invalid SRID metadata, or otherwise failed ST_Transform.
--
-- Returns at most 10 violating parcels (the full list may be
-- thousands) so logs stay readable while still identifying the
-- affected geographies.

SELECT
    parcel_id,
    du_estimated,
    du,
    'No intersecting census block — check census_2020_block_projected spatial extent and geometry validity' AS reason
FROM @this_model
WHERE COALESCE(du_estimated, 0) > 0
  AND COALESCE(du, 0) = 0
LIMIT 10
