MODEL (
  name brewgis.base_canvas.base_canvas_geometry,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id))
  ),

  depends_on (
    brewgis.comparison.sacog_parcel_shim,
    brewgis.comparison.sacog_comparison_dasymetric
  )
);

-- Base Canvas Geometry — first ETL step.
--
-- Reads raw parcel data from brewgis.parcels (via the parcels source),
-- casts geometry to PostGIS geometry (EPSG:4326), computes area columns
-- from local_srid (CA Albers, SRID 3310), and passes through source columns.
--
-- Area columns use _acres suffix per BASE_MAP_METHODOLOGY.md.

WITH assessor_categories AS (
    SELECT use_code::text, category FROM brewgis.seeds.assessor_use_codes
),

parcel_geom AS (
    SELECT
        p.parcel_id,
        p.geometry,
        ST_Transform(p.geometry, @VAR('local_srid', 3310)) AS local_geometry,
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
    FROM @parcel_table p
    LEFT JOIN assessor_categories ac ON LEFT(COALESCE(p.assessor_use_code, ''), 2) = ac.use_code
),

parcel_area AS (
    SELECT
        parcel_geom.*,
        ROUND((ST_Area(parcel_geom.local_geometry) / 4046.86)::numeric, 4) AS area_gross
    FROM parcel_geom
),

dasymetric_enrichment AS (
    SELECT
        parcel_id,
        apn,
        land_development_category,
        built_form_key,
        du_subtype,
        is_residential,
        residential_building_sqft,
        commercial_building_sqft,
        industrial_building_sqft,
        other_building_sqft,
        total_footprint_sqft,
        building_count,
        footprint_ratio,
        max_levels,
        intersection_density,
        pop_dasym_weight,
        emp_dasym_weight,
        du,
        hh_size,
        vacancy_rate,
        du_pop_dasym_weight,
        hh_dasym_weight,
        hh
    FROM brewgis.comparison.sacog_comparison_dasymetric
)

SELECT
    parcel_area.parcel_id,
    parcel_area.geometry,
    parcel_area.local_geometry,
    parcel_area.county,
    COALESCE(de.land_development_category, parcel_area.land_development_category) AS land_development_category,
    COALESCE(de.built_form_key, parcel_area.built_form_key) AS built_form_key,
    COALESCE(de.intersection_density, parcel_area.intersection_density) AS intersection_density,
    parcel_area.pop,
    parcel_area.hh,
    parcel_area.du,
    parcel_area.land_use,
    parcel_area.assessor_use_code,
    parcel_area.bldg_area_detsf_sl,
    parcel_area.bldg_area_detsf_ll,
    parcel_area.bldg_area_attsf,
    parcel_area.bldg_area_mf,
    parcel_area.bldg_area_retail_services,
    parcel_area.bldg_area_restaurant,
    parcel_area.bldg_area_accommodation,
    parcel_area.bldg_area_arts_entertainment,
    parcel_area.bldg_area_other_services,
    parcel_area.bldg_area_office_services,
    parcel_area.bldg_area_public_admin,
    parcel_area.bldg_area_education,
    parcel_area.bldg_area_medical_services,
    parcel_area.bldg_area_transport_warehousing,
    parcel_area.bldg_area_wholesale,
    parcel_area.residential_irrigated_area,
    parcel_area.commercial_irrigated_area,
    parcel_area.area_parcel_res,
    parcel_area.area_parcel_emp_ag,
    parcel_area.area_parcel_emp,
    parcel_area.area_parcel_mixed_use,
    parcel_area.area_parcel_no_use,
    parcel_area.area_gross,
    ROUND(parcel_area.area_gross::numeric, 4) AS area_gross_acres,
    ROUND(parcel_area.area_gross::numeric, 4) AS area_parcel_acres,
    ROUND((parcel_area.area_gross * 0.7)::numeric, 4) AS area_dev_condition_acres,
    ROUND((parcel_area.area_gross * 0.15)::numeric, 4) AS area_row_acres,
    de.apn,
    de.du_subtype,
    de.is_residential,
    de.residential_building_sqft,
    de.commercial_building_sqft,
    de.industrial_building_sqft,
    de.other_building_sqft,
    de.total_footprint_sqft,
    de.building_count,
    de.footprint_ratio,
    de.max_levels,
    0.0::double precision AS dasym_impervious_fraction,
    de.pop_dasym_weight,
    de.emp_dasym_weight,
    de.du AS du_estimated,
    de.hh_size,
    de.vacancy_rate,
    de.du_pop_dasym_weight,
    de.hh_dasym_weight,
    de.hh AS hh_estimated
FROM parcel_area
LEFT JOIN dasymetric_enrichment de ON parcel_area.parcel_id = de.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_base_canvas_geometry_geometry
  ON brewgis.base_canvas.base_canvas_geometry USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_base_canvas_geometry_centroid
  ON brewgis.base_canvas.base_canvas_geometry USING GIST (ST_Centroid(geometry));
