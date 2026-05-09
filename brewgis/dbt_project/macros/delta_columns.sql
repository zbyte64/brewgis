{#- -*- mode: jinja -*- #}
{#
    Delta column macro — computes COALESCE(end_col, default) - COALESCE(base_col, default)
    for each column in the provided list. Used by core_increment.sql to replace
    the 30× repeated COALESCE diff pattern.

    Usage:
        {{ delta_columns(["population", "households", ...], "es", "b", default=0.0) }}

    Returns a comma-separated list of `COALESCE(es.x, 0.0) - COALESCE(b.x, 0.0) AS x` lines.
#}
{% macro delta_columns(column_names, end_alias="es", base_alias="b", default=0.0) %}
    {%- for col in column_names %}
    COALESCE({{ end_alias }}.{{ col }}, {{ default }}) - COALESCE({{ base_alias }}.{{ col }}, {{ default }}) AS {{ col }}{% if not loop.last %},{% endif %}
    {%- endfor %}
{% endmacro %}
