{#
    Base Canvas Geometry — first ETL step

    Reads raw parcel data from the test_parcels seed, casts WKT geometry to
    PostGIS geometry (EPSG:4326), computes area columns from Web Mercator
    projection, and passes through demographic and classification columns.

    Inputs:
        test_parcels (seed): Raw parcel data with WKT geometry.

    Output columns:
        parcel_id, geometry, county, land_development_category, built_form_key,
        intersection_density, area_gross, area_parcel, area_dev_condition,
        area_row, pop, hh, du, emp (raw values preserving NULLs for imputation)

    Materialized as: view
#}
{{ config(materialized='view') }}

{%- set area_srid = var('projected_srid', 3857) -%}

{%- import 'geometry.sql' as geom -%}

WITH parcel_geom AS (
    SELECT
        parcel_id,
        ST_GeomFromText(geometry, 4326) AS geometry,
        county,
        COALESCE(NULLIF(land_development_category, ''), '') AS land_development_category,
        built_form_key,
        intersection_density,
        pop,
        hh,
        du,
        emp
    FROM {{ ref('test_parcels') }}
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
        emp
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
    emp
FROM parcel_area
