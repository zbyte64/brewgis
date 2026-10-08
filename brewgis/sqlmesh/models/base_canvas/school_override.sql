MODEL (
  name brewgis.@{region}.base_canvas_school_override,
  kind FULL,
  description 'Parcel-level base canvas with NCES public school jobs put back on the schools: each parcel holding a CCD school keeps the LEHD education jobs already on it and makes up any shortfall against its schools'' estimated jobs from the other parcels of its census block, then its district office''s block, then the region, so education jobs move between blocks while the region''s education total and every block''s other jobs are unchanged.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier; one row per parcel in the base canvas.',
    geometry = 'Parcel boundary geometry (MultiPolygon, EPSG:4326).',
    local_geometry = 'Parcel boundary in the local projected SRID used for area and clipping math.',
    county = 'County the parcel falls in, carried from the parcel source.',
    land_development_category = 'Land development category carried from base_canvas_combined.',
    built_form_key = 'Built form key carried from base_canvas_combined.',
    intersection_density = 'Intersection density carried from base_canvas_combined (intersections per square mile).',
    area_gross = 'Gross parcel area including right-of-way (acres).',
    area_gross_acres = 'Gross parcel area including right-of-way (acres, explicit unit alias of area_gross).',
    area_parcel_acres = 'Parcel area inside the parcel boundary (acres).',
    area_dev_condition_acres = 'Portion of the parcel in developed condition (acres).',
    area_row_acres = 'Portion of the parcel in public right-of-way (acres).',
    area_parcel_res = 'Residential parcel area carried from base_canvas_combined (acres).',
    area_parcel_res_acres = 'Total residential parcel area (acres, explicit unit alias of area_parcel_res).',
    area_parcel_emp_ag = 'Agricultural employment parcel area carried from base_canvas_combined (acres).',
    area_parcel_emp_ag_acres = 'Agricultural employment parcel area (acres, alias of area_parcel_emp_ag).',
    area_parcel_emp = 'Total employment parcel area carried from base_canvas_combined (acres).',
    area_parcel_emp_acres = 'Total employment parcel area (acres, explicit unit alias of area_parcel_emp).',
    area_parcel_mixed_use = 'Mixed-use parcel area carried from base_canvas_combined (acres).',
    area_parcel_mixed_use_acres = 'Mixed-use parcel area (acres, explicit unit alias of area_parcel_mixed_use).',
    area_parcel_no_use = 'Parcel area with no assigned use carried from base_canvas_combined (acres).',
    area_parcel_no_use_acres = 'Parcel area with no assigned use (acres, explicit unit alias of area_parcel_no_use).',
    pop = 'Population carried from base_canvas_combined (people).',
    pop_groupquarter = 'Group quarters population carried from base_canvas_combined (people).',
    hh = 'Households carried from base_canvas_combined (count).',
    du = 'Dwelling units carried from base_canvas_combined (count).',
    du_estimated = 'Dwelling units the dasymetric regressor estimated, carried from base_canvas_combined (count).',
    du_detsf = 'Detached single-family dwelling units carried from base_canvas_combined (count).',
    du_detsf_sl = 'Detached single-family small-lot dwelling units carried from base_canvas_combined (count).',
    du_detsf_ll = 'Detached single-family large-lot dwelling units carried from base_canvas_combined (count).',
    du_attsf = 'Attached single-family dwelling units carried from base_canvas_combined (count).',
    du_mf = 'Multi-family dwelling units carried from base_canvas_combined (count).',
    du_mf2to4 = 'Multi-family 2-4 unit dwelling units carried from base_canvas_combined (count).',
    du_mf5p = 'Multi-family 5+ unit dwelling units carried from base_canvas_combined (count).',
    du_subtype = 'Dwelling unit subtype key carried from base_canvas_combined.',
    is_residential = 'Residential flag carried from base_canvas_combined.',
    residential_building_sqft = 'Residential building floor area carried from base_canvas_combined (sq ft).',
    commercial_building_sqft = 'Commercial building floor area carried from base_canvas_combined (sq ft).',
    industrial_building_sqft = 'Industrial building floor area carried from base_canvas_combined (sq ft).',
    other_building_sqft = 'Other building floor area carried from base_canvas_combined (sq ft).',
    total_footprint_sqft = 'Total building footprint area carried from base_canvas_combined (sq ft).',
    building_count = 'Number of buildings on the parcel carried from base_canvas_combined (count).',
    footprint_ratio = 'Building footprint share of the parcel carried from base_canvas_combined (ratio, 0-1).',
    max_levels = 'Maximum building levels on the parcel carried from base_canvas_combined (count).',
    emp_dasym_weight = 'Lot-size-based employment weight carried from base_canvas_combined (weight).',
    emp = 'Total employment: the parcel''s education jobs after the school draw plus its other jobs — base_canvas_combined''s, given up to the block''s other parcels on a school parcel and scaled up on them (jobs).',
    emp_ret = 'Retail employment: base_canvas_combined''s, zero on a school parcel whose block has other parcels with non-education jobs and scaled up on those parcels (jobs).',
    emp_off = 'Office employment: base_canvas_combined''s, zero on a school parcel whose block has other parcels with non-education jobs and scaled up on those parcels (jobs).',
    emp_pub = 'Public employment: the parcel''s education jobs after the school draw plus its public administration jobs, moved like the other non-education sectors (jobs).',
    emp_ind = 'Industrial employment: base_canvas_combined''s, zero on a school parcel whose block has other parcels with non-education jobs and scaled up on those parcels (jobs).',
    emp_ag = 'Agricultural employment: base_canvas_combined''s, zero on a school parcel whose block has other parcels with non-education jobs and scaled up on those parcels (jobs).',
    emp_military = 'Military employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_retail_services = 'Retail services employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_restaurant = 'Restaurant employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_accommodation = 'Accommodation employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_arts_entertainment = 'Arts and entertainment employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_other_services = 'Other services employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_office_services = 'Office services employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_medical_services = 'Medical services employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_public_admin = 'Public administration employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_education = 'Education employment: on a school parcel its CCD schools'' estimated jobs, met first from base_canvas_combined''s education on the parcel and then from the block, district office and region pools as far as they reach, plus its education beyond that estimate (kept whole, or in a district office''s block whatever that district''s schools left of it); elsewhere base_canvas_combined''s scaled by what the schools drew from the parcel''s block (jobs).',
    emp_manufacturing = 'Manufacturing employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_wholesale = 'Wholesale employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_transport_warehousing = 'Transport and warehousing employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_utilities = 'Utilities employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_construction = 'Construction employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_agriculture = 'Agriculture employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    emp_extraction = 'Extraction employment: base_canvas_combined''s, moved off school parcels like the other non-education sectors (jobs).',
    bldg_area_detsf_sl = 'Detached single-family small-lot building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_detsf_ll = 'Detached single-family large-lot building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_attsf = 'Attached single-family building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_mf = 'Multi-family building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_retail_services = 'Retail services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_restaurant = 'Restaurant building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_accommodation = 'Accommodation building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_arts_entertainment = 'Arts and entertainment building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_other_services = 'Other services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_office_services = 'Office services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_public_admin = 'Public administration building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_education = 'Education building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_medical_services = 'Medical services building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_transport_warehousing = 'Transport and warehousing building floor area carried from base_canvas_combined (sq ft).',
    bldg_area_wholesale = 'Wholesale building floor area carried from base_canvas_combined (sq ft).',
    residential_irrigated_area = 'Residential irrigated area carried from base_canvas_combined (acres).',
    commercial_irrigated_area = 'Commercial irrigated area carried from base_canvas_combined (acres).',
    median_income = 'Median household income carried from base_canvas_combined ($ per year).',
    rent_burden_pct = 'Rent-burdened household share carried from base_canvas_combined (% as 0-100).',
    pct_minority = 'Share of people of color carried from base_canvas_combined (% as 0-100).',
    pct_college_educated = 'College-educated adult share carried from base_canvas_combined (% as 0-100).',
    cost_burden_pct = 'Cost-burdened household share carried from base_canvas_combined (% as 0-100).',
    tree_canopy_fraction = 'Tree canopy share of the parcel carried from base_canvas_combined (ratio, 0-1).',
    vacancy_rate = 'Housing vacancy rate carried from base_canvas_combined (ratio, 0-1).',
    du_pop_dasym_weight = 'Dasymetric DU and population weight carried from base_canvas_combined (weight).',
    occupied_du = 'Occupied dwelling units carried from base_canvas_combined (count).',
    land_use = 'Land use label from the parcel source, matched against the regional land use crosswalk.',
    assessor_use_code = 'Assessor use code from the parcel source, matched on its first two digits.'
  ),
  audits (
    not_null(columns := (parcel_id)),
    number_of_rows(threshold := 1),
    assert_employment_conserved,
    assert_subsector_sum_equals_emp,
    assert_column_non_negative(column_name := emp),
    assert_column_non_negative(column_name := emp_education)
  ),
  blueprints @region_blueprints()
);

-- Base Canvas School Override — NCES public school jobs on the schools.
--
-- LODES places each job at the address its employer reports, and a school
-- district that reports one address puts every teacher, aide and custodian of
-- the district on its office's census block (see models/ccd/). Redistributing
-- within a block cannot fix that: a school whose block LODES left empty has no
-- jobs to claim. Education jobs therefore get their own carve-out from the
-- per-block rule the POI override keeps — they move between blocks, and only
-- the region's education total is held.
--
-- Each parcel holding a CCD school (brewgis.<region>.school_parcels) is a
-- school parcel. Its schools' estimated jobs (brewgis.<region>.school_staff:
-- teachers times the district's school-based staff per teacher) are met first
-- by the education jobs base_canvas_combined already put on the parcel, split
-- across its schools by their estimates. Each school's shortfall is then drawn
-- from three pools in turn, pro rata when a pool cannot cover every school
-- drawing on it:
--   1. its own census block's education jobs — the jobs LODES did put at the
--      campus;
--   2. its district office's block's education jobs, beyond the district-office
--      staff the CCD counts there (LEA administrators, their support staff,
--      instructional coordinators), which stay — the pile a district reporting
--      one address leaves;
--   3. the region's remaining education jobs, every block giving the same
--      share of what it has left after 1 and 2 and its office reserve — a
--      district that reported its jobs at some other address.
--
-- A block's pool is the education jobs of its parcels without a school. A
-- school parcel's education beyond its schools' estimate is not in it: in a
-- district office's block that excess is the office pile, which only stage 2
-- (the schools of a district with its office there) draws on; anywhere else it
-- stays on the parcel, being another education employer sharing it — a
-- middle-college high school on a community college campus, a lab school on a
-- university's. A single-school charter is its own district with its office on
-- its campus, so its campus excess only ever serves itself.
--
-- Every parcel without a school keeps its education jobs scaled by what is
-- left of its block's pool, and a pile by what is left of it, so the region's
-- education total is unchanged (assert_employment_conserved). Non-education jobs keep the
-- per-block rule: a school parcel gives its non-education jobs to the other
-- parcels of its block, each scaled up keeping its own sector mix (the POI
-- override's redistribution), unless no other parcel of the block holds
-- non-education jobs.
--
-- The census block holding each parcel's point on surface is its pool, as in
-- poi_override.sql; a parcel outside every block pools alone. A district
-- office's block is the census block holding the CCD office point.
--
-- The output column set is base_canvas_combined's, verbatim and in order —
-- this model sits between it and base_canvas_poi_override, which reads the
-- school parcels' built form from the same school_parcels and leaves their
-- jobs alone.

WITH combined AS (
    SELECT * FROM brewgis.@{region}.base_canvas_combined
),

-- The census block holding each parcel's point on surface. The predicate
-- probes the blocks' GiST index on geometry.
parcel_pool AS (
    SELECT
        c.parcel_id,
        COALESCE(blk.geoid, 'parcel:' || c.parcel_id::text) AS pool_id
    FROM combined c
    LEFT JOIN LATERAL (
        SELECT b.geoid
        FROM brewgis.@{region}.census_2020_block_projected b
        WHERE ST_Intersects(b.geometry, ST_PointOnSurface(c.geometry))
        ORDER BY b.geoid
        LIMIT 1
    ) blk ON TRUE
),

schools AS (
    SELECT
        sp.ncessch,
        sp.leaid,
        sp.staff,
        sp.parcel_id,
        pp.pool_id
    FROM brewgis.@{region}.school_parcels sp
    JOIN parcel_pool pp
        ON pp.parcel_id = sp.parcel_id
    WHERE sp.staff > 0
),

school_parcel_staff AS (
    SELECT parcel_id, SUM(staff) AS staff
    FROM schools
    GROUP BY parcel_id
),

-- The district office of each district running a school parcel, with the
-- block holding its office point (probing the blocks' GiST index) and the
-- office staff that stays there.
offices AS (
    SELECT
        d.leaid,
        COALESCE(d.office_staff_fte, 0.0) AS office_staff,
        blk.geoid AS pool_id
    FROM brewgis.@{region}.ccd_districts d
    JOIN LATERAL (
        SELECT b.geoid
        FROM brewgis.@{region}.census_2020_block_projected b
        WHERE ST_Intersects(b.geometry, d.geometry)
        ORDER BY b.geoid
        LIMIT 1
    ) blk ON TRUE
    WHERE d.leaid IN (SELECT leaid FROM schools)
),

office_reserve AS (
    SELECT pool_id, SUM(office_staff) AS reserve
    FROM offices
    GROUP BY pool_id
),

-- Per parcel: its education jobs and how they may be drawn on. own_used is
-- what its own schools use; donor_edu is what every stage may draw (all of a
-- parcel without a school); pile_edu is a school parcel's excess over its
-- schools' estimate in a district office's block, which only the office stage
-- may draw (the pile a district reporting one address leaves); kept_excess is
-- the excess anywhere else, which nothing draws. o_non_edu is the sum of the
-- non-education sub-sectors (base_canvas_combined's emp is exactly its
-- sub-sectors' sum, assert_subsector_sum_equals_emp).
parcels AS (
    SELECT
        c.*,
        pp.pool_id,
        sps.parcel_id IS NOT NULL AS is_school,
        COALESCE(c.emp_education, 0.0) AS o_edu,
        COALESCE(c.emp_retail_services, 0.0) + COALESCE(c.emp_restaurant, 0.0)
            + COALESCE(c.emp_accommodation, 0.0) + COALESCE(c.emp_arts_entertainment, 0.0)
            + COALESCE(c.emp_other_services, 0.0) + COALESCE(c.emp_office_services, 0.0)
            + COALESCE(c.emp_medical_services, 0.0) + COALESCE(c.emp_public_admin, 0.0)
            + COALESCE(c.emp_manufacturing, 0.0) + COALESCE(c.emp_wholesale, 0.0)
            + COALESCE(c.emp_transport_warehousing, 0.0) + COALESCE(c.emp_utilities, 0.0)
            + COALESCE(c.emp_construction, 0.0) + COALESCE(c.emp_agriculture, 0.0)
            + COALESCE(c.emp_extraction, 0.0) + COALESCE(c.emp_military, 0.0) AS o_non_edu,
        -- LEAST ignores a null argument, so a parcel without a school is
        -- spelled out rather than LEAST(edu, null) = edu.
        CASE
            WHEN sps.parcel_id IS NULL THEN 0.0
            ELSE LEAST(COALESCE(c.emp_education, 0.0), sps.staff)
        END AS own_used,
        CASE WHEN sps.parcel_id IS NULL THEN COALESCE(c.emp_education, 0.0) ELSE 0.0 END AS donor_edu,
        CASE
            WHEN sps.parcel_id IS NOT NULL AND r.pool_id IS NOT NULL
                THEN GREATEST(COALESCE(c.emp_education, 0.0) - sps.staff, 0.0)
            ELSE 0.0
        END AS pile_edu,
        CASE
            WHEN sps.parcel_id IS NOT NULL AND r.pool_id IS NULL
                THEN GREATEST(COALESCE(c.emp_education, 0.0) - sps.staff, 0.0)
            ELSE 0.0
        END AS kept_excess
    FROM combined c
    JOIN parcel_pool pp
        ON pp.parcel_id = c.parcel_id
    LEFT JOIN school_parcel_staff sps
        ON sps.parcel_id = c.parcel_id
    LEFT JOIN office_reserve r
        ON r.pool_id = pp.pool_id
),

pools AS (
    SELECT
        pool_id,
        SUM(donor_edu) AS donor,
        SUM(pile_edu) AS pile,
        SUM(o_non_edu) AS non_edu,
        COALESCE(SUM(o_non_edu) FILTER (WHERE NOT is_school), 0.0) AS non_edu_other
    FROM parcels
    GROUP BY pool_id
),

-- Each school's share of its parcel's own education jobs, and what it still
-- needs.
school_need AS (
    SELECT
        s.*,
        s.staff - p.own_used * s.staff / sps.staff AS need
    FROM schools s
    JOIN school_parcel_staff sps
        ON sps.parcel_id = s.parcel_id
    JOIN parcels p
        ON p.parcel_id = s.parcel_id
),

-- 1. Each block's schools draw on the block's donor jobs.
block_demand AS (
    SELECT pool_id, SUM(need) AS demand
    FROM school_need
    GROUP BY pool_id
),

stage_block AS (
    SELECT
        s.*,
        s.need * LEAST(1.0, COALESCE(p.donor / NULLIF(d.demand, 0.0), 1.0)) AS from_block
    FROM school_need s
    JOIN pools p
        ON p.pool_id = s.pool_id
    JOIN block_demand d
        ON d.pool_id = s.pool_id
),

taken_block AS (
    SELECT pool_id, SUM(from_block) AS taken
    FROM stage_block
    GROUP BY pool_id
),

-- 2. The district office's block: its donor jobs left after 1 plus its pile,
-- beyond its office reserve. What the stage takes, and the reserve, come out
-- of the donor jobs and the pile in proportion.
office_pool AS (
    SELECT
        p.pool_id,
        r.reserve,
        p.donor - COALESCE(t.taken, 0.0) AS donor_left,
        p.pile,
        p.donor - COALESCE(t.taken, 0.0) + p.pile AS total
    FROM office_reserve r
    JOIN pools p
        ON p.pool_id = r.pool_id
    LEFT JOIN taken_block t
        ON t.pool_id = r.pool_id
),

office_demand AS (
    SELECT o.pool_id, SUM(s.need - s.from_block) AS demand
    FROM stage_block s
    JOIN offices o
        ON o.leaid = s.leaid
    GROUP BY o.pool_id
),

stage_office AS (
    SELECT
        s.*,
        -- Postgres LEAST ignores a null argument, so a school with no office
        -- block in reach must read as a zero share, not LEAST(1.0, null) = 1.
        (s.need - s.from_block)
        * LEAST(1.0, COALESCE(GREATEST(op.total - op.reserve, 0.0) / NULLIF(od.demand, 0.0), 0.0)) AS from_office
    FROM stage_block s
    LEFT JOIN offices o
        ON o.leaid = s.leaid
    LEFT JOIN office_pool op
        ON op.pool_id = o.pool_id
    LEFT JOIN office_demand od
        ON od.pool_id = o.pool_id
),

taken_office AS (
    SELECT
        op.pool_id,
        COALESCE(SUM(s.from_office), 0.0) * op.donor_left / NULLIF(op.total, 0.0) AS from_donor,
        COALESCE(SUM(s.from_office), 0.0) * op.pile / NULLIF(op.total, 0.0) AS from_pile,
        op.reserve * op.donor_left / NULLIF(op.total, 0.0) AS donor_reserve
    FROM office_pool op
    LEFT JOIN offices o
        ON o.pool_id = op.pool_id
    LEFT JOIN stage_office s
        ON s.leaid = o.leaid
    GROUP BY op.pool_id, op.donor_left, op.pile, op.total, op.reserve
),

-- 3. The region's remaining donor jobs: each block's left after 1, 2 and its
-- share of the office reserve. Piles are not drawn here.
pool_left AS (
    SELECT
        p.pool_id,
        GREATEST(
            p.donor - COALESCE(tb.taken, 0.0) - COALESCE(tor.from_donor, 0.0) - COALESCE(tor.donor_reserve, 0.0),
            0.0
        ) AS left_edu
    FROM pools p
    LEFT JOIN taken_block tb
        ON tb.pool_id = p.pool_id
    LEFT JOIN taken_office tor
        ON tor.pool_id = p.pool_id
),

region AS (
    SELECT
        (SELECT SUM(left_edu) FROM pool_left) AS available,
        (SELECT SUM(need - from_block - from_office) FROM stage_office) AS demand
),

stage_region AS (
    SELECT
        s.*,
        (s.need - s.from_block - s.from_office)
        * LEAST(1.0, COALESCE(r.available / NULLIF(r.demand, 0.0), 0.0)) AS from_region
    FROM stage_office s
    CROSS JOIN region r
),

taken_region AS (
    SELECT
        pl.pool_id,
        pl.left_edu * LEAST(1.0, COALESCE(r.demand / NULLIF(r.available, 0.0), 0.0)) AS taken
    FROM pool_left pl
    CROSS JOIN region r
),

-- The share of its donor jobs and of its pile each block keeps once every
-- school has drawn, clamped to [0, 1] against floating-point residue (no
-- stage takes more than it is offered).
pool_final AS (
    SELECT
        p.pool_id,
        p.non_edu,
        p.non_edu_other,
        LEAST(GREATEST(COALESCE(
            (p.donor - COALESCE(tb.taken, 0.0) - COALESCE(tor.from_donor, 0.0) - COALESCE(tr.taken, 0.0))
            / NULLIF(p.donor, 0.0),
            1.0
        ), 0.0), 1.0) AS donor_kept_share,
        LEAST(GREATEST(COALESCE(
            (p.pile - COALESCE(tor.from_pile, 0.0)) / NULLIF(p.pile, 0.0),
            1.0
        ), 0.0), 1.0) AS pile_kept_share
    FROM pools p
    LEFT JOIN taken_block tb
        ON tb.pool_id = p.pool_id
    LEFT JOIN taken_office tor
        ON tor.pool_id = p.pool_id
    LEFT JOIN taken_region tr
        ON tr.pool_id = p.pool_id
),

school_draws AS (
    SELECT
        parcel_id,
        SUM(from_block + from_office + from_region) AS drawn
    FROM stage_region
    GROUP BY parcel_id
),

-- Per parcel: its education jobs and the factor its non-education columns are
-- multiplied by. A school parcel holds what its schools use of its own, what
-- they drew, its kept excess and what is left of its pile; any other parcel
-- its education scaled by what its block's donor jobs kept. A school parcel's
-- non-education jobs go to the block's other parcels when any of them holds
-- non-education jobs.
resolved AS (
    SELECT
        p.*,
        CASE
            WHEN p.is_school THEN
                p.own_used
                + COALESCE(sd.drawn, 0.0)
                + p.kept_excess
                + p.pile_edu * pf.pile_kept_share
            -- A null (no jobs) stays null.
            ELSE p.emp_education * pf.donor_kept_share
        END AS o_emp_education,
        CASE
            WHEN pf.non_edu_other <= 0 THEN 1.0
            WHEN p.is_school THEN 0.0
            ELSE pf.non_edu / pf.non_edu_other
        END AS o_scale
    FROM parcels p
    JOIN pool_final pf
        ON pf.pool_id = p.pool_id
    LEFT JOIN school_draws sd
        ON sd.parcel_id = p.parcel_id
)

SELECT
    c.parcel_id,
    c.geometry,
    c.local_geometry,
    c.county,
    c.land_development_category,
    c.built_form_key,
    c.intersection_density,
    c.area_gross,
    c.area_gross_acres,
    c.area_parcel_acres,
    c.area_dev_condition_acres,
    c.area_row_acres,
    c.area_parcel_res,
    c.area_parcel_res_acres,
    c.area_parcel_emp_ag,
    c.area_parcel_emp_ag_acres,
    c.area_parcel_emp,
    c.area_parcel_emp_acres,
    c.area_parcel_mixed_use,
    c.area_parcel_mixed_use_acres,
    c.area_parcel_no_use,
    c.area_parcel_no_use_acres,
    c.pop,
    c.pop_groupquarter,
    c.hh,
    c.du,
    c.du_estimated,
    c.du_detsf,
    c.du_detsf_sl,
    c.du_detsf_ll,
    c.du_attsf,
    c.du_mf,
    c.du_mf2to4,
    c.du_mf5p,
    c.du_subtype,
    c.is_residential,
    c.residential_building_sqft,
    c.commercial_building_sqft,
    c.industrial_building_sqft,
    c.other_building_sqft,
    c.total_footprint_sqft,
    c.building_count,
    c.footprint_ratio,
    c.max_levels,
    c.emp_dasym_weight,
    -- A parcel base_canvas_combined left without jobs (null) stays without
    -- unless it is a school parcel, so base_canvas_imputed still imputes it.
    -- Every total is rebuilt from its parts, so emp stays its sub-sectors' sum.
    CASE
        WHEN c.emp IS NULL AND NOT c.is_school THEN NULL
        ELSE c.o_non_edu * c.o_scale + COALESCE(c.o_emp_education, 0.0)
    END AS emp,
    c.emp_ret * c.o_scale AS emp_ret,
    c.emp_off * c.o_scale AS emp_off,
    CASE
        WHEN c.emp_pub IS NULL AND NOT c.is_school THEN NULL
        ELSE COALESCE(c.emp_public_admin, 0.0) * c.o_scale + COALESCE(c.o_emp_education, 0.0)
    END AS emp_pub,
    c.emp_ind * c.o_scale AS emp_ind,
    c.emp_ag * c.o_scale AS emp_ag,
    c.emp_military * c.o_scale AS emp_military,
    c.emp_retail_services * c.o_scale AS emp_retail_services,
    c.emp_restaurant * c.o_scale AS emp_restaurant,
    c.emp_accommodation * c.o_scale AS emp_accommodation,
    c.emp_arts_entertainment * c.o_scale AS emp_arts_entertainment,
    c.emp_other_services * c.o_scale AS emp_other_services,
    c.emp_office_services * c.o_scale AS emp_office_services,
    c.emp_medical_services * c.o_scale AS emp_medical_services,
    c.emp_public_admin * c.o_scale AS emp_public_admin,
    c.o_emp_education AS emp_education,
    c.emp_manufacturing * c.o_scale AS emp_manufacturing,
    c.emp_wholesale * c.o_scale AS emp_wholesale,
    c.emp_transport_warehousing * c.o_scale AS emp_transport_warehousing,
    c.emp_utilities * c.o_scale AS emp_utilities,
    c.emp_construction * c.o_scale AS emp_construction,
    c.emp_agriculture * c.o_scale AS emp_agriculture,
    c.emp_extraction * c.o_scale AS emp_extraction,
    c.bldg_area_detsf_sl,
    c.bldg_area_detsf_ll,
    c.bldg_area_attsf,
    c.bldg_area_mf,
    c.bldg_area_retail_services,
    c.bldg_area_restaurant,
    c.bldg_area_accommodation,
    c.bldg_area_arts_entertainment,
    c.bldg_area_other_services,
    c.bldg_area_office_services,
    c.bldg_area_public_admin,
    c.bldg_area_education,
    c.bldg_area_medical_services,
    c.bldg_area_transport_warehousing,
    c.bldg_area_wholesale,
    c.residential_irrigated_area,
    c.commercial_irrigated_area,
    c.median_income,
    c.rent_burden_pct,
    c.pct_minority,
    c.pct_college_educated,
    c.cost_burden_pct,
    c.tree_canopy_fraction,
    c.vacancy_rate,
    c.du_pop_dasym_weight,
    c.occupied_du,
    c.land_use,
    c.assessor_use_code
FROM resolved c;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_school_override_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_school_override_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
