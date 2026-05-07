{# -*- mode: jinja -*- #}
{# Built form allocation macros for scenario modeling. #}


{#
    Compute density-adjusted acres.

    applied_acres = developable_acres * dev_pct / 100.0 * gross_net_pct / 100.0
    density_adjusted_acres = applied_acres * density_pct / 100.0

    Where:
        developable_acres: Developable acreage (after constraints).
        dev_pct: Percent of developable area to develop.
        gross_net_pct: Gross-to-net acreage ratio.
        density_pct: Percent of base density to apply.
#}
{% macro compute_applied_acres(developable_acres, dev_pct, gross_net_pct) %}
    ({{ developable_acres }}) * ({{ dev_pct }}) / 100.0 * ({{ gross_net_pct }}) / 100.0
{% endmacro %}


{#
    Compute dwelling units from density-adjusted acres and a density rate.

    dwelling_units = density_adjusted_acres * du_per_acre
#}
{% macro compute_dwelling_units(acres, du_per_acre) %}
    ({{ acres }}) * ({{ du_per_acre }})
{% endmacro %}


{#
    Compute population and households from dwelling units.

    population = dwelling_units * household_size
    households = dwelling_units * (1 - vacancy_rate / 100.0)
#}
{% macro compute_population(du, household_size) %}
    ({{ du }}) * ({{ household_size }})
{% endmacro %}

{% macro compute_households(du, vacancy_rate) %}
    ({{ du }}) * (1.0 - ({{ vacancy_rate }}) / 100.0)
{% endmacro %}


{#
    Compute employment from density-adjusted acres.

    employment = density_adjusted_acres * emp_per_acre
#}
{% macro compute_employment(acres, emp_per_acre) %}
    ({{ acres }}) * ({{ emp_per_acre }})
{% endmacro %}


{#
    Compute floor area (sqft) from density-adjusted acres.

    floor_area_sqft = density_adjusted_acres * 43560 * far

    Where 43560 is sqft per acre.
#}
{% macro compute_floor_area(acres, far) %}
    ({{ acres }}) * 43560.0 * ({{ far }})
{% endmacro %}


{#
    Classify land development category based on dwelling unit density.

    Classification:
        Urban:       du_per_acre >= {{ params.urban_threshold }}
        Compact:     du_per_acre >= {{ params.compact_threshold }}
        Standard:    du_per_acre >= {{ params.standard_threshold }}
        Rural:       du_per_acre < {{ params.standard_threshold }}

    Default thresholds:
        urban_threshold: 10.0
        compact_threshold: 5.0
        standard_threshold: 1.0
#}
{% macro classify_land_dev_category(du_per_acre, params=none) %}
    {%- set urban = params.get('urban_threshold', 10.0) if params else 10.0 -%}
    {%- set compact = params.get('compact_threshold', 5.0) if params else 5.0 -%}
    {%- set standard = params.get('standard_threshold', 1.0) if params else 1.0 -%}
    CASE
        WHEN {{ du_per_acre }} >= {{ urban }} THEN 'urban'
        WHEN {{ du_per_acre }} >= {{ compact }} THEN 'compact'
        WHEN {{ du_per_acre }} >= {{ standard }} THEN 'standard'
        ELSE 'rural'
    END
{% endmacro %}


{#
    Distribute total employment across sectors using a sector mix dict.

    The sector_mix is a JSON dict: {"retail": 0.3, "office": 0.4, "industrial": 0.3}

    Returns a list of (sector_name, sql_expr) pairs for use in a SELECT clause.
#}
{% macro distribute_employment(total_emp_expr, sector_mix) %}
    {%- for sector, fraction in sector_mix.items() %}
        ({{ total_emp_expr }}) * {{ fraction }} AS employment_{{ sector }}{% if not loop.last %},{% endif %}
    {%- endfor %}
{% endmacro %}
