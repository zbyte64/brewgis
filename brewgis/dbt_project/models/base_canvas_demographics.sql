{#
    Base Canvas Demographics — spatial allocation from Census ACS.

    For each parcel in ``base_canvas_geometry``, area-weight allocates
    demographic values from intersecting ACS block groups.

    Sum columns (population, households, dwelling units, sub-types):
        Allocated proportional to intersection area ÷ source area.

    Average columns (median_income, rent_burden_pct, etc.):
        Area-weighted average across intersecting block groups.

    When ACS data is unavailable or the spatial join produces no match,
    columns are left NULL for downstream imputation.

    Materialized as: table
#}
{{ config(
    materialized=var('base_canvas_materialized', 'table'),
    indexes=[
        {'columns': ['geometry'], 'type': 'gist'},
        {'columns': ['local_geometry'], 'type': 'gist'},
        {'columns': ['parcel_id'], 'unique': True},
    ])
}}

{%- set area_srid = var('projected_srid', 3857) -%}

WITH parcel_geom AS (
    SELECT
        bg.parcel_id,
        bg.geometry,
        bg.local_geometry,
        bg.county,
        bg.land_development_category,
        bg.built_form_key,
        bg.intersection_density,
        bg.area_gross,
        bg.area_parcel,
        bg.area_dev_condition,
        bg.area_row,
        bg.pop AS bg_pop,
        bg.hh AS bg_hh,
        bg.du AS bg_du,
        bg.bldg_area_detsf_sl,
        bg.bldg_area_detsf_ll,
        bg.bldg_area_attsf,
        bg.bldg_area_mf,
        bg.bldg_area_retail_services,
        bg.bldg_area_restaurant,
        bg.bldg_area_accommodation,
        bg.bldg_area_arts_entertainment,
        bg.bldg_area_other_services,
        bg.bldg_area_office_services,
        bg.bldg_area_public_admin,
        bg.bldg_area_education,
        bg.bldg_area_medical_services,
        bg.bldg_area_transport_warehousing,
        bg.bldg_area_wholesale,
        bg.land_use,
        bg.assessor_use_code,
        bg.residential_irrigated_area,
        bg.commercial_irrigated_area,
        bg.area_parcel_res,
        bg.area_parcel_emp_ag,
        bg.area_parcel_emp,
        bg.area_parcel_mixed_use,
        bg.area_parcel_no_use,
        bg.local_geometry AS geom_proj
    FROM {{ ref('base_canvas_geometry') }} bg
),

pre_acs_data AS (
    SELECT
        a.*,
        ST_Transform(a.geometry, {{ area_srid }}) AS geom_proj
    FROM {{ source('census', 'acs_block_group') }} a
    WHERE a.geometry IS NOT NULL
),

acs_data AS (
    SELECT
        a.*,
        GREATEST(ST_Area(a.geom_proj), 1e-10) AS bg_area,
        ST_Envelope(a.geom_proj) AS local_envelope
    FROM pre_acs_data a
),

-- Area-weighted spatial allocation: one row per overlapping parcel-acs pair
intersections AS (
    SELECT
        p.parcel_id,
        a.pop,
        a.hh,
        a.du,
        a.du_detsf,
        a.du_detsf_sl,
        a.du_detsf_ll,
        a.du_attsf,
        a.du_mf,
        a.du_mf2to4,
        a.du_mf5p,
        a.median_income,
        a.rent_burden_pct,
        a.pct_minority,
        a.pct_college_educated,
        a.cost_burden_pct,
        a.bg_area,
        -- More accurate but 3x slower: ST_Area(ST_Intersection(p.geom_proj, a.geom_proj)) AS intersect_area
        ST_Area(ST_ClipByBox2D(p.geom_proj, a.local_envelope)) AS intersect_area
    FROM parcel_geom p
    -- JOIN is on two indexed intersections
    JOIN acs_data a ON ST_Intersects(p.geometry, a.geometry)
),

allocated AS (
    SELECT
        parcel_id,
        -- Sum columns: weighted by intersection fraction
        SUM(pop * intersect_area / bg_area) AS pop,
        SUM(hh * intersect_area / bg_area) AS hh,
        SUM(du * intersect_area / bg_area) AS du,
        SUM(du_detsf * intersect_area / bg_area) AS du_detsf,
        SUM(du_detsf_sl * intersect_area / bg_area) AS du_detsf_sl,
        SUM(du_detsf_ll * intersect_area / bg_area) AS du_detsf_ll,
        SUM(du_attsf * intersect_area / bg_area) AS du_attsf,
        SUM(du_mf * intersect_area / bg_area) AS du_mf,
        SUM(du_mf2to4 * intersect_area / bg_area) AS du_mf2to4,
        SUM(du_mf5p * intersect_area / bg_area) AS du_mf5p,
        -- Average columns: area-weighted mean across intersecting BGs
        SUM(median_income * intersect_area) / NULLIF(SUM(intersect_area), 0) AS median_income,
        SUM(rent_burden_pct * intersect_area) / NULLIF(SUM(intersect_area), 0) AS rent_burden_pct,
        SUM(pct_minority * intersect_area) / NULLIF(SUM(intersect_area), 0) AS pct_minority,
        SUM(pct_college_educated * intersect_area) / NULLIF(SUM(intersect_area), 0) AS pct_college_educated,
        SUM(cost_burden_pct * intersect_area) / NULLIF(SUM(intersect_area), 0) AS cost_burden_pct
    FROM intersections
    GROUP BY parcel_id
)

SELECT
    p.parcel_id,
    p.geometry,
    p.local_geometry,
    p.county,
    p.land_development_category,
    p.built_form_key,
    p.intersection_density,
    p.area_gross,
    p.area_parcel,
    p.area_dev_condition,
    p.area_row,
    -- Demographics (fall back to geometry pass-through if no ACS match)
    COALESCE(a.pop, p.bg_pop) AS pop,
    NULL::double precision AS pop_groupquarter,
    COALESCE(a.hh, p.bg_hh) AS hh,
    COALESCE(a.du, p.bg_du) AS du,
    a.du_detsf,
    a.du_detsf_sl,
    a.du_detsf_ll,
    a.du_attsf,
    a.du_mf,
    a.du_mf2to4,
    a.du_mf5p,
    a.median_income,
    a.rent_burden_pct,
    a.pct_minority,
    a.pct_college_educated,
    a.cost_burden_pct,
    -- Employment is sourced entirely from LEHD allocation in base_canvas_employment
    NULL::double precision AS emp,
    -- Building areas and irrigation (pass-through to downstream models)
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
    p.land_use,
    p.assessor_use_code,
    p.residential_irrigated_area,
    p.commercial_irrigated_area,
    p.area_parcel_res,
    p.area_parcel_emp_ag,
    p.area_parcel_emp,
    p.area_parcel_mixed_use,
    p.area_parcel_no_use
FROM parcel_geom p
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id
