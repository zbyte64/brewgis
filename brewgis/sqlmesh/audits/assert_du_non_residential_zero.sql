AUDIT (
  name assert_du_non_residential_zero,
  dialect postgres
);
-- commercial/industrial/civic/ag → du=0
SELECT
  apn,
  built_form_key,
  land_development_category,
  du
FROM @this_model
WHERE (built_form_key IN ('commercial', 'industrial', 'civic', 'agricultural')
    OR land_development_category IN ('industrial', 'agricultural', 'undeveloped'))
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND COALESCE(du, -1) != 0.0;
