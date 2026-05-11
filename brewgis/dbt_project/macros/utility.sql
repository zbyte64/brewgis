{# -*- mode: jinja -*- #}
{# Utility macros for boilerplate reduction across dbt models. #}


{#
    Generate a scalar subquery to SUM a column from a ref'd table.

    Usage:
        {{ summarize_metric('core_end_state', 'population') }}
    Produces:
        (SELECT COALESCE(SUM(population), 0) FROM {{ ref('core_end_state') }}) AS total_population
#}
{% macro summarize_metric(ref_table, column) %}
    (SELECT COALESCE(SUM({{ column }}), 0) FROM {{ ref(ref_table) }}) AS total_{{ column }}
{% endmacro %}


{#
    Wrap an expression in COALESCE(..., 0.0) for null safety.

    Usage:
        {{ coalesce_zero('acres_consumed') }}
    Produces:
        COALESCE(acres_consumed, 0.0)
#}
{% macro coalesce_zero(expression) %}
    COALESCE({{ expression }}, 0.0)
{% endmacro %}


{#
    Set multiple dbt vars at once from a mapping.

    Usage:
        {{ set_vars({'source_schema': 'public', 'parcel_table': 'parcels', 'constraints': []}) }}
    Compresses 3+ lines of:
        {%- set source_schema = var('source_schema') -%}
        {%- set parcel_table = var('parcel_table') -%}
    into one block.
#}
{% macro set_vars(names_to_defaults) %}
    {%- for name, default in names_to_defaults.items() %}
        {%- set _ = var(name, default) %}
    {%- endfor %}
{% endmacro %}
