{# -*- mode: jinja -*- #}
{# Geometry and projection macros for area calculations. #}


{#
    Compute projected area in acres using a configurable SRID.

    Uses the projected_srid var for accurate area calculations. When
    projected_srid is null, falls back to ST_Area on the input geometry
    (typically SRID 4326), which produces meaningless area values.

    Usage:
        {{ st_area_projected('p.geom') }}
#}
{% macro st_area_projected(geom) %}
    {%- set srid = var('projected_srid', none) -%}
    {%- if srid %}
        ST_Area(ST_Transform({{ geom }}, {{ srid }})) / 4046.86
    {%- else %}
        -- WARNING: projected_srid not set. Area calculations in SRID 4326 are meaningless.
        -- Set projected_srid to a projected CRS (e.g. 32611 for UTM zone 11N).
        ST_Area({{ geom }}) / 4046.86
    {%- endif %}
{% endmacro %}
