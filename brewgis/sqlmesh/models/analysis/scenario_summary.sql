MODEL (
  name brewgis.analysis.scenario_summary,
  kind FULL,
  audits (
    not_null(columns := (scenario_id,))
  )
);

-- Per-Scenario Summary View
--
-- Aggregates key metrics from all module outputs into a single summary
-- per blueprint variant.
--
-- Dependencies: core_end_state, vmt, transport_ghg, total_ghg, health_impacts,
--   housing_cost_burden, sprawl_index, water_demand, energy_demand,
--   land_consumption, displacement_risk, fiscal_net_impact

WITH
core_agg AS (
    SELECT
        COALESCE(SUM(population), 0) AS total_population,
        COALESCE(SUM(households), 0) AS total_households,
        COALESCE(SUM(dwelling_units_total), 0) AS total_dwelling_units_total,
        COALESCE(SUM(employment_total), 0) AS total_employment,
        COALESCE(SUM(population) FILTER (WHERE geom IS NOT NULL), 0) AS total_pop_for_co2e_per_capita
    FROM brewgis.analysis.core_end_state
),
vmt_agg AS (
    SELECT
        COALESCE(SUM(vmt_total), 0) AS total_vmt,
        COALESCE(AVG(vmt_per_capita) FILTER (WHERE population > 0), 0) AS avg_vmt_per_capita
    FROM brewgis.analysis.vmt
),
total_ghg_agg AS (
    SELECT COALESCE(SUM(co2e_total), 0) AS total_co2e FROM brewgis.analysis.total_ghg
),
water_demand_agg AS (
    SELECT COALESCE(SUM(water_demand_af), 0) AS total_water_demand FROM brewgis.analysis.water_demand
),
land_consumption_agg AS (
    SELECT
        COALESCE(SUM(acres_consumed), 0) AS total_land_consumed,
        COALESCE(AVG(impervious_pct) FILTER (WHERE gross_acres > 0), 0) AS avg_impervious_pct
    FROM brewgis.analysis.land_consumption
),
health_agg AS (
    SELECT COALESCE(SUM(net_dalys), 0) AS total_net_dalys FROM brewgis.analysis.health_impacts
),
energy_agg AS (
    SELECT COALESCE(SUM(electricity_mwh + gas_mwh), 0) AS total_energy_demand FROM brewgis.analysis.energy_demand
),
housing_agg AS (
    SELECT COALESCE(AVG(cost_burden_pct), 0) AS avg_cost_burden_pct FROM brewgis.analysis.housing_cost_burden
),
sprawl_agg AS (
    SELECT COALESCE(AVG(sprawl_index), 0) AS avg_sprawl_index FROM brewgis.analysis.sprawl_index
),
displacement_agg AS (
    SELECT
        CASE
            WHEN COUNT(*) > 0
            THEN COUNT(*) FILTER (WHERE displacement_risk_category IN ('at_risk', 'displacement_pressure')) * 100.0 / COUNT(*)
            ELSE 0.0
        END AS displacement_risk_pct
    FROM brewgis.analysis.displacement_risk
),
metrics AS (
    SELECT *
    FROM core_agg
    CROSS JOIN vmt_agg
    CROSS JOIN total_ghg_agg
    CROSS JOIN water_demand_agg
    CROSS JOIN land_consumption_agg
    CROSS JOIN health_agg
    CROSS JOIN energy_agg
    CROSS JOIN housing_agg
    CROSS JOIN sprawl_agg
    CROSS JOIN displacement_agg
)
SELECT
    'blueprint'::text AS scenario_id,
    total_population,
    total_households,
    total_dwelling_units_total AS dwelling_units_total,
    total_employment,
    total_vmt AS vmt_total,
    ROUND((total_vmt / NULLIF(total_population, 0))::numeric, 2) AS vmt_per_capita,
    total_co2e AS co2e_total_kg,
    ROUND((total_co2e / NULLIF(total_pop_for_co2e_per_capita, 0))::numeric, 2) AS co2e_per_capita_kg,
    ROUND(avg_cost_burden_pct::numeric, 1) AS cost_burdened_hh_pct,
    avg_sprawl_index,
    total_water_demand AS water_demand_total_af,
    total_energy_demand AS energy_demand_total_mwh,
    total_land_consumed AS land_consumed_acres,
    ROUND(avg_impervious_pct::numeric, 1) AS land_consumed_pct,
    total_net_dalys AS net_dalys,
    ROUND(displacement_risk_pct::numeric, 1) AS displacement_risk_pct
FROM metrics
