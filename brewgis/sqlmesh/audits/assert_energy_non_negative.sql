AUDIT (
  name assert_energy_non_negative,
  dialect postgres
);
SELECT
  parcel_id,
  energy_electricity_res,
  energy_gas_res,
  energy_electricity_nonres,
  energy_gas_nonres,
  energy_total,
  energy_intensity_kwh_per_sqft
FROM @this_model
WHERE
  COALESCE(energy_electricity_res, 0) < 0
  OR COALESCE(energy_gas_res, 0) < 0
  OR COALESCE(energy_electricity_nonres, 0) < 0
  OR COALESCE(energy_gas_nonres, 0) < 0
  OR COALESCE(energy_total, 0) < 0
  OR COALESCE(energy_intensity_kwh_per_sqft, 0) < 0
