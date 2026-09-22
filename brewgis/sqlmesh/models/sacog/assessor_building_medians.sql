MODEL (
  name brewgis.sacog.assessor_building_medians,
  kind VIEW,
  description 'Median living area, building square footage and lot size per assessor property type of sold parcels.',
  column_descriptions (
    property_type = 'Assessor property type of the group, blank values replaced by Other.',
    parcel_count = 'Number of assessor sales rows in the group (count).',
    median_living_area = 'Median living area of the sold buildings in the group (sq ft).',
    median_building_sf = 'Median building square footage of the sold properties in the group (sq ft).',
    median_lot_size_acres = 'Median lot size of the sold parcels in the group (acres).'
  )
);

-- Assessor Building Medians — per-land-use median building characteristics.
--
-- Computes median living area, building sqft, and lot size per property type
-- from the 55K recently-sold parcels.  Used to estimate building sqft for
-- the 453K parcels without sales data.

WITH sales_with_type AS (
    SELECT
        s.*,
        COALESCE(
            NULLIF(TRIM(s.property_type), ''),
            'Other'
        ) AS property_type_clean
    FROM brewgis.sacog.assessor_sales_raw s
)

SELECT
    property_type_clean AS property_type,
    COUNT(*) AS parcel_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY living_area)
        AS median_living_area,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY building_sf)
        AS median_building_sf,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lot_size_acres)
        AS median_lot_size_acres
FROM sales_with_type
WHERE living_area IS NOT NULL
    OR building_sf IS NOT NULL
GROUP BY property_type_clean
