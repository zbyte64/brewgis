{#
    Assert that all energy columns are non-negative.

    Energy demand values represent consumption in kWh/year and must never
    be negative. Returns any rows where any energy column is < 0.
#}

SELECT
    parcel_id,
    energy_electricity_res,
    energy_gas_res,
    energy_electricity_nonres,
    energy_gas_nonres,
    energy_total,
    energy_intensity_kwh_per_sqft
FROM {{ ref('energy_demand') }}
WHERE
    energy_electricity_res < 0
    OR energy_gas_res < 0
    OR energy_electricity_nonres < 0
    OR energy_gas_nonres < 0
    OR energy_total < 0
    OR energy_intensity_kwh_per_sqft < 0
