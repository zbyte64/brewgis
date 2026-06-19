AUDIT (
  name assert_bft_tier4_area_heuristic,
  dialect postgres
);
-- lot>10ac → ag; 3-10ac+zone%A% → ag
SELECT
  apn,
  lot_size_acres,
  zone,
  built_form_key,
  CASE
    WHEN lot_size_acres > 10.0 THEN 'agricultural'
    WHEN lot_size_acres > 3.0 AND zone LIKE '%A%' THEN 'agricultural'
    WHEN lot_size_acres > 3.0 AND zone NOT LIKE '%A%' THEN 'detsf_ll'
    WHEN lot_size_acres > 0.4 THEN 'detsf_ll'
    WHEN lot_size_acres > 0.15 THEN 'detsf_sl'
  END AS expected_bft
FROM @this_model
WHERE lot_size_acres IS NOT NULL
  AND built_form_key IS NOT NULL
  AND (
    (lot_size_acres > 10.0 AND built_form_key != 'agricultural')
    OR (lot_size_acres > 3.0 AND zone LIKE '%A%' AND built_form_key != 'agricultural')
  );
