MODEL (
  name brewgis.sacog.assessor_sales,
  kind VIEW,
  description 'Sacramento County assessor sales and building characteristics keyed by APN, from assessor_sales_raw.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the sold property.',
    living_area = 'Total living area of the sold building (sq ft).',
    building_sf = 'Total building square footage reported by the assessor for the sold property (sq ft).',
    year_built = 'Effective year the sold building was built.',
    stories = 'Number of stories in the sold building.',
    bedrooms = 'Number of bedrooms in the sold building.',
    baths = 'Number of bathrooms in the sold building.',
    ground_floor_gross = 'Gross ground-floor area reported by the assessor for the sold building.',
    land_use_code = 'Assessor land-use code of the sold parcel.',
    property_type = 'Assessor property type of the sold property.',
    sales_price = 'Indicated sale price reported by the Sacramento County assessor sales layer.',
    lot_size_acres = 'Lot size of the sold parcel (acres).',
    units = 'Number of units reported by the assessor for the sold property (count).'
  )
);

-- SACOG Assessor Sales — building characteristics from Sacramento County Assessor,
-- keyed by apn.
--
-- Reads from brewgis.assessor_sales (populated by the assessor dlt pipeline
-- from ASSESSOR/MapServer/1) and renames columns for downstream building
-- median computation.

SELECT
    apn,
    living_area,
    building_sf,
    year_built,
    stories,
    bedrooms,
    baths,
    ground_floor_gross,
    land_use_code,
    property_type,
    sales_price,
    lot_size_acres,
    units
FROM brewgis.sacog.assessor_sales_raw
