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

    Materialized as: table
#}
{{ config(materialized=var('base_canvas_materialized', 'table'),
    indexes=[
        {'columns': ['geometry'], 'type': 'gist'},
        {'columns': ['local_geometry'], 'type': 'gist'},
        {'columns': ['parcel_id'], 'unique': True},
    ])
}}

{%- set area_srid = var('projected_srid', 3857) -%}
{%- set quick_parcel_clipping = var('quick_parcel_clipping', true) -%}

WITH pre_wac_data AS (
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
        ST_Transform(w.geometry, {{ area_srid }}) AS local_geometry
    FROM {{ source('lehd', 'wac_block') }} w
    WHERE w.geometry IS NOT NULL
),

wac_data AS (
    SELECT
        w.*,
        GREATEST(ST_Area(w.local_geometry), 1e-10) AS wac_area,
        ST_Envelope(w.local_geometry) AS wac_envelope
    FROM pre_wac_data w
),

-- Area-weighted spatial allocation (unfiltered — no land-use constraints)
-- Land-use filtering was removed because area-weighted block-to-parcel
-- allocation distributes block-group employment proportionally.  A parcel's
-- share represents jobs at nearby parcels within the same block, not jobs
-- on the parcel itself, so land-use constraints would silently discard
-- legitimate allocations.
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
        {% if quick_parcel_clipping %}
        ST_Area(ST_ClipByBox2D(p.local_geometry, w.wac_envelope)) AS intersect_area
        {% else %}
        ST_Area(ST_Intersection(p.local_geometry, w.local_geometry)) AS intersect_area
        {% endif %}
    FROM {{ ref('base_canvas_demographics') }} p
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
    p.local_geometry,
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
    -- Building areas and irrigation (pass-through from demographics)
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
    p.area_parcel_no_use,
    -- Employment (area-weighted from LEHD LODES WAC — no land-use constraints)
    CASE WHEN a.parcel_id IS NOT NULL
        THEN COALESCE(a.emp_retail_services, 0) + COALESCE(a.emp_restaurant, 0)
            + COALESCE(a.emp_accommodation, 0) + COALESCE(a.emp_arts_entertainment, 0)
            + COALESCE(a.emp_other_services, 0) + COALESCE(a.emp_office_services, 0)
            + COALESCE(a.emp_medical_services, 0) + COALESCE(a.emp_public_admin, 0)
            + COALESCE(a.emp_education, 0) + COALESCE(a.emp_manufacturing, 0)
            + COALESCE(a.emp_wholesale, 0) + COALESCE(a.emp_transport_warehousing, 0)
            + COALESCE(a.emp_utilities, 0) + COALESCE(a.emp_construction, 0)
            + COALESCE(a.emp_agriculture, 0) + COALESCE(a.emp_extraction, 0)
            + COALESCE(a.emp_military, 0)
        ELSE 0.0
    END AS emp,
    COALESCE(a.emp_retail_services, 0) + COALESCE(a.emp_restaurant, 0)
        + COALESCE(a.emp_accommodation, 0) + COALESCE(a.emp_arts_entertainment, 0)
        + COALESCE(a.emp_other_services, 0) AS emp_ret,
    a.emp_retail_services,
    a.emp_restaurant,
    a.emp_accommodation,
    a.emp_arts_entertainment,
    a.emp_other_services,
    COALESCE(a.emp_office_services, 0) + COALESCE(a.emp_medical_services, 0) AS emp_off,
    a.emp_office_services,
    a.emp_medical_services,
    COALESCE(a.emp_public_admin, 0) + COALESCE(a.emp_education, 0) AS emp_pub,
    a.emp_public_admin,
    a.emp_education,
    COALESCE(a.emp_manufacturing, 0) + COALESCE(a.emp_wholesale, 0)
        + COALESCE(a.emp_transport_warehousing, 0) + COALESCE(a.emp_utilities, 0)
        + COALESCE(a.emp_construction, 0) AS emp_ind,
    a.emp_manufacturing,
    a.emp_wholesale,
    a.emp_transport_warehousing,
    a.emp_utilities,
    a.emp_construction,
    COALESCE(a.emp_agriculture, 0) AS emp_ag,
    a.emp_agriculture,
    a.emp_extraction,
    a.emp_military
FROM {{ ref('base_canvas_demographics') }} p
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id
