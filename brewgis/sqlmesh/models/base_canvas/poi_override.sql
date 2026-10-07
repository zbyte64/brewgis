MODEL (
  name brewgis.@{region}.base_canvas_poi_override,
  kind FULL,
  description 'Parcel-level base canvas with the OpenStreetMap points of interest inside each parcel turned into a built form: a parcel containing a POI of a mapped category takes the built form key that category maps to, and its dwelling units and employment are set from that built form''s densities and jobs_by_sector mix instead of the regressor/LEHD allocation.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier; one row per parcel in the base canvas.',
    geometry = 'Parcel boundary geometry (MultiPolygon, EPSG:4326).',
    local_geometry = 'Parcel boundary in the local projected SRID used for area and clipping math.',
    county = 'County the parcel falls in, carried from the parcel source.',
    land_development_category = 'Land development category carried from base_canvas_combined.',
    built_form_key = 'Built form key: the POI-derived built form when a point of interest falls in the parcel, otherwise the key base_canvas_combined assigned.',
    intersection_density = 'Intersection density carried from base_canvas_combined (intersections per square mile).',
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
    pop = 'Population carried from base_canvas_combined (people).',
    pop_groupquarter = 'Group quarters population carried from base_canvas_combined (people).',
    hh = 'Households carried from base_canvas_combined (count).',
    du = 'Dwelling units: the matched built form''s du_per_acre times the parcel acres, otherwise the value base_canvas_combined derived (count).',
    du_estimated = 'Dwelling units the dasymetric regressor estimated, carried from base_canvas_combined (count).',
    du_detsf = 'Detached single-family dwelling units: zero on a parcel overridden to a built form, otherwise carried from base_canvas_combined (count).',
    du_detsf_sl = 'Detached single-family small-lot dwelling units: zero on an overridden parcel, otherwise carried from base_canvas_combined (count).',
    du_detsf_ll = 'Detached single-family large-lot dwelling units: zero on an overridden parcel, otherwise carried from base_canvas_combined (count).',
    du_attsf = 'Attached single-family dwelling units: zero on an overridden parcel, otherwise carried from base_canvas_combined (count).',
    du_mf = 'Multi-family dwelling units: zero on an overridden parcel, otherwise carried from base_canvas_combined (count).',
    du_mf2to4 = 'Multi-family 2-4 unit dwelling units: zero on an overridden parcel, otherwise carried from base_canvas_combined (count).',
    du_mf5p = 'Multi-family 5+ unit dwelling units: zero on an overridden parcel, otherwise carried from base_canvas_combined (count).',
    du_subtype = 'Dwelling unit subtype key carried from base_canvas_combined.',
    is_residential = 'Residential flag: 0 when the parcel was overridden to a built form, otherwise the flag base_canvas_combined derived.',
    residential_building_sqft = 'Residential building floor area carried from base_canvas_combined (sq ft).',
    commercial_building_sqft = 'Commercial building floor area carried from base_canvas_combined (sq ft).',
    industrial_building_sqft = 'Industrial building floor area carried from base_canvas_combined (sq ft).',
    other_building_sqft = 'Other building floor area carried from base_canvas_combined (sq ft).',
    total_footprint_sqft = 'Total building footprint area carried from base_canvas_combined (sq ft).',
    building_count = 'Number of buildings on the parcel carried from base_canvas_combined (count).',
    footprint_ratio = 'Building footprint share of the parcel carried from base_canvas_combined (ratio, 0-1).',
    max_levels = 'Maximum building levels on the parcel carried from base_canvas_combined (count).',
    emp_dasym_weight = 'Lot-size-based employment weight carried from base_canvas_combined (weight).',
    emp = 'Total employment: the matched built form''s emp_per_acre times the parcel acres, otherwise the value base_canvas_combined derived (jobs).',
    emp_ret = 'Retail employment: the overridden retail sub-sectors summed when a built form matched, otherwise carried from base_canvas_combined (jobs).',
    emp_off = 'Office employment: the overridden office sub-sectors summed when a built form matched, otherwise carried from base_canvas_combined (jobs).',
    emp_pub = 'Public employment: the overridden public sub-sectors summed when a built form matched, otherwise carried from base_canvas_combined (jobs).',
    emp_ind = 'Industrial employment: the overridden industrial sub-sectors summed when a built form matched, otherwise carried from base_canvas_combined (jobs).',
    emp_ag = 'Agricultural employment: the overridden agricultural sub-sectors summed when a built form matched, otherwise carried from base_canvas_combined (jobs).',
    emp_military = 'Military employment: the overridden military share when a built form matched, otherwise carried from base_canvas_combined (jobs).',
    emp_retail_services = 'Retail services employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_restaurant = 'Restaurant employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_accommodation = 'Accommodation employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_arts_entertainment = 'Arts and entertainment employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_other_services = 'Other services employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_office_services = 'Office services employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_medical_services = 'Medical services employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_public_admin = 'Public administration employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_education = 'Education employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_manufacturing = 'Manufacturing employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_wholesale = 'Wholesale employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_transport_warehousing = 'Transport and warehousing employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_utilities = 'Utilities employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_construction = 'Construction employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_agriculture = 'Agriculture employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    emp_extraction = 'Extraction employment: the matched built form''s share of its job total, otherwise carried from base_canvas_combined (jobs).',
    bldg_area_detsf_sl = 'Detached single-family small-lot building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_detsf_ll = 'Detached single-family large-lot building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_attsf = 'Attached single-family building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_mf = 'Multi-family building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_retail_services = 'Retail services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_restaurant = 'Restaurant building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_accommodation = 'Accommodation building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_arts_entertainment = 'Arts and entertainment building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_other_services = 'Other services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_office_services = 'Office services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_public_admin = 'Public administration building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_education = 'Education building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_medical_services = 'Medical services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_transport_warehousing = 'Transport and warehousing building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_wholesale = 'Wholesale building floor area carried from base_canvas_combined (sq ft).',
    residential_irrigated_area = 'Residential irrigated area carried from base_canvas_combined (acres).',
    commercial_irrigated_area = 'Commercial irrigated area carried from base_canvas_combined (acres).',
    median_income = 'Median household income carried from base_canvas_combined ($ per year).',
    rent_burden_pct = 'Rent-burdened household share carried from base_canvas_combined (% as 0-100).',
    pct_minority = 'Share of people of color carried from base_canvas_combined (% as 0-100).',
    pct_college_educated = 'College-educated adult share carried from base_canvas_combined (% as 0-100).',
    cost_burden_pct = 'Cost-burdened household share carried from base_canvas_combined (% as 0-100).',
    tree_canopy_fraction = 'Tree canopy share of the parcel carried from base_canvas_combined (ratio, 0-1).',
    vacancy_rate = 'Housing vacancy rate carried from base_canvas_combined (ratio, 0-1).',
    du_pop_dasym_weight = 'Dasymetric DU and population weight carried from base_canvas_combined (weight).',
    occupied_du = 'Occupied dwelling units, du times one minus vacancy rate rounded to 2 decimals, recomputed from the overridden du (count).',
    land_use = 'Land use label from the parcel source, matched against the regional land use crosswalk.',
    assessor_use_code = 'Assessor use code from the parcel source, matched on its first two digits.'
  ),
  audits (
    not_null(columns := (parcel_id)),
    number_of_rows(threshold := 1)
  ),
  -- The POI *bridge*, in addition to the published VIEW the SELECT reads:
  -- SQLMesh substitutes a referenced model's physical table in this model's
  -- statements only for a declared dependency, and the pre_statements index
  -- must land on the bridge (Postgres rejects an index on the VIEW).
  depends_on (
    brewgis.seeds.default_built_forms,
    brewgis.seeds.poi_built_form_map,
    brewgis.@{region}.poi,
    brewgis.@{region}.poi_raw
  ),
  blueprints @region_blueprints()
);

-- pre_statements
-- GiST expression index on the POI bridge so the parcel/POI ST_Intersects in
-- poi_match is an index probe per parcel instead of a nested loop over every
-- parcel x POI pair. The expression is exactly what the published
-- brewgis.<region>.poi VIEW inlines into the predicate (ST_SetSRID(geometry,
-- 4326)); an index on the bare column holds SRID 0 and is never used. It cannot
-- live in the bridge's own post_statements: the bridge is duckdb-gateway, and
-- DuckDB has no ST_SetSRID. Version-scoped name for the same reason as
-- analysis/core_end_state.sql.
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_poi_bridge_geom_')
  ON brewgis.@{region}.poi_raw
  USING GIST (ST_SetSRID(geometry, 4326));

-- Base Canvas POI Override — the base canvas with OpenStreetMap points of
-- interest turned into built forms.
--
-- A parcel that contains a point of a mapped POI category takes the built form
-- key that category maps to (``brewgis.seeds.poi_built_form_map``) and its
-- dwelling units and employment are read from that built form's densities and
-- ``jobs_by_sector`` mix (``brewgis.seeds.default_built_forms``) times the
-- parcel's acres. Nothing here is a literal: the densities live in the seeded
-- Building Type library, so retuning a transit station's ``emp_per_acre`` is a
-- one-line change in ``workspace/built_forms/default_library.py``.
--
-- One row per parcel: ``DISTINCT ON`` keeps the lowest-priority-number category
-- (hospitals before schools before ... before parks). A parcel no POI matched
-- passes every column of ``base_canvas_combined`` through untouched.
--
-- The output column set is ``base_canvas_combined``'s, verbatim and in order —
-- this model is a drop-in replacement for it in the base canvas chain.
--
-- Every share in the library is normalized to sum to 100 (the
-- ``default_built_forms`` model), so a mapped form's ``emp_*`` sub-sectors add
-- back up to its ``emp`` and the downstream reconciliation audits
-- (``assert_employment_exclusivity``, ``assert_du_subtype_sum_equals_du``) see
-- a single-sector parcel rather than a mix. All mapped forms are
-- non-residential (``du_per_acre`` 0), so the DU subtype columns are zeroed
-- rather than split: the library carries no per-subtype share to split them by.

WITH combined AS (
    SELECT * FROM brewgis.@{region}.base_canvas_combined
),

-- The built form the parcel's highest-priority POI category maps to. A point on
-- a shared boundary intersects both parcels; each parcel independently keeps its
-- own best match, so at most the shared edge is counted twice.
poi_match AS (
    SELECT DISTINCT ON (p.parcel_id)
        p.parcel_id,
        COALESCE(NULLIF(p.area_gross, 0), NULLIF(p.area_parcel_acres, 0), 0.0) AS acres,
        pm.built_form_key
    FROM combined p
    JOIN brewgis.@{region}.poi poi
        ON ST_Intersects(p.geometry, poi.geometry)
    JOIN brewgis.seeds.poi_built_form_map pm
        ON pm.poi_category = poi.category
    ORDER BY p.parcel_id, pm.priority
),

-- The matched built form's job total over the parcel's acres, and that form's
-- raw share mix. Every ``o_*`` value is null for a parcel no POI matched.
matched AS (
    SELECT
        c.*,
        m.parcel_id IS NOT NULL AS o_matched,
        m.built_form_key AS o_built_form_key,
        COALESCE(b.du_per_acre, 0.0) * m.acres AS o_du_total,
        COALESCE(b.emp_per_acre, 0.0) * m.acres AS o_emp_total,
        CASE WHEN COALESCE(b.du_per_acre, 0) > 0 THEN 1 ELSE 0 END AS o_is_residential,
        (b.jobs_by_sector ->> 'retail_services')::double precision AS o_share_retail_services,
        (b.jobs_by_sector ->> 'restaurant')::double precision AS o_share_restaurant,
        (b.jobs_by_sector ->> 'accommodation')::double precision AS o_share_accommodation,
        (b.jobs_by_sector ->> 'arts_entertainment')::double precision AS o_share_arts_entertainment,
        (b.jobs_by_sector ->> 'other_services')::double precision AS o_share_other_services,
        (b.jobs_by_sector ->> 'office_services')::double precision AS o_share_office_services,
        (b.jobs_by_sector ->> 'medical_services')::double precision AS o_share_medical_services,
        (b.jobs_by_sector ->> 'public_admin')::double precision AS o_share_public_admin,
        (b.jobs_by_sector ->> 'education')::double precision AS o_share_education,
        (b.jobs_by_sector ->> 'manufacturing')::double precision AS o_share_manufacturing,
        (b.jobs_by_sector ->> 'wholesale')::double precision AS o_share_wholesale,
        (b.jobs_by_sector ->> 'transport_warehousing')::double precision AS o_share_transport_warehousing,
        (b.jobs_by_sector ->> 'utilities')::double precision AS o_share_utilities,
        (b.jobs_by_sector ->> 'construction')::double precision AS o_share_construction,
        (b.jobs_by_sector ->> 'agriculture')::double precision AS o_share_agriculture,
        (b.jobs_by_sector ->> 'extraction')::double precision AS o_share_extraction,
        (b.jobs_by_sector ->> 'military')::double precision AS o_share_military
    FROM combined c
    LEFT JOIN poi_match m
        ON c.parcel_id = m.parcel_id
    LEFT JOIN brewgis.seeds.default_built_forms b
        ON b.key = m.built_form_key
),

-- The built form's jobs split by share: each sub-sector is its own share of the
-- form's job total, and each group column is the sum of its own sub-sectors (the
-- base canvas groups, per services/base_canvas_pipeline.py _EMPLOYMENT_COLUMNS).
resolved AS (
    SELECT
        m.*,
        m.o_emp_total * COALESCE(m.o_share_retail_services, 0.0) / 100.0 AS o_emp_retail_services,
        m.o_emp_total * COALESCE(m.o_share_restaurant, 0.0) / 100.0 AS o_emp_restaurant,
        m.o_emp_total * COALESCE(m.o_share_accommodation, 0.0) / 100.0 AS o_emp_accommodation,
        m.o_emp_total * COALESCE(m.o_share_arts_entertainment, 0.0) / 100.0 AS o_emp_arts_entertainment,
        m.o_emp_total * COALESCE(m.o_share_other_services, 0.0) / 100.0 AS o_emp_other_services,
        m.o_emp_total * COALESCE(m.o_share_office_services, 0.0) / 100.0 AS o_emp_office_services,
        m.o_emp_total * COALESCE(m.o_share_medical_services, 0.0) / 100.0 AS o_emp_medical_services,
        m.o_emp_total * COALESCE(m.o_share_public_admin, 0.0) / 100.0 AS o_emp_public_admin,
        m.o_emp_total * COALESCE(m.o_share_education, 0.0) / 100.0 AS o_emp_education,
        m.o_emp_total * COALESCE(m.o_share_manufacturing, 0.0) / 100.0 AS o_emp_manufacturing,
        m.o_emp_total * COALESCE(m.o_share_wholesale, 0.0) / 100.0 AS o_emp_wholesale,
        m.o_emp_total * COALESCE(m.o_share_transport_warehousing, 0.0) / 100.0 AS o_emp_transport_warehousing,
        m.o_emp_total * COALESCE(m.o_share_utilities, 0.0) / 100.0 AS o_emp_utilities,
        m.o_emp_total * COALESCE(m.o_share_construction, 0.0) / 100.0 AS o_emp_construction,
        m.o_emp_total * COALESCE(m.o_share_agriculture, 0.0) / 100.0 AS o_emp_agriculture,
        m.o_emp_total * COALESCE(m.o_share_extraction, 0.0) / 100.0 AS o_emp_extraction,
        m.o_emp_total * COALESCE(m.o_share_military, 0.0) / 100.0 AS o_emp_military,
        m.o_emp_total * (
            COALESCE(m.o_share_retail_services, 0.0)
            + COALESCE(m.o_share_restaurant, 0.0)
            + COALESCE(m.o_share_accommodation, 0.0)
            + COALESCE(m.o_share_arts_entertainment, 0.0)
            + COALESCE(m.o_share_other_services, 0.0)
        ) / 100.0 AS o_emp_ret,
        m.o_emp_total * (
            COALESCE(m.o_share_office_services, 0.0)
            + COALESCE(m.o_share_medical_services, 0.0)
        ) / 100.0 AS o_emp_off,
        m.o_emp_total * (
            COALESCE(m.o_share_public_admin, 0.0)
            + COALESCE(m.o_share_education, 0.0)
        ) / 100.0 AS o_emp_pub,
        m.o_emp_total * (
            COALESCE(m.o_share_manufacturing, 0.0)
            + COALESCE(m.o_share_wholesale, 0.0)
            + COALESCE(m.o_share_transport_warehousing, 0.0)
            + COALESCE(m.o_share_utilities, 0.0)
            + COALESCE(m.o_share_construction, 0.0)
        ) / 100.0 AS o_emp_ind,
        m.o_emp_total * (
            COALESCE(m.o_share_agriculture, 0.0)
            + COALESCE(m.o_share_extraction, 0.0)
        ) / 100.0 AS o_emp_ag
    FROM matched m
)

SELECT
    c.parcel_id,
    c.geometry,
    c.local_geometry,
    c.county,
    c.land_development_category,
    CASE WHEN c.o_matched THEN c.o_built_form_key ELSE c.built_form_key END AS built_form_key,
    c.intersection_density,
    c.area_gross,
    c.area_gross_acres,
    c.area_parcel_acres,
    c.area_dev_condition_acres,
    c.area_row_acres,
    c.area_parcel_res,
    c.area_parcel_res_acres,
    c.area_parcel_emp_ag,
    c.area_parcel_emp_ag_acres,
    c.area_parcel_emp,
    c.area_parcel_emp_acres,
    c.area_parcel_mixed_use,
    c.area_parcel_mixed_use_acres,
    c.area_parcel_no_use,
    c.area_parcel_no_use_acres,
    c.pop,
    c.pop_groupquarter,
    c.hh,
    CASE WHEN c.o_matched THEN c.o_du_total ELSE c.du END AS du,
    c.du_estimated,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_detsf END AS du_detsf,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_detsf_sl END AS du_detsf_sl,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_detsf_ll END AS du_detsf_ll,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_attsf END AS du_attsf,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_mf END AS du_mf,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_mf2to4 END AS du_mf2to4,
    CASE WHEN c.o_matched THEN 0.0 ELSE c.du_mf5p END AS du_mf5p,
    c.du_subtype,
    CASE WHEN c.o_matched THEN c.o_is_residential ELSE c.is_residential END AS is_residential,
    c.residential_building_sqft,
    c.commercial_building_sqft,
    c.industrial_building_sqft,
    c.other_building_sqft,
    c.total_footprint_sqft,
    c.building_count,
    c.footprint_ratio,
    c.max_levels,
    c.emp_dasym_weight,
    CASE WHEN c.o_matched THEN c.o_emp_total ELSE c.emp END AS emp,
    CASE WHEN c.o_matched THEN c.o_emp_ret ELSE c.emp_ret END AS emp_ret,
    CASE WHEN c.o_matched THEN c.o_emp_off ELSE c.emp_off END AS emp_off,
    CASE WHEN c.o_matched THEN c.o_emp_pub ELSE c.emp_pub END AS emp_pub,
    CASE WHEN c.o_matched THEN c.o_emp_ind ELSE c.emp_ind END AS emp_ind,
    CASE WHEN c.o_matched THEN c.o_emp_ag ELSE c.emp_ag END AS emp_ag,
    CASE WHEN c.o_matched THEN c.o_emp_military ELSE c.emp_military END AS emp_military,
    CASE WHEN c.o_matched THEN c.o_emp_retail_services ELSE c.emp_retail_services END AS emp_retail_services,
    CASE WHEN c.o_matched THEN c.o_emp_restaurant ELSE c.emp_restaurant END AS emp_restaurant,
    CASE WHEN c.o_matched THEN c.o_emp_accommodation ELSE c.emp_accommodation END AS emp_accommodation,
    CASE WHEN c.o_matched THEN c.o_emp_arts_entertainment ELSE c.emp_arts_entertainment END AS emp_arts_entertainment,
    CASE WHEN c.o_matched THEN c.o_emp_other_services ELSE c.emp_other_services END AS emp_other_services,
    CASE WHEN c.o_matched THEN c.o_emp_office_services ELSE c.emp_office_services END AS emp_office_services,
    CASE WHEN c.o_matched THEN c.o_emp_medical_services ELSE c.emp_medical_services END AS emp_medical_services,
    CASE WHEN c.o_matched THEN c.o_emp_public_admin ELSE c.emp_public_admin END AS emp_public_admin,
    CASE WHEN c.o_matched THEN c.o_emp_education ELSE c.emp_education END AS emp_education,
    CASE WHEN c.o_matched THEN c.o_emp_manufacturing ELSE c.emp_manufacturing END AS emp_manufacturing,
    CASE WHEN c.o_matched THEN c.o_emp_wholesale ELSE c.emp_wholesale END AS emp_wholesale,
    CASE WHEN c.o_matched THEN c.o_emp_transport_warehousing ELSE c.emp_transport_warehousing END AS emp_transport_warehousing,
    CASE WHEN c.o_matched THEN c.o_emp_utilities ELSE c.emp_utilities END AS emp_utilities,
    CASE WHEN c.o_matched THEN c.o_emp_construction ELSE c.emp_construction END AS emp_construction,
    CASE WHEN c.o_matched THEN c.o_emp_agriculture ELSE c.emp_agriculture END AS emp_agriculture,
    CASE WHEN c.o_matched THEN c.o_emp_extraction ELSE c.emp_extraction END AS emp_extraction,
    c.bldg_area_detsf_sl,
    c.bldg_area_detsf_ll,
    c.bldg_area_attsf,
    c.bldg_area_mf,
    c.bldg_area_retail_services,
    c.bldg_area_restaurant,
    c.bldg_area_accommodation,
    c.bldg_area_arts_entertainment,
    c.bldg_area_other_services,
    c.bldg_area_office_services,
    c.bldg_area_public_admin,
    c.bldg_area_education,
    c.bldg_area_medical_services,
    c.bldg_area_transport_warehousing,
    c.bldg_area_wholesale,
    c.residential_irrigated_area,
    c.commercial_irrigated_area,
    c.median_income,
    c.rent_burden_pct,
    c.pct_minority,
    c.pct_college_educated,
    c.cost_burden_pct,
    c.tree_canopy_fraction,
    c.vacancy_rate,
    c.du_pop_dasym_weight,
    -- Occupancy is du times one minus vacancy in base_canvas_combined; an
    -- overridden parcel's du is not the one that produced its carried value, so
    -- the two are recomputed together.
    CASE WHEN c.o_matched
        THEN ROUND((c.o_du_total * (1.0 - COALESCE(c.vacancy_rate, 0.0)))::numeric, 2)
        ELSE c.occupied_du END AS occupied_du,
    c.land_use,
    c.assessor_use_code
FROM resolved c;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_poi_override_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_poi_override_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
