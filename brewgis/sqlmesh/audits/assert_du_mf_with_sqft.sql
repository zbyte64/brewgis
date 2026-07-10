AUDIT (
  name assert_du_mf_with_sqft,
  dialect postgres
);
-- mf2to4/mf5p/attsf + res_sqft>0 → du ≥ min, du ≈ res_sqft/region_avg
SELECT
  apn,
  built_form_key,
  residential_building_sqft,
  region_avg_sqft_per_unit,
  min_du,
  du,
  ROUND(residential_building_sqft / NULLIF(region_avg_sqft_per_unit, 0)) AS estimated_from_sqft
FROM @this_model
WHERE built_form_key IN ('bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_attached_residential','bt__urban_mid_rise_residential')
  AND COALESCE(residential_building_sqft, 0) > 0
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND du IS NOT NULL
  AND du < (
    CASE
      WHEN built_form_key = 'bt__medium_density_attached_residential' THEN 2.0
      ELSE 5.0
    END
  );
