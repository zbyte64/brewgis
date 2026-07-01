MODEL (
  name brewgis.assessor.parcel_bft_tier1_sales,
  kind VIEW,
  audits (
    assert_bft_sales_sfr_lot_boundary,
    assert_bft_sales_mf_unit_boundary
  )
);

-- Tier 1 (highest priority): from sales/property data. Returns one row per
-- parcel successfully classified by sales data alone. Only outputs
-- (apn, built_form_key) — callers JOIN the source tables for additional
-- attributes.

WITH sales_data AS (
    SELECT
        apn,
        actual_living_sqft,
        actual_building_sqft,
        property_type,
        sales_lot_size_acres,
        units
    FROM brewgis.assessor.sacog_assessor_sales_deduped
)
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
    END AS built_form_key
FROM sales_data
WHERE CASE
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
    END IS NOT NULL;
