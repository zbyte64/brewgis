MODEL (
  name brewgis.assessor.parcel_partition_stats,
  kind FULL,
  audits (
    not_null(columns := (land_development_category))
  )
);

-- Parcel Partition Stats — per-category standard deviations for k-NN distance
-- normalization in tier3 dasymetric imputation.
--
-- Extracted from parcel_dasymetric_weights to decouple the aggregation from
-- the main model, allowing it to be read as an indexed table rather than
-- computed as a CTE from the multi-reference known_parcels.

SELECT
    COALESCE(k.land_development_category, '') AS land_development_category,
    STDDEV_POP(k.intersection_density) AS s_int_dens,
    STDDEV_POP(k.lot_size_acres) AS s_ls,
    STDDEV_POP(k.footprint_ratio) AS s_fr
FROM brewgis.assessor.parcel_known_features k
GROUP BY k.land_development_category;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_partition_stats_land_dev_cat_@snapshot_hash
  ON @this_model USING btree (land_development_category);
ANALYZE @this_model;
