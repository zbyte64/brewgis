{#- -*- mode: jinja -*- #}
{#
    Override dbt's default generate_schema_name macro.

    The default concatenates {profile_schema}_{custom_schema}, producing
    "public_scenario_N" when profile has schema=public and +schema is set
    to "scenario_N". This override returns custom_schema_name verbatim
    when set, or falls back to the target schema from the profile.

    This makes Django the canonical source of truth for schema names
    (via the Scenario model's target_schema property), and allows the
    schema_name to be freely configured without dbt prefixing it.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
