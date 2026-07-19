MODEL (
  name brewgis.staging.wac_block_raw,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (geoid, data_year),
    batch_size 100000
  ),
  audits (
    not_null(columns := (geoid, data_year))
  )
);

-- LEHD LODES WAC → Block-Level Employment (Raw CNS Split)
--
-- Joins lodes_raw staging data with TIGER/Line block geometry (15-digit
-- GEOID), splits CNS employment into NAICS-based sub-sectors using CBP
-- proportions, and distributes CNS16 (unclassified) employment
-- proportionally across sub-sectors.
--
-- Geometry resolution — three-tier fallback:
--   Tier 1: exact 15-digit geoid match to tiger_blocks (preferred)
--   Tier 2: 12-digit block group match to tiger_block_groups
--   Tier 3: any block group in the same census tract (tiger_block_groups)
--   Excluded: blocks with no TIGER match at any tier
--
-- CBP proportion parameters (SQLMesh @VAR variables, defaulting to passthrough):
--   @VAR('cbp_11', 0.0)          = agriculture share of CNS01
--   @VAR('cbp_21', 0.0)          = extraction share of CNS01
--   @VAR('cbp_48', 0.0)          = transport share of CNS03
--   @VAR('cbp_49', 0.0)          = warehousing share of CNS03
--   @VAR('cbp_22', 0.0)          = utilities share of CNS03
--   @VAR('cbp_42', 0.0)          = wholesale share of CNS03
--   @VAR('cbp_721', 0.0)         = accommodation share of CNS13
--   @VAR('cns18_20_edu_frac', 0.24)  = education share of CNS18-20 govt workers
--   @VAR('cns18_20_med_frac', 0.37)  = medical share of CNS18-20 govt workers
--   @VAR('cns18_20_pub_frac', 0.39)  = public admin share of CNS18-20 govt workers

WITH lodes_blocks AS (
    SELECT DISTINCT
        w_geocode AS block_geoid,
        LEFT(w_geocode, 12) AS bg,
        LEFT(w_geocode, 11) AS tract
    FROM public.lodes_raw
    WHERE year = @lodes_year
      AND LEFT(w_geocode, 5) = CONCAT(@state_fips, @county_fips)
),

block_geometry_map AS (
    SELECT
        lb.block_geoid,
        COALESCE(
            tb.geometry,
            tbg.geometry,
            tbg_fallback.geometry
        ) AS geometry
    FROM lodes_blocks lb
    LEFT JOIN public.tiger_blocks tb
        ON lb.block_geoid = tb.geoid
        AND tb.vintage = @tiger_block_vintage
    LEFT JOIN public.tiger_block_groups tbg
        ON lb.bg = tbg.geoid
        AND tbg.vintage = @tiger_vintage
    LEFT JOIN LATERAL (
        SELECT geometry FROM public.tiger_block_groups
        WHERE geoid LIKE lb.tract || '%'
          AND vintage = @tiger_vintage
        LIMIT 1
    ) tbg_fallback ON tb.geoid IS NULL AND tbg.geoid IS NULL
    WHERE COALESCE(tb.geometry, tbg.geometry, tbg_fallback.geometry) IS NOT NULL
),

cbp_sub_sectors AS (
    SELECT
        lr.w_geocode AS geoid,
        ST_Multi(bm.geometry) AS geometry,
        lr.c000,
        -- CNS01 -> goods producing: agriculture (11), extraction (21), remainder construction (23)
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns01, 0)::numeric * @VAR('cbp_11', 0.0), 1))
            ELSE 0 END AS emp_agriculture_cbp,
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns01, 0)::numeric * @VAR('cbp_21', 0.0), 1))
            ELSE 0 END AS emp_extraction_cbp,
        CASE WHEN COALESCE(lr.cns01, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns01, 0)::numeric
                - ROUND(COALESCE(lr.cns01, 0)::numeric * @VAR('cbp_11', 0.0), 1)
                - ROUND(COALESCE(lr.cns01, 0)::numeric * @VAR('cbp_21', 0.0), 1))
            ELSE 0 END AS emp_construction_cbp,
        -- CNS02 -> manufacturing
        COALESCE(lr.cns02, 0)::numeric AS emp_manufacturing_cbp,
        -- CNS03 -> trade/transport/utilities
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * (@VAR('cbp_48', 0.0) + @VAR('cbp_49', 0.0)), 1))
            ELSE 0 END AS emp_transport_warehousing_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * @VAR('cbp_22', 0.0), 1))
            ELSE 0 END AS emp_utilities_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, ROUND(COALESCE(lr.cns03, 0)::numeric * @VAR('cbp_42', 0.0), 1))
            ELSE 0 END AS emp_wholesale_cbp,
        CASE WHEN COALESCE(lr.cns03, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns03, 0)::numeric
                - ROUND(COALESCE(lr.cns03, 0)::numeric * (@VAR('cbp_48', 0.0) + @VAR('cbp_49', 0.0)), 1)
                - ROUND(COALESCE(lr.cns03, 0)::numeric * @VAR('cbp_22', 0.0), 1)
                - ROUND(COALESCE(lr.cns03, 0)::numeric * @VAR('cbp_42', 0.0), 1))
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
            THEN GREATEST(0, ROUND(COALESCE(lr.cns13, 0)::numeric * @VAR('cbp_721', 0.0), 1))
            ELSE 0 END AS emp_accommodation_cbp,
        CASE WHEN COALESCE(lr.cns13, 0) > 0
            THEN GREATEST(0, COALESCE(lr.cns13, 0)::numeric
                - ROUND(COALESCE(lr.cns13, 0)::numeric * @VAR('cbp_721', 0.0), 1))
            ELSE 0 END AS emp_restaurant_cbp,
        -- CNS14 -> other services
        COALESCE(lr.cns14, 0)::numeric AS emp_other_services_cbp,
        -- CNS15 + CNS18-20 -> public admin (all government sectors)
        COALESCE(lr.cns15, 0)::numeric AS emp_public_admin_cbp,
        -- CNS18-20: government workers (Federal, State, Local) distributed
        -- to education/medical/public_admin via fixed fractions.
        COALESCE(lr.cns18, 0) + COALESCE(lr.cns19, 0) + COALESCE(lr.cns20, 0) AS cns18_20_govt,
        -- CNS17 -> military
        COALESCE(lr.cns17::numeric, 0)::numeric AS emp_military_cbp,
        -- CNS16 unclassified (distributed in later CTE)
        COALESCE(lr.cns16::numeric, 0)::numeric AS cns16_unclassified
    FROM public.lodes_raw lr
    JOIN block_geometry_map bm
        ON lr.w_geocode = bm.block_geoid
    WHERE lr.year = @lodes_year
      AND LEFT(lr.w_geocode, 5) = CONCAT(@state_fips, @county_fips)
),

-- Compute CBP-based aggregate columns and classified_total for CNS16 distribution.
cbp_aggregates AS (
    SELECT
        *,
        (emp_retail_services_cbp + emp_restaurant_cbp + emp_accommodation_cbp
            + emp_arts_entertainment_cbp + emp_other_services_cbp) AS emp_ret_cbpm,
        (emp_office_services_cbp + emp_medical_services_cbp) AS emp_off_cbpm,
        (emp_education_cbp + emp_public_admin_cbp) AS emp_pub_cbpm,
        (emp_manufacturing_cbp + emp_wholesale_cbp + emp_transport_warehousing_cbp
            + emp_utilities_cbp + emp_construction_cbp) AS emp_ind_cbpm,
        -- Total classified employment (excludes CNS16 and C000)
        (
            emp_agriculture_cbp + emp_extraction_cbp + emp_construction_cbp
            + emp_manufacturing_cbp + emp_transport_warehousing_cbp
            + emp_utilities_cbp + emp_wholesale_cbp + emp_retail_services_cbp
            + emp_office_services_cbp + emp_education_cbp + emp_medical_services_cbp
            + emp_arts_entertainment_cbp + emp_accommodation_cbp + emp_restaurant_cbp
            + emp_other_services_cbp + emp_public_admin_cbp + emp_military_cbp
        ) AS classified_total
    FROM cbp_sub_sectors
),

-- Uses CBP proportions directly (SACOG calibration removed).
calibrated_sectors AS (
    SELECT
        geoid,
        geometry,
        c000 AS emp,
        cns18_20_govt,
        cns16_unclassified,
        emp_agriculture_cbp AS emp_agriculture_calibrated,
        emp_extraction_cbp AS emp_extraction_calibrated,
        emp_construction_cbp AS emp_construction_calibrated,
        emp_manufacturing_cbp AS emp_manufacturing_calibrated,
        emp_transport_warehousing_cbp AS emp_transport_warehousing_calibrated,
        emp_utilities_cbp AS emp_utilities_calibrated,
        emp_wholesale_cbp AS emp_wholesale_calibrated,
        emp_retail_services_cbp AS emp_retail_services_calibrated,
        emp_office_services_cbp AS emp_office_services_calibrated,
        emp_education_cbp AS emp_education_calibrated,
        emp_medical_services_cbp AS emp_medical_services_calibrated,
        emp_arts_entertainment_cbp AS emp_arts_entertainment_calibrated,
        emp_accommodation_cbp AS emp_accommodation_calibrated,
        emp_restaurant_cbp AS emp_restaurant_calibrated,
        emp_other_services_cbp AS emp_other_services_calibrated,
        emp_public_admin_cbp AS emp_public_admin_calibrated,
        emp_military_cbp AS emp_military_calibrated,
        emp_agriculture_cbp AS emp_ag,
        emp_ret_cbpm AS emp_ret,
        emp_off_cbpm AS emp_off,
        emp_pub_cbpm AS emp_pub,
        emp_ind_cbpm AS emp_ind,
        classified_total
    FROM cbp_aggregates
),

with_cns16 AS (
    SELECT
        geoid,
        geometry,
        emp,
        cns18_20_govt,
        ROUND(emp_agriculture_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_agriculture_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_agriculture,
        ROUND(emp_extraction_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_extraction_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_extraction,
        ROUND(emp_construction_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_construction_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_construction,
        ROUND(emp_manufacturing_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_manufacturing_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_manufacturing,
        ROUND(emp_transport_warehousing_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_transport_warehousing_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_transport_warehousing,
        ROUND(emp_utilities_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_utilities_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_utilities,
        ROUND(emp_wholesale_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_wholesale_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_wholesale,
        ROUND(emp_retail_services_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_retail_services_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_retail_services,
        ROUND(emp_office_services_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_office_services_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_office_services,
        ROUND(emp_education_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_education_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_education,
        ROUND(emp_medical_services_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_medical_services_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_medical_services,
        ROUND(emp_arts_entertainment_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_arts_entertainment_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_arts_entertainment,
        ROUND(emp_accommodation_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_accommodation_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_accommodation,
        ROUND(emp_restaurant_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_restaurant_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_restaurant,
        ROUND(emp_other_services_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_other_services_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_other_services,
        ROUND(emp_public_admin_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_public_admin_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_public_admin,
        ROUND(emp_military_calibrated +
            CASE
                WHEN cns16_unclassified > 0 AND classified_total > 0
                THEN cns16_unclassified * emp_military_calibrated / classified_total
                WHEN cns16_unclassified > 0 AND classified_total = 0
                THEN cns16_unclassified / 17.0
                ELSE 0
            END, 1) AS emp_military,
        emp_ag,
        emp_ret,
        emp_off,
        emp_pub,
        emp_ind
    FROM calibrated_sectors
),

-- Distribute CNS18-20 government employment across education, medical,
-- and public_admin sub-sectors using fixed fractions from dbt default vars.
with_govt AS (
    SELECT
        geoid,
        geometry,
        emp,
        make_date(@lodes_year::int, 1, 1) AS data_year,
        ROUND(emp_education + cns18_20_govt * @VAR('cns18_20_edu_frac', 0.24), 1) AS emp_education,
        ROUND(emp_medical_services + cns18_20_govt * @VAR('cns18_20_med_frac', 0.37), 1) AS emp_medical_services,
        ROUND(emp_public_admin + cns18_20_govt * @VAR('cns18_20_pub_frac', 0.39), 1) AS emp_public_admin,
        emp_agriculture,
        emp_extraction,
        emp_construction,
        emp_manufacturing,
        emp_transport_warehousing,
        emp_utilities,
        emp_wholesale,
        emp_retail_services,
        emp_office_services,
        emp_arts_entertainment,
        emp_accommodation,
        emp_restaurant,
        emp_other_services,
        emp_military,
        emp_ag,
        emp_ret,
        emp_off,
        emp_pub,
        emp_ind
    FROM with_cns16
)

SELECT
    geoid,
    geometry,
    emp,
    data_year,
    emp_education,
    emp_medical_services,
    emp_public_admin,
    emp_agriculture,
    emp_extraction,
    emp_construction,
    emp_manufacturing,
    emp_transport_warehousing,
    emp_utilities,
    emp_wholesale,
    emp_retail_services,
    emp_office_services,
    emp_arts_entertainment,
    emp_accommodation,
    emp_restaurant,
    emp_other_services,
    emp_military,
    emp_ag,
    emp_ret,
    emp_off,
    emp_pub,
    emp_ind
FROM with_govt;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_wac_block_raw_geom_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_wac_block_raw_geoid_@snapshot_hash
  ON @this_model USING btree (geoid);
ANALYZE @this_model;
