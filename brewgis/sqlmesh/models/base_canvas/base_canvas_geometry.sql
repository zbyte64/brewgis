MODEL (
  name brewgis.@{region}.base_canvas_geometry,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  description 'Parcel-level Base Canvas rows from the region parcel source, with dasymetric weights and DU estimates.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier from the region parcel source.',
    geometry = 'Parcel geometry in WGS84 (EPSG:4326).',
    local_geometry = 'Parcel geometry projected to local_srid (CA Albers, EPSG:3310).',
    county = 'County name of the parcel from the parcels source.',
    land_development_category = 'Land development category, preferring the dasymetric value.',
    built_form_key = 'Built form key, preferring the dasymetric value over the parcel value.',
    intersection_density = 'Intersection density at the parcel (intersections per km2).',
    pop = 'Population of the parcel passed through from the parcels source (people).',
    hh = 'Household count of the parcel, passed through from the parcels source.',
    du = 'Dwelling unit count of the parcel, passed through from the parcels source.',
    land_use = 'Land use label from the parcels source.',
    assessor_use_code = 'Assessor use code from the parcels source.',
    bldg_area_detsf_sl = 'Detached single-family small-lot building floor area (sq ft).',
    bldg_area_detsf_ll = 'Detached single-family large-lot building floor area (sq ft).',
    bldg_area_attsf = 'Attached single-family building floor area (sq ft).',
    bldg_area_mf = 'Multi-family building floor area (sq ft).',
    bldg_area_retail_services = 'Retail services building floor area (sq ft).',
    bldg_area_restaurant = 'Restaurant building floor area (sq ft).',
    bldg_area_accommodation = 'Accommodation building floor area (sq ft).',
    bldg_area_arts_entertainment = 'Arts and entertainment building floor area (sq ft).',
    bldg_area_other_services = 'Other services building floor area (sq ft).',
    bldg_area_office_services = 'Office services building floor area (sq ft).',
    bldg_area_public_admin = 'Public administration building floor area (sq ft).',
    bldg_area_education = 'Education building floor area (sq ft).',
    bldg_area_medical_services = 'Medical services building floor area (sq ft).',
    bldg_area_transport_warehousing = 'Transport and warehousing building floor area (sq ft).',
    bldg_area_wholesale = 'Wholesale building floor area (sq ft).',
    residential_irrigated_area = 'Residential irrigated area of the parcel (acres).',
    commercial_irrigated_area = 'Commercial irrigated area of the parcel (acres).',
    area_parcel_res = 'Parcel area in residential use (acres).',
    area_parcel_emp_ag = 'Parcel area in agricultural employment use (acres).',
    area_parcel_emp = 'Parcel area in employment use (acres).',
    area_parcel_mixed_use = 'Parcel area in mixed use (acres).',
    area_parcel_no_use = 'Parcel area with no assigned use (acres).',
    area_gross = 'Gross parcel area computed from the local geometry (acres).',
    area_gross_acres = 'Gross parcel area rounded to 4 decimals (acres).',
    area_parcel_acres = 'Parcel area rounded to 4 decimals (acres); equal to the gross area here.',
    area_dev_condition_acres = 'Developable-condition area, 70 percent of the gross parcel area (acres).',
    area_row_acres = 'Right-of-way area, 15 percent of the gross parcel area (acres).',
    apn = 'Assessor parcel number (APN) from the dasymetric crosswalk.',
    du_subtype = 'Dwelling unit subtype from the dasymetric source.',
    is_residential = 'Flag indicating residential use from the dasymetric source.',
    residential_building_sqft = 'Residential building floor area of the parcel (sq ft).',
    commercial_building_sqft = 'Commercial building floor area of the parcel (sq ft).',
    industrial_building_sqft = 'Industrial building floor area of the parcel (sq ft).',
    other_building_sqft = 'Other building floor area of the parcel (sq ft).',
    total_footprint_sqft = 'Total building footprint area of the parcel (sq ft).',
    building_count = 'Number of buildings on the parcel.',
    footprint_ratio = 'Building footprint area divided by parcel area (0-1).',
    max_levels = 'Maximum building level count on the parcel.',
    dasym_impervious_fraction = 'Impervious surface fraction placeholder, currently a constant 0.0.',
    pop_dasym_weight = 'Population dasymetric weight based on residential floor area (sq ft).',
    emp_dasym_weight = 'Employment dasymetric weight from non-residential floor area scaled by intersection density.',
    du_estimated = 'Dwelling units from the 2-tier cascade: assessor units, then the DU regressor.',
    hh_size = 'Mean household size from the ACS block group (people per household).',
    vacancy_rate = 'Vacancy rate used for household estimation (fraction 0-1).',
    du_pop_dasym_weight = 'Population weight: dwelling units times household size (people).',
    hh_dasym_weight = 'Household weight: dwelling units times occupancy (households).',
    hh_estimated = 'Estimated households: dwelling units times occupancy (households).'
  ),
  audits (
    not_null(columns := (parcel_id))
  ),

  -- depends_on uses macro refs (@parcel_table / @dasymetric_source) that
  -- resolve to each blueprint instance's concrete parcel_shim and
  -- comparison_dasymetric models, so plan ordering works per region.
  depends_on (
    brewgis.seeds.assessor_use_codes,
    @parcel_table,
    @dasymetric_source
  ),
  blueprints @region_blueprints()
);

-- Base Canvas Geometry — first ETL step.
--
-- Reads raw parcel data from brewgis.parcels (via the parcels source),
-- casts geometry to PostGIS geometry (EPSG:4326), computes area columns
-- from local_srid (CA Albers, SRID 3310), and passes through source columns.
--
-- Area columns use _acres suffix per BASE_MAP_METHODOLOGY.md.

WITH assessor_categories AS (
    SELECT use_code::text, category FROM brewgis.seeds.assessor_use_codes
),

parcel_geom AS (
    SELECT
        p.parcel_id,
        p.geometry,
        ST_Transform(p.geometry, @VAR('local_srid', 3310)) AS local_geometry,
        p.county,
        COALESCE(
            NULLIF(p.land_development_category, ''),
            ac.category, ''
        ) AS land_development_category,
        p.built_form_key,
        p.intersection_density,
        p.pop,
        p.hh,
        p.du,
        p.land_use,
        p.assessor_use_code,
        p.bldg_area_detsf_sl,
        p.bldg_area_detsf_ll,
        p.bldg_area_attsf,
        p.bldg_area_mf,
        p.bldg_area_retail_services,
        p.bldg_area_restaurant,
        p.bldg_area_accommodation,
        p.bldg_area_arts_entertainment,
        p.bldg_area_other_services,
        p.bldg_area_office_services,
        p.bldg_area_public_admin,
        p.bldg_area_education,
        p.bldg_area_medical_services,
        p.bldg_area_transport_warehousing,
        p.bldg_area_wholesale,
        p.residential_irrigated_area,
        p.commercial_irrigated_area,
        p.area_parcel_res,
        p.area_parcel_emp_ag,
        p.area_parcel_emp,
        p.area_parcel_mixed_use,
        p.area_parcel_no_use
    FROM @parcel_table p
    LEFT JOIN assessor_categories ac ON LEFT(COALESCE(p.assessor_use_code, ''), 2) = ac.use_code
),

parcel_area AS (
    SELECT
        parcel_geom.*,
        ROUND((ST_Area(parcel_geom.local_geometry) / 4046.86)::numeric, 4) AS area_gross
    FROM parcel_geom
),

dasymetric_enrichment AS (
    SELECT
        parcel_id,
        apn,
        land_development_category,
        built_form_key,
        du_subtype,
        is_residential,
        residential_building_sqft,
        commercial_building_sqft,
        industrial_building_sqft,
        other_building_sqft,
        total_footprint_sqft,
        building_count,
        footprint_ratio,
        max_levels,
        intersection_density,
        pop_dasym_weight,
        emp_dasym_weight,
        du,
        hh_size,
        vacancy_rate,
        du_pop_dasym_weight,
        hh_dasym_weight,
        hh,
        bldg_area_detsf_sl,
        bldg_area_detsf_ll,
        bldg_area_attsf,
        bldg_area_mf,
        bldg_area_retail_services,
        bldg_area_restaurant,
        bldg_area_accommodation,
        bldg_area_arts_entertainment,
        bldg_area_other_services,
        bldg_area_office_services,
        bldg_area_public_admin,
        bldg_area_education,
        bldg_area_medical_services,
        bldg_area_transport_warehousing,
        bldg_area_wholesale
    FROM @dasymetric_source
)

SELECT
    parcel_area.parcel_id,
    parcel_area.geometry,
    parcel_area.local_geometry,
    parcel_area.county,
    COALESCE(de.land_development_category, parcel_area.land_development_category) AS land_development_category,
    COALESCE(de.built_form_key, parcel_area.built_form_key) AS built_form_key,
    COALESCE(de.intersection_density, parcel_area.intersection_density) AS intersection_density,
    parcel_area.pop,
    parcel_area.hh,
    parcel_area.du,
    parcel_area.land_use,
    parcel_area.assessor_use_code,
    COALESCE(de.bldg_area_detsf_sl, parcel_area.bldg_area_detsf_sl) AS bldg_area_detsf_sl,
    COALESCE(de.bldg_area_detsf_ll, parcel_area.bldg_area_detsf_ll) AS bldg_area_detsf_ll,
    COALESCE(de.bldg_area_attsf, parcel_area.bldg_area_attsf) AS bldg_area_attsf,
    COALESCE(de.bldg_area_mf, parcel_area.bldg_area_mf) AS bldg_area_mf,
    COALESCE(de.bldg_area_retail_services, parcel_area.bldg_area_retail_services) AS bldg_area_retail_services,
    COALESCE(de.bldg_area_restaurant, parcel_area.bldg_area_restaurant) AS bldg_area_restaurant,
    COALESCE(de.bldg_area_accommodation, parcel_area.bldg_area_accommodation) AS bldg_area_accommodation,
    COALESCE(de.bldg_area_arts_entertainment, parcel_area.bldg_area_arts_entertainment) AS bldg_area_arts_entertainment,
    COALESCE(de.bldg_area_other_services, parcel_area.bldg_area_other_services) AS bldg_area_other_services,
    COALESCE(de.bldg_area_office_services, parcel_area.bldg_area_office_services) AS bldg_area_office_services,
    COALESCE(de.bldg_area_public_admin, parcel_area.bldg_area_public_admin) AS bldg_area_public_admin,
    COALESCE(de.bldg_area_education, parcel_area.bldg_area_education) AS bldg_area_education,
    COALESCE(de.bldg_area_medical_services, parcel_area.bldg_area_medical_services) AS bldg_area_medical_services,
    COALESCE(de.bldg_area_transport_warehousing, parcel_area.bldg_area_transport_warehousing) AS bldg_area_transport_warehousing,
    COALESCE(de.bldg_area_wholesale, parcel_area.bldg_area_wholesale) AS bldg_area_wholesale,
    parcel_area.residential_irrigated_area,
    parcel_area.commercial_irrigated_area,
    parcel_area.area_parcel_res,
    parcel_area.area_parcel_emp_ag,
    parcel_area.area_parcel_emp,
    parcel_area.area_parcel_mixed_use,
    parcel_area.area_parcel_no_use,
    parcel_area.area_gross,
    ROUND(parcel_area.area_gross::numeric, 4) AS area_gross_acres,
    ROUND(parcel_area.area_gross::numeric, 4) AS area_parcel_acres,
    ROUND((parcel_area.area_gross * 0.7)::numeric, 4) AS area_dev_condition_acres,
    ROUND((parcel_area.area_gross * 0.15)::numeric, 4) AS area_row_acres,
    de.apn,
    de.du_subtype,
    de.is_residential,
    de.residential_building_sqft,
    de.commercial_building_sqft,
    de.industrial_building_sqft,
    de.other_building_sqft,
    de.total_footprint_sqft,
    de.building_count,
    de.footprint_ratio,
    de.max_levels,
    0.0::double precision AS dasym_impervious_fraction,
    de.pop_dasym_weight,
    de.emp_dasym_weight,
    de.du AS du_estimated,
    de.hh_size,
    de.vacancy_rate,
    de.du_pop_dasym_weight,
    de.hh_dasym_weight,
    de.hh AS hh_estimated,
FROM parcel_area
LEFT JOIN dasymetric_enrichment de ON parcel_area.parcel_id = de.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_geometry_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_geometry_centroid_')
  ON @this_model USING GIST (ST_Centroid(geometry));
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_geometry_parcel_id_')
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_geometry_apn_')
  ON @this_model USING btree (apn);
  ANALYZE @this_model;
