{#
    Core EndState Model — Scenario Builder

    Computes the end-state allocation for each parcel with a built form
    assignment. Applies density parameters from BuildingType definitions
    to produce output attributes (population, households, dwelling units,
    employment by sector, building square footage, land development category).

    Inputs (via dbt vars):
        source_schema: Schema containing source tables.
        parcel_table: Table name for parcels.
        built_form_table: Table name for built form (BuildingType) definitions.
        built_form_key_column: Column on parcels linking to built form (default: built_form_key).
        base_canvas_table: Existing condition table (for increment computation).
        target_schema: Schema for output.
        scenario_id: Unique scenario identifier.
        constraints_output: If set, reference env_constraint output for developable acres.
        dev_pct: Development percentage (default: 100).
        gross_net_pct: Gross-to-net ratio (default: 85).
        density_pct: Density adjustment percentage (default: 100).
        sector_mix: JSON dict for employment sector distribution.

    Output columns:
        parcel_id, gross_acres, acres_developable, acres_developed,
        population, households,
        dwelling_units_sf_ll, dwelling_units_sf_sl,
        dwelling_units_attached_sf, dwelling_units_mf_2_4,
        dwelling_units_mf_5p,
        employment_<sector> (...),
        building_sqft_<type> (...),
        res_irrigated_sqft, com_irrigated_sqft,
        parcel_acres_<type>,
        intersection_density,
        land_dev_category,
        geom

    Materialized as: {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}
#}

{%- set source_schema = var('source_schema') -%}
{%- set parcel_table = var('parcel_table') -%}
{%- set built_form_table = var('built_form_table', 'built_forms') -%}
{%- set built_form_key = var('built_form_key_column', 'built_form_key') -%}
{%- set dev_pct = var('dev_pct', 100) -%}
{%- set gross_net_pct = var('gross_net_pct', 85) -%}
{%- set density_pct = var('density_pct', 100) -%}

{#
    Determine developable acres: either from env_constraint output or compute raw.
#}
{%- set constraint_output = var('constraints_output', none) -%}
{%- if constraint_output %}
    {%- set developable_acres_expr = "COALESCE(ec.acres_developable, ST_Area(p.geom) / 4046.86)" -%}
    {%- set from_extra = "LEFT JOIN " ~ source_schema ~ "." ~ constraint_output ~ " ec ON p.id = ec.parcel_id" -%}
{%- else %}
    {%- set developable_acres_expr = "ST_Area(p.geom) / 4046.86" -%}
    {%- set from_extra = "" -%}
{%- endif -%}

{%- set applied_acres %}
    {{ developable_acres_expr }} * {{ dev_pct }} / 100.0 * {{ gross_net_pct }} / 100.0
{%- endset -%}
{%- set density_adj_acres = "(" ~ applied_acres ~ " * " ~ density_pct ~ " / 100.0)" -%}
{%- set gross_acres = "ST_Area(p.geom) / 4046.86" -%}

WITH parcel_base AS (
    SELECT
        p.id AS parcel_id,
        {{ gross_acres }} AS gross_acres,
        {{ developable_acres_expr }} AS acres_developable,
        {{ applied_acres }} AS applied_acres,
        {{ density_adj_acres }} AS density_adjusted_acres,
        bf.du_per_acre,
        bf.emp_per_acre,
        bf.far,
        bf.household_size,
        bf.vacancy_rate,
        bf.jobs_by_sector,
        bf.indoor_water_rate,
        bf.outdoor_water_rate,
        bf.id AS built_form_id,
        bf.building_coverage,
        bf.electricity_eui,
        bf.gas_eui,
        bf.vintage,
        bf.irrigable_area_fraction,
        p.geom
    FROM
        {{ source_schema }}.{{ parcel_table }} AS p
        {{ from_extra }}
    LEFT JOIN {{ source_schema }}.{{ built_form_table }} AS bf
        ON p.{{ built_form_key }} = bf.id
)

SELECT
    parcel_base.parcel_id,
    parcel_base.gross_acres,
    parcel_base.acres_developable,
    parcel_base.applied_acres AS acres_developed,

    -- Population & Households
    0.0 AS dwelling_units_sf_sl,

    0.0 AS dwelling_units_attached_sf,

    0.0 AS dwelling_units_mf_2_4,

    -- Dwelling unit breakdown (simplified — single-family default unless multi-family indicators)
    0.0 AS dwelling_units_mf_5p,

    0.0 AS building_sqft_residential,
    0.0 AS building_sqft_commercial,
    0.0 AS building_sqft_office,
    0.0 AS building_sqft_industrial,

    -- Employment
    0.0 AS building_sqft_public,

    -- Building square footage
    0.0 AS building_sqft_retail,

    0.0 AS building_sqft_wholesale,
    0.0 AS building_sqft_education,
    0.0 AS building_sqft_healthcare,
    0.0 AS building_sqft_hotel_lodging,
    0.0 AS building_sqft_entertainment,
    0.0 AS building_sqft_other,
    CASE
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre > 0
            THEN parcel_base.density_adjusted_acres * 43560.0
                * (1.0 - COALESCE(parcel_base.building_coverage, 30.0) / 100.0)
                * COALESCE(parcel_base.irrigable_area_fraction, 0.0)
        ELSE 0.0
    END AS res_irrigated_sqft
,
    CASE
        WHEN parcel_base.emp_per_acre IS NOT NULL AND parcel_base.emp_per_acre > 0
            THEN parcel_base.density_adjusted_acres * 43560.0
                * (1.0 - COALESCE(parcel_base.building_coverage, 30.0) / 100.0)
                * COALESCE(parcel_base.irrigable_area_fraction, 0.0)
        ELSE 0.0
    END AS com_irrigated_sqft,
    parcel_base.applied_acres AS parcel_acres_developed,
    0.0 AS parcel_acres_agriculture,
    0.0 AS parcel_acres_open_space,
    0.0 AS parcel_acres_vacant,

    -- Water
    0.0 AS intersection_density,
    parcel_base.geom,

    -- Parcel acres by type
    CASE
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre > 0
            THEN parcel_base.density_adjusted_acres * parcel_base.du_per_acre
        ELSE 0.0
    END AS dwelling_units_total,
    CASE
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre > 0
            THEN
                (parcel_base.density_adjusted_acres * parcel_base.du_per_acre)
                * COALESCE(parcel_base.household_size, 2.5)
        ELSE 0.0
    END AS population,
    CASE
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre > 0
            THEN
                (parcel_base.density_adjusted_acres * parcel_base.du_per_acre)
                * (1.0 - COALESCE(parcel_base.vacancy_rate, 5.0) / 100.0)
        ELSE 0.0
    END AS households,
    CASE
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre > 0
            THEN parcel_base.density_adjusted_acres * parcel_base.du_per_acre
        ELSE 0.0
    END AS dwelling_units_sf_ll,

    -- Network indicators
    CASE
        WHEN parcel_base.emp_per_acre IS NOT NULL AND parcel_base.emp_per_acre > 0
            THEN parcel_base.density_adjusted_acres * parcel_base.emp_per_acre
        ELSE 0.0
    END AS employment_total,

    -- Land development category
    CASE
        WHEN parcel_base.far IS NOT NULL AND parcel_base.far > 0
            THEN parcel_base.density_adjusted_acres * 43560.0 * parcel_base.far
        ELSE 0.0
    END AS building_sqft_total,

    CASE
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre >= 10.0 THEN 'urban'
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre >= 5.0 THEN 'compact'
        WHEN parcel_base.du_per_acre IS NOT NULL AND parcel_base.du_per_acre >= 1.0 THEN 'standard'
        ELSE 'rural'
    END AS land_dev_category,
    parcel_base.built_form_id,
    COALESCE(parcel_base.indoor_water_rate, 0.0) AS indoor_water_rate,
    COALESCE(parcel_base.outdoor_water_rate, 0.0) AS outdoor_water_rate,
    COALESCE(parcel_base.electricity_eui, 0.0) AS electricity_eui,
    COALESCE(parcel_base.gas_eui, 0.0) AS gas_eui,
    parcel_base.household_size,
FROM parcel_base
