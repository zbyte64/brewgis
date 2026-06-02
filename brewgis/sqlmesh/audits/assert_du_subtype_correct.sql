AUDIT (
  name assert_du_subtype_correct,
  dialect postgres
);
WITH expected AS (
  SELECT 'APN001' AS parcel_id, 'detsf_ll' AS expected_du_subtype
  UNION ALL
  SELECT 'APN010', 'detsf_ll'
  UNION ALL
  SELECT 'APN011', 'detsf_ll'
  UNION ALL
  SELECT 'APN007', 'attsf'
  UNION ALL
  SELECT 'APN012', 'attsf'
  UNION ALL
  SELECT 'APN013', 'mf2to4'
  UNION ALL
  SELECT 'APN014', 'mf5p'
  UNION ALL
  SELECT 'APN003', NULL
  UNION ALL
  SELECT 'APN004', NULL
)
SELECT
  e.parcel_id,
  e.expected_du_subtype,
  m.du_subtype AS actual_du_subtype
FROM expected e
LEFT JOIN @this m ON e.parcel_id = m.apn
WHERE m.du_subtype IS DISTINCT FROM e.expected_du_subtype
