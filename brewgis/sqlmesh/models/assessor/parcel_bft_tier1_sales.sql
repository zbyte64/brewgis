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
),
at_parcels AS (
    SELECT apn FROM brewgis.assessor.sacog_assessor_parcels WHERE landuse LIKE 'AT%'
),
classifications AS (
    SELECT
        sd.apn,
        CASE
            WHEN (sd.property_type IN ('SFR', 'Single Family Residence') OR sd.property_type LIKE 'Single Family%')
                AND COALESCE(sd.sales_lot_size_acres, 0) < 0.15 THEN 'bt__medium_density_detached_residential'
            WHEN (sd.property_type IN ('SFR', 'Single Family Residence') OR sd.property_type LIKE 'Single Family%')
                AND COALESCE(sd.sales_lot_size_acres, 0) >= 0.15 THEN 'bt__low_density_detached_residential'
            WHEN sd.property_type LIKE '%Townhouse%' THEN 'bt__medium_density_attached_residential'
            WHEN sd.property_type LIKE '%Row%House%' THEN 'bt__medium_density_attached_residential'
            WHEN sd.property_type LIKE '%Attached%' THEN 'bt__medium_density_attached_residential'
            WHEN sd.property_type LIKE '%PUD%' THEN 'bt__medium_density_attached_residential'
            WHEN sd.property_type IN ('Condo', 'Condominium', 'Uncondo',
                                       'Pud', 'Attch') THEN 'bt__medium_density_attached_residential'
            WHEN (sd.property_type IN ('MF', 'Multiple Family Residence') OR sd.property_type LIKE 'Multiple Family%')
                AND COALESCE(sd.units, 0) BETWEEN 2 AND 4 THEN 'bt__medium_density_attached_residential'
            WHEN (sd.property_type IN ('MF', 'Multiple Family Residence') OR sd.property_type LIKE 'Multiple Family%')
                AND COALESCE(sd.units, 0) >= 5 THEN 'bt__high_density_attached_residential'
            WHEN (sd.property_type IN ('Commercial', 'Retail', 'Office', 'Restaurant', 'Hotel', 'Medical',
                  'Retail/Commercial', 'Commercial/Office')) THEN 'bt__communityneighborhood_retail'
            WHEN (sd.property_type IN ('Industrial', 'Manufacturing', 'Warehouse', 'Industrial/Manufacturing',
                  'Transport/Warehouse', 'Construction')) THEN 'bt__light_industrial'
            WHEN (sd.property_type IN ('Agricultural', 'Farm/Ranch', 'Vacant Agricultural')) THEN 'bt__agriculture'
            WHEN (sd.property_type IN ('Civic', 'Institutional', 'Church', 'School', 'Government', 'Education',
                  'Public', 'Hospital', 'Medical Facility'))
                OR sd.property_type LIKE '%Church%' OR sd.property_type LIKE '%School%'
                OR sd.property_type LIKE '%Government%' THEN 'bt__publicquasi_public'
            ELSE NULL
        END AS built_form_key,
        CASE WHEN at.apn IS NOT NULL THEN 1 ELSE 0 END AS is_at_parcel
    FROM sales_data sd
    LEFT JOIN at_parcels at ON sd.apn = at.apn
)
SELECT apn, built_form_key
FROM classifications
WHERE built_form_key IS NOT NULL
  AND NOT (is_at_parcel = 1 AND built_form_key NOT IN ('bt__medium_density_attached_residential', 'bt__high_density_attached_residential'));
