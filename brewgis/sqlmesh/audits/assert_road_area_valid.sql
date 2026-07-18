AUDIT (
  name assert_road_area_valid,
  dialect postgres
);

-- Assert that at least 0.1% of parcels have non-zero road total area.
-- Zero across the board means the ST_Intersects spatial join silently
-- failed (e.g. DuckDB bridge produced Infinity/NaN local_geometry).
--
-- 0.1% threshold: with 239k road segments in Sacramento County most
-- parcels should intersect at least one road. Zero hits means the
-- geometry pipeline is broken.

WITH stats AS (
    SELECT
        COUNT(*) AS total_parcels,
        COUNT(CASE WHEN road_total_area > 0 THEN 1 END) AS nonzero_parcels,
        ROUND(
            100.0 * COUNT(CASE WHEN road_total_area > 0 THEN 1 END)
            / NULLIF(COUNT(*), 0),
            4
        ) AS nonzero_pct
    FROM @this_model
)
SELECT
    total_parcels,
    nonzero_parcels,
    nonzero_pct
FROM stats
WHERE nonzero_pct < 0.1;
