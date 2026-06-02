MODEL (
  name brewgis.analysis.water_demand,
  kind FULL,
);

SELECT
    es.parcel_id,
    es.gross_acres,
    es.acres_developed,

    -- Residential indoor (L/yr): households * household_size * indoor_water_rate * 365
    es.households * es.household_size * es.indoor_water_rate * 365.0 AS water_demand_res_indoor,

    -- Residential outdoor (L/yr): irrigated sqft -> m2 * outdoor_water_rate (L/m2/yr)
    es.res_irrigated_sqft * 0.092903 * es.outdoor_water_rate AS water_demand_res_outdoor,

    -- Non-residential indoor (L/yr): employment * default_rate * 365
    es.employment_total * @nonres_indoor_water_rate * 365.0 AS water_demand_nonres_indoor,

    -- Non-residential outdoor (L/yr): irrigated sqft -> m2 * outdoor_water_rate
    es.com_irrigated_sqft * 0.092903 * es.outdoor_water_rate AS water_demand_nonres_outdoor,

    -- Total water demand (L/yr)
    (es.households * es.household_size * es.indoor_water_rate * 365.0)
      + (es.res_irrigated_sqft * 0.092903 * es.outdoor_water_rate)
      + (es.employment_total * @nonres_indoor_water_rate * 365.0)
      + (es.com_irrigated_sqft * 0.092903 * es.outdoor_water_rate)
    AS water_demand_total,

    -- Per-unit water demand (L/person+job/yr)
    CASE WHEN (es.population + es.employment_total) > 0
        THEN ((es.households * es.household_size * es.indoor_water_rate * 365.0)
              + (es.res_irrigated_sqft * 0.092903 * es.outdoor_water_rate)
              + (es.employment_total * @nonres_indoor_water_rate * 365.0)
              + (es.com_irrigated_sqft * 0.092903 * es.outdoor_water_rate))
             / (es.population + es.employment_total)
        ELSE 0.0
    END AS water_demand_per_unit,

    es.population,
    es.employment_total,
    es.dwelling_units_total,
    es.geom

FROM brewgis.analysis.core_end_state AS es;


-- ------------------------------------------------------------
-- Energy Demand
--   Residential and non-residential energy demand (kWh/year)
--   per parcel, using end-state allocation and BuildingType
--   energy use intensities (EUI).
-- Source (dbt): brewgis/dbt_project/models/energy_demand.sql
-- ------------------------------------------------------------
