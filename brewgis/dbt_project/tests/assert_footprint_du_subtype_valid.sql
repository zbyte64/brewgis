{#
    Assert that footprint-imputed property_type values are from the
    valid set of residential property types.

    Valid types: Single Family Residence, Condominium, Multiple Family Residence
    NULL is allowed (no imputation possible for some parcels).
#}

SELECT
    apn,
    imputed_property_type
FROM {{ ref('parcel_footprint_imputed') }}
WHERE imputed_property_type IS NOT NULL
  AND imputed_property_type NOT IN (
      'Single Family Residence',
      'Condominium',
      'Multiple Family Residence',
      'SFR',
      'Condo',
      'MF',
      'Comm',
      'Ind',
      'Vacant',
      'Other'
  )
