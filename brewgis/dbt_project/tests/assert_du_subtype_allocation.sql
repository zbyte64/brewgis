{#
    Assert that DU sub-type hard-filter allocation is working correctly.

    When du_subtype is set on a parcel (from assessor data), only the
    matching ACS sub-type total should be allocated — other sub-types
    should be 0 (or very close to 0 due to floating point).

    Test cases (from parcel_dasymetric_weights + base_canvas_demographics):
      - Parcels with du_subtype = 'attsf' → du_detsf_sl = 0, du_detsf_ll = 0
      - Parcels with du_subtype = 'mf2to4' → du_mf5p = 0
      - Parcels with du_subtype = 'detsf_sl' → du_attsf = 0, du_mf2to4 = 0
#}

WITH subtype_violations AS (
    SELECT
        parcel_id,
        du_subtype,
        du_detsf_sl,
        du_detsf_ll,
        du_attsf,
        du_mf2to4,
        du_mf5p
    FROM {{ ref('base_canvas_demographics') }}
    WHERE
        du_subtype IS NOT NULL
        AND (
            (du_subtype = 'attsf' AND (du_detsf_sl > 0.01 OR du_detsf_ll > 0.01))
            OR (du_subtype = 'mf2to4' AND du_mf5p > 0.01)
            OR (du_subtype = 'detsf_sl' AND (du_attsf > 0.01 OR du_mf2to4 > 0.01))
            OR (du_subtype = 'detsf_ll' AND (du_attsf > 0.01 OR du_mf2to4 > 0.01))
            OR (du_subtype = 'mf5p' AND du_mf2to4 > 0.01)
        )
)

SELECT * FROM subtype_violations
