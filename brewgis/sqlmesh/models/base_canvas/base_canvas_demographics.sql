MODEL (
  name brewgis.base_canvas.base_canvas_demographics,
  kind FULL,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- Base Canvas Demographics — spatial allocation from Census ACS.
--
-- For each parcel in base_canvas_geometry, allocates demographic values
-- from intersecting ACS block groups using area-weighted proportional
-- allocation (dasymetric weights disabled by default).
--
-- Sum columns (population, households, dwelling units, sub-types):
--   Proportional to intersection area / source area.
--
-- Average columns (median_income, rent_burden_pct, etc.):
--   Area-weighted mean across intersecting block groups.

WITH parcel_geom AS (
    SELECT
        bg.parcel_id,
        bg.geometry,
        bg.local_geometry,
        bg.county,
        bg.land_development_category,
        bg.built_form_key,
        bg.intersection_density,
        bg.area_gross,
        bg.area_parcel,
        bg.area_dev_condition,
        bg.area_row,
        bg.pop AS bg_pop,
        bg.hh AS bg_hh,
        bg.du AS bg_du,
        bg.bldg_area_detsf_sl,
        bg.bldg_area_detsf_ll,
        bg.bldg_area_attsf,
        bg.bldg_area_mf,
        bg.bldg_area_retail_services,
        bg.bldg_area_restaurant,
        bg.bldg_area_accommodation,
        bg.bldg_area_arts_entertainment,
        bg.bldg_area_other_services,
        bg.bldg_area_office_services,
        bg.bldg_area_public_admin,
        bg.bldg_area_education,
        bg.bldg_area_medical_services,
        bg.bldg_area_transport_warehousing,
        bg.bldg_area_wholesale,
        bg.land_use,
        bg.assessor_use_code,
        bg.residential_irrigated_area,
        bg.commercial_irrigated_area,
        bg.area_parcel_res,
        bg.area_parcel_emp_ag,
        bg.area_parcel_emp,
        bg.area_parcel_mixed_use,
        bg.area_parcel_no_use,
        bg.du_subtype,
        bg.footprint_living_sqft,
        bg.footprint_building_sqft,
        bg.estimated_building_sqft,
        bg.dasym_impervious_fraction,
        bg.pop_dasym_weight,
        bg.emp_dasym_weight,
        bg.du_dasym_weight,
        bg.residential_building_sqft,
        bg.non_residential_building_sqft,
        bg.residential_building_count,
        bg.non_residential_building_count,
        bg.max_levels
    FROM brewgis.base_canvas.base_canvas_geometry bg
),

acs_data AS (
    SELECT
        a.*,
        pdb.vacancy_rate,
        pdb.group_quarters_pop AS pop_groupquarter_pdb,
        pdb.low_response_score,
        pdb.below_poverty_pct,
        pdb.renter_occupied_pct,
        GREATEST(ST_Area(ST_Transform(a.geometry, @VAR('local_srid', 3310))), 1e-10) AS bg_area,
        ST_Envelope(ST_Transform(a.geometry, @VAR('local_srid', 3310))) AS local_envelope
    FROM brewgis.staging.acs_block_group a
    LEFT JOIN brewgis.staging.pdb_block_group pdb
        ON a.geoid = pdb.geoid
        AND pdb.data_year = make_date(2024, 1, 1)
    WHERE a.geometry IS NOT NULL
),

-- Spatial allocation: one row per overlapping parcel-acs pair
-- Apply population mask: only allocate to parcels with residential building
-- presence. Parcels without building data (NULL) continue to receive
-- population since we cannot distinguish missing data from zero buildings.
intersections AS (
    SELECT
        p.parcel_id,
        a.geoid,
        a.pop,
        a.hh,
        a.du,
        a.du_detsf,
        a.du_detsf_sl,
        a.du_detsf_ll,
        a.du_attsf,
        a.du_mf,
        a.du_mf2to4,
        a.du_mf5p,
        a.median_income,
        a.rent_burden_pct,
        a.pct_minority,
        a.pct_college_educated,
        a.cost_burden_pct,
        a.vacancy_rate,
        a.pop_groupquarter_pdb,
        a.low_response_score,
        a.below_poverty_pct,
        a.renter_occupied_pct,
        a.bg_area,
        ST_Area(ST_ClipByBox2D(ST_Transform(p.geometry, @VAR('local_srid', 3310)), a.local_envelope)) AS raw_intersect_area,
        p.pop_dasym_weight,
        p.residential_building_sqft,
        p.area_gross
    FROM parcel_geom p
    JOIN acs_data a ON ST_Intersects(p.geometry, a.geometry)
    WHERE (p.residential_building_count IS NULL AND p.residential_building_sqft IS NULL)
       OR p.residential_building_count > 0
       OR p.residential_building_sqft > 0
),

-- Apply building footprint area cap for large parcels (>= 1 acre).
-- For these parcels, the intersection area is bounded by the total
-- residential building footprint area (converted from sqft to sq m).
-- This prevents population from spreading across large undeveloped
-- parcels that happen to have a small house, matching CA-POP methodology.
intersections_adjusted AS (
    SELECT
        i.parcel_id,
        i.geoid,
        i.pop,
        i.hh,
        i.du,
        i.du_detsf,
        i.du_detsf_sl,
        i.du_detsf_ll,
        i.du_attsf,
        i.du_mf,
        i.du_mf2to4,
        i.du_mf5p,
        i.median_income,
        i.rent_burden_pct,
        i.pct_minority,
        i.pct_college_educated,
        i.cost_burden_pct,
        i.vacancy_rate,
        i.pop_groupquarter_pdb,
        i.low_response_score,
        i.below_poverty_pct,
        i.renter_occupied_pct,
        i.bg_area,
        CASE WHEN i.area_gross >= 1.0
             THEN LEAST(i.raw_intersect_area, COALESCE(i.residential_building_sqft * 0.09290304, i.raw_intersect_area))
             ELSE i.raw_intersect_area
        END AS intersect_area,
        CASE WHEN i.area_gross >= 1.0
             THEN LEAST(i.raw_intersect_area, COALESCE(i.residential_building_sqft * 0.09290304, i.raw_intersect_area))
             ELSE i.raw_intersect_area
        END * COALESCE(i.pop_dasym_weight, 1.0) AS weighted_intersect_area
    FROM intersections i
),

bg_weighted_totals AS (
    SELECT geoid, SUM(weighted_intersect_area) AS bg_weighted_total
    FROM intersections_adjusted
    GROUP BY geoid
),

allocated AS (
    SELECT
        i.parcel_id,
        SUM(i.pop * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS pop,
        SUM(i.hh * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS hh,
        SUM(i.du * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du,
        SUM(i.du_detsf * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_detsf,
        SUM(i.du_detsf_sl * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_detsf_sl,
        SUM(i.du_detsf_ll * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_detsf_ll,
        SUM(i.du_attsf * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_attsf,
        SUM(i.du_mf * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_mf,
        SUM(i.du_mf2to4 * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_mf2to4,
        SUM(i.du_mf5p * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS du_mf5p,
        SUM(i.median_income * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS median_income,
        SUM(i.rent_burden_pct * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS rent_burden_pct,
        SUM(i.pct_minority * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS pct_minority,
        SUM(i.pct_college_educated * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS pct_college_educated,
        SUM(i.cost_burden_pct * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS cost_burden_pct,
        SUM(i.pop_groupquarter_pdb * i.weighted_intersect_area / NULLIF(bwt.bg_weighted_total, 0)) AS pop_groupquarter,
        SUM(i.vacancy_rate * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS vacancy_rate,
        SUM(i.low_response_score * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS low_response_score,
        SUM(i.below_poverty_pct * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS below_poverty_pct,
        SUM(i.renter_occupied_pct * i.intersect_area) / NULLIF(SUM(i.intersect_area), 0) AS renter_occupied_pct
    FROM intersections_adjusted i
    LEFT JOIN bg_weighted_totals bwt ON i.geoid = bwt.geoid
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
    COALESCE(a.pop, p.bg_pop) AS pop,
    COALESCE(a.pop_groupquarter, 0.0) AS pop_groupquarter,
    COALESCE(a.hh, p.bg_hh) AS hh,
    COALESCE(a.du, p.bg_du) AS du,
    a.du_detsf,
    a.du_detsf_sl,
    a.du_detsf_ll,
    a.du_attsf,
    a.du_mf,
    a.du_mf2to4,
    a.du_mf5p,
    p.du_subtype,
    a.median_income,
    a.rent_burden_pct,
    a.pct_minority,
    a.pct_college_educated,
    a.cost_burden_pct,
    a.vacancy_rate,
    a.low_response_score,
    a.below_poverty_pct,
    a.renter_occupied_pct,
    NULL::double precision AS emp,
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
    p.footprint_living_sqft,
    p.footprint_building_sqft,
    p.estimated_building_sqft,
    p.dasym_impervious_fraction,
    p.pop_dasym_weight,
    p.emp_dasym_weight,
    p.du_dasym_weight,
    p.residential_building_sqft,
    p.non_residential_building_sqft,
    p.residential_building_count,
    p.non_residential_building_count,
    p.max_levels
FROM parcel_geom p
LEFT JOIN allocated a ON p.parcel_id = a.parcel_id;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_base_canvas_demographics_geometry
  ON brewgis.base_canvas.base_canvas_demographics USING GIST (geometry)
);
