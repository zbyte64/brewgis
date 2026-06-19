AUDIT (
  name assert_du_urban_default,
  dialect postgres
);
-- urban/mixed + no assessor + no subtype → du=1
SELECT
  apn,
  land_development_category,
  built_form_key,
  assessor_units,
  du
FROM @this_model
WHERE land_development_category IN ('urban', 'mixed_use')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND built_form_key NOT IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p', 'commercial', 'industrial', 'civic', 'agricultural')
  AND (du IS NULL OR ABS(du - 1.0) > 0.01);
