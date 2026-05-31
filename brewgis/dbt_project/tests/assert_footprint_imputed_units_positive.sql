{#
    Assert that imputed numeric fields are non-negative.

    Verifies that imputed_units >= 0, imputed_living_sqft >= 0,
    and imputed_building_sqft >= 0 for all imputed parcels.
#}

SELECT
    apn,
    imputed_units,
    imputed_living_sqft,
    imputed_building_sqft
FROM {{ ref('parcel_footprint_imputed') }}
WHERE imputed_property_type IS NOT NULL
  AND (
      imputed_units < 0
   OR imputed_living_sqft < 0
   OR imputed_building_sqft < 0
  )
