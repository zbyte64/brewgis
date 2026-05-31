{#
    Assert that parcel_footprint_imputed covers >60% of assessor parcels
    that have building footprints (footprint_ratio > 0).

    This verifies the three-tier KNN imputation successfully finds
    neighbors for the vast majority of parcels with footprint data.
#}

{% set min_coverage_pct = var('footprint_imputation_coverage_pct', 60) %}

WITH stats AS (
    SELECT
        COUNT(*) AS total_with_footprints,
        COUNT(imputed_property_type) AS imputed_count,
        ROUND(
            100.0 * COUNT(imputed_property_type) / NULLIF(COUNT(*), 0),
            1
        ) AS coverage_pct
    FROM {{ ref('parcel_footprint_imputed') }}
)

SELECT
    total_with_footprints,
    imputed_count,
    coverage_pct
FROM stats
WHERE coverage_pct < {{ min_coverage_pct }}
