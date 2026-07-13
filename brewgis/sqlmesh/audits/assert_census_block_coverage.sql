AUDIT (
  name assert_census_block_coverage,
  dialect postgres
);

-- Assert that every parcel with du_estimated ≥ 0.5 has du > 0 after
-- the census block allocation in base_canvas_combined, UNLESS the
-- parcel's intersecting census blocks all have total_housing_units = 0.
--
-- The regressor-ratio-scaled allocation constrains DU to Census 2020
-- block total_housing_units. When a block has 0 housing units, the
-- formula produces du = 0, which is correct — not a mapping failure.
--
-- A parcel with du = 0 but du_estimated ≥ 0.5 AND intersecting at
-- least one block with total_housing_units > 0 means the ST_Intersects
-- join truly found no matching block — typically because census block
-- geometry was under-fetched, has invalid SRID metadata, or otherwise
-- failed ST_Transform.
--
-- Returns at most 10 violating parcels so logs stay readable while
-- still identifying the affected geographies.

SELECT
    c.parcel_id,
    c.du_estimated,
    c.du,
    'No intersecting census block — check census_2020_block_projected spatial extent and geometry validity' AS reason
FROM @this_model c
WHERE COALESCE(c.du_estimated, 0) >= 0.5
  AND COALESCE(c.du, 0) = 0
  AND EXISTS (
    SELECT 1
    FROM brewgis.staging.census_2020_block_projected cb
    WHERE ST_Intersects(c.geometry, cb.geometry)
      AND cb.total_housing_units > 0
  )
LIMIT 10
