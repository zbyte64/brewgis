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
        area_row, pop, hh, du, emp (raw values preserving NULLs for imputation)

    Materialized as: view
#}
{{ config(materialized=var('base_canvas_materialized', 'view')) }}

{%- set area_srid = var('projected_srid', 3857) -%}

WITH parcel_geom AS (
    SELECT
        parcel_id,
        {% if var('parcel_geometry_type', 'wkt') == 'geometry' %}
            geometry
        {% else %}
            ST_GeomFromText(geometry, 4326) AS geometry
        {% endif %},
        county,
        COALESCE(NULLIF(land_development_category, ''), '') AS land_development_category,
        built_form_key,
        intersection_density,
        pop,
        hh,
        du,
        emp
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
