MODEL (
  name brewgis.assessor.parcel_known_features,
  kind FULL,
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
-- Indexes support <-> KNN scans, ST_DWithin, land_development_category filters,
-- and composite (category, geometry) lookups.

WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse,
        LEFT(landuse::text, 2) AS landuse_prefix,
        LEFT(landuse::text, 1) AS landuse_first_char,
        zone,
        land_development_category
    FROM brewgis.assessor.sacog_assessor_parcels
),



-- Deduplicated sales data
sales_data AS (
    SELECT
        apn,
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        sales_lot_size_acres,
        units
    FROM brewgis.assessor.sacog_assessor_sales_deduped
    WHERE apn IN (SELECT apn FROM assessor_parcels)
),

-- Tier 1 (highest priority): from sales/property data
tier1_built_form_key AS (
    SELECT
        apn,
        CASE
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, 0) < 0.15 THEN 'detsf_sl'
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, 0) >= 0.15 THEN 'detsf_ll'
            WHEN property_type IN ('Condo', 'Condominium') THEN 'attsf'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) >= 5 THEN 'mf5p'
            WHEN (property_type IN ('Commercial', 'Retail', 'Office', 'Restaurant', 'Hotel', 'Medical',
                  'Retail/Commercial', 'Commercial/Office')) THEN 'commercial'
            WHEN (property_type IN ('Industrial', 'Manufacturing', 'Warehouse', 'Industrial/Manufacturing',
                  'Transport/Warehouse', 'Construction')) THEN 'industrial'
            WHEN (property_type IN ('Agricultural', 'Farm/Ranch', 'Vacant Agricultural')) THEN 'agricultural'
            WHEN (property_type IN ('Civic', 'Institutional', 'Church', 'School', 'Government', 'Education',
                  'Public', 'Hospital', 'Medical Facility'))
                OR property_type LIKE '%Church%' OR property_type LIKE '%School%'
                OR property_type LIKE '%Government%' THEN 'civic'
            ELSE NULL
        END AS built_form_key,
        property_type,
        units,
        sales_lot_size_acres
    FROM sales_data
),

-- Tier 0: from landuse code
tier0_built_form_key AS (
    SELECT
        ap.apn,
        CASE
            WHEN ap.landuse_prefix LIKE 'A1' THEN
                CASE
                    WHEN ap.lot_size_acres < 0.15 THEN 'detsf_sl'
                    ELSE 'detsf_ll'
                END
            WHEN ap.landuse_prefix LIKE 'A3' THEN 'attsf'
            WHEN ap.landuse_prefix LIKE 'A4' THEN 'detsf_sl'
            WHEN ap.landuse_prefix LIKE 'AE' THEN 'commercial'
            WHEN ap.landuse_prefix LIKE 'AF' THEN 'industrial'
            WHEN ap.landuse_prefix LIKE 'AG' THEN 'agricultural'
            WHEN ap.landuse_prefix IN ('AH', 'AJ') THEN 'civic'
            WHEN ap.landuse_prefix LIKE 'AD' THEN 'undeveloped'
            ELSE NULL
        END AS built_form_key
    FROM assessor_parcels ap
    WHERE ap.landuse IS NOT NULL
)

SELECT
    ap.apn,
    ap.geometry,
    ap.lot_size_acres,
    COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
    COALESCE(id.intersection_density, 0) AS intersection_density,
    COALESCE(t1.built_form_key, t0.built_form_key) AS built_form_key,
    ap.land_development_category
FROM assessor_parcels ap
LEFT JOIN tier1_built_form_key t1 ON ap.apn = t1.apn AND t1.built_form_key IS NOT NULL
LEFT JOIN tier0_built_form_key t0 ON ap.apn = t0.apn AND t0.built_form_key IS NOT NULL
LEFT JOIN brewgis.assessor.parcel_building_sqft_by_type bs ON ap.apn = bs.apn
LEFT JOIN brewgis.assessor.overture_intersection_density id ON ap.apn = id.apn
WHERE COALESCE(t1.built_form_key, t0.built_form_key) IS NOT NULL
  AND COALESCE(t1.built_form_key, t0.built_form_key) IN (
      'detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p', 'commercial', 'industrial'
  );

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_geometry
  ON brewgis.assessor.parcel_known_features USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_apn
  ON brewgis.assessor.parcel_known_features (apn);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_land_dev_cat
  ON brewgis.assessor.parcel_known_features (land_development_category);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_lot_size_acres
  ON brewgis.assessor.parcel_known_features (lot_size_acres);
  CREATE INDEX IF NOT EXISTS idx_parcel_known_features_cat_geom
  ON brewgis.assessor.parcel_known_features USING GIST (land_development_category, geometry);
ANALYZE brewgis.assessor.parcel_known_features;
