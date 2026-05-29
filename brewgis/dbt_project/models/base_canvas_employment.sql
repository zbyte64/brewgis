{#
    Base Canvas Employment — spatial allocation from LEHD LODES WAC.

    For each parcel from ``base_canvas_demographics``, allocates employment
    values from intersecting LEHD WAC blocks.

    Sub-sector employment columns are allocated proportionally from the WAC
    table.  Aggregate columns and total emp are computed by summing sub-sectors.

    By default uses area-weighted allocation.  When ``dasymetric_weights_table``
    is set, employment is allocated proportional to ``emp_dasym_weight * intersect_area``
    per WAC block, enabling parcel-level refinement from assessor data.

    When ``employment_land_use_constrain`` is true, allocates employment types
    only to parcels with matching land development categories:
      - emp_weight: 0 for `undeveloped`, 1 otherwise (applied to all employment)
      - ind_weight: 1 for `industrial` or NULL, 0 otherwise (emp_ind sub-sectors)
      - ag_weight: 1 for `agricultural`/`industrial` or NULL, 0 otherwise (emp_ag sub-sectors)

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
{%- set dasym_table = var('dasymetric_weights_table', none) -%}
{%- set constrain = var('employment_land_use_constrain', false) -%}

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

-- Parcel geometry with optional dasymetric weight join
parcel_with_weights AS (
    SELECT
        p.*
        {% if dasym_table %}
        ,
        dw.emp_dasym_weight
        {% endif %}
    FROM {{ ref('base_canvas_demographics') }} p
    {% if dasym_table %}
    LEFT JOIN {{ dasym_table }} dw
        ON p.parcel_id::text = dw.parcel_id
    {% endif %}
),

intersections AS (
    SELECT
        p.parcel_id,
        {% if dasym_table %}
        w.geoid,
        {% endif %}
        p.land_development_category,
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
        {% if dasym_table %}
        COALESCE(p.emp_dasym_weight, 1.0) AS emp_dasym_weight,
        {% endif %}
        {% if constrain %}
        CASE WHEN p.land_development_category = 'undeveloped' THEN 0.0 ELSE 1.0 END AS emp_weight,
        CASE WHEN p.land_development_category = 'industrial' OR p.land_development_category IS NULL THEN 1.0 ELSE 0.0 END AS ind_weight,
        CASE WHEN p.land_development_category IN ('agricultural', 'industrial') OR p.land_development_category IS NULL THEN 1.0 ELSE 0.0 END AS ag_weight,
        {% endif %}
        {% if quick_parcel_clipping %}
        ST_Area(ST_ClipByBox2D(p.local_geometry, w.wac_envelope)) AS intersect_area
        {% else %}
        ST_Area(ST_Intersection(p.local_geometry, w.local_geometry)) AS intersect_area
        {% endif %}
    FROM parcel_with_weights p
    JOIN wac_data w ON ST_Intersects(p.geometry, w.geometry)
)

{% if dasym_table %}
-- Per-WAC-block total dasymetric weight for normalization
, wac_weights AS (
    SELECT
        i.geoid,
        SUM(i.emp_dasym_weight * i.intersect_area) AS total_emp_weight
    FROM intersections i
    GROUP BY i.geoid
)

, allocated AS (
    SELECT
        i.parcel_id,
        SUM(i.emp * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp,
        SUM(i.emp_retail_services * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_retail_services,
        SUM(i.emp_restaurant * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_restaurant,
        SUM(i.emp_accommodation * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_accommodation,
        SUM(i.emp_arts_entertainment * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_arts_entertainment,
        SUM(i.emp_other_services * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_other_services,
        SUM(i.emp_office_services * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_office_services,
        SUM(i.emp_medical_services * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_medical_services,
        SUM(i.emp_public_admin * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_public_admin,
        SUM(i.emp_education * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_education,
        SUM(i.emp_manufacturing * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ind_weight{% endif %}) AS emp_manufacturing,
        SUM(i.emp_wholesale * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ind_weight{% endif %}) AS emp_wholesale,
        SUM(i.emp_transport_warehousing * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ind_weight{% endif %}) AS emp_transport_warehousing,
        SUM(i.emp_utilities * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ind_weight{% endif %}) AS emp_utilities,
        SUM(i.emp_construction * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ind_weight{% endif %}) AS emp_construction,
        SUM(i.emp_agriculture * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ag_weight{% endif %}) AS emp_agriculture,
        SUM(i.emp_extraction * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ag_weight{% endif %}) AS emp_extraction,
        SUM(i.emp_military * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_military,
        SUM(i.emp_ret * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_ret,
        SUM(i.emp_off * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_off,
        SUM(i.emp_pub * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.emp_weight{% endif %}) AS emp_pub,
        SUM(i.emp_ind * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ind_weight{% endif %}) AS emp_ind,
        SUM(i.emp_ag * i.emp_dasym_weight * i.intersect_area
            / NULLIF(wac_weights.total_emp_weight, 0)
            {% if constrain %} * i.ag_weight{% endif %}) AS emp_ag
    FROM intersections i
    LEFT JOIN wac_weights ON i.geoid = wac_weights.geoid
    GROUP BY i.parcel_id
)

{% else %}

, allocated AS (
    SELECT
        parcel_id,
        SUM(emp * intersect_area / wac_area{% if constrain %} * emp_weight{% endif %}) AS emp,
        SUM(emp_retail_services * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_retail_services,
        SUM(emp_restaurant * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_restaurant,
        SUM(emp_accommodation * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_accommodation,
        SUM(emp_arts_entertainment * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_arts_entertainment,
        SUM(emp_other_services * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_other_services,
        SUM(emp_office_services * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_office_services,
        SUM(emp_medical_services * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_medical_services,
        SUM(emp_public_admin * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_public_admin,
        SUM(emp_education * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_education,
        SUM(emp_manufacturing * intersect_area / wac_area
            {% if constrain %} * ind_weight{% endif %}) AS emp_manufacturing,
        SUM(emp_wholesale * intersect_area / wac_area
            {% if constrain %} * ind_weight{% endif %}) AS emp_wholesale,
        SUM(emp_transport_warehousing * intersect_area / wac_area
            {% if constrain %} * ind_weight{% endif %}) AS emp_transport_warehousing,
        SUM(emp_utilities * intersect_area / wac_area
            {% if constrain %} * ind_weight{% endif %}) AS emp_utilities,
        SUM(emp_construction * intersect_area / wac_area
            {% if constrain %} * ind_weight{% endif %}) AS emp_construction,
        SUM(emp_agriculture * intersect_area / wac_area
            {% if constrain %} * ag_weight{% endif %}) AS emp_agriculture,
        SUM(emp_extraction * intersect_area / wac_area
            {% if constrain %} * ag_weight{% endif %}) AS emp_extraction,
        SUM(emp_military * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_military,
        SUM(emp_ret * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_ret,
        SUM(emp_off * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_off,
        SUM(emp_pub * intersect_area / wac_area
            {% if constrain %} * emp_weight{% endif %}) AS emp_pub,
        SUM(emp_ind * intersect_area / wac_area
            {% if constrain %} * ind_weight{% endif %}) AS emp_ind,
        SUM(emp_ag * intersect_area / wac_area
            {% if constrain %} * ag_weight{% endif %}) AS emp_ag
    FROM intersections
    GROUP BY parcel_id
)

{% endif %}

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
