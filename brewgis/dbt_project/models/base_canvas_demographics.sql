{#
    Base Canvas Demographics — spatial allocation from Census ACS.

    For each parcel in ``base_canvas_geometry``, allocates demographic values
    from intersecting ACS block groups.

    Sum columns (population, households, dwelling units, sub-types):
        By default: proportional to intersection area ÷ source area.
        With dasymetric weights: proportional to ``pop_dasym_weight * intersect_area``
        per block group, enabling parcel-level refinement from assessor data.

    Average columns (median_income, rent_burden_pct, etc.):
        Area-weighted mean across intersecting block groups (unchanged).

    Dasymetric weighting is enabled by setting the ``dasymetric_weights_table``
    dbt var to a table containing ``parcel_id`` and ``pop_dasym_weight``.

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
{%- set dasym_table = var('dasymetric_weights_table', none) -%}

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
        {% if dasym_table %}
        ,
        dw.pop_dasym_weight
        {% endif %}
    FROM {{ ref('base_canvas_geometry') }} bg
    {% if dasym_table %}
    LEFT JOIN {{ dasym_table }} dw
        ON bg.parcel_id::text = dw.parcel_id
    {% endif %}
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

-- Spatial allocation: one row per overlapping parcel-acs pair
intersections AS (
    SELECT
        p.parcel_id,
        a.geoid,
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
        {% if dasym_table %}
        COALESCE(p.pop_dasym_weight, 1.0) AS pop_dasym_weight,
        {% endif %}
        ST_Area(ST_ClipByBox2D(p.geom_proj, a.local_envelope)) AS intersect_area
    FROM parcel_geom p
    JOIN acs_data a ON ST_Intersects(p.geometry, a.geometry)
)

{% if dasym_table %}
-- Per-block-group total dasymetric weight for normalization
, bg_weights AS (
    SELECT
        i.geoid,
        SUM(i.pop_dasym_weight * i.intersect_area) AS total_pop_weight
    FROM intersections i
    GROUP BY i.geoid
)

, allocated AS (
    SELECT
        i.parcel_id,
        SUM(i.pop * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS pop,
        SUM(i.hh * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS hh,
        SUM(i.du * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du,
        SUM(i.du_detsf * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_detsf,
        SUM(i.du_detsf_sl * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_detsf_sl,
        SUM(i.du_detsf_ll * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_detsf_ll,
        SUM(i.du_attsf * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_attsf,
        SUM(i.du_mf * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_mf,
        SUM(i.du_mf2to4 * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_mf2to4,
        SUM(i.du_mf5p * i.pop_dasym_weight * i.intersect_area
            / NULLIF(bw.total_pop_weight, 0)) AS du_mf5p,
        SUM(i.median_income * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0)
            AS median_income,
        SUM(i.rent_burden_pct * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0)
            AS rent_burden_pct,
        SUM(i.pct_minority * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0)
            AS pct_minority,
        SUM(i.pct_college_educated * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0)
            AS pct_college_educated,
        SUM(i.cost_burden_pct * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0)
            AS cost_burden_pct
    FROM intersections i
    LEFT JOIN bg_weights bw ON i.geoid = bw.geoid
    GROUP BY i.parcel_id
)

{% else %}

, allocated AS (
    SELECT
        parcel_id,
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
        SUM(median_income * intersect_area) / NULLIF(SUM(intersect_area), 0) AS median_income,
        SUM(rent_burden_pct * intersect_area) / NULLIF(SUM(intersect_area), 0) AS rent_burden_pct,
        SUM(pct_minority * intersect_area) / NULLIF(SUM(intersect_area), 0) AS pct_minority,
        SUM(pct_college_educated * intersect_area) / NULLIF(SUM(intersect_area), 0) AS pct_college_educated,
        SUM(cost_burden_pct * intersect_area) / NULLIF(SUM(intersect_area), 0) AS cost_burden_pct
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
    NULL::double precision AS emp,
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
