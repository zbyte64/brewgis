MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level end-state population, units, employment and floor area: the base canvas''s own values for a BASE scenario, else computed from the assigned built form parameters.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developable = 'Acres available for development; currently the full gross area (acres).',
    acres_developed = 'Developed acres after the development and gross-to-net adjustments (acres).',
    pop = 'Population: the base canvas''s own value for a BASE scenario, else from the allocated dwelling units and the built form household size (people).',
    hh = 'Households: the base canvas''s own value for a BASE scenario, else from the allocated dwelling units and the built form vacancy rate (households).',
    du_detsf_ll = 'Dwelling units on a large-lot detached built form (du_type detsf_ll) — the base canvas''s own value for a BASE scenario, else recomputed; zero on every other class.',
    du_detsf_sl = 'Dwelling units on a small-lot detached built form (du_type detsf_sl) — the base canvas''s own value for a BASE scenario, else recomputed; zero on every other class.',
    du_attsf = 'Dwelling units on an attached single-family built form (du_type attsf) — the base canvas''s own value for a BASE scenario, else recomputed; zero on every other class.',
    du_mf2to4 = 'Dwelling units on a 2-4 unit multifamily built form (du_type mf2to4) — the base canvas''s own value for a BASE scenario, else recomputed; zero on every other class.',
    du_mf5p = 'Dwelling units on a 5+ unit multifamily built form (du_type mf5p) — the base canvas''s own value for a BASE scenario, else recomputed; zero on every other class.',
    du = 'Total dwelling units: the base canvas''s own value for a BASE scenario, else from the developed acres and the du_per_acre rate.',
    emp = 'Employment: the base canvas''s own value for a BASE scenario, else from the developed acres and the built form emp_per_acre rate (jobs).',
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
    du_type = 'Housing class of the assigned built form (detsf_ll, detsf_sl, attsf, mf2to4, mf5p); empty when the form has no dwelling units.',
    jobs_by_sector = 'Employment sector weights trip generation reads: the base canvas''s own sector jobs for a BASE scenario, else the assigned built form''s percentage mix (percent of emp_per_acre); empty when neither carries a mix.',
    indoor_water_rate = 'Built form indoor water rate (litres per person per day), default 200.',
    outdoor_water_rate = 'Built form outdoor water rate (litres per sq metre per year).',
    electricity_eui = 'Built form electricity use intensity (kWh per sq metre per year).',
    gas_eui = 'Built form gas use intensity (kWh per sq metre per year).',
    household_size = 'Household size of the assigned built form (persons); null when unset.',
    geometry = 'Parcel boundary geometry (EPSG:4326).',
    centroid_local = 'Parcel centroid projected to the region local SRID (indexed for buffer joins).'
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
--   @blueprint_var('scenario_type'):      "base" carries the base canvas's own
--                                         pop/hh/du/emp and sector mix (a base
--                                         scenario changes nothing); any other
--                                         value recomputes them from the built
--                                         form the scenario deployed.
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
--   built_form_id, built_form_key, du_type, jobs_by_sector,
--   indoor_water_rate, outdoor_water_rate,
--   electricity_eui, gas_eui, household_size, geometry, centroid_local

WITH parcel_base AS (
    SELECT
        p.parcel_id,
        @st_area_projected(p.geometry) AS area_gross_acres,
        -- Developable acres from env_constraint if available, else raw area
        @st_area_projected(p.geometry) AS acres_developable,
        bf.du_per_acre,
        bf.du_type,
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
        -- The base canvas's own end-state quantities, read from the same row —
        -- no extra join. A BASE scenario carries them (it changes nothing); an
        -- ALTERNATIVE scenario redeploys built forms, so each is recomputed from
        -- the built form instead (see the final SELECT).
        p.pop AS canvas_pop,
        p.hh AS canvas_hh,
        p.du AS canvas_du,
        p.du_detsf_ll AS canvas_du_detsf_ll,
        p.du_detsf_sl AS canvas_du_detsf_sl,
        p.du_attsf AS canvas_du_attsf,
        p.du_mf2to4 AS canvas_du_mf2to4,
        p.du_mf5p AS canvas_du_mf5p,
        p.emp AS canvas_emp,
        p.emp_retail_services AS canvas_emp_retail_services,
        p.emp_other_services AS canvas_emp_other_services,
        p.emp_restaurant AS canvas_emp_restaurant,
        p.emp_accommodation AS canvas_emp_accommodation,
        p.emp_arts_entertainment AS canvas_emp_arts_entertainment,
        p.emp_office_services AS canvas_emp_office_services,
        p.emp_medical_services AS canvas_emp_medical_services,
        p.emp_public_admin AS canvas_emp_public_admin,
        p.emp_education AS canvas_emp_education,
        p.emp_manufacturing AS canvas_emp_manufacturing,
        p.emp_wholesale AS canvas_emp_wholesale,
        p.emp_transport_warehousing AS canvas_emp_transport_warehousing,
        p.emp_utilities AS canvas_emp_utilities,
        p.emp_construction AS canvas_emp_construction,
        p.emp_agriculture AS canvas_emp_agriculture,
        p.emp_military AS canvas_emp_military,
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
        du_type,
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
        is_nonresidential,

        -- Base-canvas end-state quantities (pass-through; see parcel_base).
        canvas_pop,
        canvas_hh,
        canvas_du,
        canvas_du_detsf_ll,
        canvas_du_detsf_sl,
        canvas_du_attsf,
        canvas_du_mf2to4,
        canvas_du_mf5p,
        canvas_emp,
        canvas_emp_retail_services,
        canvas_emp_other_services,
        canvas_emp_restaurant,
        canvas_emp_accommodation,
        canvas_emp_arts_entertainment,
        canvas_emp_office_services,
        canvas_emp_medical_services,
        canvas_emp_public_admin,
        canvas_emp_education,
        canvas_emp_manufacturing,
        canvas_emp_wholesale,
        canvas_emp_transport_warehousing,
        canvas_emp_utilities,
        canvas_emp_construction,
        canvas_emp_agriculture,
        canvas_emp_military
    FROM parcel_base
),

-- Derived end-state quantities from the built form: what an ALTERNATIVE scenario
-- gets, and the BASE scenario's fallback where the canvas carries nothing. In
-- their own CTE because a select list cannot reference a sibling output alias —
-- here ``density_adjusted_acres`` is a real column of ``computed``.
derived AS (
    SELECT
        c.*,
        @compute_population(
            CASE WHEN c.du_per_acre IS NOT NULL AND c.du_per_acre > 0
                THEN c.density_adjusted_acres * c.du_per_acre
                ELSE 0.0 END,
            COALESCE(c.household_size, 2.5)
        ) AS derived_pop,
        @compute_households(
            CASE WHEN c.du_per_acre IS NOT NULL AND c.du_per_acre > 0
                THEN c.density_adjusted_acres * c.du_per_acre
                ELSE 0.0 END,
            COALESCE(c.vacancy_rate, 5.0)
        ) AS derived_hh,
        CASE WHEN c.du_type = 'detsf_ll'
            THEN @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre)
            ELSE 0.0 END AS derived_du_detsf_ll,
        CASE WHEN c.du_type = 'detsf_sl'
            THEN @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre)
            ELSE 0.0 END AS derived_du_detsf_sl,
        CASE WHEN c.du_type = 'attsf'
            THEN @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre)
            ELSE 0.0 END AS derived_du_attsf,
        CASE WHEN c.du_type = 'mf2to4'
            THEN @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre)
            ELSE 0.0 END AS derived_du_mf2to4,
        CASE WHEN c.du_type = 'mf5p'
            THEN @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre)
            ELSE 0.0 END AS derived_du_mf5p,
        @compute_dwelling_units(c.density_adjusted_acres, c.du_per_acre) AS derived_du,
        CASE WHEN c.is_nonresidential
            THEN @compute_employment(c.density_adjusted_acres, c.emp_per_acre)
            ELSE 0.0 END AS derived_emp
    FROM computed AS c
)

SELECT
    c.parcel_id,
    c.area_gross_acres,
    c.acres_developable,
    c.applied_acres AS acres_developed,

    -- Population & Households. A BASE scenario changes nothing, so it carries
    -- the base canvas's own values; an ALTERNATIVE scenario recomputes them from
    -- the built form it deployed. The COALESCE is the canvas-missing fallback —
    -- a base canvas that does not carry these columns still gets an end state.
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_pop, c.derived_pop)
        ELSE c.derived_pop END AS pop,

    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_hh, c.derived_hh)
        ELSE c.derived_hh END AS hh,

    -- Dwelling unit breakdown. Each built form declares one housing class
    -- (BuildingType.du_type), so exactly one of these columns is non-zero and
    -- their sum is `du` — the same partition the SACOG base canvas holds.
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_du_detsf_ll, c.derived_du_detsf_ll)
        ELSE c.derived_du_detsf_ll END AS du_detsf_ll,
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_du_detsf_sl, c.derived_du_detsf_sl)
        ELSE c.derived_du_detsf_sl END AS du_detsf_sl,
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_du_attsf, c.derived_du_attsf)
        ELSE c.derived_du_attsf END AS du_attsf,
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_du_mf2to4, c.derived_du_mf2to4)
        ELSE c.derived_du_mf2to4 END AS du_mf2to4,
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_du_mf5p, c.derived_du_mf5p)
        ELSE c.derived_du_mf5p END AS du_mf5p,

    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_du, c.derived_du)
        ELSE c.derived_du END AS du,

    -- Employment
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN COALESCE(c.canvas_emp, c.derived_emp)
        ELSE c.derived_emp END AS emp,

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
    COALESCE(c.du_type, '') AS du_type,
    -- Employment sector mix. A BASE scenario uses the canvas's own sector jobs
    -- directly — trip_generation normalizes these weights by their sum, so raw
    -- counts are the right unit — while an ALTERNATIVE scenario keeps the built
    -- form's own percentage mix.
    CASE WHEN @blueprint_var('scenario_type') = 'base'
        THEN jsonb_build_object(
            'retail_services', c.canvas_emp_retail_services,
            'other_services', c.canvas_emp_other_services,
            'restaurant', c.canvas_emp_restaurant,
            'accommodation', c.canvas_emp_accommodation,
            'arts_entertainment', c.canvas_emp_arts_entertainment,
            'office_services', c.canvas_emp_office_services,
            'medical_services', c.canvas_emp_medical_services,
            'public_admin', c.canvas_emp_public_admin,
            'education', c.canvas_emp_education,
            'manufacturing', c.canvas_emp_manufacturing,
            'wholesale', c.canvas_emp_wholesale,
            'transport_warehousing', c.canvas_emp_transport_warehousing,
            'utilities', c.canvas_emp_utilities,
            'construction', c.canvas_emp_construction,
            'agriculture', c.canvas_emp_agriculture,
            'military', c.canvas_emp_military
        )
        ELSE COALESCE(c.jobs_by_sector, '{}'::jsonb)
    END AS jobs_by_sector,
    COALESCE(c.indoor_water_rate, 200.0) AS indoor_water_rate,
    COALESCE(c.outdoor_water_rate, 100.0) AS outdoor_water_rate,
    COALESCE(c.electricity_eui, 100.0) AS electricity_eui,
    COALESCE(c.gas_eui, 50.0) AS gas_eui,
    c.household_size,
    c.geometry,

    -- Projected centroid, indexed below: the quarter-mile / one-mile context
    -- joins filter parcels by a distance expressed in local units, so the
    -- radius is a constant and the join is index-driven. Never reproject the
    -- geometry for the distance itself (see the AGENTS local-unit rule).
    ST_Transform(ST_Centroid(c.geometry), @local_srid()) AS centroid_local
FROM derived AS c;

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

  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_core_end_state_centroid_local_')
  ON @this_model USING GIST (centroid_local);


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
