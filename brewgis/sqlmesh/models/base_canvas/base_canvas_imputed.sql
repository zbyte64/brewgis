MODEL (
  name brewgis.@{region}.base_canvas_imputed,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  description 'Parcel-level base canvas imputed from base_canvas_combined in three tiers: keep the value, else the county average, else a national default.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier; one row per parcel in the base canvas.',
    geometry = 'Parcel boundary geometry (MultiPolygon, EPSG:4326).',
    local_geometry = 'Parcel boundary in the local projected SRID used for area and clipping math.',
    county = 'County the parcel falls in, carried from the parcel source.',
    land_development_category = 'Land development category carried from base_canvas_combined.',
    built_form_key = 'Built form key carried from base_canvas_combined.',
    intersection_density = 'Intersection density imputed from the county average, else 12.5 (intersections per km2).',
    area_gross = 'Gross parcel area including right-of-way (acres).',
    area_gross_acres = 'Gross parcel area including right-of-way (acres, explicit unit alias of area_gross).',
    area_parcel_acres = 'Parcel area inside the parcel boundary (acres).',
    area_dev_condition_acres = 'Portion of the parcel in developed condition (acres).',
    area_row_acres = 'Portion of the parcel in public right-of-way (acres).',
    area_parcel_res = 'Residential parcel area carried from base_canvas_combined (acres).',
    area_parcel_res_acres = 'Total residential parcel area (acres, explicit unit alias of area_parcel_res).',
    area_parcel_emp_ag = 'Agricultural employment parcel area carried from base_canvas_combined (acres).',
    area_parcel_emp_ag_acres = 'Agricultural employment parcel area (acres, alias of area_parcel_emp_ag).',
    area_parcel_emp = 'Total employment parcel area carried from base_canvas_combined (acres).',
    area_parcel_emp_acres = 'Total employment parcel area (acres, explicit unit alias of area_parcel_emp).',
    area_parcel_mixed_use = 'Mixed-use parcel area carried from base_canvas_combined (acres).',
    area_parcel_mixed_use_acres = 'Mixed-use parcel area (acres, explicit unit alias of area_parcel_mixed_use).',
    area_parcel_no_use = 'Parcel area with no assigned use carried from base_canvas_combined (acres).',
    area_parcel_no_use_acres = 'Parcel area with no assigned use (acres, explicit unit alias of area_parcel_no_use).',
    pop = 'Population imputed with the county average, else zero when null (people).',
    pop_groupquarter = 'Group quarters population, zero when null (people).',
    hh = 'Households imputed with the county average, else zero when null (count).',
    du = 'Dwelling units imputed with the county average, else zero when null (count).',
    du_detsf = 'Detached single-family dwelling units imputed from the county DU subtype shares (count).',
    du_detsf_sl = 'Detached single-family small-lot units imputed from county DU subtype shares (count).',
    du_detsf_ll = 'Detached single-family large-lot units imputed from county DU subtype shares (count).',
    du_attsf = 'Attached single-family units imputed from the county DU subtype shares (count).',
    du_mf = 'Multi-family dwelling units imputed from the county DU subtype shares (count).',
    du_mf2to4 = 'Multi-family 2-4 unit dwellings imputed from county DU subtype shares (count).',
    du_mf5p = 'Multi-family 5+ unit dwellings imputed from county DU subtype shares (count).',
    du_subtype = 'Dwelling unit subtype key assigned to the parcel.',
    is_residential = 'Flag marking the parcel as residential.',
    residential_building_sqft = 'Residential building floor area from base_canvas_combined, zero when null (sq ft).',
    commercial_building_sqft = 'Commercial building floor area from base_canvas_combined, zero when null (sq ft).',
    industrial_building_sqft = 'Industrial building floor area from base_canvas_combined, zero when null (sq ft).',
    other_building_sqft = 'Other building floor area from base_canvas_combined, zero when null (sq ft).',
    total_footprint_sqft = 'Total building footprint area from base_canvas_combined, zero when null (sq ft).',
    building_count = 'Number of buildings on the parcel, zero when null (count).',
    footprint_ratio = 'Building footprint share of parcel area, zero when null (ratio, 0-1).',
    max_levels = 'Maximum building levels on the parcel, zero when null (count).',
    emp = 'Total employment imputed with the county average, else zero when null (jobs).',
    emp_ret = 'Retail employment carried from base_canvas_combined (jobs).',
    emp_retail_services = 'Retail services employment carried from base_canvas_combined (jobs).',
    emp_restaurant = 'Restaurant employment carried from base_canvas_combined (jobs).',
    emp_accommodation = 'Accommodation employment carried from base_canvas_combined (jobs).',
    emp_arts_entertainment = 'Arts and entertainment employment carried from base_canvas_combined (jobs).',
    emp_other_services = 'Other services employment carried from base_canvas_combined (jobs).',
    emp_off = 'Office employment carried from base_canvas_combined (jobs).',
    emp_office_services = 'Office services employment carried from base_canvas_combined (jobs).',
    emp_medical_services = 'Medical services employment carried from base_canvas_combined (jobs).',
    emp_pub = 'Public employment carried from base_canvas_combined (jobs).',
    emp_public_admin = 'Public administration employment carried from base_canvas_combined (jobs).',
    emp_education = 'Education employment carried from base_canvas_combined (jobs).',
    emp_ind = 'Industrial employment carried from base_canvas_combined (jobs).',
    emp_manufacturing = 'Manufacturing employment carried from base_canvas_combined (jobs).',
    emp_wholesale = 'Wholesale employment carried from base_canvas_combined (jobs).',
    emp_transport_warehousing = 'Transport and warehousing employment carried from base_canvas_combined (jobs).',
    emp_utilities = 'Utilities employment carried from base_canvas_combined (jobs).',
    emp_construction = 'Construction employment carried from base_canvas_combined (jobs).',
    emp_ag = 'Agricultural employment carried from base_canvas_combined (jobs).',
    emp_agriculture = 'Agriculture employment carried from base_canvas_combined (jobs).',
    emp_extraction = 'Extraction employment carried from base_canvas_combined (jobs).',
    emp_military = 'Military employment carried from base_canvas_combined (jobs).',
    bldg_area_detsf_sl = 'Detached single-family small-lot building floor area (sq ft).',
    bldg_area_detsf_ll = 'Detached single-family large-lot building floor area (sq ft).',
    bldg_area_attsf = 'Attached single-family building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_mf = 'Multi-family building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_retail_services = 'Retail services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_restaurant = 'Restaurant building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_accommodation = 'Accommodation building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_arts_entertainment = 'Arts and entertainment building floor area (sq ft).',
    bldg_area_other_services = 'Other services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_office_services = 'Office services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_public_admin = 'Public administration building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_education = 'Education building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_medical_services = 'Medical services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_transport_warehousing = 'Transport and warehousing building floor area (sq ft).',
    bldg_area_wholesale = 'Wholesale building floor area carried from base_canvas_combined (sq ft).',
    residential_irrigated_area = 'Residential irrigated area carried from base_canvas_combined (acres).',
    commercial_irrigated_area = 'Commercial irrigated area carried from base_canvas_combined (acres).',
    median_income = 'Median household income carried from base_canvas_combined ($ per year).',
    rent_burden_pct = 'Rent-burdened household share from base_canvas_combined (% as 0-100).',
    pct_minority = 'Share of people of color carried from base_canvas_combined (% as 0-100).',
    pct_college_educated = 'College-educated adult share carried from base_canvas_combined (% as 0-100).',
    cost_burden_pct = 'Cost-burdened household share carried from base_canvas_combined (% as 0-100).',
    vacancy_rate = 'Housing vacancy rate carried from base_canvas_combined (ratio, 0-1).',
    occupied_du = 'Occupied dwelling units carried from base_canvas_combined (count).',
    land_use = 'Land use label from the parcel source, matched against the regional land use crosswalk.',
    assessor_use_code = 'Assessor use code from the parcel source, matched on its first two digits.'
  ),
  audits (
    not_null(columns := (parcel_id))
  ),
  blueprints @region_blueprints()
);

-- Base Canvas Imputed — three-tier imputation cascade.
--
-- Tier 1: Direct value from base_canvas_attributes (preserves existing values)
-- Tier 2: County average for remaining NULLs (window function)
-- Tier 3: National default constant as final fallback
-- Always treat 0 as 0, NULLs are what we fill in.

WITH attributes AS (
    SELECT * FROM brewgis.@{region}.base_canvas_combined
),

-- Tier 2: County averages for key numeric columns
regional_avg AS (
    SELECT
        county,
        AVG(pop) AS county_avg_pop,
        AVG(hh) AS county_avg_hh,
        AVG(du) AS county_avg_du,
        AVG(emp) AS county_avg_emp,
        AVG(intersection_density) AS county_avg_int_density
    FROM attributes
    GROUP BY county
),

-- County average DU sub-type proportions for imputation
du_subtype_proportions AS (
    SELECT
        county,
        SUM(du_detsf_sl) / NULLIF(SUM(du), 0) AS pct_detsf_sl,
        SUM(du_detsf_ll) / NULLIF(SUM(du), 0) AS pct_detsf_ll,
        SUM(du_attsf) / NULLIF(SUM(du), 0) AS pct_attsf,
        SUM(du_mf2to4) / NULLIF(SUM(du), 0) AS pct_mf2to4,
        SUM(du_mf5p) / NULLIF(SUM(du), 0) AS pct_mf5p
    FROM attributes
    WHERE du > 0 AND du_detsf_sl IS NOT NULL
    GROUP BY county
)

SELECT
    a.parcel_id,
    a.geometry,
    a.local_geometry,
    a.county,
    a.land_development_category,
    a.built_form_key,
    ROUND(COALESCE(
        a.intersection_density,
        r.county_avg_int_density,
        12.5
    )::numeric, 2) AS intersection_density,
    a.area_gross,
    a.area_gross_acres,
    a.area_parcel_acres,
    a.area_dev_condition_acres,
    a.area_row_acres,
    a.area_parcel_res,
    a.area_parcel_res_acres,
    a.area_parcel_emp_ag,
    a.area_parcel_emp_ag_acres,
    a.area_parcel_emp,
    a.area_parcel_emp_acres,
    a.area_parcel_mixed_use,
    a.area_parcel_mixed_use_acres,
    a.area_parcel_no_use,
    a.area_parcel_no_use_acres,
    COALESCE(a.pop, r.county_avg_pop, 0.0) AS pop,
    COALESCE(a.pop_groupquarter, 0.0) AS pop_groupquarter,
    COALESCE(a.hh, r.county_avg_hh, 0.0) AS hh,
    COALESCE(a.du, r.county_avg_du, 0.0) AS du,
    COALESCE(a.du_detsf, dp.pct_detsf_sl * COALESCE(a.du, r.county_avg_du, 0.0)
        + dp.pct_detsf_ll * COALESCE(a.du, r.county_avg_du, 0.0), 0.0) AS du_detsf,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_detsf_sl * a.du, 0.0)
        ELSE COALESCE(a.du_detsf_sl, dp.pct_detsf_sl * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_detsf_sl,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_detsf_ll * a.du, 0.0)
        ELSE COALESCE(a.du_detsf_ll, dp.pct_detsf_ll * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_detsf_ll,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_attsf * a.du, 0.0)
        ELSE COALESCE(a.du_attsf, dp.pct_attsf * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_attsf,
    COALESCE(a.du_mf, dp.pct_mf2to4 * COALESCE(a.du, r.county_avg_du, 0.0)
        + dp.pct_mf5p * COALESCE(a.du, r.county_avg_du, 0.0), 0.0) AS du_mf,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_mf2to4 * a.du, 0.0)
        ELSE COALESCE(a.du_mf2to4, dp.pct_mf2to4 * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_mf2to4,
    CASE
        WHEN a.du IS NOT NULL AND a.du > 0
             AND COALESCE(a.du_detsf_sl, 0) = 0 AND COALESCE(a.du_detsf_ll, 0) = 0
             AND COALESCE(a.du_attsf, 0) = 0 AND COALESCE(a.du_mf2to4, 0) = 0
             AND COALESCE(a.du_mf5p, 0) = 0
        THEN COALESCE(dp.pct_mf5p * a.du, 0.0)
        ELSE COALESCE(a.du_mf5p, dp.pct_mf5p * COALESCE(a.du, r.county_avg_du, 0.0), 0.0)
    END AS du_mf5p,
    a.du_subtype,
    a.is_residential,
    COALESCE(a.residential_building_sqft, 0.0) AS residential_building_sqft,
    COALESCE(a.commercial_building_sqft, 0.0) AS commercial_building_sqft,
    COALESCE(a.industrial_building_sqft, 0.0) AS industrial_building_sqft,
    COALESCE(a.other_building_sqft, 0.0) AS other_building_sqft,
    COALESCE(a.total_footprint_sqft, 0.0) AS total_footprint_sqft,
    COALESCE(a.building_count, 0) AS building_count,
    COALESCE(a.footprint_ratio, 0.0) AS footprint_ratio,
    COALESCE(a.max_levels, 0) AS max_levels,
    COALESCE(a.emp, r.county_avg_emp, 0.0) AS emp,
    a.emp_ret,
    a.emp_retail_services,
    a.emp_restaurant,
    a.emp_accommodation,
    a.emp_arts_entertainment,
    a.emp_other_services,
    a.emp_off,
    a.emp_office_services,
    a.emp_medical_services,
    a.emp_pub,
    a.emp_public_admin,
    a.emp_education,
    a.emp_ind,
    a.emp_manufacturing,
    a.emp_wholesale,
    a.emp_transport_warehousing,
    a.emp_utilities,
    a.emp_construction,
    a.emp_ag,
    a.emp_agriculture,
    a.emp_extraction,
    a.emp_military,
    a.bldg_area_detsf_sl,
    a.bldg_area_detsf_ll,
    a.bldg_area_attsf,
    a.bldg_area_mf,
    a.bldg_area_retail_services,
    a.bldg_area_restaurant,
    a.bldg_area_accommodation,
    a.bldg_area_arts_entertainment,
    a.bldg_area_other_services,
    a.bldg_area_office_services,
    a.bldg_area_public_admin,
    a.bldg_area_education,
    a.bldg_area_medical_services,
    a.bldg_area_transport_warehousing,
    a.bldg_area_wholesale,
    a.residential_irrigated_area,
    a.commercial_irrigated_area,
    a.median_income,
    a.rent_burden_pct,
    a.pct_minority,
    a.pct_college_educated,
    a.cost_burden_pct,
    a.vacancy_rate,
    a.occupied_du,
    a.land_use,
    a.assessor_use_code
FROM attributes a
LEFT JOIN regional_avg r ON a.county = r.county
LEFT JOIN du_subtype_proportions dp ON a.county = dp.county;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_imputed_geom_')
  ON @this_model USING GIST (geometry);;
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_imputed_parcel_id_')
  ON @this_model USING btree (parcel_id);;
ANALYZE @this_model;
