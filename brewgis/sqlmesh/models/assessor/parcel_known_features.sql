MODEL (
  name brewgis.assessor.parcel_known_features,
  kind CUSTOM (
    materialization 'partitioned_full',
    materialization_properties (
      'partition_by' = 'land_development_category'
    )
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  )
);

-- Parcel Known Features — materialized table of parcels with known built_form_key
-- plus feature columns needed for k-NN distance computation in tier3 dasymetric
-- imputation (intersection_density, lot_size_acres, footprint_ratio).
--
-- This model replaces parcel_classified_geometry as a superset with additional
-- columns (footprint_ratio, intersection_density) that let the tier3 LATERAL
-- KNN scan return all needed fields directly — eliminating the 7.6M JOIN back
-- to known_parcels in parcel_dasymetric_weights.
--
-- Reads from the decomposed tier1_sales and tier0_landuse VIEWs instead of
-- duplicating Tier0/Tier1 CTEs. This fixes the previous divergence where
-- parcel_known_features mapped AT landuse to mf2to4 while the classification
-- model correctly returned NULL (letting building footprints handle AT parcels).
--
-- Indexes support <-> KNN scans, ST_DWithin, land_development_category filters,
-- and composite (category, geometry) lookups.

WITH tier1 AS (
    SELECT apn, built_form_key FROM brewgis.assessor.parcel_bft_tier1_sales
),
tier0 AS (
    SELECT apn, built_form_key FROM brewgis.assessor.parcel_bft_tier0_landuse
)
SELECT
    ap.apn,
    ap.geometry,
    ap.lot_size_acres,
    COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
    COALESCE(id.intersection_density, 0) AS intersection_density,
    COALESCE(tier1.built_form_key, tier0.built_form_key) AS built_form_key,
    ap.land_development_category
FROM brewgis.assessor.sacog_assessor_parcels ap
LEFT JOIN tier1 ON ap.apn = tier1.apn
LEFT JOIN tier0 ON ap.apn = tier0.apn
LEFT JOIN brewgis.assessor.parcel_building_sqft_by_type bs ON ap.apn = bs.apn
LEFT JOIN brewgis.assessor.overture_intersection_density id ON ap.apn = id.apn
WHERE COALESCE(tier1.built_form_key, tier0.built_form_key) IS NOT NULL
  AND COALESCE(tier1.built_form_key, tier0.built_form_key) IN (
      'bt__low_density_detached_residential', 'bt__medium_density_detached_residential', 'bt__medium_high_density_detached_residential',
      'bt__very_low_density_detached_residential', 'bt__rural_residential', 'bt__medium_density_attached_residential',
      'bt__medium_high_density_attached_residential', 'bt__high_density_attached_residential', 'bt__very_high_density_attached_residential',
      'bt__urban_attached_residential', 'bt__urban_mid_rise_residential', 'bt__mobile_home_park', 'bt__farm_home',
      'bt__blank_place_type', 'bt__communityneighborhood_retail', 'bt__communityneighborhood_commercial',
      'bt__communityneighborhood_commercialoffice', 'bt__regional_retail', 'bt__residentialretail_mixed_use_low',
      'bt__residentialretail_mixed_use_high', 'bt__moderate_intensity_office', 'bt__high_intensity_office',
      'bt__cbd_office', 'bt__light_industrialoffice', 'bt__hotel', 'bt__light_industrial', 'bt__heavy_industrial',
      'bt__agricultural_processingretail_employment', 'bt__agriculture', 'bt__publicquasi_public', 'bt__civic_institution',
      'bt__k_12_school', 'bt__college_university', 'bt__medical_facility', 'bt__park_and_open_space', 'bt__airport'
  );

-- post_statements
  CREATE EXTENSION IF NOT EXISTS btree_gist;
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_land_dev_cat_@snapshot_hash
  ON @this_model USING btree (land_development_category);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_lot_size_acres_@snapshot_hash
  ON @this_model USING btree (lot_size_acres);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_cat_lot_geom_@snapshot_hash
  ON @this_model USING GIST (land_development_category, lot_size_acres, geometry);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_cat_geom_@snapshot_hash
  ON @this_model USING GIST (land_development_category, geometry);
ANALYZE @this_model;
