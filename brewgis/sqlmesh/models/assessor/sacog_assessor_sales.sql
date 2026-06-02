MODEL (
  name brewgis.assessor.sacog_assessor_sales,
  kind VIEW
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
FROM brewgis.assessor_sales
