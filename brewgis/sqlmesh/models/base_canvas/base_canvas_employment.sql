MODEL (
  name brewgis.base_canvas.base_canvas_employment,
  kind FULL,
  audits (
    not_null(columns := (parcel_id)),
    assert_employment_conserved,
    assert_commercial_sectors_use_commercial_sqft,
    assert_industrial_sectors_use_industrial_sqft
  )
);

-- Base Canvas Employment — sector-constrained allocation from LEHD WAC blocks
-- using building sqft by type (Section 7 of methodology).
--
-- Each employment sector uses the relevant building sqft type as allocation weight:
--   Commercial sectors → commercial_building_sqft
--   Industrial sectors → industrial_building_sqft
--   Other sectors      → other_building_sqft
--
-- No separate land-use exclusion mask needed — the sqft weight naturally
-- excludes parcels with zero relevant building area.

WITH
-- Parcel data from demographics stage (includes building sqft by type)
parcel_with_weights AS (
    SELECT
        p.*
    FROM brewgis.base_canvas.base_canvas_demographics p
),

-- Spatial intersection: parcels → WAC blocks
-- For each sector group, use the relevant building sqft type as weight
intersections AS (
    SELECT
        p.parcel_id,
        w.geoid,
        p.commercial_building_sqft,
        p.industrial_building_sqft,
        p.other_building_sqft,
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
        -- Commercial weight (for retail, restaurant, accommodation, arts, other_services, office, medical)
        COALESCE(p.commercial_building_sqft, 0) AS commercial_weight,
        -- Industrial weight (for manufacturing, wholesale, transport_warehousing, utilities, construction)
        COALESCE(p.industrial_building_sqft, 0) AS industrial_weight,
        -- Other weight (for public_admin, education, agriculture, extraction, military)
        COALESCE(p.other_building_sqft, 0) AS other_weight,
        -- Emp dasymetric weight (lot-size-based fallback for employment allocation)
        COALESCE(p.emp_dasym_weight, 0) AS emp_dasy_weight,
        -- Emp total weight (sum of all building sqft types)
        COALESCE(p.commercial_building_sqft, 0)
            + COALESCE(p.industrial_building_sqft, 0)
            + COALESCE(p.other_building_sqft, 0) AS total_emp_weight,
        p.area_gross
    FROM parcel_with_weights p
    JOIN brewgis.staging.wac_block_projected w ON ST_Intersects(p.geometry, w.geometry)
),

-- Per-WAC-block total weight denominators
block_weight_totals AS (
    SELECT
        geoid,
        SUM(commercial_weight) AS block_commercial_weight,
        SUM(industrial_weight) AS block_industrial_weight,
        SUM(other_weight) AS block_other_weight,
        SUM(total_emp_weight) AS block_total_emp_weight,
        SUM(emp_dasy_weight) AS block_emp_dasym_weight
    FROM intersections
    GROUP BY geoid
),

-- Sector-constrained allocation
-- Each sector allocates proportional to its relevant sqft type within the WAC block.
-- Parcels with zero relevant sqft get zero allocation for that sector.
allocated AS (
    SELECT
        i.parcel_id,
        -- Total employment: all sectors summed
        SUM(
            CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_retail_services * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_retail_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_restaurant * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_restaurant * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_accommodation * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_accommodation * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_arts_entertainment * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_arts_entertainment * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_other_services * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_other_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_office_services * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_office_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_commercial_weight > 0
                    THEN i.emp_medical_services * i.commercial_weight / bwt.block_commercial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_medical_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_industrial_weight > 0
                    THEN i.emp_manufacturing * i.industrial_weight / bwt.block_industrial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_manufacturing * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_industrial_weight > 0
                    THEN i.emp_wholesale * i.industrial_weight / bwt.block_industrial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_wholesale * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_industrial_weight > 0
                    THEN i.emp_transport_warehousing * i.industrial_weight / bwt.block_industrial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_transport_warehousing * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_industrial_weight > 0
                    THEN i.emp_utilities * i.industrial_weight / bwt.block_industrial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_utilities * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_industrial_weight > 0
                    THEN i.emp_construction * i.industrial_weight / bwt.block_industrial_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_construction * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_other_weight > 0
                    THEN i.emp_public_admin * i.other_weight / bwt.block_other_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_public_admin * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_other_weight > 0
                    THEN i.emp_education * i.other_weight / bwt.block_other_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_education * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_other_weight > 0
                    THEN i.emp_agriculture * i.other_weight / bwt.block_other_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_agriculture * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_other_weight > 0
                    THEN i.emp_extraction * i.other_weight / bwt.block_other_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_extraction * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
            + CASE
                WHEN bwt.block_other_weight > 0
                    THEN i.emp_military * i.other_weight / bwt.block_other_weight
                WHEN bwt.block_emp_dasym_weight > 0
                    THEN i.emp_military * i.emp_dasy_weight / bwt.block_emp_dasym_weight
                ELSE 0.0
            END
        ) AS emp,
        -- Commercial sectors → commercial weight
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_retail_services * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_retail_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_retail_services,
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_restaurant * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_restaurant * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_restaurant,
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_accommodation * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_accommodation * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_accommodation,
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_arts_entertainment * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_arts_entertainment * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_arts_entertainment,
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_other_services * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_other_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_other_services,
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_office_services * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_office_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_office_services,
        SUM(CASE
            WHEN bwt.block_commercial_weight > 0
                THEN i.emp_medical_services * i.commercial_weight / bwt.block_commercial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_medical_services * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_medical_services,
        -- Industrial sectors → industrial weight
        SUM(CASE
            WHEN bwt.block_industrial_weight > 0
                THEN i.emp_manufacturing * i.industrial_weight / bwt.block_industrial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_manufacturing * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_manufacturing,
        SUM(CASE
            WHEN bwt.block_industrial_weight > 0
                THEN i.emp_wholesale * i.industrial_weight / bwt.block_industrial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_wholesale * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_wholesale,
        SUM(CASE
            WHEN bwt.block_industrial_weight > 0
                THEN i.emp_transport_warehousing * i.industrial_weight / bwt.block_industrial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_transport_warehousing * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_transport_warehousing,
        SUM(CASE
            WHEN bwt.block_industrial_weight > 0
                THEN i.emp_utilities * i.industrial_weight / bwt.block_industrial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_utilities * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_utilities,
        SUM(CASE
            WHEN bwt.block_industrial_weight > 0
                THEN i.emp_construction * i.industrial_weight / bwt.block_industrial_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_construction * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_construction,
        -- Other sectors → other weight
        SUM(CASE
            WHEN bwt.block_other_weight > 0
                THEN i.emp_public_admin * i.other_weight / bwt.block_other_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_public_admin * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_public_admin,
        SUM(CASE
            WHEN bwt.block_other_weight > 0
                THEN i.emp_education * i.other_weight / bwt.block_other_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_education * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_education,
        SUM(CASE
            WHEN bwt.block_other_weight > 0
                THEN i.emp_agriculture * i.other_weight / bwt.block_other_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_agriculture * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_agriculture,
        SUM(CASE
            WHEN bwt.block_other_weight > 0
                THEN i.emp_extraction * i.other_weight / bwt.block_other_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_extraction * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_extraction,
        SUM(CASE
            WHEN bwt.block_other_weight > 0
                THEN i.emp_military * i.other_weight / bwt.block_other_weight
            WHEN bwt.block_emp_dasym_weight > 0
                THEN i.emp_military * i.emp_dasy_weight / bwt.block_emp_dasym_weight
            ELSE 0.0
        END) AS emp_military
    FROM intersections i
    LEFT JOIN block_weight_totals bwt ON i.geoid = bwt.geoid
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
    p.area_gross_acres,
    p.area_parcel_acres,
    p.area_dev_condition_acres,
    p.area_row_acres,
    p.pop,
    p.pop_groupquarter,
    p.hh,
    p.du,
    p.du_subtype,
    p.is_residential,
    p.residential_building_sqft,
    p.commercial_building_sqft,
    p.industrial_building_sqft,
    p.other_building_sqft,
    p.total_footprint_sqft,
    p.building_count,
    p.footprint_ratio,
    p.max_levels,
    p.dasym_impervious_fraction,
    p.pop_dasym_weight,
    p.emp_dasym_weight,
    p.du_estimated,
    p.hh_size,
    p.vacancy_rate,
    p.du_pop_dasym_weight,
    p.hh_dasym_weight,
    p.hh_estimated,
    p.median_income,
    p.rent_burden_pct,
    p.pct_minority,
    p.pct_college_educated,
    p.cost_burden_pct,
    p.vacancy_rate AS vacancy_rate_demo,
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
    CASE WHEN a.parcel_id IS NOT NULL THEN
        COALESCE(a.emp_retail_services, 0) + COALESCE(a.emp_restaurant, 0)
        + COALESCE(a.emp_accommodation, 0) + COALESCE(a.emp_arts_entertainment, 0)
        + COALESCE(a.emp_other_services, 0) + COALESCE(a.emp_office_services, 0)
        + COALESCE(a.emp_medical_services, 0) + COALESCE(a.emp_public_admin, 0)
        + COALESCE(a.emp_education, 0) + COALESCE(a.emp_manufacturing, 0)
        + COALESCE(a.emp_wholesale, 0) + COALESCE(a.emp_transport_warehousing, 0)
        + COALESCE(a.emp_utilities, 0) + COALESCE(a.emp_construction, 0)
        + COALESCE(a.emp_agriculture, 0) + COALESCE(a.emp_extraction, 0)
        + COALESCE(a.emp_military, 0)
    ELSE 0.0 END AS emp,
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
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_base_canvas_employment_geometry
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_base_canvas_employment_parcel_id
  ON @this_model USING btree (parcel_id);
