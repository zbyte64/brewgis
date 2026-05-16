{#
    Base Canvas Geometry — first ETL step.

    Reads raw parcel data from the configured source table (via dbt vars),
    casts geometry to PostGIS geometry (EPSG:4326), computes area columns
    from the configured projected SRID, and passes through source columns.

    Source table is resolved via ``source('brewgis', 'parcels')`` which uses
    the ``parcel_table`` var.  In the SACOG comparison context, this resolves
    to ``public.sacog_comparison_parcels``.

    Inputs:
        {{ source('brewgis', 'parcels') }} (dynamic — configured via dbt vars)

    Output columns:
        parcel_id, geometry, county, land_development_category, built_form_key,
        intersection_density, area_gross, area_parcel, area_dev_condition,
        area_row, pop, hh, du, emp, land_use, assessor_use_code,
        bldg_area_* (building area by sub-type), residential_irrigated_area,
        commercial_irrigated_area (raw values preserving NULLs for imputation)

    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view'), indexes=[{'columns': ['geometry'], 'type': 'gist'}]) }}

{%- set area_srid = var('projected_srid', 3857) -%}

WITH parcel_geom AS (
    SELECT
        parcel_id,
        geometry,
        county,
        COALESCE(NULLIF(land_development_category, ''), '') AS land_development_category,
        built_form_key,
        intersection_density,
        pop,
        hh,
        du,
        emp,
        land_use,
        assessor_use_code,
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
        bldg_area_wholesale,
        residential_irrigated_area,
        commercial_irrigated_area,
        area_parcel_res,
        area_parcel_emp_ag,
        area_parcel_emp,
        area_parcel_mixed_use,
        area_parcel_no_use
    FROM {{ source('brewgis', 'parcels') }}
),

parcel_area AS (
    SELECT
        parcel_id,
        geometry,
        county,
        land_development_category,
        built_form_key,
        intersection_density,
        ROUND((ST_Area(ST_Transform(geometry, {{ area_srid }})) / 4046.86)::numeric, 4) AS area_gross,
        pop,
        hh,
        du,
        emp,
        land_use,
        assessor_use_code,
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
        bldg_area_wholesale,
        residential_irrigated_area,
        commercial_irrigated_area,
        area_parcel_res,
        area_parcel_emp_ag,
        area_parcel_emp,
        area_parcel_mixed_use,
        area_parcel_no_use
    FROM parcel_geom
)

SELECT
    parcel_id,
    geometry,
    county,
    land_development_category,
    built_form_key,
    intersection_density,
    area_gross,
    ROUND((area_gross * 0.85)::numeric, 4) AS area_parcel,
    ROUND((area_gross * 0.7)::numeric, 4) AS area_dev_condition,
    ROUND((area_gross * 0.15)::numeric, 4) AS area_row,
    pop,
    hh,
    du,
    emp,
    land_use,
    assessor_use_code,
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
    bldg_area_wholesale,
    residential_irrigated_area,
    commercial_irrigated_area,
    area_parcel_res,
    area_parcel_emp_ag,
    area_parcel_emp,
    area_parcel_mixed_use,
    area_parcel_no_use
FROM parcel_area
