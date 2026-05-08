{# -*- mode: jinja -*- #}
{# Custom generic test macros for Brew GIS dbt testing. #}


{#
    Assert that a column contains only non-negative values.

    Returns rows where column < 0 (violations).
#}
{% macro test_non_negative(model, column_name) %}
    select *
    from {{ model }}
    where {{ column_name }} < 0
{% endmacro %}


{#
    Assert that a set of proportion columns sums to approximately 1.0 per row.

    Each row's non-null columns are summed; rows whose total differs from
    1.0 by more than `tolerance` (default: 0.01) are returned as violations.

    Usage:
        {{ proportion_sum(ref('mode_choice'), columns=['mode_share_auto', 'mode_share_transit', 'mode_share_walk', 'mode_share_bike'], tolerance=0.01) }}
#}
{% macro test_proportion_sum(model, columns, tolerance) %}
    select *
    from (
        select *,
            (0 {% for col in columns %} + coalesce({{ col }}, 0){% endfor %}) as _total
        from {{ model }}
    ) t
    where abs(_total - 1.0) > {{ tolerance | default(0.01) }}
{% endmacro %}


{#
    Assert that acres_consumed does not exceed area_gross in land consumption models.

    Returns rows where acres_consumed > gross_acres (violations).
#}
{% macro test_acres_consumed_le_gross(model) %}
    select *
    from {{ model }}
    where acres_consumed > gross_acres
{% endmacro %}


{#
    Assert that a column falls within the specified inclusive range.

    Returns rows where column < min_value or column > max_value.

    Usage:
        {{ column_between(ref('env_constraint'), 'developable_proportion', 0, 1) }}
#}
{% macro test_column_between(model, column_name, min_value, max_value) %}
    select *
    from {{ model }}
    where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endmacro %}
