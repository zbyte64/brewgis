AUDIT (
  name assert_bft_landuse_A1_to_detsf,
  dialect postgres
);
-- A1% landuse + intersection_density sigmoid > 0.5 → detsf_sl
-- A1% landuse + intersection_density sigmoid <= 0.5 → detsf_ll
-- Uses overture_intersection_density as the decision input.
-- COALESCE to 225.0 for parcels without computed intersection density.
SELECT
  t0.apn,
  ap.landuse,
  COALESCE(id.intersection_density, 225.0) AS intersection_density,
  t0.built_form_key,
  CASE
    WHEN 1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) > 0.5
        THEN 'detsf_sl'
    ELSE 'detsf_ll'
  END AS expected_bft
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
LEFT JOIN brewgis.assessor.overture_intersection_density id ON t0.apn = id.apn
WHERE ap.landuse LIKE 'A1%'
  AND (
    (1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) > 0.5
        AND t0.built_form_key != 'detsf_sl')
    OR
    (1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) <= 0.5
        AND t0.built_form_key != 'detsf_ll')
  );
