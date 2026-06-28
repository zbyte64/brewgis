MODEL (
  name brewgis.assessor.parcel_building_sqft_by_type,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  depends_on (
    brewgis.assessor.parcel_building_footprints
  )
);

-- Parcel Building Square Footage by Type — per-parcel total building sqft
-- broken into 4 Overture-derived buckets: residential, commercial, industrial,
-- other.
--
-- Built from parcel_building_footprints which performs the spatial join
-- once and computes the Overture class-based buckets directly, avoiding
-- a redundant second spatial join to buildings_combined.
--
-- Mixed-use buildings (class IS NULL or 'mixed') are split:
--   levels > 1  → ground floor = commercial, upper floors = residential
--   levels <= 1 → 50/50 residential / commercial

SELECT
    apn,
    total_footprint_sqft,
    building_count,
    footprint_ratio,
    lot_size_acres,
    COALESCE(overture_residential_sqft, 0)::double precision AS residential_building_sqft,
    COALESCE(overture_commercial_sqft, 0)::double precision AS commercial_building_sqft,
    COALESCE(overture_industrial_sqft, 0)::double precision AS industrial_building_sqft,
    COALESCE(overture_other_sqft, 0)::double precision AS other_building_sqft,
    residential_building_count,
    non_residential_building_count,
    max_levels,
    land_development_category,
    geometry
FROM brewgis.assessor.parcel_building_footprints;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_building_sqft_by_type_apn
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_parcel_building_sqft_by_type_geometry
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
