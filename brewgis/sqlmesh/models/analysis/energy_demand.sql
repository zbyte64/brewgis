MODEL (
  name brewgis.analysis.energy_demand,
  kind FULL,
);

SELECT
    es.parcel_id,
    es.area_gross_acres,
    es.acres_developed,

    -- Residential electric (kWh/yr): dwelling units * avg_unit_area_m2 * EUI (kWh/m2/yr)
    -- Avg unit area = acres_developed * 43560 * FAR / dwelling_units
    COALESCE(
        es.du * es.electricity_eui * 0.092903
        * (es.acres_developed * 43560.0 * @res_far_default / NULLIF(es.du, 0)),
        0.0
    ) AS energy_electricity_res,

    -- Residential gas (kWh/yr)
    COALESCE(
        es.du * es.gas_eui * 0.092903
        * (es.acres_developed * 43560.0 * @res_far_default / NULLIF(es.du, 0)),
        0.0
    ) AS energy_gas_res,

    -- Non-residential electric (kWh/yr): building_sqft -> m2 * EUI
    COALESCE(es.building_sqft_total * 0.092903 * es.electricity_eui, 0.0) AS energy_electricity_nonres,

    -- Non-residential gas (kWh/yr)
    COALESCE(es.building_sqft_total * 0.092903 * es.gas_eui, 0.0) AS energy_gas_nonres,

    -- Total energy (kWh/yr)
    COALESCE(
        es.du * es.electricity_eui * 0.092903
        * (es.acres_developed * 43560.0 * @res_far_default / NULLIF(es.du, 0)),
        0.0
    )
    + COALESCE(
        es.du * es.gas_eui * 0.092903
        * (es.acres_developed * 43560.0 * @res_far_default / NULLIF(es.du, 0)),
        0.0
    )
    + COALESCE(es.building_sqft_total * 0.092903 * es.electricity_eui, 0.0)
    + COALESCE(es.building_sqft_total * 0.092903 * es.gas_eui, 0.0)
    AS energy_total,

    -- Energy intensity (kWh/sqft)
    CASE WHEN es.building_sqft_total > 0
        THEN (
            COALESCE(
                es.du * es.electricity_eui * 0.092903
                * (es.acres_developed * 43560.0 * @res_far_default / NULLIF(es.du, 0)),
                0.0
            )
            + COALESCE(
                es.du * es.gas_eui * 0.092903
                * (es.acres_developed * 43560.0 * @res_far_default / NULLIF(es.du, 0)),
                0.0
            )
            + COALESCE(es.building_sqft_total * 0.092903 * es.electricity_eui, 0.0)
            + COALESCE(es.building_sqft_total * 0.092903 * es.gas_eui, 0.0)
        ) / es.building_sqft_total
        ELSE 0.0
    END AS energy_intensity_kwh_per_sqft,

    es.du,
    es.building_sqft_total,
    es.pop,
    es.emp,
    es.geometry

FROM brewgis.analysis.core_end_state AS es;


-- ------------------------------------------------------------
-- Land Consumption (L1 + L2)
--   L1: Land use transition classification and acres consumed
--   L2: Impervious surface estimation (building, parking, ROW)
-- Source (dbt): brewgis/dbt_project/models/land_consumption.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_energy_demand_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_energy_demand_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
