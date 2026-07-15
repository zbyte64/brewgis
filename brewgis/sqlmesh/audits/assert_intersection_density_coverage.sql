AUDIT (
  name assert_intersection_density_coverage,
  dialect postgres
);

-- Assert that at least 10% of parcels have non-zero intersection density.
-- Zero across the board means either overture_intersection_points is empty
-- (transport data missing) or the ST_DWithin spatial join is failing.

WITH stats AS (
    SELECT
        COUNT(*) AS total_parcels,
        COUNT(CASE WHEN intersection_density > 0 THEN 1 END) AS nonzero_parcels,
        ROUND(
            100.0 * COUNT(CASE WHEN intersection_density > 0 THEN 1 END)
            / NULLIF(COUNT(*), 0),
            1
        ) AS nonzero_pct
    FROM @this_model
)
SELECT
    total_parcels,
    nonzero_parcels,
    nonzero_pct
FROM stats
WHERE nonzero_pct < 10.0;
