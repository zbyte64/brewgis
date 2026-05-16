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

    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view')) }}

{%- set area_srid = var('projected_srid', 3857) -%}

WITH parcel_geom AS (
    SELECT
        bg.parcel_id,
        bg.geometry,
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
        bg.emp AS bg_emp,
        ST_Transform(bg.geometry, {{ area_srid }}) AS geom_proj
    FROM {{ ref('base_canvas_geometry') }} bg
),

acs_data AS (
    SELECT
        a.geoid,
        a.pop,
        a.hh,
        a.du,
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
        ST_Transform(a.geometry, {{ area_srid }}) AS geom_proj,
        GREATEST(ST_Area(ST_Transform(a.geometry, {{ area_srid }})), 1e-10) AS bg_area
    FROM {{ source('brewgis', 'acs_block_group') }} a
    WHERE a.geometry IS NOT NULL
),

-- Area-weighted spatial allocation: one row per overlapping parcel-acs pair
intersections AS (
    SELECT
        p.parcel_id,
        p.geom_proj AS p_geom,
        a.geom_proj AS a_geom,
        a.pop,
        a.hh,
        a.du,
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
        ST_Area(ST_Intersection(p.geom_proj, a.geom_proj)) / a.bg_area AS weight,
        ST_Area(ST_Intersection(p.geom_proj, a.geom_proj)) AS int_area
    FROM parcel_geom p
    JOIN acs_data a ON ST_Intersects(p.geom_proj, a.geom_proj)
),

allocated AS (
    SELECT
        parcel_id,
        -- Sum columns: weighted by intersection fraction
        SUM(pop * weight) AS pop,
        SUM(hh * weight) AS hh,
        SUM(du * weight) AS du,
        SUM(du_detsf_sl * weight) AS du_detsf_sl,
        SUM(du_detsf_ll * weight) AS du_detsf_ll,
        SUM(du_attsf * weight) AS du_attsf,
        SUM(du_mf * weight) AS du_mf,
        SUM(du_mf2to4 * weight) AS du_mf2to4,
        SUM(du_mf5p * weight) AS du_mf5p,
        -- Average columns: area-weighted mean across intersecting BGs
        SUM(median_income * int_area) / NULLIF(SUM(int_area), 0) AS median_income,
        SUM(rent_burden_pct * int_area) / NULLIF(SUM(int_area), 0) AS rent_burden_pct,
        SUM(pct_minority * int_area) / NULLIF(SUM(int_area), 0) AS pct_minority,
        SUM(pct_college_educated * int_area) / NULLIF(SUM(int_area), 0) AS pct_college_educated,
        SUM(cost_burden_pct * int_area) / NULLIF(SUM(int_area), 0) AS cost_burden_pct
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
    -- Demographics (fall back to geometry pass-through if no ACS match)
    COALESCE(a.pop, p.bg_pop) AS pop,
    NULL::double precision AS pop_groupquarter,
    COALESCE(a.hh, p.bg_hh) AS hh,
    COALESCE(a.du, p.bg_du) AS du,
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
    -- Carry-through employment from geometry
    p.bg_emp AS emp
FROM parcel_geom p
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id
