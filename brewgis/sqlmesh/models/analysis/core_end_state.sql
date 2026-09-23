MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level end-state population, units, employment and floor area from built form parameters.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developable = 'Acres available for development; currently the full gross area (acres).',
    acres_developed = 'Developed acres after the development and gross-to-net adjustments (acres).',
    pop = 'Population from the allocated dwelling units and the built form household size (people).',
    hh = 'Households from the allocated dwelling units and the built form vacancy rate (households).',
    du_detsf_ll = 'Detached single-family large-lot units; the only subtype this model populates.',
    du_detsf_sl = 'Detached single-family small-lot dwelling units (always zero here).',
    du_attsf = 'Attached single-family dwelling units (always zero here).',
    du_mf2to4 = 'Multi-family 2-4 unit dwelling units (always zero here).',
    du_mf5p = 'Multi-family 5 or more unit dwelling units (always zero here).',
    du = 'Total dwelling units from the developed acres and the du_per_acre rate.',
    emp = 'Employment from developed acres and the built form emp_per_acre rate (jobs).',
    building_sqft_total = 'Total floor area from developed acres and the FAR (sq ft).',
    building_sqft_residential = 'Residential floor area; zero, the FAR total is not split by use.',
    building_sqft_commercial = 'Commercial floor area; zero, the FAR total is not split by use.',
    bldg_area_office_services = 'Office services floor area (always zero in this model).',
    building_sqft_industrial = 'Industrial floor area (always zero in this model).',
    bldg_area_public_admin = 'Public administration floor area (always zero in this model).',
    bldg_area_retail_services = 'Retail services floor area (always zero in this model).',
    bldg_area_wholesale = 'Wholesale floor area (always zero in this model).',
    bldg_area_education = 'Education floor area (always zero in this model).',
    bldg_area_medical_services = 'Medical services floor area (always zero in this model).',
    bldg_area_accommodation = 'Accommodation floor area (always zero in this model).',
    bldg_area_arts_entertainment = 'Arts and entertainment floor area (always zero here).',
    building_sqft_other = 'Other non-residential floor area (always zero in this model).',
    residential_irrigated_area = 'Residential irrigated area from developed acres and coverage (acres).',
    commercial_irrigated_area = 'Non-residential irrigated area from developed acres (acres).',
    parcel_acres_developed = 'Parcel acres in the developed use, equal to the developed acres.',
    parcel_acres_agriculture = 'Parcel acres in agriculture; zero in the end state (acres).',
    parcel_acres_open_space = 'Parcel acres in open space; zero in the end state (acres).',
    parcel_acres_vacant = 'Parcel acres left vacant; zero in the end state (acres).',
    intersection_density = 'Intersection density (intersections per km2).',
    land_development_category = 'Land development category from the built form du_per_acre rate.',
    built_form_id = 'Identifier of the built form assigned to the parcel.',
    built_form_key = 'Key of the built form assigned to the parcel.',
    indoor_water_rate = 'Built form indoor water rate (litres per person per day), default 200.',
    outdoor_water_rate = 'Built form outdoor water rate (litres per sq metre per year).',
    electricity_eui = 'Built form electricity use intensity (kWh per sq metre per year).',
    gas_eui = 'Built form gas use intensity (kWh per sq metre per year).',
    household_size = 'Household size of the assigned built form (persons); null when unset.',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('core_end_state'),
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
--   @blueprint_var('dev_pct'):            Development percentage (default 100)
--   @blueprint_var('gross_net_pct'):      Gross-to-net ratio (default 85)
--   @blueprint_var('density_pct'):        Density adjustment percentage (default 100)
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
        p.parcel_id,
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
        -- Key normalization (not a plain `=`): a canvas's built_form_key is
        -- either an ETL slug written by the base-canvas layer or the display
        -- name the paint surfaces wrote, while built_forms.key holds only the
        -- latter. A raw comparison silently drops every slug-keyed parcel,
        -- which zeroes the densities this model derives from them — and with
        -- them trips, VMT and everything downstream. See the macro.
        ON @normalize_built_form_key(p.built_form_key)
            = @normalize_built_form_key(bf.key)
),

computed AS (
    SELECT
        parcel_id,
        area_gross_acres,
        acres_developable,
        -- Density-adjusted acres
        @compute_applied_acres(acres_developable, @blueprint_var('dev_pct'), @blueprint_var('gross_net_pct')) AS applied_acres,
        @compute_applied_acres(acres_developable, @blueprint_var('dev_pct'), @blueprint_var('gross_net_pct'))
            * @blueprint_var('density_pct') / 100.0 AS density_adjusted_acres,
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
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_end_state_geometry_')
  ON @this_model USING GIST (geometry);

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_end_state_parcel_id_')
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_end_state_parcel_acres_ag_')
  ON @this_model USING btree (parcel_acres_agriculture);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_end_state_land_dev_cat_')
  ON @this_model USING btree (land_development_category);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_end_state_acres_dev_')
  ON @this_model USING btree (acres_developed);


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
