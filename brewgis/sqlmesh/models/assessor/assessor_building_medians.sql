MODEL (
  name brewgis.assessor.assessor_building_medians,
  kind VIEW
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
    FROM public.sacog_assessor_sales_raw s
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
