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
  AND COALESCE(built_form_key, '') NOT IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND COALESCE(du, -1) != 0.0
  -- Exclude parcels that match Tier 5 (urban/mixed_use default → du=1)
  -- Tier 5 fires before Tier 6 in the COALESCE priority, giving du=1 for
  -- non-residential bft in urban/mixed_use LDC when no assessor units exist.
  AND NOT (land_development_category IN ('urban', 'mixed_use')
           AND COALESCE(built_form_key, '') NOT IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p'));
