MODEL (
  name brewgis.assessor.parcel_sales_features,
  kind FULL,
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  )
);

-- Parcel Sales Features — materialized known parcels table for k-NN imputation.
--
-- Pre-materializes the `known` CTE from parcel_footprint_imputed with GiST
-- and B-tree indexes, avoiding unindexed CTE scans during the three-tier
-- imputation cascade (especially tier3's ST_DWithin county-wide search).

WITH latest_block_groups AS (
    SELECT DISTINCT ON (apn) *
    FROM brewgis.assessor.parcel_block_groups
    ORDER BY apn, data_year DESC
)
SELECT DISTINCT ON (pbf.apn)
    pbf.apn,
    pbf.geometry,
    pbf.footprint_ratio,
    pbf.building_count,
    pbf.lot_size_acres,
    pbf.land_development_category,
    pbg.block_group_geoid,
    pbg.tract_geoid,
    s.property_type,
    COALESCE(s.units, 1) AS units,
    s.living_area AS living_sqft,
    s.building_sf AS building_sqft
FROM brewgis.assessor.parcel_building_footprints pbf
JOIN latest_block_groups pbg ON pbf.apn = pbg.apn
JOIN public.sacog_assessor_sales_raw s ON pbf.apn = s.apn
WHERE pbf.footprint_ratio > 0
  AND s.property_type IS NOT NULL
  AND s.property_type != '';

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_sales_features_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_parcel_sales_features_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_parcel_sales_features_bg_ldc_@snapshot_hash
  ON @this_model USING btree (block_group_geoid, land_development_category);
  CREATE INDEX IF NOT EXISTS idx_parcel_sales_features_tract_ldc_@snapshot_hash
  ON @this_model USING btree (tract_geoid, land_development_category);
  CREATE INDEX IF NOT EXISTS idx_parcel_sales_features_ldc_@snapshot_hash
  ON @this_model USING btree (land_development_category);
ANALYZE @this_model;
