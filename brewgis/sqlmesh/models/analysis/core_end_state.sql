MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level end-state population, households, dwelling units, employment, floor area and parcel acres read from the scenario canvas, with the assigned built form''s rate/metadata fields passed through.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developable = 'Acres available for development; currently the full gross area (acres).',
    acres_developed = 'Developed acres: residential + employment + mixed-use parcel acres (acres).',
    pop = 'Population, read from the base layer (@parcel_table) unconditionally (people).',
    hh = 'Households, read from the base layer (households).',
    du_detsf_ll = 'Dwelling units on a large-lot detached built form (du_type detsf_ll), read from the base layer; zero on every other class.',
    du_detsf_sl = 'Dwelling units on a small-lot detached built form (du_type detsf_sl), read from the base layer; zero on every other class.',
    du_attsf = 'Dwelling units on an attached single-family built form (du_type attsf), read from the base layer; zero on every other class.',
    du_mf2to4 = 'Dwelling units on a 2-4 unit multifamily built form (du_type mf2to4), read from the base layer; zero on every other class.',
    du_mf5p = 'Dwelling units on a 5+ unit multifamily built form (du_type mf5p), read from the base layer; zero on every other class.',
    du = 'Total dwelling units, read from the base layer (units).',
    emp = 'Employment, read from the base layer (jobs).',
    building_sqft_residential = 'Residential floor area: the base layer''s four residential bldg_area columns (sq ft).',
    building_sqft_commercial = 'Commercial floor area: the base layer''s eleven non-residential bldg_area columns (sq ft).',
    building_sqft_total = 'Total floor area: residential + commercial, read from the base layer''s bldg_area columns (sq ft).',
    building_sqft_industrial = 'Industrial floor area: the base layer''s wholesale + transport/warehousing floor area (sq ft).',
    building_sqft_other = 'Other non-residential floor area: the base layer''s bldg_area_other_services (sq ft).',
    bldg_area_office_services = 'Office services floor area from the base layer (sq ft).',
    bldg_area_public_admin = 'Public administration floor area from the base layer (sq ft).',
    bldg_area_retail_services = 'Retail services floor area from the base layer (sq ft).',
    bldg_area_wholesale = 'Wholesale floor area from the base layer (sq ft).',
    bldg_area_education = 'Education floor area from the base layer (sq ft).',
    bldg_area_medical_services = 'Medical services floor area from the base layer (sq ft).',
    bldg_area_accommodation = 'Accommodation floor area from the base layer (sq ft).',
    bldg_area_arts_entertainment = 'Arts and entertainment floor area from the base layer (sq ft).',
    residential_irrigated_area = 'Residential irrigated area, read from the base layer (acres).',
    commercial_irrigated_area = 'Non-residential irrigated area, read from the base layer (acres).',
    parcel_acres_developed = 'Parcel acres in the developed use: residential + employment + mixed-use (acres).',
    parcel_acres_agriculture = 'Parcel acres in agricultural employment use, read from the base layer (acres).',
    parcel_acres_open_space = 'Parcel acres neither developed nor vacant: gross area less developed and no-use acres (acres).',
    parcel_acres_vacant = 'Parcel acres in no use, read from the base layer (acres).',
    intersection_density = 'Intersection density (intersections per km2), read from the base layer.',
    land_development_category = 'Land development category, read from the base layer.',
    built_form_id = 'Identifier of the built form assigned to the parcel (null when the canvas key matches no built form).',
    built_form_key = 'Built form key of the parcel: the canvas''s own key, else the matched built form''s key.',
    du_type = 'Housing class of the assigned built form (detsf_ll, detsf_sl, attsf, mf2to4, mf5p); empty when the form has no dwelling units.',
    jobs_by_sector = 'Employment by sector, read from the base layer''s emp_* columns (jobs).',
    indoor_water_rate = 'Built form indoor water rate (litres per person per day), default 200.',
    outdoor_water_rate = 'Built form outdoor water rate (litres per sq metre per year), default 100.',
    electricity_eui = 'Built form electricity use intensity (kWh per sq metre per year), default 100.',
    gas_eui = 'Built form gas use intensity (kWh per sq metre per year), default 50.',
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
-- Reads the scenario's end state straight off @parcel_table: every stock
-- column the base layer carries (population, households, dwelling units,
-- employment and its sector breakdown, floor area by use, parcel acres,
-- irrigated areas, land development category, intersection density) is taken
-- verbatim from the parcel row, unconditionally and with no scenario_type
-- branch. @parcel_table is the selected scenario's canvas rather than a raw
-- table — the workspace's effective base table for a BASE scenario, and
-- brewgis.scenario_canvas.canvas_<pk> (base canvas LEFT JOINed with the
-- scenario's PaintedCanvas overrides, COALESCE(painted, base)) for an
-- ALTERNATIVE one — so a painted override flows through without this model
-- knowing it happened. That is exactly why the model must not branch: the
-- correct source is the same reference in every case.
--
-- Built forms (BuildingType) supply only the rate/parameter fields the base
-- layer does not carry: indoor/outdoor water rates, electricity/gas EUI,
-- household size, du_type, and the built_form_id metadata. du_per_acre,
-- emp_per_acre and far are painting inputs (what a paint operation writes as
-- explicit du/pop/hh/emp overrides), never a substitute this model recomputes
-- from.
--
-- Input variables:
--   @parcel_table:       The scenario canvas: parcel geometry, stock columns
--                        (pop/hh/du/emp/bldg_area_*/area_parcel_*), and the
--                        built_form_key used to resolve the rate fields.
--   @built_form_table:   BuildingType definitions; only the rate/metadata
--                        fields are read (indoor_water_rate, outdoor_water_rate,
--                        electricity_eui, gas_eui, household_size, du_type).
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
        p.geometry,
        @st_area_projected(p.geometry) AS area_gross_acres,
        @st_area_projected(p.geometry) AS acres_developable,
        -- Stock: population / households / dwelling units (base layer).
        COALESCE(p.pop, 0.0) AS pop,
        COALESCE(p.hh, 0.0) AS hh,
        COALESCE(p.du, 0.0) AS du,
        COALESCE(p.du_detsf_ll, 0.0) AS du_detsf_ll,
        COALESCE(p.du_detsf_sl, 0.0) AS du_detsf_sl,
        COALESCE(p.du_attsf, 0.0) AS du_attsf,
        COALESCE(p.du_mf2to4, 0.0) AS du_mf2to4,
        COALESCE(p.du_mf5p, 0.0) AS du_mf5p,
        -- Stock: employment + sector breakdown (base layer).
        COALESCE(p.emp, 0.0) AS emp,
        COALESCE(p.emp_retail_services, 0.0) AS emp_retail_services,
        COALESCE(p.emp_other_services, 0.0) AS emp_other_services,
        COALESCE(p.emp_restaurant, 0.0) AS emp_restaurant,
        COALESCE(p.emp_accommodation, 0.0) AS emp_accommodation,
        COALESCE(p.emp_arts_entertainment, 0.0) AS emp_arts_entertainment,
        COALESCE(p.emp_office_services, 0.0) AS emp_office_services,
        COALESCE(p.emp_medical_services, 0.0) AS emp_medical_services,
        COALESCE(p.emp_public_admin, 0.0) AS emp_public_admin,
        COALESCE(p.emp_education, 0.0) AS emp_education,
        COALESCE(p.emp_manufacturing, 0.0) AS emp_manufacturing,
        COALESCE(p.emp_wholesale, 0.0) AS emp_wholesale,
        COALESCE(p.emp_transport_warehousing, 0.0) AS emp_transport_warehousing,
        COALESCE(p.emp_utilities, 0.0) AS emp_utilities,
        COALESCE(p.emp_construction, 0.0) AS emp_construction,
        COALESCE(p.emp_agriculture, 0.0) AS emp_agriculture,
        COALESCE(p.emp_military, 0.0) AS emp_military,
        -- Stock: floor area by use (base layer).
        COALESCE(p.bldg_area_detsf_sl, 0.0) AS bldg_area_detsf_sl,
        COALESCE(p.bldg_area_detsf_ll, 0.0) AS bldg_area_detsf_ll,
        COALESCE(p.bldg_area_attsf, 0.0) AS bldg_area_attsf,
        COALESCE(p.bldg_area_mf, 0.0) AS bldg_area_mf,
        COALESCE(p.bldg_area_retail_services, 0.0) AS bldg_area_retail_services,
        COALESCE(p.bldg_area_restaurant, 0.0) AS bldg_area_restaurant,
        COALESCE(p.bldg_area_accommodation, 0.0) AS bldg_area_accommodation,
        COALESCE(p.bldg_area_arts_entertainment, 0.0) AS bldg_area_arts_entertainment,
        COALESCE(p.bldg_area_other_services, 0.0) AS bldg_area_other_services,
        COALESCE(p.bldg_area_office_services, 0.0) AS bldg_area_office_services,
        COALESCE(p.bldg_area_public_admin, 0.0) AS bldg_area_public_admin,
        COALESCE(p.bldg_area_education, 0.0) AS bldg_area_education,
        COALESCE(p.bldg_area_medical_services, 0.0) AS bldg_area_medical_services,
        COALESCE(p.bldg_area_transport_warehousing, 0.0) AS bldg_area_transport_warehousing,
        COALESCE(p.bldg_area_wholesale, 0.0) AS bldg_area_wholesale,
        -- Stock: irrigated areas + parcel acres + classification (base layer).
        COALESCE(p.residential_irrigated_area, 0.0) AS residential_irrigated_area,
        COALESCE(p.commercial_irrigated_area, 0.0) AS commercial_irrigated_area,
        COALESCE(p.area_parcel_res, 0.0) AS area_parcel_res,
        COALESCE(p.area_parcel_emp, 0.0) AS area_parcel_emp,
        COALESCE(p.area_parcel_mixed_use, 0.0) AS area_parcel_mixed_use,
        COALESCE(p.area_parcel_no_use, 0.0) AS area_parcel_no_use,
        COALESCE(p.area_parcel_emp_ag, 0.0) AS area_parcel_emp_ag,
        COALESCE(p.land_development_category, '') AS land_development_category,
        COALESCE(p.intersection_density, 0.0) AS intersection_density,
        -- Built-form-only rate/metadata fields (the base layer carries none of
        -- these). A parcel whose canvas key matches no built form still gets
        -- the documented defaults.
        COALESCE(bf.indoor_water_rate, 200.0) AS indoor_water_rate,
        COALESCE(bf.outdoor_water_rate, 100.0) AS outdoor_water_rate,
        COALESCE(bf.electricity_eui, 100.0) AS electricity_eui,
        COALESCE(bf.gas_eui, 50.0) AS gas_eui,
        -- Nullable, as before: an unset household size is mode_choice's own
        -- fallback chain to resolve, not a value this model invents.
        bf.household_size AS household_size,
        COALESCE(bf.du_type, '') AS du_type,
        bf.id AS built_form_id,
        COALESCE(p.built_form_key, bf.key) AS built_form_key
    FROM @ref_model(@parcel_table) AS p
    LEFT JOIN @ref_model(@built_form_table) AS bf
        -- Key normalization (not a plain `=`): a canvas's built_form_key is
        -- either an ETL slug written by the base-canvas layer or the display
        -- name the paint surfaces wrote, while built_forms.key holds only the
        -- latter. A raw comparison silently drops every slug-keyed parcel,
        -- which strips the rate fields (water, EUI) it resolves. See the macro.
        ON @normalize_built_form_key(p.built_form_key)
            = @normalize_built_form_key(bf.key)
)

SELECT
    parcel_id,
    area_gross_acres,
    acres_developable,
    (area_parcel_res + area_parcel_emp + area_parcel_mixed_use) AS acres_developed,
    pop,
    hh,
    du_detsf_ll,
    du_detsf_sl,
    du_attsf,
    du_mf2to4,
    du_mf5p,
    du,
    emp,

    -- Residential floor area: the four residential bldg_area columns.
    (bldg_area_detsf_sl + bldg_area_detsf_ll + bldg_area_attsf + bldg_area_mf) AS building_sqft_residential,
    -- Commercial floor area: the eleven non-residential bldg_area columns.
    (bldg_area_retail_services + bldg_area_restaurant + bldg_area_accommodation
     + bldg_area_arts_entertainment + bldg_area_other_services + bldg_area_office_services
     + bldg_area_public_admin + bldg_area_education + bldg_area_medical_services
     + bldg_area_transport_warehousing + bldg_area_wholesale) AS building_sqft_commercial,
    (bldg_area_detsf_sl + bldg_area_detsf_ll + bldg_area_attsf + bldg_area_mf
     + bldg_area_retail_services + bldg_area_restaurant + bldg_area_accommodation
     + bldg_area_arts_entertainment + bldg_area_other_services + bldg_area_office_services
     + bldg_area_public_admin + bldg_area_education + bldg_area_medical_services
     + bldg_area_transport_warehousing + bldg_area_wholesale) AS building_sqft_total,
    (bldg_area_wholesale + bldg_area_transport_warehousing) AS building_sqft_industrial,
    bldg_area_other_services AS building_sqft_other,
    bldg_area_office_services,
    bldg_area_public_admin,
    bldg_area_retail_services,
    bldg_area_wholesale,
    bldg_area_education,
    bldg_area_medical_services,
    bldg_area_accommodation,
    bldg_area_arts_entertainment,
    residential_irrigated_area,
    commercial_irrigated_area,

    -- Parcel acres by type. Open space is what is neither developed nor in the
    -- base layer's no-use acres; agricultural employment acres are reported
    -- separately and therefore still count as open space here.
    (area_parcel_res + area_parcel_emp + area_parcel_mixed_use) AS parcel_acres_developed,
    area_parcel_emp_ag AS parcel_acres_agriculture,
    GREATEST(
        area_gross_acres - (area_parcel_res + area_parcel_emp + area_parcel_mixed_use + area_parcel_no_use),
        0.0
    ) AS parcel_acres_open_space,
    area_parcel_no_use AS parcel_acres_vacant,

    -- Network indicator + classification: the base layer's own values.
    intersection_density,
    land_development_category,

    -- Built form metadata + rate pass-throughs.
    built_form_id,
    built_form_key,
    du_type,
    jsonb_build_object(
        'retail_services', emp_retail_services,
        'other_services', emp_other_services,
        'restaurant', emp_restaurant,
        'accommodation', emp_accommodation,
        'arts_entertainment', emp_arts_entertainment,
        'office_services', emp_office_services,
        'medical_services', emp_medical_services,
        'public_admin', emp_public_admin,
        'education', emp_education,
        'manufacturing', emp_manufacturing,
        'wholesale', emp_wholesale,
        'transport_warehousing', emp_transport_warehousing,
        'utilities', emp_utilities,
        'construction', emp_construction,
        'agriculture', emp_agriculture,
        'military', emp_military
    ) AS jobs_by_sector,
    indoor_water_rate,
    outdoor_water_rate,
    electricity_eui,
    gas_eui,
    household_size,
    geometry,

    -- Projected centroid, indexed below: the quarter-mile / one-mile context
    -- joins filter parcels by a distance expressed in local units, so the
    -- radius is a constant and the join is index-driven. Never reproject the
    -- geometry for the distance itself (see the AGENTS local-unit rule).
    ST_Transform(ST_Centroid(geometry), @local_srid()) AS centroid_local
FROM parcel_base;

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
