{#
    Assert that parcel_dasymetric_weights carries footprint_imputed_*
    columns for parcels with Overture building footprints but no sales data.

    Every parcel with building footprints should have either actual_living_sqft
    (from assessor sales) OR footprint_imputed_living_sqft (from Overture k-NN).

    Verifies three things:
      1. Parcels WITH actual_sqft AND footprints: OK regardless of footprint_imputed
      2. Parcels WITHOUT actual_sqft but WITH footprints: must have footprint_imputed
      3. Non-null living area exists on every parcel with building footprints
         (either actual or imputed — some coverage is better than no data)
#}

-- Failure mode 1: parcel has building footprints but neither actual nor imputed sqft
WITH footprint_parcels AS (
    SELECT apn
    FROM {{ ref('parcel_building_footprints') }}
    WHERE footprint_ratio > 0
),

no_sqft AS (
    SELECT
        dw.apn,
        dw.actual_living_sqft,
        dw.footprint_imputed_living_sqft,
        'missing living sqft on parcel with building footprints' AS failure_reason
    FROM {{ ref('parcel_dasymetric_weights') }} dw
    JOIN footprint_parcels fp ON dw.apn = fp.apn
    WHERE dw.actual_living_sqft IS NULL
      AND dw.footprint_imputed_living_sqft IS NULL
)

SELECT apn, failure_reason, actual_living_sqft, footprint_imputed_living_sqft
FROM no_sqft
