{#
    Assert that du_subtype is classified correctly for both short-code
    and long-name property types, including the fix for Bug #4.

    Test parcel selection from parcel_dasymetric_weights:
      APN001  SFR             0.25 acres  1 unit   → detsf_ll
      APN010  Single Family Residence  0.18 acres  1 unit   → detsf_ll
      APN011  Single Family Residence  0.30 acres  1 unit   → detsf_ll
      APN007  Condo           0.18 acres  1 unit   → attsf
      APN012  Condominium     0.20 acres  1 unit   → attsf
      APN013  Multiple Family Residence  0.50 acres  3 units  → mf2to4
      APN014  Multiple Family Residence  1.00 acres  12 units → mf5p
      APN003  Comm            0.50 acres  0 units  → NULL (non-residential)
      APN004  Ind             5.00 acres  0 units  → NULL (non-residential)
#}

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
    pdw.du_subtype AS actual_du_subtype
FROM expected e
LEFT JOIN {{ ref('parcel_dasymetric_weights') }} pdw
    ON e.parcel_id = pdw.apn
WHERE
    pdw.du_subtype IS DISTINCT FROM e.expected_du_subtype
