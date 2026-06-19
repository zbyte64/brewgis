AUDIT (
  name assert_bft_tier_priority,
  dialect postgres
);
-- Tier1 (sales) > Tier0 (landuse) > Tier2 (Overture) > Tier3/Tier4
-- Parcels with sales records that classify should NEVER be overridden by landuse classification
SELECT
  apn,
  built_form_key,
  property_type,
  landuse,
  'Tier1 sales should take priority over landuse' AS violation
FROM @this_model
WHERE property_type IN ('SFR', 'Single Family Residence', 'Condo', 'Condominium',
    'MF', 'Multiple Family Residence', 'Commercial', 'Industrial',
    'Retail', 'Office', 'Restaurant', 'Hotel', 'Medical')
  AND built_form_key IS NOT NULL
  AND landuse IS NOT NULL
  AND (
    -- If landuse says A1 (residential) but sales says Industrial, built_form_key should be industrial
    (property_type IN ('Industrial', 'Manufacturing', 'Warehouse') AND built_form_key != 'industrial')
    OR (property_type IN ('Commercial', 'Retail', 'Office') AND built_form_key != 'commercial')
  );
