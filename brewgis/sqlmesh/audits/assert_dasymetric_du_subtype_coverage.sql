AUDIT (
  name assert_dasymetric_du_subtype_coverage,
  dialect postgres
);
WITH stats AS (
  SELECT
    COUNT(*) AS total_parcels,
    COUNT(du_subtype) AS classified_parcels,
    ROUND(
      100.0 * COUNT(du_subtype) / NULLIF(COUNT(*), 0),
      1
    ) AS coverage_pct
  FROM @this_model
)
SELECT
  total_parcels,
  classified_parcels,
  coverage_pct
FROM stats
WHERE coverage_pct < 30
