MODEL (
  name brewgis.analysis.agriculture,
  kind FULL,
);

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
            THEN es.parcel_acres_agriculture * @crop_yield_per_acre
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_yield_per_acre
        ELSE 0.0
    END AS crop_yield_tons,
    -- Market value
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * @crop_yield_per_acre * @crop_market_price_per_ton
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_yield_per_acre * @crop_market_price_per_ton
        ELSE 0.0
    END AS market_value,
    -- Production cost
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * @crop_production_cost_per_acre
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_production_cost_per_acre
        ELSE 0.0
    END AS production_cost,
    -- Net return = market_value - production_cost
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * @crop_yield_per_acre * @crop_market_price_per_ton
                 - es.parcel_acres_agriculture * @crop_production_cost_per_acre
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_yield_per_acre * @crop_market_price_per_ton
                 - es.acres_developed * @crop_production_cost_per_acre
        ELSE 0.0
    END AS net_return,
    -- Water consumption (acre-feet)
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * @crop_water_per_acre_af
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_water_per_acre_af
        ELSE 0.0
    END AS water_consumption_af,
    -- Labor hours
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * @crop_labor_hours_per_acre
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_labor_hours_per_acre
        ELSE 0.0
    END AS labor_hours,
    -- Truck trips
    CASE
        WHEN es.parcel_acres_agriculture > 0
            THEN es.parcel_acres_agriculture * @crop_truck_trips_per_acre
        WHEN es.land_dev_category = 'rural' AND es.acres_developed > 0
            THEN es.acres_developed * @crop_truck_trips_per_acre
        ELSE 0.0
    END AS truck_trips,
    es.geom
FROM brewgis.analysis.core_end_state AS es
WHERE
    es.parcel_acres_agriculture > 0
    OR (es.land_dev_category = 'rural' AND es.acres_developed > 0);


-- ------------------------------------------------------------
-- Stormwater Runoff (S1)
--   Estimates stormwater runoff volume changes from land use
--   change and impervious surface increase using the Simple
--   Method (Schueler, 1987).
-- Source (dbt): brewgis/dbt_project/models/stormwater_runoff.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_agriculture_geom
  ON @this_model USING GIST (geom);
  CREATE INDEX IF NOT EXISTS idx_agriculture_parcel_id
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
