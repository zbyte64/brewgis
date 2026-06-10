MODEL (
  name brewgis.analysis.core_end_state,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    number_of_rows(threshold := 1)
  )
);

-- Core EndState Model — Scenario Builder
--
-- Computes the end-state allocation for each parcel with a built form
-- assignment. Applies density parameters from BuildingType definitions
-- to produce output attributes (population, households, dwelling units,
-- employment by sector, building square footage, land development category).
--
-- Input variables:
--   @parcel_table:       Parcel geometries with built_form_key and attributes
--   @built_form_table:   BuildingType definitions (du_per_acre, emp_per_acre,
--                        far, household_size, vacancy_rate, etc.)
--   @dev_pct:            Development percentage (default 100)
--   @gross_net_pct:      Gross-to-net ratio (default 85)
--   @density_pct:        Density adjustment percentage (default 100)
--
-- Output columns:
--   parcel_id, gross_acres, acres_developable, acres_developed,
--   population, households, dwelling_units_total,
--   dwelling_units_sf_ll, dwelling_units_sf_sl,
--   dwelling_units_attached_sf, dwelling_units_mf_2_4,
--   dwelling_units_mf_5p, employment_total,
--   building_sqft_total, building_sqft_residential,
--   building_sqft_commercial, building_sqft_office,
--   building_sqft_industrial, building_sqft_public,
--   building_sqft_retail, building_sqft_wholesale,
--   building_sqft_education, building_sqft_healthcare,
--   building_sqft_hotel_lodging, building_sqft_entertainment,
--   building_sqft_other,
--   res_irrigated_sqft, com_irrigated_sqft,
--   parcel_acres_developed, parcel_acres_agriculture,
--   parcel_acres_open_space, parcel_acres_vacant,
--   intersection_density, land_dev_category,
--   built_form_id, indoor_water_rate, outdoor_water_rate,
--   electricity_eui, gas_eui, household_size, geom

WITH parcel_base AS (
    SELECT
        p.id AS parcel_id,
        @st_area_projected(p.geom) AS gross_acres,
        -- Developable acres from env_constraint if available, else raw area
        COALESCE(ec.acres_developable, @st_area_projected(p.geom)) AS acres_developable,
        bf.du_per_acre,
        bf.emp_per_acre,
        bf.far,
        bf.household_size,
        bf.vacancy_rate,
        bf.jobs_by_sector,
        bf.indoor_water_rate,
        bf.outdoor_water_rate,
        bf.id AS built_form_id,
        bf.building_coverage,
        bf.electricity_eui,
        bf.gas_eui,
        bf.vintage,
        bf.irrigable_area_fraction,
        p.intersection_density,
        p.geom,
        p.du_per_acre IS NOT NULL AND p.du_per_acre > 0 AS is_residential,
        bf.emp_per_acre IS NOT NULL AND bf.emp_per_acre > 0 AS is_nonresidential
    FROM @parcel_table AS p
    LEFT JOIN brewgis.analysis.env_constraint AS ec
        ON p.id = ec.parcel_id
    LEFT JOIN @built_form_table AS bf
        ON p.built_form_key = bf.key
),

computed AS (
    SELECT
        parcel_id,
        gross_acres,
        acres_developable,
        -- Density-adjusted acres
        @compute_applied_acres(acres_developable, @dev_pct, @gross_net_pct) AS applied_acres,
        @compute_applied_acres(acres_developable, @dev_pct, @gross_net_pct)
            * @density_pct / 100.0 AS density_adjusted_acres,
        du_per_acre,
        emp_per_acre,
        far,
        household_size,
        vacancy_rate,
        jobs_by_sector,
        indoor_water_rate,
        outdoor_water_rate,
        built_form_id,
        building_coverage,
        electricity_eui,
        gas_eui,
        vintage,
        irrigable_area_fraction,
        intersection_density,
        geom,
        is_residential,
        is_nonresidential
    FROM parcel_base
)

SELECT
    c.parcel_id,
    c.gross_acres,
    c.acres_developable,
    c.applied_acres AS acres_developed,

    -- Population & Households
    @compute_population(
        CASE WHEN c.du_per_acre IS NOT NULL AND c.du_per_acre > 0
            THEN c.density_adjusted_acres * c.du_per_acre
            ELSE 0.0 END,
        COALESCE(c.household_size, 2.5)
    ) AS population,

    @compute_households(
        CASE WHEN c.du_per_acre IS NOT NULL AND c.du_per_acre > 0
            THEN c.density_adjusted_acres * c.du_per_acre
            ELSE 0.0 END,
        COALESCE(c.vacancy_rate, 5.0)
    ) AS households,

    -- Dwelling unit breakdown
    @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre) AS dwelling_units_sf_ll,
    0.0 AS dwelling_units_sf_sl,
    0.0 AS dwelling_units_attached_sf,
    0.0 AS dwelling_units_mf_2_4,
    0.0 AS dwelling_units_mf_5p,

    @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre) AS dwelling_units_total,

    -- Employment
    CASE
        WHEN c.is_nonresidential
        THEN @compute_employment(c.density_adjusted_acres, c.emp_per_acre)
        ELSE 0.0
    END AS employment_total,

    -- Building square footage
    @compute_floor_area(c.density_adjusted_acres, c.far) AS building_sqft_total,
    0.0 AS building_sqft_residential,
    0.0 AS building_sqft_commercial,
    0.0 AS building_sqft_office,
    0.0 AS building_sqft_industrial,
    0.0 AS building_sqft_public,
    0.0 AS building_sqft_retail,
    0.0 AS building_sqft_wholesale,
    0.0 AS building_sqft_education,
    0.0 AS building_sqft_healthcare,
    0.0 AS building_sqft_hotel_lodging,
    0.0 AS building_sqft_entertainment,
    0.0 AS building_sqft_other,

    -- Irrigated area
    CASE
        WHEN c.is_residential
        THEN c.density_adjusted_acres * 43560.0
            * (1.0 - COALESCE(c.building_coverage, 30.0) / 100.0)
            * COALESCE(c.irrigable_area_fraction, 0.0)
        ELSE 0.0
    END AS res_irrigated_sqft,

    CASE
        WHEN c.is_nonresidential
        THEN c.density_adjusted_acres * 43560.0
            * (1.0 - COALESCE(c.building_coverage, 30.0) / 100.0)
            * COALESCE(c.irrigable_area_fraction, 0.0)
        ELSE 0.0
    END AS com_irrigated_sqft,

    -- Parcel acres by type
    c.applied_acres AS parcel_acres_developed,
    0.0 AS parcel_acres_agriculture,
    0.0 AS parcel_acres_open_space,
    0.0 AS parcel_acres_vacant,

    -- Network indicators
    COALESCE(c.intersection_density, 0.0) AS intersection_density,

    -- Land development category
    @classify_land_dev_category(c.du_per_acre) AS land_dev_category,

    -- Built form metadata
    c.built_form_id,
    COALESCE(c.indoor_water_rate, 0.0) AS indoor_water_rate,
    COALESCE(c.outdoor_water_rate, 0.0) AS outdoor_water_rate,
    COALESCE(c.electricity_eui, 0.0) AS electricity_eui,
    COALESCE(c.gas_eui, 0.0) AS gas_eui,
    c.household_size,
    c.geom
FROM computed AS c;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_core_end_state_parcel_id
  ON brewgis.analysis.core_end_state (parcel_id)
);
