{#
    Base Canvas Employment — spatial allocation from LEHD LODES WAC.

    For each parcel from ``base_canvas_demographics``, area-weight allocates
    employment values from intersecting LEHD WAC blocks.

    Sub-sector employment columns (emp_retail_services, emp_restaurant, etc.)
    are allocated proportionally from the WAC table.  Aggregate columns
    (emp_ret, emp_off, emp_pub, emp_ind, emp_ag, emp_military) and total
    emp are computed by summing their sub-sectors.

    When LEHD data is unavailable or the spatial join produces no match,
    columns are left NULL for downstream imputation.

    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view')) }}

{%- set area_srid = var('projected_srid', 3857) -%}

WITH parcel_geom AS (
    SELECT
        d.*,
        ST_Transform(d.geometry, {{ area_srid }}) AS geom_proj
    FROM {{ ref('base_canvas_demographics') }} d
),

wac_data AS (
    SELECT
        w.geoid,
        w.emp,
        w.emp_retail_services,
        w.emp_restaurant,
        w.emp_accommodation,
        w.emp_arts_entertainment,
        w.emp_other_services,
        w.emp_office_services,
        w.emp_medical_services,
        w.emp_public_admin,
        w.emp_education,
        w.emp_manufacturing,
        w.emp_wholesale,
        w.emp_transport_warehousing,
        w.emp_utilities,
        w.emp_construction,
        w.emp_agriculture,
        w.emp_extraction,
        w.emp_military,
        w.emp_ret,
        w.emp_off,
        w.emp_pub,
        w.emp_ind,
        w.emp_ag,
        w.geometry,
        ST_Transform(w.geometry, {{ area_srid }}) AS geom_proj,
        GREATEST(ST_Area(ST_Transform(w.geometry, {{ area_srid }})), 1e-10) AS wac_area
    FROM {{ source('lehd', 'wac_block') }} w
    WHERE w.geometry IS NOT NULL
),

-- Area-weighted spatial allocation
intersections AS (
    SELECT
        p.parcel_id,
        w.emp,
        w.emp_retail_services,
        w.emp_restaurant,
        w.emp_accommodation,
        w.emp_arts_entertainment,
        w.emp_other_services,
        w.emp_office_services,
        w.emp_medical_services,
        w.emp_public_admin,
        w.emp_education,
        w.emp_manufacturing,
        w.emp_wholesale,
        w.emp_transport_warehousing,
        w.emp_utilities,
        w.emp_construction,
        w.emp_agriculture,
        w.emp_extraction,
        w.emp_military,
        w.emp_ret,
        w.emp_off,
        w.emp_pub,
        w.emp_ind,
        w.emp_ag,
        w.wac_area,
        ST_Area(ST_Intersection(p.geom_proj, w.geom_proj)) AS intersect_area
    FROM parcel_geom p
    JOIN wac_data w ON ST_Intersects(p.geometry, w.geometry)
),

allocated AS (
    SELECT
        parcel_id,
        SUM(emp * intersect_area / wac_area) AS emp,
        SUM(emp_retail_services * intersect_area / wac_area) AS emp_retail_services,
        SUM(emp_restaurant * intersect_area / wac_area) AS emp_restaurant,
        SUM(emp_accommodation * intersect_area / wac_area) AS emp_accommodation,
        SUM(emp_arts_entertainment * intersect_area / wac_area) AS emp_arts_entertainment,
        SUM(emp_other_services * intersect_area / wac_area) AS emp_other_services,
        SUM(emp_office_services * intersect_area / wac_area) AS emp_office_services,
        SUM(emp_medical_services * intersect_area / wac_area) AS emp_medical_services,
        SUM(emp_public_admin * intersect_area / wac_area) AS emp_public_admin,
        SUM(emp_education * intersect_area / wac_area) AS emp_education,
        SUM(emp_manufacturing * intersect_area / wac_area) AS emp_manufacturing,
        SUM(emp_wholesale * intersect_area / wac_area) AS emp_wholesale,
        SUM(emp_transport_warehousing * intersect_area / wac_area) AS emp_transport_warehousing,
        SUM(emp_utilities * intersect_area / wac_area) AS emp_utilities,
        SUM(emp_construction * intersect_area / wac_area) AS emp_construction,
        SUM(emp_agriculture * intersect_area / wac_area) AS emp_agriculture,
        SUM(emp_extraction * intersect_area / wac_area) AS emp_extraction,
        SUM(emp_military * intersect_area / wac_area) AS emp_military,
        SUM(emp_ret * intersect_area / wac_area) AS emp_ret,
        SUM(emp_off * intersect_area / wac_area) AS emp_off,
        SUM(emp_pub * intersect_area / wac_area) AS emp_pub,
        SUM(emp_ind * intersect_area / wac_area) AS emp_ind,
        SUM(emp_ag * intersect_area / wac_area) AS emp_ag
    FROM intersections
    GROUP BY parcel_id
)

SELECT
    p.parcel_id,
    p.geometry,
    p.county,
    p.land_development_category,
    p.built_form_key,
    p.intersection_density,
    p.area_gross,
    p.area_parcel,
    p.area_dev_condition,
    p.area_row,
    p.pop,
    p.pop_groupquarter,
    p.hh,
    p.du,
    p.du_detsf,
    p.du_detsf_sl,
    p.du_detsf_ll,
    p.du_attsf,
    p.du_mf,
    p.du_mf2to4,
    p.du_mf5p,
    p.median_income,
    p.rent_burden_pct,
    p.pct_minority,
    p.pct_college_educated,
    p.cost_burden_pct,
    -- Employment (from LEHD allocation, or fall through from demographics)
    COALESCE(a.emp, p.emp) AS emp,
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
    a.emp_military
FROM parcel_geom p
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id
