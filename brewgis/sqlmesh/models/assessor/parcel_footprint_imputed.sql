MODEL (
  name brewgis.assessor.parcel_footprint_imputed,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  )
);

-- Parcel Footprint Imputed — three-tier k-NN imputation of building
-- characteristics for parcels without assessor sales data.
--
-- Uses Overture building footprint features (footprint_ratio, building_count,
-- lot_size_acres) to find the k=5 most similar parcels WITH assessor sales
-- data (known parcels) within the same geography/land-use partition.
--
-- Three-tier fallback strategy:
--   Tier 1 — same block_group_geoid + same land_development_category
--   Tier 2 — same tract_geoid + same land_development_category
--   Tier 3 — same land_development_category (county-wide)
--
-- k = 5 (default footprint_imputation_k)

WITH
-- Latest block group assignment per APN
latest_block_groups AS (
    SELECT DISTINCT ON (apn) *
    FROM brewgis.assessor.parcel_block_groups
    ORDER BY apn, data_year DESC
),

-- Parcels with building footprint features but NO sales data
unknown AS (
    SELECT
        pbf.apn,
        pbf.geometry,
        pbf.footprint_ratio,
        pbf.building_count,
        pbf.lot_size_acres,
        pbf.land_development_category,
        pbg.block_group_geoid,
        pbg.tract_geoid
    FROM brewgis.assessor.parcel_building_footprints pbf
    JOIN latest_block_groups pbg ON pbf.apn = pbg.apn
    LEFT JOIN brewgis.assessor.parcel_sales_features k ON pbf.apn = k.apn
    WHERE pbf.footprint_ratio > 0
      AND k.apn IS NULL
),

-- Z-score statistics per (block_group, land_development_category) partition
partition_stats AS (
    SELECT
        COALESCE(k.block_group_geoid, '') AS block_group_geoid,
        COALESCE(k.land_development_category, '') AS land_development_category,
        STDDEV_POP(k.footprint_ratio) AS s_fr,
        STDDEV_POP(k.building_count) AS s_bc,
        STDDEV_POP(k.lot_size_acres) AS s_ls,
        AVG(k.footprint_ratio) AS m_fr,
        AVG(k.building_count) AS m_bc,
        AVG(k.lot_size_acres) AS m_ls
    FROM brewgis.assessor.parcel_sales_features k
    GROUP BY k.block_group_geoid, k.land_development_category
),

-- Tract-level z-score stats (fallback for tier 2)
tract_stats AS (
    SELECT
        COALESCE(k.tract_geoid, '') AS tract_geoid,
        COALESCE(k.land_development_category, '') AS land_development_category,
        STDDEV_POP(k.footprint_ratio) AS s_fr,
        STDDEV_POP(k.building_count) AS s_bc,
        STDDEV_POP(k.lot_size_acres) AS s_ls,
        AVG(k.footprint_ratio) AS m_fr,
        AVG(k.building_count) AS m_bc,
        AVG(k.lot_size_acres) AS m_ls
    FROM brewgis.assessor.parcel_sales_features k
    GROUP BY k.tract_geoid, k.land_development_category
),

-- County-wide z-score stats (fallback for tier 3)
county_stats AS (
    SELECT
        COALESCE(k.land_development_category, '') AS land_development_category,
        STDDEV_POP(k.footprint_ratio) AS s_fr,
        STDDEV_POP(k.building_count) AS s_bc,
        STDDEV_POP(k.lot_size_acres) AS s_ls,
        AVG(k.footprint_ratio) AS m_fr,
        AVG(k.building_count) AS m_bc,
        AVG(k.lot_size_acres) AS m_ls
    FROM brewgis.assessor.parcel_sales_features k
    GROUP BY k.land_development_category
),

-- Tier 1: same block_group + same land_development_category
tier1 AS (
    SELECT
        u.apn,
        k.apn AS neighbor_apn,
        k.property_type,
        k.units,
        k.living_sqft,
        k.building_sqft,
        SQRT(
            POWER(
                COALESCE(
                    (u.footprint_ratio - k.footprint_ratio)
                    / NULLIF(ps.s_fr, 0), 0
                ), 2
            )
            + POWER(
                COALESCE(
                    (u.building_count - k.building_count)
                    / NULLIF(ps.s_bc, 0), 0
                ), 2
            )
            + POWER(
                COALESCE(
                    (u.lot_size_acres - k.lot_size_acres)
                    / NULLIF(ps.s_ls, 0), 0
                ), 2
            )
        ) AS distance,
        1 AS tier
    FROM unknown u
    LEFT JOIN partition_stats ps
        ON u.block_group_geoid = ps.block_group_geoid
       AND u.land_development_category = ps.land_development_category
    JOIN brewgis.assessor.parcel_sales_features k
        ON u.block_group_geoid = k.block_group_geoid
       AND u.land_development_category = k.land_development_category
       AND k.footprint_ratio BETWEEN
           u.footprint_ratio - 3 * COALESCE(ps.s_fr, u.footprint_ratio + 1)
           AND u.footprint_ratio + 3 * COALESCE(ps.s_fr, u.footprint_ratio + 1)
       AND k.building_count BETWEEN
           u.building_count - 3 * COALESCE(ps.s_bc, u.building_count + 5)
           AND u.building_count + 3 * COALESCE(ps.s_bc, u.building_count + 5)
       AND k.lot_size_acres BETWEEN
           u.lot_size_acres - 3 * COALESCE(ps.s_ls, u.lot_size_acres + 1)
           AND u.lot_size_acres + 3 * COALESCE(ps.s_ls, u.lot_size_acres + 1)
),

tier1_ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn ORDER BY distance
        ) AS rn
    FROM tier1
),

-- Tier 2: fallback — same tract + same land_development_category
tier2 AS (
    SELECT
        u.apn,
        k.apn AS neighbor_apn,
        k.property_type,
        k.units,
        k.living_sqft,
        k.building_sqft,
        SQRT(
            POWER(
                COALESCE(
                    (u.footprint_ratio - k.footprint_ratio)
                    / NULLIF(ts.s_fr, 0), 0
                ), 2
            )
            + POWER(
                COALESCE(
                    (u.building_count - k.building_count)
                    / NULLIF(ts.s_bc, 0), 0
                ), 2
            )
            + POWER(
                COALESCE(
                    (u.lot_size_acres - k.lot_size_acres)
                    / NULLIF(ts.s_ls, 0), 0
                ), 2
            )
        ) AS distance,
        2 AS tier
    FROM unknown u
    LEFT JOIN tract_stats ts
        ON u.tract_geoid = ts.tract_geoid
       AND u.land_development_category = ts.land_development_category
    JOIN brewgis.assessor.parcel_sales_features k
        ON u.tract_geoid = k.tract_geoid
       AND u.land_development_category = k.land_development_category
       AND k.footprint_ratio BETWEEN
           u.footprint_ratio - 3 * COALESCE(ts.s_fr, u.footprint_ratio + 1)
           AND u.footprint_ratio + 3 * COALESCE(ts.s_fr, u.footprint_ratio + 1)
       AND k.building_count BETWEEN
           u.building_count - 3 * COALESCE(ts.s_bc, u.building_count + 5)
           AND u.building_count + 3 * COALESCE(ts.s_bc, u.building_count + 5)
       AND k.lot_size_acres BETWEEN
           u.lot_size_acres - 3 * COALESCE(ts.s_ls, u.lot_size_acres + 1)
           AND u.lot_size_acres + 3 * COALESCE(ts.s_ls, u.lot_size_acres + 1)
    WHERE NOT EXISTS (SELECT 1 FROM tier1 WHERE tier1.apn = u.apn AND tier1.distance IS NOT NULL)
),

tier2_ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn ORDER BY distance
        ) AS rn
    FROM tier2
),

-- Tier 3: fallback — same land_development_category (county-wide)
tier3 AS (
    SELECT
        u.apn,
        k.apn AS neighbor_apn,
        k.property_type,
        k.units,
        k.living_sqft,
        k.building_sqft,
        SQRT(
            POWER(
                COALESCE(
                    (u.footprint_ratio - k.footprint_ratio)
                    / NULLIF(cs.s_fr, 0), 0
                ), 2
            )
            + POWER(
                COALESCE(
                    (u.building_count - k.building_count)
                    / NULLIF(cs.s_bc, 0), 0
                ), 2
            )
            + POWER(
                COALESCE(
                    (u.lot_size_acres - k.lot_size_acres)
                    / NULLIF(cs.s_ls, 0), 0
                ), 2
            )
        ) AS distance,
        3 AS tier
    FROM unknown u
    LEFT JOIN county_stats cs
        ON u.land_development_category = cs.land_development_category
    JOIN brewgis.assessor.parcel_sales_features k
        ON u.land_development_category = k.land_development_category
       AND ST_DWithin(u.geometry, k.geometry, 5000)
       AND k.footprint_ratio BETWEEN
           u.footprint_ratio - 3 * COALESCE(cs.s_fr, u.footprint_ratio + 1)
           AND u.footprint_ratio + 3 * COALESCE(cs.s_fr, u.footprint_ratio + 1)
       AND k.building_count BETWEEN
           u.building_count - 3 * COALESCE(cs.s_bc, u.building_count + 5)
           AND u.building_count + 3 * COALESCE(cs.s_bc, u.building_count + 5)
       AND k.lot_size_acres BETWEEN
           u.lot_size_acres - 3 * COALESCE(cs.s_ls, u.lot_size_acres + 1)
           AND u.lot_size_acres + 3 * COALESCE(cs.s_ls, u.lot_size_acres + 1)
    WHERE NOT EXISTS (SELECT 1 FROM tier1 WHERE tier1.apn = u.apn AND tier1.distance IS NOT NULL)
      AND NOT EXISTS (SELECT 1 FROM tier2 WHERE tier2.apn = u.apn AND tier2.distance IS NOT NULL)
),

tier3_ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn ORDER BY distance
        ) AS rn
    FROM tier3
),

-- Combined nearest neighbors (k=5 per tier)
combined AS (
    SELECT apn, neighbor_apn, property_type, units, living_sqft, building_sqft, tier
    FROM tier1_ranked WHERE rn <= 5
    UNION ALL
    SELECT apn, neighbor_apn, property_type, units, living_sqft, building_sqft, tier
    FROM tier2_ranked WHERE rn <= 5
    UNION ALL
    SELECT apn, neighbor_apn, property_type, units, living_sqft, building_sqft, tier
    FROM tier3_ranked WHERE rn <= 5
),

-- Aggregate to imputed values per APN
imputed AS (
    SELECT
        apn,
        MIN(tier) AS imputed_from_tier,
        COUNT(*) AS neighbor_count,
        MODE() WITHIN GROUP (ORDER BY property_type) AS imputed_property_type,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY units) AS imputed_units,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY living_sqft) AS imputed_living_sqft,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY building_sqft) AS imputed_building_sqft
    FROM combined
    GROUP BY apn
)

SELECT
    pbf.apn,
    pbf.total_footprint_sqft,
    pbf.building_count,
    pbf.footprint_ratio,
    pbf.lot_size_acres,
    pbf.land_development_category,
    pbf.residential_building_sqft,
    pbf.non_residential_building_sqft,
    pbf.residential_building_count,
    pbf.non_residential_building_count,
    pbf.max_levels,
    pbg.block_group_geoid,
    pbg.tract_geoid,
    i.imputed_property_type,
    i.imputed_units,
    i.imputed_living_sqft,
    i.imputed_building_sqft,
    i.imputed_from_tier,
    i.neighbor_count
FROM brewgis.assessor.parcel_building_footprints pbf
LEFT JOIN latest_block_groups pbg ON pbf.apn = pbg.apn
JOIN imputed i ON pbf.apn = i.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_footprint_imputed_apn
  ON brewgis.assessor.parcel_footprint_imputed (apn);
