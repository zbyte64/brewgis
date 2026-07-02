AUDIT (
  name assert_bft_tier_priority,
  dialect postgres
);
-- Commerce/industry classification should only come from tier1 (sales).
-- If built_form_key_source is NOT tier1, the sales data was available but
-- gave a non-commercial/non-industrial result, meaning the COALESCE priority
-- is correct (tier1 wins). This smoke test verifies that tier1 overrides
-- tier0-4 for parcels that WOULD otherwise get commercial/industrial from
-- a lower tier (e.g., A3 landuse + retail sales → attsf from tier1, not
-- attsf from tier0 — tier1 wins regardless).
--
-- The COALESCE already guarantees tier1 overrides all others, so this audit
-- simply checks that known commercial/industrial codes from non-tier1
-- sources are correctly overridden.
SELECT
  r.apn,
  r.built_form_key,
  r.built_form_key_source,
  'Expected tier1 override for commercial/industrial built_form_key' AS violation
FROM @this_model r
WHERE r.built_form_key IN ('commercial', 'industrial')
  AND r.built_form_key_source != 'tier1'
  AND EXISTS (
      SELECT 1 FROM brewgis.assessor.parcel_bft_tier1_sales t1
      WHERE t1.apn = r.apn
  );
