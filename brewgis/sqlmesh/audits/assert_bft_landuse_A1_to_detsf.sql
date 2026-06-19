AUDIT (
  name assert_bft_landuse_A1_to_detsf,
  dialect postgres
);
-- A1% landuse + lot<0.15 → detsf_sl; A1% landuse + lot≥0.15 → detsf_ll
SELECT
  apn,
  landuse,
  lot_size_acres,
  built_form_key,
  CASE
    WHEN lot_size_acres < 0.15 THEN 'detsf_sl'
    ELSE 'detsf_ll'
  END AS expected_bft
FROM @this_model
WHERE landuse LIKE 'A1%'
  AND (
    (lot_size_acres < 0.15 AND built_form_key != 'detsf_sl')
    OR (lot_size_acres >= 0.15 AND built_form_key != 'detsf_ll')
  );
