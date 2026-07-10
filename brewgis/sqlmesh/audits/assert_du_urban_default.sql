AUDIT (
  name assert_du_urban_default,
  dialect postgres
);
-- urban/mixed + no assessor + no subtype → du=1
SELECT
  apn,
  land_development_category,
  built_form_key,
  assessor_units,
  du
FROM @this_model
WHERE land_development_category IN ('urban', 'mixed_use')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND built_form_key NOT IN ('bt__low_density_detached_residential','bt__medium_density_detached_residential','bt__medium_high_density_detached_residential','bt__very_low_density_detached_residential','bt__rural_residential','bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_attached_residential','bt__urban_mid_rise_residential','bt__mobile_home_park','bt__farm_home','bt__blank_place_type','bt__communityneighborhood_retail','bt__light_industrial','bt__publicquasi_public','bt__agriculture')
  AND (du IS NULL OR ABS(du - 1.0) > 0.01);
