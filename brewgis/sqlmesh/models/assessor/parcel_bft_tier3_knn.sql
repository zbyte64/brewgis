MODEL (
  name brewgis.assessor.parcel_bft_tier3_knn,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    assert_bft_tier3_knn_non_empty
  )
);

-- Tier 3: landuse-constrained KNN imputation for parcels without Tier0/Tier1/Tier2
-- classification. Uses a LATERAL spatial join to find the 200 nearest known-feature
-- parcels, scores them by standardized distance, and assigns the MODE built_form_key
-- of the 5 nearest neighbors.

WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        LEFT(landuse::text, 2) AS landuse_prefix,
        land_development_category
    FROM brewgis.assessor.sacog_assessor_parcels
),
building_metrics AS (
    SELECT
        apn,
        COALESCE(footprint_ratio, 0) AS footprint_ratio
    FROM brewgis.assessor.parcel_building_sqft_by_type
),
int_density AS (
    SELECT
        apn,
        intersection_density
    FROM brewgis.assessor.overture_intersection_density
),
unknown_parcels AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        COALESCE(id.intersection_density, 0) AS intersection_density,
        ap.land_development_category,
        ap.landuse_prefix
    FROM assessor_parcels ap
    LEFT JOIN building_metrics bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    WHERE NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier0_landuse t0 WHERE t0.apn = ap.apn)
      AND NOT EXISTS (SELECT 1 FROM brewgis.assessor.parcel_bft_tier1_sales t1 WHERE t1.apn = ap.apn)
),
tier3_candidates AS (
    SELECT
        u.apn,
        kf.neighbor_apn,
        kf.built_form_key,
        POWER(COALESCE((u.intersection_density - kf.intersection_density) / NULLIF(ps.s_int_dens, 0), 0), 2)
            + POWER(COALESCE((u.lot_size_acres - kf.lot_size_acres) / NULLIF(ps.s_ls, 0), 0), 2)
            + POWER(COALESCE((u.footprint_ratio - kf.footprint_ratio) / NULLIF(ps.s_fr, 0), 0), 2)
            AS distance_sq
    FROM unknown_parcels u
    LEFT JOIN @ref_model(@parcel_partition_stats_model) ps
        ON COALESCE(u.land_development_category, '') = ps.land_development_category
    CROSS JOIN LATERAL (
        SELECT kf.apn AS neighbor_apn, kf.built_form_key,
               kf.intersection_density, kf.lot_size_acres, kf.footprint_ratio
        FROM @ref_model(@parcel_known_features_model) kf
        WHERE kf.land_development_category = u.land_development_category
          AND kf.lot_size_acres BETWEEN
              u.lot_size_acres - 3 * COALESCE(ps.s_ls, u.lot_size_acres + 100)
              AND u.lot_size_acres + 3 * COALESCE(ps.s_ls, u.lot_size_acres + 100)
          AND ST_DWithin(u.geometry, kf.geometry, 5000)
          AND (
              (u.landuse_prefix LIKE 'A2' AND kf.built_form_key IN ('bt__medium_density_attached_residential', 'bt__high_density_attached_residential', 'bt__medium_high_density_attached_residential', 'bt__very_high_density_attached_residential', 'bt__urban_attached_residential', 'bt__urban_mid_rise_residential'))
              OR (u.landuse_prefix IN ('AT') AND kf.built_form_key IN ('bt__medium_density_attached_residential', 'bt__high_density_attached_residential', 'bt__medium_high_density_attached_residential', 'bt__very_high_density_attached_residential', 'bt__urban_attached_residential', 'bt__urban_mid_rise_residential'))
              OR (u.landuse_prefix NOT LIKE 'A2' AND u.landuse_prefix NOT IN ('AT'))
          )
        ORDER BY u.geometry <-> kf.geometry
        LIMIT 200
    ) kf
),
tier3_ranked AS (
    SELECT
        u.apn,
        u.neighbor_apn,
        u.built_form_key,
        u.distance_sq,
        ROW_NUMBER() OVER (
            PARTITION BY u.apn ORDER BY u.distance_sq
        ) AS rn
    FROM tier3_candidates u
)
SELECT
    apn,
    MODE() WITHIN GROUP (ORDER BY built_form_key) AS built_form_key
FROM tier3_ranked
WHERE rn <= 5
  AND distance_sq IS NOT NULL
GROUP BY apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_bft_tier3_knn_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
