MODEL (
  name brewgis.analysis.building_water_ghg,
  kind FULL,
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,))
  )
);

-- G2 — Buildings & Water GHG
--
-- Computes greenhouse gas emissions (CO2e) from building energy consumption
-- and water/wastewater treatment. Uses eGRID emission factors for electricity
-- and standard factors for natural gas.
--
-- Variables:
--   @ghg_egrid_co2_per_kwh: CO2e per kWh for electricity (default: 0.417 kg).
--   @ghg_gas_co2_per_kwh: CO2e per kWh for natural gas (default: 0.181 kg).
--   @ghg_water_supply_kwh_per_mg: kWh per million gallons for water supply (default: 1427).
--   @ghg_wastewater_kwh_per_mg: kWh per million gallons for wastewater (default: 1911).
--   @ghg_liters_per_million_gallons: Liters per million gallons (default: 3785411.8).

WITH energy_data AS (
    SELECT
        ed.parcel_id,
        ed.energy_electricity_res,
        ed.energy_gas_res,
        ed.energy_electricity_nonres,
        ed.energy_gas_nonres,
        wd.water_demand_total,
        es.population,
        es.geom,
        -- Energy CO2e (kg): electric kWh x eGRID factor + gas kWh x gas factor
        COALESCE(
            (ed.energy_electricity_res + ed.energy_electricity_nonres) * @ghg_egrid_co2_per_kwh
            + (ed.energy_gas_res + ed.energy_gas_nonres) * @ghg_gas_co2_per_kwh,
            0.0
        ) AS co2e_energy_kg,
        -- Water/wastewater CO2e (kg): L -> MG x (supply + wastewater kWh/MG) x eGRID factor
        CASE
            WHEN COALESCE(wd.water_demand_total, 0.0) > 0
            THEN wd.water_demand_total / @ghg_liters_per_million_gallons
                * (@ghg_water_supply_kwh_per_mg + @ghg_wastewater_kwh_per_mg)
                * @ghg_egrid_co2_per_kwh
            ELSE 0.0
        END AS co2e_water_kg
    FROM brewgis.analysis.energy_demand AS ed
    LEFT JOIN brewgis.analysis.water_demand AS wd
        ON ed.parcel_id = wd.parcel_id
    LEFT JOIN brewgis.analysis.core_end_state AS es
        ON ed.parcel_id = es.parcel_id
)

SELECT
    parcel_id,

    -- Building energy CO2e (kg)
    co2e_energy_kg AS co2e_energy_total_kg,

    -- Water/wastewater CO2e (kg)
    co2e_water_kg AS co2e_water_total_kg,

    -- Total CO2e
    co2e_energy_kg + co2e_water_kg AS co2e_total_kg,

    -- Per-capita CO2e
    CASE
        WHEN population > 0
        THEN (co2e_energy_kg + co2e_water_kg) / population
        ELSE 0.0
    END AS co2e_per_capita_kg,

    geom
FROM energy_data;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_building_water_ghg_geom
  ON brewgis.analysis.building_water_ghg USING GIST (geom);

  CREATE INDEX IF NOT EXISTS idx_building_water_ghg_parcel_id
  ON brewgis.analysis.building_water_ghg (parcel_id);
