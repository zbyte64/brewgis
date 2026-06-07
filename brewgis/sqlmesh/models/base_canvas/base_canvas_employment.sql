MODEL (
  name brewgis.base_canvas.base_canvas_employment,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Base Canvas Employment — spatial allocation from LEHD LODES WAC.
--
-- For each parcel from base_canvas_demographics, allocates employment
-- values from intersecting LEHD WAC blocks using area-weighted allocation.
-- Dasymetric weights and land-use constraints disabled (default).

WITH wac_data AS (
    SELECT
        w.geoid,
        w.emp,
        w.emp_retail_services,
        w.emp_restaurant,
        w.emp_accommodation,
        w.emp_arts_entertainment,
        w.emp_other_services,
        w.emp_office_services,
        w.emp_medical_services,
        w.emp_public_admin,
        w.emp_education,
        w.emp_manufacturing,
        w.emp_wholesale,
        w.emp_transport_warehousing,
        w.emp_utilities,
        w.emp_construction,
        w.emp_agriculture,
        w.emp_extraction,
        w.emp_military,
        w.emp_ret,
        w.emp_off,
        w.emp_pub,
        w.emp_ind,
        w.emp_ag,
        w.geometry,
        ST_Transform(w.geometry, 3857) AS local_geometry
    FROM brewgis.staging.wac_block w
    WHERE w.geometry IS NOT NULL
),

wac_prep AS (
    SELECT
        w.*,
        GREATEST(ST_Area(w.local_geometry), 1e-10) AS wac_area,
        ST_Envelope(w.local_geometry) AS wac_envelope
    FROM wac_data w
),

-- Parcel geometry from base_canvas_demographics
parcel_with_weights AS (
    SELECT
        p.*
    FROM brewgis.base_canvas.base_canvas_demographics p
),

-- Land classification reference tables
assessor_codes AS (
    SELECT use_code::text, category FROM brewgis.seeds.assessor_use_codes
),

sacog_use AS (
    SELECT land_use_label, category FROM brewgis.seeds.sacog_land_use
),

-- Spatial intersection with area computation
intersections AS (
    SELECT
        p.parcel_id,
        w.geoid,
        -- Land development category from parcel
        COALESCE(
            NULLIF(p.land_development_category, ''),
            ac.category,
            su.category,
            'urban'
        ) AS land_development_category,
        w.emp,
        w.emp_retail_services,
        w.emp_restaurant,
        w.emp_accommodation,
        w.emp_arts_entertainment,
        w.emp_other_services,
        w.emp_office_services,
        w.emp_medical_services,
        w.emp_public_admin,
        w.emp_education,
        w.emp_manufacturing,
        w.emp_wholesale,
        w.emp_transport_warehousing,
        w.emp_utilities,
        w.emp_construction,
        w.emp_agriculture,
        w.emp_extraction,
        w.emp_military,
        w.emp_ret,
        w.emp_off,
        w.emp_pub,
        w.emp_ind,
        w.emp_ag,
        w.wac_area,
        ST_Area(ST_ClipByBox2D(p.local_geometry, w.wac_envelope)) AS intersect_area
    FROM parcel_with_weights p
    JOIN wac_prep w ON ST_Intersects(p.geometry, w.geometry)
    LEFT JOIN assessor_codes ac
        ON LEFT(COALESCE(p.assessor_use_code, ''), 2) = ac.use_code::text
    LEFT JOIN sacog_use su
        ON TRIM(COALESCE(p.land_use, '')) = su.land_use_label
),

-- Per-WAC-block total intersection area for normalization
block_intersect_totals AS (
    SELECT
        i.geoid,
        SUM(i.intersect_area) AS total_intersect_area
    FROM intersections i
    GROUP BY i.geoid
),

allocated AS (
    SELECT
        i.parcel_id,
        SUM(i.emp * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp,
        SUM(i.emp_retail_services * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_retail_services,
        SUM(i.emp_restaurant * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_restaurant,
        SUM(i.emp_accommodation * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_accommodation,
        SUM(i.emp_arts_entertainment * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_arts_entertainment,
        SUM(i.emp_other_services * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_other_services,
        SUM(i.emp_office_services * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_office_services,
        SUM(i.emp_medical_services * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_medical_services,
        SUM(i.emp_public_admin * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_public_admin,
        SUM(i.emp_education * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_education,
        SUM(i.emp_manufacturing * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_manufacturing,
        SUM(i.emp_wholesale * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_wholesale,
        SUM(i.emp_transport_warehousing * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_transport_warehousing,
        SUM(i.emp_utilities * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_utilities,
        SUM(i.emp_construction * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_construction,
        SUM(i.emp_agriculture * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_agriculture,
        SUM(i.emp_extraction * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_extraction,
        SUM(i.emp_military * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_military,
        SUM(i.emp_ret * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_ret,
        SUM(i.emp_off * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_off,
        SUM(i.emp_pub * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_pub,
        SUM(i.emp_ind * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_ind,
        SUM(i.emp_ag * i.intersect_area / NULLIF(bit.total_intersect_area, 0)) AS emp_ag
    FROM intersections i
    LEFT JOIN block_intersect_totals bit ON i.geoid = bit.geoid
    GROUP BY i.parcel_id
)

SELECT
    p.parcel_id,
    p.geometry,
    p.local_geometry,
    p.county,
    p.land_development_category,
    p.built_form_key,
    p.intersection_density,
    p.area_gross,
    p.area_parcel,
    p.area_dev_condition,
    p.area_row,
    p.pop,
    p.pop_groupquarter,
    p.hh,
    p.du,
    p.du_detsf,
    p.du_detsf_sl,
    p.du_detsf_ll,
    p.du_attsf,
    p.du_mf,
    p.du_mf2to4,
    p.du_mf5p,
    p.du_subtype,
    p.median_income,
    p.rent_burden_pct,
    p.pct_minority,
    p.pct_college_educated,
    p.cost_burden_pct,
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
    p.land_use,
    p.assessor_use_code,
    p.residential_irrigated_area,
    p.commercial_irrigated_area,
    p.area_parcel_res,
    p.area_parcel_emp_ag,
    p.area_parcel_emp,
    p.area_parcel_mixed_use,
    p.area_parcel_no_use,
    CASE WHEN a.parcel_id IS NOT NULL
        THEN COALESCE(a.emp_retail_services, 0) + COALESCE(a.emp_restaurant, 0)
            + COALESCE(a.emp_accommodation, 0) + COALESCE(a.emp_arts_entertainment, 0)
            + COALESCE(a.emp_other_services, 0) + COALESCE(a.emp_office_services, 0)
            + COALESCE(a.emp_medical_services, 0) + COALESCE(a.emp_public_admin, 0)
            + COALESCE(a.emp_education, 0) + COALESCE(a.emp_manufacturing, 0)
            + COALESCE(a.emp_wholesale, 0) + COALESCE(a.emp_transport_warehousing, 0)
            + COALESCE(a.emp_utilities, 0) + COALESCE(a.emp_construction, 0)
            + COALESCE(a.emp_agriculture, 0) + COALESCE(a.emp_extraction, 0)
            + COALESCE(a.emp_military, 0)
        ELSE 0.0
    END AS emp,
    COALESCE(a.emp_retail_services, 0) + COALESCE(a.emp_restaurant, 0)
        + COALESCE(a.emp_accommodation, 0) + COALESCE(a.emp_arts_entertainment, 0)
        + COALESCE(a.emp_other_services, 0) AS emp_ret,
    a.emp_retail_services,
    a.emp_restaurant,
    a.emp_accommodation,
    a.emp_arts_entertainment,
    a.emp_other_services,
    COALESCE(a.emp_office_services, 0) + COALESCE(a.emp_medical_services, 0) AS emp_off,
    a.emp_office_services,
    a.emp_medical_services,
    COALESCE(a.emp_public_admin, 0) + COALESCE(a.emp_education, 0) AS emp_pub,
    a.emp_public_admin,
    a.emp_education,
    COALESCE(a.emp_manufacturing, 0) + COALESCE(a.emp_wholesale, 0)
        + COALESCE(a.emp_transport_warehousing, 0) + COALESCE(a.emp_utilities, 0)
        + COALESCE(a.emp_construction, 0) AS emp_ind,
    a.emp_manufacturing,
    a.emp_wholesale,
    a.emp_transport_warehousing,
    a.emp_utilities,
    a.emp_construction,
    COALESCE(a.emp_agriculture, 0) AS emp_ag,
    a.emp_agriculture,
    a.emp_extraction,
    a.emp_military
FROM brewgis.base_canvas.base_canvas_demographics p
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id
