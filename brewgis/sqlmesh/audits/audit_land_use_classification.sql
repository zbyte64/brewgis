AUDIT (
  name audit_land_use_classification,
  dialect postgres
);
SELECT
  pk,
  land_development_category
FROM @this
WHERE land_development_category IS NOT NULL
  AND land_development_category NOT IN (
    'urban', 'suburban', 'rural',
    'agricultural', 'industrial',
    'undeveloped', 'conservation',
    'mixed_use', 'commercial', 'residential'
  )
