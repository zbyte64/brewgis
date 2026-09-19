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
--   Column names follow the base_canvas convention wherever a base_canvas
--   equivalent exists (pop/hh/du/emp, area_*_acres, bldg_area_*, du_*
--   subtypes, *_irrigated_area in acres) so core_increment.sql can diff
--   this table against a real base_canvas table without a name/unit
--   mismatch. Columns with no base_canvas analog (scenario-only quantities
--   like acres_developed/acres_developable, or BuildingType rate/metadata
--   pass-throughs like electricity_eui) keep their original names.
--
--   parcel_id, area_gross_acres, acres_developable, acres_developed,
--   pop, hh, du,
--   du_detsf_ll, du_detsf_sl,
--   du_attsf, du_mf2to4,
--   du_mf5p, emp,
--   building_sqft_total, building_sqft_residential,
--   building_sqft_commercial, bldg_area_office_services,
--   building_sqft_industrial, bldg_area_public_admin,
--   bldg_area_retail_services, bldg_area_wholesale,
--   bldg_area_education, bldg_area_medical_services,
--   bldg_area_accommodation, bldg_area_arts_entertainment,
--   building_sqft_other,
--   residential_irrigated_area, commercial_irrigated_area,
--   parcel_acres_developed, parcel_acres_agriculture,
--   parcel_acres_open_space, parcel_acres_vacant,
--   intersection_density, land_development_category,
--   built_form_id, built_form_key, indoor_water_rate, outdoor_water_rate,
--   electricity_eui, gas_eui, household_size, geometry

WITH parcel_base AS (
    SELECT
        p.id AS parcel_id,
        @st_area_projected(p.geometry) AS area_gross_acres,
        -- Developable acres from env_constraint if available, else raw area
        @st_area_projected(p.geometry) AS acres_developable,
        bf.du_per_acre,
        bf.emp_per_acre,
        bf.far,
        bf.household_size,
        bf.vacancy_rate,
        bf.jobs_by_sector,
        bf.indoor_water_rate,
        bf.outdoor_water_rate,
        bf.id AS built_form_id,
        bf.key AS built_form_key,
        bf.building_coverage,
        bf.electricity_eui,
        bf.gas_eui,
        bf.vintage,
        bf.irrigable_area_fraction,
        p.intersection_density,
        p.geometry,
        bf.du_per_acre IS NOT NULL AND bf.du_per_acre > 0 AS is_residential,
        bf.emp_per_acre IS NOT NULL AND bf.emp_per_acre > 0 AS is_nonresidential
    FROM @ref_model(@parcel_table) AS p
    LEFT JOIN @ref_model(@built_form_table) AS bf
        ON p.built_form_key = bf.key
),

computed AS (
    SELECT
        parcel_id,
        area_gross_acres,
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
        built_form_key,
        building_coverage,
        electricity_eui,
        gas_eui,
        vintage,
        irrigable_area_fraction,
        intersection_density,
        geometry,
        is_residential,
        is_nonresidential
    FROM parcel_base
)

SELECT
    c.parcel_id,
    c.area_gross_acres,
    c.acres_developable,
    c.applied_acres AS acres_developed,

    -- Population & Households
    @compute_population(
        CASE WHEN c.du_per_acre IS NOT NULL AND c.du_per_acre > 0
            THEN c.density_adjusted_acres * c.du_per_acre
            ELSE 0.0 END,
        COALESCE(c.household_size, 2.5)
    ) AS pop,

    @compute_households(
        CASE WHEN c.du_per_acre IS NOT NULL AND c.du_per_acre > 0
            THEN c.density_adjusted_acres * c.du_per_acre
            ELSE 0.0 END,
        COALESCE(c.vacancy_rate, 5.0)
    ) AS hh,

    -- Dwelling unit breakdown
    @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre) AS du_detsf_ll,
    0.0 AS du_detsf_sl,
    0.0 AS du_attsf,
    0.0 AS du_mf2to4,
    0.0 AS du_mf5p,

    @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre) AS du,

    -- Employment
    CASE
        WHEN c.is_nonresidential
        THEN @compute_employment(c.density_adjusted_acres, c.emp_per_acre)
        ELSE 0.0
    END AS emp,

    -- Building square footage
    @compute_floor_area(c.density_adjusted_acres, c.far) AS building_sqft_total,
    0.0 AS building_sqft_residential,
    0.0 AS building_sqft_commercial,
    0.0 AS bldg_area_office_services,
    0.0 AS building_sqft_industrial,
    0.0 AS bldg_area_public_admin,
    0.0 AS bldg_area_retail_services,
    0.0 AS bldg_area_wholesale,
    0.0 AS bldg_area_education,
    0.0 AS bldg_area_medical_services,
    0.0 AS bldg_area_accommodation,
    0.0 AS bldg_area_arts_entertainment,
    0.0 AS building_sqft_other,

    -- Irrigated area (acres, matching base_canvas's residential_irrigated_area
    -- / commercial_irrigated_area — no *43560.0 sqft conversion)
    CASE
        WHEN c.is_residential
        THEN c.density_adjusted_acres
            * (1.0 - COALESCE(c.building_coverage, 30.0) / 100.0)
            * COALESCE(c.irrigable_area_fraction, 0.3)
        ELSE 0.0
    END AS residential_irrigated_area,

    CASE
        WHEN c.is_nonresidential
        THEN c.density_adjusted_acres
            * (1.0 - COALESCE(c.building_coverage, 30.0) / 100.0)
            * COALESCE(c.irrigable_area_fraction, 0.3)
        ELSE 0.0
    END AS commercial_irrigated_area,

    -- Parcel acres by type
    c.applied_acres AS parcel_acres_developed,
    0.0 AS parcel_acres_agriculture,
    0.0 AS parcel_acres_open_space,
    0.0 AS parcel_acres_vacant,

    -- Network indicators
    COALESCE(c.intersection_density, 0.0) AS intersection_density,

    -- Land development category
    @classify_land_dev_category(c.du_per_acre) AS land_development_category,

    -- Built form metadata
    c.built_form_id,
    c.built_form_key,
    COALESCE(c.indoor_water_rate, 200.0) AS indoor_water_rate,
    COALESCE(c.outdoor_water_rate, 100.0) AS outdoor_water_rate,
    COALESCE(c.electricity_eui, 100.0) AS electricity_eui,
    COALESCE(c.gas_eui, 50.0) AS gas_eui,
    c.household_size,
    c.geometry
FROM computed AS c;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_core_end_state_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS idx_core_end_state_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_core_end_state_parcel_acres_ag_@snapshot_hash
  ON @this_model USING btree (parcel_acres_agriculture);
  CREATE INDEX IF NOT EXISTS idx_core_end_state_land_dev_cat_@snapshot_hash
  ON @this_model USING btree (land_development_category);
  CREATE INDEX IF NOT EXISTS idx_core_end_state_acres_dev_@snapshot_hash
  ON @this_model USING btree (acres_developed);
