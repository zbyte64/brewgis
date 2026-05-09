{#
    Agriculture Model — Crop yield, value, and resource use

    Computes agricultural output for parcels with agricultural land use.
    Identifies agricultural parcels by land_dev_category = 'rural' (parcels
    without sufficient density to qualify as urban/compact/standard).

    Config vars:
        crop_yield_per_acre: Crop yield in tons per acre (default: 8.0).
        crop_market_price_per_ton: Market price per ton (default: 200).
        crop_production_cost_per_acre: Production cost per acre (default: 800).
        crop_water_per_acre_af: Water consumption acre-feet/acre (default: 3.0).
        crop_labor_hours_per_acre: Labor hours per acre (default: 15).
        crop_truck_trips_per_acre: Truck trips per acre (default: 2).

    Source table: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}

    Output columns:
        parcel_id, crop_type, acres_cultivated,
        crop_yield_tons, market_value, production_cost, net_return,
        water_consumption_af, labor_hours, truck_trips, geom

    Materialized as: {{ var('target_schema') }}.agriculture_{{ var('scenario_id') }}
#}
{%- set scenario_id = var('scenario_id') -%}
{{ config(alias='agriculture_' ~ scenario_id) }}

{%- set crop_yield = var('crop_yield_per_acre', 8.0) -%}
{%- set crop_price = var('crop_market_price_per_ton', 200) -%}
{%- set prod_cost = var('crop_production_cost_per_acre', 800) -%}
{%- set water_af = var('crop_water_per_acre_af', 3.0) -%}
{%- set labor_hrs = var('crop_labor_hours_per_acre', 15) -%}
{%- set truck_trips = var('crop_truck_trips_per_acre', 2) -%}

SELECT
    es.parcel_id,
    -- Crop type: inferred from available data; default to "general_agriculture"
    'general_agriculture' AS crop_type,
    -- Acres cultivated: use parcel_acres_agriculture, or acres_developed as proxy for rural parcels
    CASE
        WHEN es.parcel_acres_agriculture > 0 THEN es.parcel_acres_agriculture
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed
        ELSE 0.0
    END AS acres_cultivated,
    -- Crop yield (tons)
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ crop_yield }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ crop_yield }}
        ELSE 0.0
    END AS crop_yield_tons,
    -- Market value
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ crop_yield }} * {{ crop_price }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ crop_yield }} * {{ crop_price }}
        ELSE 0.0
    END AS market_value,
    -- Production cost
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ prod_cost }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ prod_cost }}
        ELSE 0.0
    END AS production_cost,
    -- Net return = market_value - production_cost
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ crop_yield }} * {{ crop_price }}
                 - es.parcel_acres_agriculture * {{ prod_cost }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ crop_yield }} * {{ crop_price }}
                 - es.acres_developed * {{ prod_cost }}
        ELSE 0.0
    END AS net_return,
    -- Water consumption (acre-feet)
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ water_af }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ water_af }}
        ELSE 0.0
    END AS water_consumption_af,
    -- Labor hours
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ labor_hrs }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ labor_hrs }}
        ELSE 0.0
    END AS labor_hours,
    -- Truck trips
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * {{ truck_trips }}
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * {{ truck_trips }}
        ELSE 0.0
    END AS truck_trips,
    es.geom
FROM {{ ref('core_end_state') }} AS es
WHERE
    es.parcel_acres_agriculture > 0
    OR (es.land_dev_category = 'rural' AND es.acres_developed > 0)
