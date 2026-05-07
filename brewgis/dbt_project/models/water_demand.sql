{#
    Water Demand Model — Scenario Builder

    Computes residential and non-residential water demand (liters/year)
    for each parcel, using end-state allocation and BuildingType coefficients.

    Inputs (via dbt vars):
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        nonres_indoor_water_rate: Default non-residential indoor rate (L/employee/day, default: 50).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, gross_acres, acres_developed,
        water_demand_res_indoor, water_demand_res_outdoor,
        water_demand_nonres_indoor, water_demand_nonres_outdoor,
        water_demand_total, water_demand_per_unit,
        population, employment_total, dwelling_units_total,
        geom

    Materialized as: {{ var('target_schema') }}.water_demand_{{ var('scenario_id') }}
#}

SELECT
    es.parcel_id,
    es.gross_acres,
    es.acres_developed,

    -- Residential indoor (L/yr): households * household_size * indoor_water_rate * 365
    es.households * es.household_size * es.indoor_water_rate * 365.0 AS water_demand_res_indoor,

    -- Residential outdoor (L/yr): irrigated sqft -> m2 * outdoor_water_rate (L/m2/yr)
    es.res_irrigated_sqft * 0.092903 * es.outdoor_water_rate AS water_demand_res_outdoor,

    -- Non-residential indoor (L/yr): employment * default_rate * 365
    es.employment_total * {{ var('nonres_indoor_water_rate', 50) }} * 365.0 AS water_demand_nonres_indoor,

    -- Non-residential outdoor (L/yr): irrigated sqft -> m2 * outdoor_water_rate
    es.com_irrigated_sqft * 0.092903 * es.outdoor_water_rate AS water_demand_nonres_outdoor,

    -- Total water demand (L/yr)
    (es.households * es.household_size * es.indoor_water_rate * 365.0)
      + (es.res_irrigated_sqft * 0.092903 * es.outdoor_water_rate)
      + (es.employment_total * {{ var('nonres_indoor_water_rate', 50) }} * 365.0)
      + (es.com_irrigated_sqft * 0.092903 * es.outdoor_water_rate)
    AS water_demand_total,

    -- Per-unit water demand (L/person+job/yr)
    CASE WHEN (es.population + es.employment_total) > 0
        THEN ((es.households * es.household_size * es.indoor_water_rate * 365.0)
              + (es.res_irrigated_sqft * 0.092903 * es.outdoor_water_rate)
              + (es.employment_total * {{ var('nonres_indoor_water_rate', 50) }} * 365.0)
              + (es.com_irrigated_sqft * 0.092903 * es.outdoor_water_rate))
             / (es.population + es.employment_total)
        ELSE 0.0
    END AS water_demand_per_unit,

    es.population,
    es.employment_total,
    es.dwelling_units_total,
    es.geom

FROM {{ var('target_schema') }}.end_state_{{ var('scenario_id') }} AS es
