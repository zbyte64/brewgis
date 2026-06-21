AUDIT (
  name assert_bft_tier3b_footprint_filter,
  dialect postgres
);
-- lot>3ac + footprint_ratio<0.02 → agricultural (Tier 3b)
SELECT
  apn,
  lot_size_acres,
  footprint_ratio,
  built_form_key
FROM @this_model
WHERE built_form_key_source NOT IN ('tier1', 'tier0', 'tier2', 'tier3')
  AND lot_size_acres > 3.0
  AND COALESCE(footprint_ratio, 0) < 0.02
  AND COALESCE(built_form_key, '') != 'agricultural'
  AND COALESCE(built_form_key, '') != '';
