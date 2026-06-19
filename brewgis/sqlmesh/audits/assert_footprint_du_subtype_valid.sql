AUDIT (
  name assert_footprint_du_subtype_valid,
  dialect postgres
);
SELECT
  apn,
  imputed_property_type
FROM @this_model
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
