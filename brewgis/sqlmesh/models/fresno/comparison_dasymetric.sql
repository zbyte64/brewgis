MODEL (
  name brewgis.fresno.comparison_dasymetric,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Fresno Comparison Dasymetric Crosswalk — 1:1 parcel-to-APN mapping.
--
-- Since Fresno parcels lack assessor APNs, each parcel has a 1:1 mapping
-- where parcel_id = apn.  Scalar quantities are passed through directly
-- (no proportional allocation needed).  Output column contract is identical
-- to sacog_comparison_dasymetric so that base_canvas_geometry can consume it
-- via the dasymetric_source variable override.

WITH apn_weights AS (
    SELECT
        si.parcel_id,
        si.apn,
        si.intersect_area_sqft,
        -- 1:1 mapping: apn_total_area = intersect_area_sqft, apn_weight = 1.0
        si.intersect_area_sqft AS apn_total_area,
        1.0::double precision AS apn_weight
    FROM brewgis.fresno.dasymetric_intersections si
),

scaled AS (
    SELECT
        aw.parcel_id,
        aw.apn,
        aw.apn_weight,
        aw.intersect_area_sqft,
        1 AS rn,
        sp.geometry,
        -- Pass through scalar quantities directly (1:1 mapping)
        dw.lot_size_acres         AS lot_size_acres,
        dw.actual_living_sqft     AS actual_living_sqft,
        dw.actual_building_sqft   AS actual_building_sqft,
        dw.residential_building_sqft AS residential_building_sqft,
        dw.commercial_building_sqft  AS commercial_building_sqft,
        dw.industrial_building_sqft  AS industrial_building_sqft,
        dw.other_building_sqft       AS other_building_sqft,
        dw.total_footprint_sqft      AS total_footprint_sqft,
        dw.building_count            AS building_count,
        dw.pop_dasym_weight AS pop_dasym_weight,
        dw.emp_dasym_weight AS emp_dasym_weight,
        -- DU estimation from fresno_du_estimation (Fresno-specific, same contract as parcel_du_estimation)
        de.du               AS du,
        de.pop_dasym_weight AS du_pop_dasym_weight,
        de.hh_dasym_weight  AS hh_dasym_weight,
        de.hh               AS hh,
        dw.land_development_category,
        -- Categoricals from dasymetric weights
        NULL::text AS built_form_key,
        NULL::text AS du_subtype,
        NULL::int AS is_residential,
        dw.footprint_ratio,
        dw.max_levels,
        dw.intersection_density,
        -- DU breakdown from regressor (from fresno_du_regressor via du_estimation)
        de.du_detsf_sl_regressor  AS du_detsf_sl,
        de.du_detsf_ll_regressor  AS du_detsf_ll,
        de.du_attsf_regressor     AS du_attsf,
        de.du_mf2to4_regressor    AS du_mf2to4,
        de.du_mf5p_regressor      AS du_mf5p,
        de.du_total_regressor     AS du_total_regressor,
        -- Building sqft from regressor (from fresno_sqft_regressor)
        dr.bldg_sqft_detsf_sl          AS bldg_area_detsf_sl,
        dr.bldg_sqft_detsf_ll          AS bldg_area_detsf_ll,
        dr.bldg_sqft_attsf             AS bldg_area_attsf,
        dr.bldg_sqft_mf                AS bldg_area_mf,
        dr.bldg_sqft_retail_services   AS bldg_area_retail_services,
        dr.bldg_sqft_restaurant        AS bldg_area_restaurant,
        dr.bldg_sqft_accommodation     AS bldg_area_accommodation,
        dr.bldg_sqft_arts_entertainment AS bldg_area_arts_entertainment,
        dr.bldg_sqft_other_services    AS bldg_area_other_services,
        dr.bldg_sqft_office_services   AS bldg_area_office_services,
        dr.bldg_sqft_public_admin      AS bldg_area_public_admin,
        dr.bldg_sqft_education         AS bldg_area_education,
        dr.bldg_sqft_medical_services  AS bldg_area_medical_services,
        dr.bldg_sqft_transport_warehousing AS bldg_area_transport_warehousing,
        dr.bldg_sqft_wholesale         AS bldg_area_wholesale,
        -- Rates from du_estimation
        de.hh_size,
        de.vacancy_rate,
        -- Employment sector ratios from fresno_emp_ratios_regressor
        er.emp_ret_per_acre AS emp_ret_per_acre,
        er.emp_off_per_acre AS emp_off_per_acre,
        er.emp_pub_per_acre AS emp_pub_per_acre,
        er.emp_ind_per_acre AS emp_ind_per_acre,
        er.emp_ag_per_acre  AS emp_ag_per_acre
    FROM apn_weights aw
    JOIN brewgis.fresno.parcel_shim sp
        ON aw.parcel_id = sp.parcel_id
    JOIN brewgis.fresno.dasymetric_weights dw
        ON aw.apn = dw.apn
    LEFT JOIN brewgis.fresno.du_estimation de
        ON aw.apn = de.apn
    LEFT JOIN brewgis.fresno.sqft_regressor dr
        ON aw.apn = dr.apn
    LEFT JOIN brewgis.fresno.emp_ratios_regressor er
        ON aw.apn = er.apn
)

SELECT
    parcel_id,
    geometry,
    -- Scalars: pass through directly (1:1 mapping means SUM = value)
    SUM(lot_size_acres) AS lot_size_acres,
    SUM(actual_living_sqft) AS actual_living_sqft,
    SUM(actual_building_sqft) AS actual_building_sqft,
    SUM(residential_building_sqft) AS residential_building_sqft,
    SUM(commercial_building_sqft) AS commercial_building_sqft,
    SUM(industrial_building_sqft) AS industrial_building_sqft,
    SUM(other_building_sqft) AS other_building_sqft,
    SUM(total_footprint_sqft) AS total_footprint_sqft,
    SUM(building_count) AS building_count,
    SUM(pop_dasym_weight) AS pop_dasym_weight,
    SUM(emp_dasym_weight) AS emp_dasym_weight,
    SUM(du) AS du,
    SUM(du_pop_dasym_weight) AS du_pop_dasym_weight,
    SUM(hh_dasym_weight) AS hh_dasym_weight,
    SUM(hh) AS hh,
    -- Regressor DU breakdown
    SUM(du_detsf_sl) AS du_detsf_sl,
    SUM(du_detsf_ll) AS du_detsf_ll,
    SUM(du_attsf) AS du_attsf,
    SUM(du_mf2to4) AS du_mf2to4,
    SUM(du_mf5p) AS du_mf5p,
    SUM(du_total_regressor) AS du_total_regressor,
    -- Regressor building sqft
    SUM(bldg_area_detsf_sl) AS bldg_area_detsf_sl,
    SUM(bldg_area_detsf_ll) AS bldg_area_detsf_ll,
    SUM(bldg_area_attsf) AS bldg_area_attsf,
    SUM(bldg_area_mf) AS bldg_area_mf,
    SUM(bldg_area_retail_services) AS bldg_area_retail_services,
    SUM(bldg_area_restaurant) AS bldg_area_restaurant,
    SUM(bldg_area_accommodation) AS bldg_area_accommodation,
    SUM(bldg_area_arts_entertainment) AS bldg_area_arts_entertainment,
    SUM(bldg_area_other_services) AS bldg_area_other_services,
    SUM(bldg_area_office_services) AS bldg_area_office_services,
    SUM(bldg_area_public_admin) AS bldg_area_public_admin,
    SUM(bldg_area_education) AS bldg_area_education,
    SUM(bldg_area_medical_services) AS bldg_area_medical_services,
    SUM(bldg_area_transport_warehousing) AS bldg_area_transport_warehousing,
    SUM(bldg_area_wholesale) AS bldg_area_wholesale,
    -- APN identifier (parcel_id since 1:1)
    MAX(CASE WHEN rn = 1 THEN apn END) AS apn,
    -- Categoricals
    MAX(CASE WHEN rn = 1 THEN land_development_category END)
        AS land_development_category,
    MAX(CASE WHEN rn = 1 THEN built_form_key END) AS built_form_key,
    MAX(CASE WHEN rn = 1 THEN du_subtype END) AS du_subtype,
    MAX(CASE WHEN rn = 1 THEN is_residential END) AS is_residential,
    -- Ratio/density
    SUM(footprint_ratio * apn_weight) / NULLIF(SUM(apn_weight), 0) AS footprint_ratio,
    SUM(max_levels * apn_weight) / NULLIF(SUM(apn_weight), 0) AS max_levels,
    SUM(intersection_density * apn_weight) / NULLIF(SUM(apn_weight), 0) AS intersection_density,
    -- Rates
    SUM(hh_size * apn_weight) / NULLIF(SUM(apn_weight), 0) AS hh_size,
    SUM(vacancy_rate * apn_weight) / NULLIF(SUM(apn_weight), 0) AS vacancy_rate,
    -- Employment sector ratios
    SUM(COALESCE(emp_ret_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_ret_per_acre,
    SUM(COALESCE(emp_off_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_off_per_acre,
    SUM(COALESCE(emp_pub_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_pub_per_acre,
    SUM(COALESCE(emp_ind_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_ind_per_acre,
    SUM(COALESCE(emp_ag_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_ag_per_acre
FROM scaled
GROUP BY parcel_id, geometry;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fresno_comparison_dasymetric_geom_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_fresno_comparison_dasymetric_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_fresno_comparison_dasymetric_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
