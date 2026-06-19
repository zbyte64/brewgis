AUDIT (
  name assert_bft_sales_sfr_lot_boundary,
  dialect postgres
);
-- SFR + lot<0.15 → detsf_sl; ≥0.15 → detsf_ll
SELECT
  apn,
  property_type,
  sales_lot_size_acres,
  built_form_key,
  CASE
    WHEN COALESCE(sales_lot_size_acres, 0) < 0.15 THEN 'detsf_sl'
    ELSE 'detsf_ll'
  END AS expected_bft
FROM @this_model
WHERE (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
  AND (
    (COALESCE(sales_lot_size_acres, 0) < 0.15 AND built_form_key != 'detsf_sl')
    OR (COALESCE(sales_lot_size_acres, 0) >= 0.15 AND built_form_key != 'detsf_ll')
  );
