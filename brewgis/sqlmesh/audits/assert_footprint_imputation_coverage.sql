AUDIT (
  name assert_footprint_imputation_coverage,
  dialect postgres
);
WITH stats AS (
  SELECT
    COUNT(*) AS total_with_footprints,
    COUNT(imputed_property_type) AS imputed_count,
    ROUND(
      100.0 * COUNT(imputed_property_type) / NULLIF(COUNT(*), 0),
      1
    ) AS coverage_pct
  FROM @this_model
)
SELECT
  total_with_footprints,
  imputed_count,
  coverage_pct
FROM stats
WHERE coverage_pct < 60
