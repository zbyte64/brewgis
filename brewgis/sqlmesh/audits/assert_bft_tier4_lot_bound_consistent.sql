AUDIT (
  name assert_bft_tier4_lot_bound_consistent,
  dialect postgres
);
-- Tier4 produces bt__medium_density_detached_residential / bt__low_density_detached_residential
-- for parcels that fall through all higher tiers (tier0 through tier3). This audit
-- checks that tier4's medium/low density decisions are consistent with the
-- intersection-density sigmoid used by tier0.
--
-- When tier0 uses sigmoid(intersection_density) and tier4 uses a lot-size
-- heuristic, they may diverge. Any row returned here is a violation — tier4
-- should agree with the sigmoid for parcels where tier0 would have classified.
SELECT
  t4.apn,
  t4.built_form_key,
  COALESCE(id.intersection_density, 225.0) AS intersection_density,
  CASE
    WHEN 1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) > 0.5
        THEN 'bt__medium_density_detached_residential'
    ELSE 'bt__low_density_detached_residential'
  END AS tier0_classification
FROM @this_model t4
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t4.apn = ap.apn
LEFT JOIN brewgis.assessor.overture_intersection_density id ON t4.apn = id.apn
WHERE t4.built_form_key IN ('bt__medium_density_detached_residential', 'bt__low_density_detached_residential')
  AND (
    (t4.built_form_key = 'bt__medium_density_detached_residential'
        AND 1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) <= 0.5)
    OR
    (t4.built_form_key = 'bt__low_density_detached_residential'
        AND 1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) > 0.5)
  );
