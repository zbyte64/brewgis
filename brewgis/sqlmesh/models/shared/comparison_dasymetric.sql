MODEL (
  name brewgis.@{region}.comparison_dasymetric,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  ),
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- Region Comparison Dasymetric Crosswalk — enriches parcels with dasymetric
-- weights, DU estimation, and regressor predictions.
--
-- For regions with real assessor APNs (SACOG) multiple parcels can share one
-- APN (or one parcel intersects several APNs); scalar quantities are
-- allocated proportionally by intersection area then summed per parcel.
-- For regions without assessor data (Fresno) the dasymetric_intersections
-- adapter yields a 1:1 parcel→apn mapping, so apn_weight = 1.0 and the sums
-- pass values through unchanged.  Identical SQL — the adapter difference
-- makes both cases work.
--
-- Categorical columns are taken from the APN with the largest intersection
-- area for that parcel. The aggregation by parcel_id produces exactly one
-- row per parcel (INCREMENTAL_BY_UNIQUE_KEY-safe for base_canvas_geometry).

WITH apn_weights AS (
    SELECT
        si.parcel_id,
        si.apn,
        si.intersect_area_sqft,
        SUM(si.intersect_area_sqft) OVER (PARTITION BY si.apn) AS apn_total_area,
        CASE
            WHEN SUM(si.intersect_area_sqft) OVER (PARTITION BY si.apn) > 0
            THEN si.intersect_area_sqft
                 / SUM(si.intersect_area_sqft) OVER (PARTITION BY si.apn)
            ELSE 1.0
        END AS apn_weight
    FROM brewgis.@{region}.dasymetric_intersections si
),

scaled AS (
    SELECT
        aw.parcel_id,
        aw.apn,
        aw.apn_weight,
        aw.intersect_area_sqft,
        ROW_NUMBER() OVER (
            PARTITION BY aw.parcel_id
            ORDER BY aw.intersect_area_sqft DESC
        ) AS rn,
        sp.geometry,
        -- Allocate scalar quantities proportionally
        dw.lot_size_acres          * aw.apn_weight AS lot_size_acres,
        dw.actual_living_sqft      * aw.apn_weight AS actual_living_sqft,
        dw.actual_building_sqft    * aw.apn_weight AS actual_building_sqft,
        dw.residential_building_sqft * aw.apn_weight AS residential_building_sqft,
        dw.commercial_building_sqft  * aw.apn_weight AS commercial_building_sqft,
        dw.industrial_building_sqft  * aw.apn_weight AS industrial_building_sqft,
        dw.other_building_sqft       * aw.apn_weight AS other_building_sqft,
        dw.total_footprint_sqft      * aw.apn_weight AS total_footprint_sqft,
        -- Building count: allocate then round
        ROUND(dw.building_count * aw.apn_weight)::int AS building_count,
        -- Dasymetric weights: allocate proportionally
        dw.pop_dasym_weight * aw.apn_weight AS pop_dasym_weight,
        dw.emp_dasym_weight * aw.apn_weight AS emp_dasym_weight,
        -- DU estimation: allocate proportionally
        de.du              * aw.apn_weight AS du,
        de.pop_dasym_weight * aw.apn_weight AS du_pop_dasym_weight,
        de.hh_dasym_weight  * aw.apn_weight AS hh_dasym_weight,
        de.hh               * aw.apn_weight AS hh,
        -- Categorical labels
        dw.land_development_category,
        NULL::text AS built_form_key,
        NULL::text AS du_subtype,
        NULL::int AS is_residential,
        -- Ratio/density columns (unchanged per APN)
        dw.footprint_ratio,
        dw.max_levels,
        dw.intersection_density,
        -- DU breakdown from regressor (proportional allocation)
        de.du_detsf_sl_regressor  * aw.apn_weight AS du_detsf_sl,
        de.du_detsf_ll_regressor  * aw.apn_weight AS du_detsf_ll,
        de.du_attsf_regressor     * aw.apn_weight AS du_attsf,
        de.du_mf2to4_regressor    * aw.apn_weight AS du_mf2to4,
        de.du_mf5p_regressor      * aw.apn_weight AS du_mf5p,
        de.du_total_regressor     * aw.apn_weight AS du_total_regressor,
        -- Building sqft from sqft_regressor (renamed for downstream compat)
        dr.bldg_sqft_detsf_sl          * aw.apn_weight AS bldg_area_detsf_sl,
        dr.bldg_sqft_detsf_ll          * aw.apn_weight AS bldg_area_detsf_ll,
        dr.bldg_sqft_attsf             * aw.apn_weight AS bldg_area_attsf,
        dr.bldg_sqft_mf                * aw.apn_weight AS bldg_area_mf,
        dr.bldg_sqft_retail_services   * aw.apn_weight AS bldg_area_retail_services,
        dr.bldg_sqft_restaurant        * aw.apn_weight AS bldg_area_restaurant,
        dr.bldg_sqft_accommodation     * aw.apn_weight AS bldg_area_accommodation,
        dr.bldg_sqft_arts_entertainment * aw.apn_weight AS bldg_area_arts_entertainment,
        dr.bldg_sqft_other_services    * aw.apn_weight AS bldg_area_other_services,
        dr.bldg_sqft_office_services   * aw.apn_weight AS bldg_area_office_services,
        dr.bldg_sqft_public_admin      * aw.apn_weight AS bldg_area_public_admin,
        dr.bldg_sqft_education         * aw.apn_weight AS bldg_area_education,
        dr.bldg_sqft_medical_services  * aw.apn_weight AS bldg_area_medical_services,
        dr.bldg_sqft_transport_warehousing * aw.apn_weight AS bldg_area_transport_warehousing,
        dr.bldg_sqft_wholesale         * aw.apn_weight AS bldg_area_wholesale,
        -- Rates from du_estimation
        de.hh_size,
        de.vacancy_rate,
        -- Employment sector ratios from emp_ratios_regressor
        er.emp_ret_per_acre AS emp_ret_per_acre,
        er.emp_off_per_acre AS emp_off_per_acre,
        er.emp_pub_per_acre AS emp_pub_per_acre,
        er.emp_ind_per_acre AS emp_ind_per_acre,
        er.emp_ag_per_acre  AS emp_ag_per_acre
    FROM apn_weights aw
    JOIN brewgis.@{region}.parcel_shim sp
        ON aw.parcel_id = sp.parcel_id
    JOIN brewgis.@{region}.parcel_dasymetric_weights dw
        ON aw.apn = dw.apn
    LEFT JOIN brewgis.@{region}.parcel_du_estimation de
        ON aw.apn = de.apn
    LEFT JOIN brewgis.@{region}.sqft_regressor dr
        ON aw.apn = dr.apn
    LEFT JOIN brewgis.@{region}.emp_ratios_regressor er
        ON aw.apn = er.apn
)

SELECT
    parcel_id,
    geometry,
    -- Scalars: sum allocated contributions from all matching APNs
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
    -- Regressor DU breakdown (proportional allocation summed)
    SUM(du_detsf_sl) AS du_detsf_sl,
    SUM(du_detsf_ll) AS du_detsf_ll,
    SUM(du_attsf) AS du_attsf,
    SUM(du_mf2to4) AS du_mf2to4,
    SUM(du_mf5p) AS du_mf5p,
    SUM(du_total_regressor) AS du_total_regressor,
    -- Regressor building sqft (proportional allocation summed)
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
    -- APN identifier: from the dominant APN (largest intersection area)
    MAX(CASE WHEN rn = 1 THEN apn END) AS apn,
    -- Categoricals: pick from the APN with the largest intersection area
    MAX(CASE WHEN rn = 1 THEN land_development_category END)
        AS land_development_category,
    MAX(CASE WHEN rn = 1 THEN built_form_key END) AS built_form_key,
    MAX(CASE WHEN rn = 1 THEN du_subtype END) AS du_subtype,
    MAX(CASE WHEN rn = 1 THEN is_residential END)
        AS is_residential,
    -- Ratio/density: weighted by apn_weight (sum of weights per parcel)
    SUM(footprint_ratio * apn_weight) / NULLIF(SUM(apn_weight), 0) AS footprint_ratio,
    SUM(max_levels * apn_weight) / NULLIF(SUM(apn_weight), 0) AS max_levels,
    SUM(intersection_density * apn_weight) / NULLIF(SUM(apn_weight), 0) AS intersection_density,
    -- Rates: weighted by apn_weight
    SUM(hh_size * apn_weight) / NULLIF(SUM(apn_weight), 0) AS hh_size,
    SUM(vacancy_rate * apn_weight) / NULLIF(SUM(apn_weight), 0) AS vacancy_rate,
    -- Employment sector ratios: weighted by apn_weight
    SUM(COALESCE(emp_ret_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_ret_per_acre,
    SUM(COALESCE(emp_off_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_off_per_acre,
    SUM(COALESCE(emp_pub_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_pub_per_acre,
    SUM(COALESCE(emp_ind_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_ind_per_acre,
    SUM(COALESCE(emp_ag_per_acre, 0) * apn_weight) / NULLIF(SUM(apn_weight), 0) AS emp_ag_per_acre
FROM scaled
GROUP BY parcel_id, geometry;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_comparison_dasymetric_geom_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_@{region}_comparison_dasymetric_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_@{region}_comparison_dasymetric_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  ANALYZE @this_model;
