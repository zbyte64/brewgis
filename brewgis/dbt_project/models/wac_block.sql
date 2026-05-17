{#
    LEHD LODES WAC → Block Group Employment Table

    Joins lodes_raw staging data with TIGER/Line block group geometry,
    splits CNS employment into NAICS-based sub-sectors using CBP proportions,
    and computes aggregate employment columns.

    For SACOG region (CA/067), applies calibrated sub-sector proportions
    and zeros out agriculture, extraction, and military. The SACOG flag
    is a numeric var (0 or 1) used in CASE expressions — the SQL structure
    is always the same regardless of input.

    Inputs (via dbt vars):
        source_schema: Schema containing source tables (default public)
        lodes_raw_table: lodes_raw table name (default lodes_raw)
        tiger_bg_table: tiger_block_groups table name (default tiger_block_groups)
        year: LEHD data year
        is_sacog: 1 for SACOG calibration, 0 for general (default 0)
        cbp_11..cbp_721: CBP NAICS proportion parameters

    Output: lehd.wac_block — persistent table read by _allocate_employment
#}

{{ config(materialized='table', schema='lehd', 
    indexes=[{'columns': ['geometry'], 'type': 'gist'}]) 
}}

{% set year = var('year', 2021) %}
{% set is_sacog = var('is_sacog', 0) %}
{% set cbp_11 = var('cbp_11', 0.0) %}
{% set cbp_21 = var('cbp_21', 0.0) %}
{% set cbp_48 = var('cbp_48', 0.0) %}
{% set cbp_49 = var('cbp_49', 0.0) %}
{% set cbp_22 = var('cbp_22', 0.0) %}
{% set cbp_42 = var('cbp_42', 0.0) %}
{% set cbp_721 = var('cbp_721', 0.0) %}

WITH cbp_sub_sectors AS (
    SELECT
        LEFT(lr.w_geocode, 12) AS geoid,
        ST_Multi(ST_GeomFromText(tbg.geometry, 4326)) AS geometry,
        lr.c000,
        -- CNS01 -> goods producing: agriculture (11), extraction (21), remainder construction (23)
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_11 }}, 1))
            ELSE 0 END AS emp_agriculture_cbp,
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_21 }}, 1))
            ELSE 0 END AS emp_extraction_cbp,
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns01, 0)::numeric
                - ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_11 }}, 1)
                - ROUND(COALESCE(lr.cns01, 0)::numeric * {{ cbp_21 }}, 1))
            ELSE 0 END AS emp_construction_cbp,
        -- CNS02 -> manufacturing
        COALESCE(lr.cns02, 0)::numeric AS emp_manufacturing_cbp,
        -- CNS03 -> trade/transport/utilities
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * ({{ cbp_48 }} + {{ cbp_49 }}), 1))
            ELSE 0 END AS emp_transport_warehousing_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_22 }}, 1))
            ELSE 0 END AS emp_utilities_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_42 }}, 1))
            ELSE 0 END AS emp_wholesale_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns03, 0)::numeric
                - ROUND(COALESCE(lr.cns03, 0)::numeric * ({{ cbp_48 }} + {{ cbp_49 }}), 1)
                - ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_22 }}, 1)
                - ROUND(COALESCE(lr.cns03, 0)::numeric * {{ cbp_42 }}, 1))
            ELSE 0 END AS emp_retail_services_cbp,
        -- CNS04-CNS09 -> office services
        (COALESCE(lr.cns04, 0) + COALESCE(lr.cns05, 0) + COALESCE(lr.cns06, 0)
            + COALESCE(lr.cns07, 0) + COALESCE(lr.cns08, 0) + COALESCE(lr.cns09, 0)
        )::numeric AS emp_office_services_cbp,
        -- CNS10 -> education
        COALESCE(lr.cns10, 0)::numeric AS emp_education_cbp,
        -- CNS11 -> medical
        COALESCE(lr.cns11, 0)::numeric AS emp_medical_services_cbp,
        -- CNS12 -> arts/entertainment
        COALESCE(lr.cns12, 0)::numeric AS emp_arts_entertainment_cbp,
        -- CNS13 -> accommodation/food: accommodation (721), remainder restaurant (722)
        CASE WHEN COALESCE(lr.cns13, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns13, 0)::numeric * {{ cbp_721 }}, 1))
            ELSE 0 END AS emp_accommodation_cbp,
        CASE WHEN COALESCE(lr.cns13, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns13, 0)::numeric
                - ROUND(COALESCE(lr.cns13, 0)::numeric * {{ cbp_721 }}, 1))
            ELSE 0 END AS emp_restaurant_cbp,
        -- CNS14 -> other services
        COALESCE(lr.cns14, 0)::numeric AS emp_other_services_cbp,
        -- CNS15 -> public admin
        COALESCE(lr.cns15, 0)::numeric AS emp_public_admin_cbp,
        -- CNS17 -> military (CNS16 unclassified, excluded)
        COALESCE(lr.cns17, 0)::numeric AS emp_military_cbp
    FROM {{ source('brewgis', 'lodes_raw') }} lr
    JOIN {{ source('brewgis', 'tiger_block_groups') }} tbg
        ON LEFT(lr.w_geocode, 12) = tbg.geoid
    WHERE lr.year = {{ year }}
),
cbp_aggregates AS (
    SELECT
        *,
        (emp_retail_services_cbp + emp_restaurant_cbp + emp_accommodation_cbp
         + emp_arts_entertainment_cbp + emp_other_services_cbp) AS emp_ret,
        (emp_office_services_cbp + emp_medical_services_cbp) AS emp_off,
        (emp_education_cbp + emp_public_admin_cbp) AS emp_pub,
        (emp_manufacturing_cbp + emp_wholesale_cbp + emp_transport_warehousing_cbp
         + emp_utilities_cbp + emp_construction_cbp + emp_extraction_cbp + emp_agriculture_cbp) AS emp_ind,
        emp_agriculture_cbp AS emp_ag
    FROM cbp_sub_sectors
)
SELECT
    geoid,
    geometry,
    c000 AS emp,
    -- Sub-sector: SACOG-calibrated or CBP-based (determined by :is_sacog flag)
    CASE WHEN {{ is_sacog }} = 1 AND emp_ret > 0
        THEN ROUND(emp_ret * 76395.0 / 163859.0, 1) ELSE emp_retail_services_cbp
    END AS emp_retail_services,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ret > 0
        THEN ROUND(emp_ret * 42520.0 / 163859.0, 1) ELSE emp_restaurant_cbp
    END AS emp_restaurant,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ret > 0
        THEN ROUND(emp_ret * 3827.0 / 163859.0, 1) ELSE emp_accommodation_cbp
    END AS emp_accommodation,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ret > 0
        THEN ROUND(emp_ret * 7567.0 / 163859.0, 1) ELSE emp_arts_entertainment_cbp
    END AS emp_arts_entertainment,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ret > 0
        THEN ROUND(emp_ret * 33330.0 / 163859.0, 1) ELSE emp_other_services_cbp
    END AS emp_other_services,
    CASE WHEN {{ is_sacog }} = 1 AND emp_off > 0
        THEN ROUND(emp_off * 236721.0 / 259466.0, 1) ELSE emp_office_services_cbp
    END AS emp_office_services,
    CASE WHEN {{ is_sacog }} = 1 AND emp_off > 0
        THEN ROUND(emp_off * 22745.0 / 259466.0, 1) ELSE emp_medical_services_cbp
    END AS emp_medical_services,
    CASE WHEN {{ is_sacog }} = 1 AND emp_pub > 0
        THEN ROUND(emp_pub * 16924.0 / 44285.0, 1) ELSE emp_public_admin_cbp
    END AS emp_public_admin,
    CASE WHEN {{ is_sacog }} = 1 AND emp_pub > 0
        THEN ROUND(emp_pub * 27361.0 / 44285.0, 1) ELSE emp_education_cbp
    END AS emp_education,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ind > 0
        THEN ROUND(emp_ind * 46244.0 / 74702.0, 1) ELSE emp_manufacturing_cbp
    END AS emp_manufacturing,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ind > 0
        THEN ROUND(emp_ind * 10672.0 / 74702.0, 1) ELSE emp_wholesale_cbp
    END AS emp_wholesale,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ind > 0
        THEN ROUND(emp_ind * 14229.0 / 74702.0, 1) ELSE emp_transport_warehousing_cbp
    END AS emp_transport_warehousing,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ind > 0
        THEN ROUND(emp_ind * 719.0 / 74702.0, 1) ELSE emp_utilities_cbp
    END AS emp_utilities,
    CASE WHEN {{ is_sacog }} = 1 AND emp_ind > 0
        THEN ROUND(emp_ind * 2838.0 / 74702.0, 1) ELSE emp_construction_cbp
    END AS emp_construction,
    -- SACOG zeros out agriculture, extraction, military
    CASE WHEN {{ is_sacog }} = 1 THEN 0 ELSE emp_agriculture_cbp END AS emp_agriculture,
    CASE WHEN {{ is_sacog }} = 1 THEN 0 ELSE emp_extraction_cbp END AS emp_extraction,
    CASE WHEN {{ is_sacog }} = 1 THEN 0 ELSE emp_military_cbp END AS emp_military,
    -- Aggregate columns (CBP-based)
    emp_ret,
    emp_off,
    emp_pub,
    emp_ind,
    emp_ag
FROM cbp_aggregates
