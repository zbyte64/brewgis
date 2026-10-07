MODEL (
  name brewgis.@{region}.wac_block_raw,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (geoid, data_year),
    batch_size 100000
  ),
  description 'Block-level LEHD LODES WAC employment with its CNS01-CNS20 NAICS sectors mapped to base-canvas sub-sectors and TIGER-matched geometry, one row per block and year.',
  column_descriptions (
    geoid = '15-digit census block GEOID (state+county+tract+block FIPS) from LODES w_geocode.',
    geometry = 'Block geometry (EPSG:4326) from TIGER/Line, matched at block, block group or tract level.',
    emp = 'Total jobs reported for the block by LODES C000.',
    data_year = 'First day of the LODES year (make_date(@lodes_year, 1, 1)) the jobs refer to.',
    emp_education = 'Educational services jobs: LODES CNS15 (NAICS 61).',
    emp_medical_services = 'Health care and social assistance jobs: LODES CNS16 (NAICS 62).',
    emp_public_admin = 'Public administration jobs: LODES CNS20 (NAICS 92).',
    emp_agriculture = 'Agriculture, forestry, fishing and hunting jobs: LODES CNS01 (NAICS 11).',
    emp_extraction = 'Mining, quarrying, and oil and gas extraction jobs: LODES CNS02 (NAICS 21).',
    emp_construction = 'Construction jobs: LODES CNS04 (NAICS 23).',
    emp_manufacturing = 'Manufacturing jobs: LODES CNS05 (NAICS 31-33).',
    emp_transport_warehousing = 'Transportation and warehousing jobs: LODES CNS08 (NAICS 48-49).',
    emp_utilities = 'Utilities jobs: LODES CNS03 (NAICS 22).',
    emp_wholesale = 'Wholesale trade jobs: LODES CNS06 (NAICS 42).',
    emp_retail_services = 'Retail trade jobs: LODES CNS07 (NAICS 44-45).',
    emp_office_services = 'Office services jobs: LODES CNS09 through CNS14 (NAICS 51-56) summed.',
    emp_arts_entertainment = 'Arts, entertainment and recreation jobs: LODES CNS17 (NAICS 71).',
    emp_accommodation = 'Accommodation jobs: LODES CNS18 (NAICS 72) times the CBP NAICS 721 share (@cbp_721).',
    emp_restaurant = 'Food services jobs: LODES CNS18 (NAICS 72) remainder after the accommodation share.',
    emp_other_services = 'Other services jobs: LODES CNS19 (NAICS 81).',
    emp_military = 'Military jobs, always 0: LODES WAC has no armed-forces segment; kept for the base canvas schema.',
    emp_ag = 'Agricultural employment (jobs), equal to emp_agriculture (base canvas aggregate).',
    emp_ret = 'Retail employment (jobs): the five retail sub-sectors summed (base canvas aggregate).',
    emp_off = 'Office employment (jobs): office services plus medical services (base canvas aggregate).',
    emp_pub = 'Public employment (jobs): education plus public administration (base canvas aggregate).',
    emp_ind = 'Industrial employment (jobs): manufacturing, wholesale, transport, utilities, construction.'
  ),
  audits (
    not_null(columns := (geoid, data_year))
  ),
  blueprints @region_blueprints()
);

-- LEHD LODES WAC → Block-Level Employment
--
-- Joins lodes_raw staging data with TIGER/Line block geometry (15-digit
-- GEOID) and maps the LODES CNS01-CNS20 NAICS sectors (LODES8 tech doc,
-- WAC table) to base-canvas sub-sectors. Every CNS column maps one-to-one
-- except CNS09-CNS14 (office services) and CNS18 (NAICS 72), which is split
-- into accommodation (721) and food services (722) by @cbp_721. LODES WAC
-- has no armed-forces segment, so emp_military is 0.
--
-- Geometry resolution — three-tier fallback:
--   Tier 1: exact 15-digit geoid match to tiger_blocks (preferred)
--   Tier 2: 12-digit block group match to tiger_block_groups
--   Tier 3: any block group in the same census tract (tiger_block_groups)
--   Excluded: blocks with no TIGER match at any tier
--
-- @VAR('cbp_721', 0.0) = NAICS 721 (accommodation) share of CNS18 (NAICS 72)

WITH lodes_blocks AS (
    SELECT DISTINCT
        w_geocode AS block_geoid,
        LEFT(w_geocode, 12) AS bg,
        LEFT(w_geocode, 11) AS tract
    FROM brewgis.@{region}.lodes_raw
    WHERE year = @lodes_year
      AND LEFT(w_geocode, 5) IN (
        SELECT CONCAT(@state_fips, c) FROM UNNEST(STRING_TO_ARRAY(@county_fips, ',')) AS c
      )
),

block_geometry_map AS (
    SELECT
        lb.block_geoid,
        COALESCE(
            tb.wgs84_geometry,
            tbg.wgs84_geometry,
            tbg_fallback.wgs84_geometry
        ) AS geometry
    FROM lodes_blocks lb
    LEFT JOIN brewgis.census.tiger_blocks tb
        ON lb.block_geoid = tb.geoid
        AND tb.vintage = @tiger_block_vintage
    LEFT JOIN brewgis.census.tiger_block_groups tbg
        ON lb.bg = tbg.geoid
        AND tbg.vintage = @tiger_vintage
    LEFT JOIN LATERAL (
        SELECT wgs84_geometry FROM brewgis.census.tiger_block_groups
        WHERE geoid LIKE lb.tract || '%'
          AND vintage = @tiger_vintage
        LIMIT 1
    ) tbg_fallback ON tb.geoid IS NULL AND tbg.geoid IS NULL
    WHERE COALESCE(tb.wgs84_geometry, tbg.wgs84_geometry, tbg_fallback.wgs84_geometry) IS NOT NULL
),

sectors AS (
    SELECT
        lr.w_geocode AS geoid,
        ST_Multi(bm.geometry) AS geometry,
        lr.c000 AS emp,
        COALESCE(lr.cns01, 0)::numeric AS emp_agriculture,
        COALESCE(lr.cns02, 0)::numeric AS emp_extraction,
        COALESCE(lr.cns03, 0)::numeric AS emp_utilities,
        COALESCE(lr.cns04, 0)::numeric AS emp_construction,
        COALESCE(lr.cns05, 0)::numeric AS emp_manufacturing,
        COALESCE(lr.cns06, 0)::numeric AS emp_wholesale,
        COALESCE(lr.cns07, 0)::numeric AS emp_retail_services,
        COALESCE(lr.cns08, 0)::numeric AS emp_transport_warehousing,
        -- CNS09-CNS14 (NAICS 51-56) -> office services
        (COALESCE(lr.cns09, 0) + COALESCE(lr.cns10, 0) + COALESCE(lr.cns11, 0)
            + COALESCE(lr.cns12, 0) + COALESCE(lr.cns13, 0) + COALESCE(lr.cns14, 0)
        )::numeric AS emp_office_services,
        COALESCE(lr.cns15, 0)::numeric AS emp_education,
        COALESCE(lr.cns16, 0)::numeric AS emp_medical_services,
        COALESCE(lr.cns17, 0)::numeric AS emp_arts_entertainment,
        -- CNS18 (NAICS 72): accommodation (721), remainder food services (722)
        ROUND(COALESCE(lr.cns18, 0)::numeric * @VAR('cbp_721', 0.0), 1) AS emp_accommodation,
        COALESCE(lr.cns18, 0)::numeric
            - ROUND(COALESCE(lr.cns18, 0)::numeric * @VAR('cbp_721', 0.0), 1) AS emp_restaurant,
        COALESCE(lr.cns19, 0)::numeric AS emp_other_services,
        COALESCE(lr.cns20, 0)::numeric AS emp_public_admin,
        0::numeric AS emp_military
    FROM brewgis.@{region}.lodes_raw lr
    JOIN block_geometry_map bm
        ON lr.w_geocode = bm.block_geoid
    WHERE lr.year = @lodes_year
      AND LEFT(lr.w_geocode, 5) IN (
        SELECT CONCAT(@state_fips, c) FROM UNNEST(STRING_TO_ARRAY(@county_fips, ',')) AS c
      )
)

SELECT
    geoid,
    geometry,
    emp,
    make_date(@lodes_year::int, 1, 1) AS data_year,
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
    emp_agriculture AS emp_ag,
    (emp_retail_services + emp_restaurant + emp_accommodation
        + emp_arts_entertainment + emp_other_services) AS emp_ret,
    (emp_office_services + emp_medical_services) AS emp_off,
    (emp_education + emp_public_admin) AS emp_pub,
    (emp_manufacturing + emp_wholesale + emp_transport_warehousing
        + emp_utilities + emp_construction) AS emp_ind
FROM sectors;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_wac_block_raw_geom_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_wac_block_raw_geoid_')
  ON @this_model USING btree (geoid);
ANALYZE @this_model;
