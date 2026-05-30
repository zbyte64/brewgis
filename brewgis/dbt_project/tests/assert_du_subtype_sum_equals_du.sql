{#
    Assert that DU sub-type columns sum to total dwelling units within tolerance.

    For each parcel, du_detsf_sl + du_detsf_ll + du_attsf + du_mf2to4 + du_mf5p
    should equal du (within floating-point tolerance of 0.5).

    This validates the imputation and hard-filter allocation produce
    internally consistent totals.

    Runs against base_canvas_imputed (final imputation step).
#}

WITH du_subtype_sum AS (
    SELECT
        parcel_id,
        du,
        du_detsf_sl,
        du_detsf_ll,
        du_attsf,
        du_mf2to4,
        du_mf5p,
        COALESCE(du_detsf_sl, 0) + COALESCE(du_detsf_ll, 0)
            + COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0)
            + COALESCE(du_mf5p, 0) AS sub_type_sum
    FROM {{ ref('base_canvas_imputed') }}
    WHERE du IS NOT NULL AND du > 0
)

SELECT
    parcel_id,
    du,
    sub_type_sum,
    sub_type_sum - du AS delta
FROM du_subtype_sum
WHERE ABS(sub_type_sum - du) > 0.5
