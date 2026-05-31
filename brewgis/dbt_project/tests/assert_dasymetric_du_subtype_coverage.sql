{#
    Assert that parcel_dasymetric_weights.du_subtype is non-NULL for
    at least 30% of parcels, verifying the footprint-imputed fallback
    meaningfully improves coverage over the assessor-only baseline (~5.7%).

    The 30% threshold is conservative — the upstream pipeline should
    produce >60% with footprint data, but test seed data may be smaller.
#}

{% set min_coverage_pct = var('dasymetric_du_subtype_coverage_pct', 30) %}

WITH stats AS (
    SELECT
        COUNT(*) AS total_parcels,
        COUNT(du_subtype) AS classified_parcels,
        ROUND(
            100.0 * COUNT(du_subtype) / NULLIF(COUNT(*), 0),
            1
        ) AS coverage_pct
    FROM {{ ref('parcel_dasymetric_weights') }}
)

SELECT
    total_parcels,
    classified_parcels,
    coverage_pct
FROM stats
WHERE coverage_pct < {{ min_coverage_pct }}
