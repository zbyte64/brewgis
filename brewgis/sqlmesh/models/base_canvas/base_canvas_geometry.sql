MODEL (
  name brewgis.base_canvas.base_canvas_geometry,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Base Canvas Geometry — first ETL step.
--
-- Reads raw parcel data from brewgis.parcels (via the parcels source),
-- casts geometry to PostGIS geometry (EPSG:4326), computes area columns
-- from SRID 3857, and passes through source columns.

WITH assessor_categories AS (
    SELECT use_code::text, category FROM assessor_use_codes
),

parcel_geom AS (
    SELECT
        p.parcel_id,
        p.geometry,
        ST_Transform(p.geometry, 3857) AS local_geometry,
        p.county,
        COALESCE(
            NULLIF(p.land_development_category, ''),
            ac.category, ''
        ) AS land_development_category,
        p.built_form_key,
        p.intersection_density,
        p.pop,
        p.hh,
        p.du,
        p.land_use,
        p.assessor_use_code,
        p.bldg_area_detsf_sl,
        p.bldg_area_detsf_ll,
        p.bldg_area_attsf,
        p.bldg_area_mf,
        p.bldg_area_retail_services,
        p.bldg_area_restaurant,
        p.bldg_area_accommodation,
        p.bldg_area_arts_entertainment,
        p.bldg_area_other_services,
        p.bldg_area_office_services,
        p.bldg_area_public_admin,
        p.bldg_area_education,
        p.bldg_area_medical_services,
        p.bldg_area_transport_warehousing,
        p.bldg_area_wholesale,
        p.residential_irrigated_area,
        p.commercial_irrigated_area,
        p.area_parcel_res,
        p.area_parcel_emp_ag,
        p.area_parcel_emp,
        p.area_parcel_mixed_use,
        p.area_parcel_no_use
    FROM public.parcels p
    LEFT JOIN assessor_categories ac ON LEFT(COALESCE(p.assessor_use_code, ''), 2) = ac.use_code
),

parcel_area AS (
    SELECT
        parcel_geom.*,
        ROUND((ST_Area(parcel_geom.local_geometry) / 4046.86)::numeric, 4) AS area_gross
    FROM parcel_geom
)

SELECT
    parcel_area.*,
    ROUND(area_gross::numeric, 4) AS area_parcel,
    ROUND((area_gross * 0.7)::numeric, 4) AS area_dev_condition,
    ROUND((area_gross * 0.15)::numeric, 4) AS area_row
FROM parcel_area
