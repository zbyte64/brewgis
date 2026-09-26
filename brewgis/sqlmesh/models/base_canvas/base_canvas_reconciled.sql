MODEL (
  name brewgis.@{region}.base_canvas_reconciled,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  description 'Parcel-level end state of the base canvas: base_canvas_imputed with aggregate DU and employment columns recomputed from their sub-column parts, after the DU and employment sub-sectors were reconciled against the source parcel-level exclusivity invariants (detached XOR attached/multi-family, military XOR all other employment, public XOR retail/industrial), with each losing group transferred into the dominant sub-sector of the winner so the per-parcel DU and employment totals are unchanged.',
  column_descriptions (
    parcel_id = 'Unique parcel identifier; one row per parcel in the base canvas.',
    geometry_key = 'Parcel identifier reused as the geometry join key (alias of parcel_id).',
    id_source = 'Always NULL in this model; placeholder for the upstream ID source label.',
    geography_id = 'Always NULL in this model; placeholder for a resolved geography identifier.',
    geometry = 'Parcel boundary geometry (MultiPolygon, EPSG:4326).',
    county = 'County the parcel falls in, carried from the parcel source.',
    land_development_category = 'Land development category carried from base_canvas_imputed.',
    built_form_key = 'Built form key describing the development pattern of the parcel.',
    intersection_density = 'Intersection density carried from base_canvas_imputed (intersections per km2).',
    area_gross = 'Gross parcel area including right-of-way (acres).',
    area_gross_acres = 'Gross parcel area including right-of-way (acres, explicit unit alias of area_gross).',
    area_parcel_acres = 'Parcel area inside the parcel boundary (acres).',
    area_parcel = 'Parcel area inside the parcel boundary (acres, alias of area_parcel_acres).',
    area_dev_condition_acres = 'Portion of the parcel in developed condition (acres).',
    area_dev_condition = 'Portion of the parcel in developed condition (acres, alias of area_dev_condition_acres).',
    area_row_acres = 'Portion of the parcel in public right-of-way (acres).',
    area_row = 'Portion of the parcel in public right-of-way (acres, alias of area_row_acres).',
    area_parcel_res = 'Total residential parcel area (acres).',
    area_parcel_res_acres = 'Total residential parcel area (acres, explicit unit alias of area_parcel_res).',
    area_parcel_res_detsf = 'Detached single-family parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_res_detsf_sl = 'Detached single-family small-lot parcel area (acres); zero placeholder.',
    area_parcel_res_detsf_ll = 'Detached single-family large-lot parcel area (acres); zero placeholder.',
    area_parcel_res_attsf = 'Attached single-family parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_res_mf = 'Multi-family parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_emp_ag = 'Agricultural employment parcel area (acres).',
    area_parcel_emp_ag_acres = 'Agricultural employment parcel area (acres, alias of area_parcel_emp_ag).',
    area_parcel_emp = 'Total employment parcel area (acres).',
    area_parcel_emp_acres = 'Total employment parcel area (acres, explicit unit alias of area_parcel_emp).',
    area_parcel_emp_ret = 'Retail employment parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_emp_off = 'Office employment parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_emp_pub = 'Public employment parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_emp_ind = 'Industrial employment parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_emp_military = 'Military employment parcel area (acres); zero placeholder, not allocated yet.',
    area_parcel_mixed_use = 'Mixed-use parcel area (acres).',
    area_parcel_mixed_use_acres = 'Mixed-use parcel area (acres, explicit unit alias of area_parcel_mixed_use).',
    area_parcel_no_use = 'Parcel area with no assigned use (acres).',
    area_parcel_no_use_acres = 'Parcel area with no assigned use (acres, explicit unit alias of area_parcel_no_use).',
    land_use = 'Land use label from the parcel source, matched against the regional land use crosswalk.',
    assessor_use_code = 'Assessor use code from the parcel source, matched on its first two digits.',
    pop = 'Total population carried from base_canvas_imputed (people).',
    pop_groupquarter = 'Group quarters population carried from base_canvas_imputed (people).',
    hh = 'Households carried from base_canvas_imputed (count).',
    du = 'Total dwelling units from base_canvas_imputed, the total the subtypes are scaled to (count).',
    du_detsf_sl = 'Detached single-family small-lot dwelling units scaled so subtypes sum to du (count).',
    du_detsf_ll = 'Detached single-family large-lot dwelling units scaled so subtypes sum to du (count).',
    du_detsf = 'Detached single-family dwelling units (small plus large lot) scaled so subtypes sum to du (count).',
    du_attsf = 'Attached single-family dwelling units scaled so subtypes sum to du (count).',
    du_mf2to4 = 'Multi-family 2-4 unit dwelling units scaled so subtypes sum to du (count).',
    du_mf5p = 'Multi-family 5+ unit dwelling units scaled so subtypes sum to du (count).',
    du_mf = 'Multi-family dwelling units (2-4 plus 5+ unit) scaled so subtypes sum to du (count).',
    du_subtype = 'Dwelling unit subtype key assigned to the parcel.',
    is_residential = 'Flag marking the parcel as residential.',
    residential_building_sqft = 'Residential building floor area carried from base_canvas_imputed (sq ft).',
    commercial_building_sqft = 'Commercial building floor area carried from base_canvas_imputed (sq ft).',
    industrial_building_sqft = 'Industrial building floor area carried from base_canvas_imputed (sq ft).',
    other_building_sqft = 'Other building floor area carried from base_canvas_imputed (sq ft).',
    total_footprint_sqft = 'Total building footprint area carried from base_canvas_imputed (sq ft).',
    building_count = 'Number of buildings on the parcel, carried from base_canvas_imputed (count).',
    footprint_ratio = 'Building footprint share of parcel area, carried from base_canvas_imputed (ratio, 0-1).',
    max_levels = 'Maximum building levels on the parcel, carried from base_canvas_imputed (count).',
    emp_ret = 'Retail employment recomputed as the sum of the five retail sub-sectors (jobs).',
    emp_retail_services = 'Retail services employment carried from base_canvas_imputed (jobs).',
    emp_restaurant = 'Restaurant employment carried from base_canvas_imputed (jobs).',
    emp_accommodation = 'Accommodation employment carried from base_canvas_imputed (jobs).',
    emp_arts_entertainment = 'Arts and entertainment employment carried from base_canvas_imputed (jobs).',
    emp_other_services = 'Other services employment carried from base_canvas_imputed (jobs).',
    emp_off = 'Office employment recomputed as office services plus medical services (jobs).',
    emp_office_services = 'Office services employment carried from base_canvas_imputed (jobs).',
    emp_medical_services = 'Medical services employment carried from base_canvas_imputed (jobs).',
    emp_pub = 'Public employment recomputed as public administration plus education (jobs).',
    emp_public_admin = 'Public administration employment carried from base_canvas_imputed (jobs).',
    emp_education = 'Education employment carried from base_canvas_imputed (jobs).',
    emp_ind = 'Industrial employment recomputed as the sum of its five sub-sectors (jobs).',
    emp_manufacturing = 'Manufacturing employment carried from base_canvas_imputed (jobs).',
    emp_wholesale = 'Wholesale employment carried from base_canvas_imputed (jobs).',
    emp_transport_warehousing = 'Transport and warehousing employment carried from base_canvas_imputed (jobs).',
    emp_utilities = 'Utilities employment carried from base_canvas_imputed (jobs).',
    emp_construction = 'Construction employment carried from base_canvas_imputed (jobs).',
    emp_ag = 'Agricultural employment recomputed as agriculture plus extraction (jobs).',
    emp_agriculture = 'Agriculture employment carried from base_canvas_imputed (jobs).',
    emp_extraction = 'Extraction employment carried from base_canvas_imputed (jobs).',
    emp = 'Total employment recomputed as the sum of the six sector groups (jobs).',
    emp_military = 'Military employment carried from base_canvas_imputed (jobs).',
    bldg_area_detsf_sl = 'Detached single-family small-lot building floor area (sq ft).',
    bldg_area_detsf_ll = 'Detached single-family large-lot building floor area (sq ft).',
    bldg_area_attsf = 'Attached single-family building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_mf = 'Multi-family building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_retail_services = 'Retail services building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_restaurant = 'Restaurant building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_accommodation = 'Accommodation building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_arts_entertainment = 'Arts and entertainment building floor area (sq ft).',
    bldg_area_other_services = 'Other services building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_office_services = 'Office services building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_public_admin = 'Public administration building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_education = 'Education building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_medical_services = 'Medical services building floor area carried from base_canvas_imputed (sq ft).',
    bldg_area_transport_warehousing = 'Transport and warehousing building floor area (sq ft).',
    bldg_area_wholesale = 'Wholesale building floor area carried from base_canvas_imputed (sq ft).',
    residential_irrigated_area = 'Residential irrigated area carried from base_canvas_imputed (acres).',
    commercial_irrigated_area = 'Commercial irrigated area carried from base_canvas_imputed (acres).',
    median_income = 'Median household income carried from base_canvas_imputed ($ per year).',
    rent_burden_pct = 'Rent-burdened household share carried from base_canvas_imputed (% as 0-100).',
    pct_minority = 'Share of people of color carried from base_canvas_imputed (% as 0-100).',
    pct_college_educated = 'College-educated adult share carried from base_canvas_imputed (% as 0-100).',
    cost_burden_pct = 'Cost-burdened household share carried from base_canvas_imputed (% as 0-100).',
    vacancy_rate = 'Housing vacancy rate carried from base_canvas_imputed (ratio, 0-1).',
    occupied_du = 'Occupied dwelling units carried from base_canvas_imputed (count).'
  ),
  audits (
    assert_du_subtype_sum_equals_du,
    assert_du_exclusivity,
    assert_employment_exclusivity,
    is_base_canvas_compatible
  ),
  blueprints @region_blueprints()
);

-- Base Canvas Reconciled — recompute aggregate columns from sub-columns.
--
-- Reads from base_canvas_imputed and ensures that aggregate columns
-- equal the sum of their constituent sub-columns.
--
-- This is the final base_canvas equivalent — the end state of the
-- full 11-step ETL pipeline.

WITH imputed AS (
    SELECT * FROM brewgis.@{region}.base_canvas_imputed
),

-- Enforce the DU exclusivity invariants the regressors violate.
--
-- SACOG source (502,874 parcels): du_detsf never co-occurs with du_attsf/du_mf,
-- and du_detsf_ll never co-occurs with du_detsf_sl — 0 of 393,426 DU parcels
-- violate either. The subtype regressors predict each subtype independently, so
-- they do.
--
-- Winner-take-all per tier, and the loser's units are transferred into the
-- winner's dominant sub-sector rather than dropped, so the parcel keeps its full
-- unit count. Ties go to the detached family and, inside a family, to the
-- earlier lot size / subtype in declaration order. Because nothing is dropped,
-- du_scale below is still du / (raw subtype sum) and each parcel's du total is
-- untouched by this step.
--
-- Layered over separate CTEs because Postgres does not resolve an output alias
-- from a sibling expression in the same SELECT list.
du_detsf_split AS (
    SELECT
        *,
        -- tier 1: du_detsf_ll XOR du_detsf_sl, the winner absorbing the loser's units
        CASE WHEN COALESCE(du_detsf_ll, 0) > 0 AND COALESCE(du_detsf_sl, 0) > 0
             THEN CASE WHEN COALESCE(du_detsf_ll, 0) >= COALESCE(du_detsf_sl, 0)
                       THEN COALESCE(du_detsf_ll, 0) + COALESCE(du_detsf_sl, 0)
                       ELSE 0 END
             ELSE COALESCE(du_detsf_ll, 0) END AS s1_detsf_ll,
        CASE WHEN COALESCE(du_detsf_ll, 0) > 0 AND COALESCE(du_detsf_sl, 0) > 0
             THEN CASE WHEN COALESCE(du_detsf_sl, 0) > COALESCE(du_detsf_ll, 0)
                       THEN COALESCE(du_detsf_sl, 0) + COALESCE(du_detsf_ll, 0)
                       ELSE 0 END
             ELSE COALESCE(du_detsf_sl, 0) END AS s1_detsf_sl
    FROM imputed
),

du_family AS (
    SELECT
        *,
        (s1_detsf_ll + s1_detsf_sl) AS det_total,
        (COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0) + COALESCE(du_mf5p, 0)) AS mix_total,
        -- tier 2: detached XOR {attached, multi-family}
        (s1_detsf_ll + s1_detsf_sl) > 0
            AND (COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0) + COALESCE(du_mf5p, 0)) > 0
            AND (s1_detsf_ll + s1_detsf_sl)
                >= (COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0) + COALESCE(du_mf5p, 0)) AS du_detsf_wins,
        (s1_detsf_ll + s1_detsf_sl) > 0
            AND (COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0) + COALESCE(du_mf5p, 0)) > 0
            AND (COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0) + COALESCE(du_mf5p, 0))
                > (s1_detsf_ll + s1_detsf_sl) AS du_mix_wins,
        -- the attached/multi-family family's dominant subtype, i.e. where the
        -- detached units land when that family wins (ties: attsf, then mf2to4)
        CASE
            WHEN COALESCE(du_attsf, 0) >= COALESCE(du_mf2to4, 0)
                 AND COALESCE(du_attsf, 0) >= COALESCE(du_mf5p, 0) THEN 'attsf'
            WHEN COALESCE(du_mf2to4, 0) >= COALESCE(du_mf5p, 0) THEN 'mf2to4'
            ELSE 'mf5p'
        END AS du_mix_dom
    FROM du_detsf_split
),

du_exclusive AS (
    SELECT
        *,
        CASE WHEN du_mix_wins THEN 0
             WHEN du_detsf_wins AND s1_detsf_ll >= s1_detsf_sl THEN s1_detsf_ll + mix_total
             ELSE s1_detsf_ll END AS x_du_detsf_ll,
        CASE WHEN du_mix_wins THEN 0
             WHEN du_detsf_wins AND s1_detsf_sl > s1_detsf_ll THEN s1_detsf_sl + mix_total
             ELSE s1_detsf_sl END AS x_du_detsf_sl,
        CASE WHEN du_detsf_wins THEN 0
             WHEN du_mix_wins AND du_mix_dom = 'attsf' THEN COALESCE(du_attsf, 0) + det_total
             ELSE COALESCE(du_attsf, 0) END AS x_du_attsf,
        CASE WHEN du_detsf_wins THEN 0
             WHEN du_mix_wins AND du_mix_dom = 'mf2to4' THEN COALESCE(du_mf2to4, 0) + det_total
             ELSE COALESCE(du_mf2to4, 0) END AS x_du_mf2to4,
        CASE WHEN du_detsf_wins THEN 0
             WHEN du_mix_wins AND du_mix_dom = 'mf5p' THEN COALESCE(du_mf5p, 0) + det_total
             ELSE COALESCE(du_mf5p, 0) END AS x_du_mf5p
    FROM du_family
),

-- Recompute DU sub-types proportionally to fit the total du.
-- With methodology Section 5, du_subtype is one-hot from built_form_key,
-- so reconciliation should scale proportionally within each subtype.


-- Recompute DU sub-types proportionally to fit the total du.
-- With methodology Section 5, du_subtype is one-hot from built_form_key,
-- so reconciliation should scale proportionally within each subtype.
-- The exclusivity tiers above transfer rather than drop, so this scale factor is
-- still du / (raw subtype sum) and no parcel's du total changes.
du_reconciled AS (
    SELECT
        *,
        (x_du_detsf_sl + x_du_detsf_ll) AS raw_detsf,
        (x_du_mf2to4 + x_du_mf5p) AS raw_mf,
        CASE
            WHEN COALESCE(x_du_detsf_sl + x_du_detsf_ll + x_du_attsf + x_du_mf2to4 + x_du_mf5p, 0) = 0
                THEN 1.0
            ELSE du / NULLIF(x_du_detsf_sl + x_du_detsf_ll + x_du_attsf + x_du_mf2to4 + x_du_mf5p, 0)
        END AS du_scale
    FROM du_exclusive
),

-- Employment sector exclusivity.
--
-- SACOG source (502,874 parcels): emp_pub never co-occurs with emp_ret or
-- emp_ind (0 of 21,626 employment parcels violate it), and emp_military is
-- exclusive against every other employment sector. Office and agricultural
-- employment mix freely, so only military-versus-everything (tier 1) and
-- pub-versus-retail/industrial (tier 2) are enforced, in that order, so tier 2
-- judges the state tier 1 left behind.
--
-- Winner-take-all per tier, and the loser is transferred into the dominant
-- sub-sector of the winning side instead of being dropped, so a parcel always
-- keeps its full job count. The dominant sub-sector is the largest value, ties
-- going to the earlier column in declaration order (retail, office, public,
-- industrial, agricultural).
--
-- emp_mil is MATERIALIZED and deliberately narrow (parcel_id + the 17 tier-1
-- columns). tier 2 reads ten of those columns a dozen times over, and inlining
-- the chain duplicates the whole tier-1 expression tree at every reference:
-- the first cut evaluated ~10^5 expression nodes per row, which measured as
-- >5 minutes per full scan and a backend OOM. It cannot simply be folded into
-- the outer query either - the final SELECT would then re-derive the tiers once
-- per output column (measured 297 s per full scan). Materializing here keeps the
-- build at ~15 s, and because the model is materialized rather than a view,
-- readers still get full filter pushdown.
emp_flags AS (
    SELECT
        *,
        COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0) + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0) + COALESCE(emp_other_services, 0) AS grp_ret,
        COALESCE(emp_office_services, 0) + COALESCE(emp_medical_services, 0) AS grp_off,
        COALESCE(emp_public_admin, 0) + COALESCE(emp_education, 0) AS grp_pub,
        COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0) + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0) + COALESCE(emp_construction, 0) AS grp_ind,
        COALESCE(emp_agriculture, 0) + COALESCE(emp_extraction, 0) AS grp_ag,
        GREATEST(
            COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0), COALESCE(emp_wholesale, 0), COALESCE(emp_transport_warehousing, 0), COALESCE(emp_utilities, 0), COALESCE(emp_construction, 0), COALESCE(emp_agriculture, 0), COALESCE(emp_extraction, 0)
        ) AS nonmil_max
    FROM du_reconciled
),

emp_wins AS (
    SELECT
        *,
        (COALESCE(emp_military, 0) > 0
            AND (grp_ret + grp_off + grp_pub + grp_ind + grp_ag) > 0
            AND COALESCE(emp_military, 0) >= (grp_ret + grp_off + grp_pub + grp_ind + grp_ag)) AS mil_wins,
        (COALESCE(emp_military, 0) > 0
            AND (grp_ret + grp_off + grp_pub + grp_ind + grp_ag) > 0
            AND COALESCE(emp_military, 0) < (grp_ret + grp_off + grp_pub + grp_ind + grp_ag)) AS nonmil_wins
    FROM emp_flags
),

emp_mil AS MATERIALIZED (
    SELECT
        parcel_id,
        CASE WHEN nonmil_wins THEN 0
             WHEN mil_wins THEN COALESCE(emp_military, 0)
                 + (grp_ret + grp_off + grp_pub + grp_ind + grp_ag)
             ELSE COALESCE(emp_military, 0) END AS m1_emp_military,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_retail_services, 0) = nonmil_max
                 THEN COALESCE(emp_retail_services, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_retail_services, 0) END AS m1_emp_retail_services,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_restaurant, 0) = nonmil_max
                  AND COALESCE(emp_restaurant, 0) > GREATEST(COALESCE(emp_retail_services, 0))
                 THEN COALESCE(emp_restaurant, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_restaurant, 0) END AS m1_emp_restaurant,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_accommodation, 0) = nonmil_max
                  AND COALESCE(emp_accommodation, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0))
                 THEN COALESCE(emp_accommodation, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_accommodation, 0) END AS m1_emp_accommodation,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_arts_entertainment, 0) = nonmil_max
                  AND COALESCE(emp_arts_entertainment, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0))
                 THEN COALESCE(emp_arts_entertainment, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_arts_entertainment, 0) END AS m1_emp_arts_entertainment,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_other_services, 0) = nonmil_max
                  AND COALESCE(emp_other_services, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0))
                 THEN COALESCE(emp_other_services, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_other_services, 0) END AS m1_emp_other_services,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_office_services, 0) = nonmil_max
                  AND COALESCE(emp_office_services, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0))
                 THEN COALESCE(emp_office_services, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_office_services, 0) END AS m1_emp_office_services,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_medical_services, 0) = nonmil_max
                  AND COALESCE(emp_medical_services, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0))
                 THEN COALESCE(emp_medical_services, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_medical_services, 0) END AS m1_emp_medical_services,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_public_admin, 0) = nonmil_max
                  AND COALESCE(emp_public_admin, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0))
                 THEN COALESCE(emp_public_admin, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_public_admin, 0) END AS m1_emp_public_admin,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_education, 0) = nonmil_max
                  AND COALESCE(emp_education, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0))
                 THEN COALESCE(emp_education, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_education, 0) END AS m1_emp_education,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_manufacturing, 0) = nonmil_max
                  AND COALESCE(emp_manufacturing, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0))
                 THEN COALESCE(emp_manufacturing, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_manufacturing, 0) END AS m1_emp_manufacturing,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_wholesale, 0) = nonmil_max
                  AND COALESCE(emp_wholesale, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0))
                 THEN COALESCE(emp_wholesale, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_wholesale, 0) END AS m1_emp_wholesale,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_transport_warehousing, 0) = nonmil_max
                  AND COALESCE(emp_transport_warehousing, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0), COALESCE(emp_wholesale, 0))
                 THEN COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_transport_warehousing, 0) END AS m1_emp_transport_warehousing,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_utilities, 0) = nonmil_max
                  AND COALESCE(emp_utilities, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0), COALESCE(emp_wholesale, 0), COALESCE(emp_transport_warehousing, 0))
                 THEN COALESCE(emp_utilities, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_utilities, 0) END AS m1_emp_utilities,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_construction, 0) = nonmil_max
                  AND COALESCE(emp_construction, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0), COALESCE(emp_wholesale, 0), COALESCE(emp_transport_warehousing, 0), COALESCE(emp_utilities, 0))
                 THEN COALESCE(emp_construction, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_construction, 0) END AS m1_emp_construction,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_agriculture, 0) = nonmil_max
                  AND COALESCE(emp_agriculture, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0), COALESCE(emp_wholesale, 0), COALESCE(emp_transport_warehousing, 0), COALESCE(emp_utilities, 0), COALESCE(emp_construction, 0))
                 THEN COALESCE(emp_agriculture, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_agriculture, 0) END AS m1_emp_agriculture,
        CASE WHEN mil_wins THEN 0
             WHEN nonmil_wins AND COALESCE(emp_extraction, 0) = nonmil_max
                  AND COALESCE(emp_extraction, 0) > GREATEST(COALESCE(emp_retail_services, 0), COALESCE(emp_restaurant, 0), COALESCE(emp_accommodation, 0), COALESCE(emp_arts_entertainment, 0), COALESCE(emp_other_services, 0), COALESCE(emp_office_services, 0), COALESCE(emp_medical_services, 0), COALESCE(emp_public_admin, 0), COALESCE(emp_education, 0), COALESCE(emp_manufacturing, 0), COALESCE(emp_wholesale, 0), COALESCE(emp_transport_warehousing, 0), COALESCE(emp_utilities, 0), COALESCE(emp_construction, 0), COALESCE(emp_agriculture, 0))
                 THEN COALESCE(emp_extraction, 0) + COALESCE(emp_military, 0)
             ELSE COALESCE(emp_extraction, 0) END AS m1_emp_extraction
    FROM emp_wins
),

emp_pub_totals AS (
    SELECT
        *,
        (m1_emp_public_admin + m1_emp_education) AS pub_group,
        (m1_emp_retail_services + m1_emp_restaurant + m1_emp_accommodation
            + m1_emp_arts_entertainment + m1_emp_other_services
            + m1_emp_manufacturing + m1_emp_wholesale + m1_emp_transport_warehousing
            + m1_emp_utilities + m1_emp_construction) AS mix_group,
        GREATEST(
            m1_emp_retail_services, m1_emp_restaurant, m1_emp_accommodation, m1_emp_arts_entertainment, m1_emp_other_services, m1_emp_manufacturing, m1_emp_wholesale, m1_emp_transport_warehousing, m1_emp_utilities, m1_emp_construction
        ) AS mix_max
    FROM emp_mil
),

emp_pub_wins AS (
    SELECT
        *,
        (pub_group > 0 AND mix_group > 0 AND pub_group >= mix_group) AS pub_wins,
        (pub_group > 0 AND mix_group > 0 AND pub_group < mix_group) AS mix_wins
    FROM emp_pub_totals
),

-- Each output column is the surviving value of its side, plus the jobs the side
-- absorbs from the tier-2 loser.
employment_exclusive AS (
    SELECT
        parcel_id,
        m1_emp_military AS x_emp_military,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_retail_services, 0) = mix_max
                      THEN m1_emp_retail_services + pub_group
             ELSE m1_emp_retail_services END AS x_emp_retail_services,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_restaurant, 0) = mix_max
                      AND COALESCE(m1_emp_restaurant, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0))
                      THEN m1_emp_restaurant + pub_group
             ELSE m1_emp_restaurant END AS x_emp_restaurant,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_accommodation, 0) = mix_max
                      AND COALESCE(m1_emp_accommodation, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0))
                      THEN m1_emp_accommodation + pub_group
             ELSE m1_emp_accommodation END AS x_emp_accommodation,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_arts_entertainment, 0) = mix_max
                      AND COALESCE(m1_emp_arts_entertainment, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0))
                      THEN m1_emp_arts_entertainment + pub_group
             ELSE m1_emp_arts_entertainment END AS x_emp_arts_entertainment,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_other_services, 0) = mix_max
                      AND COALESCE(m1_emp_other_services, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0), COALESCE(m1_emp_arts_entertainment, 0))
                      THEN m1_emp_other_services + pub_group
             ELSE m1_emp_other_services END AS x_emp_other_services,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_manufacturing, 0) = mix_max
                      AND COALESCE(m1_emp_manufacturing, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0), COALESCE(m1_emp_arts_entertainment, 0), COALESCE(m1_emp_other_services, 0))
                      THEN m1_emp_manufacturing + pub_group
             ELSE m1_emp_manufacturing END AS x_emp_manufacturing,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_wholesale, 0) = mix_max
                      AND COALESCE(m1_emp_wholesale, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0), COALESCE(m1_emp_arts_entertainment, 0), COALESCE(m1_emp_other_services, 0), COALESCE(m1_emp_manufacturing, 0))
                      THEN m1_emp_wholesale + pub_group
             ELSE m1_emp_wholesale END AS x_emp_wholesale,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_transport_warehousing, 0) = mix_max
                      AND COALESCE(m1_emp_transport_warehousing, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0), COALESCE(m1_emp_arts_entertainment, 0), COALESCE(m1_emp_other_services, 0), COALESCE(m1_emp_manufacturing, 0), COALESCE(m1_emp_wholesale, 0))
                      THEN m1_emp_transport_warehousing + pub_group
             ELSE m1_emp_transport_warehousing END AS x_emp_transport_warehousing,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_utilities, 0) = mix_max
                      AND COALESCE(m1_emp_utilities, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0), COALESCE(m1_emp_arts_entertainment, 0), COALESCE(m1_emp_other_services, 0), COALESCE(m1_emp_manufacturing, 0), COALESCE(m1_emp_wholesale, 0), COALESCE(m1_emp_transport_warehousing, 0))
                      THEN m1_emp_utilities + pub_group
             ELSE m1_emp_utilities END AS x_emp_utilities,
        CASE WHEN pub_wins THEN 0
             WHEN mix_wins AND COALESCE(m1_emp_construction, 0) = mix_max
                      AND COALESCE(m1_emp_construction, 0) > GREATEST(COALESCE(m1_emp_retail_services, 0), COALESCE(m1_emp_restaurant, 0), COALESCE(m1_emp_accommodation, 0), COALESCE(m1_emp_arts_entertainment, 0), COALESCE(m1_emp_other_services, 0), COALESCE(m1_emp_manufacturing, 0), COALESCE(m1_emp_wholesale, 0), COALESCE(m1_emp_transport_warehousing, 0), COALESCE(m1_emp_utilities, 0))
                      THEN m1_emp_construction + pub_group
             ELSE m1_emp_construction END AS x_emp_construction,
        CASE WHEN mix_wins THEN 0
             WHEN pub_wins AND COALESCE(m1_emp_public_admin, 0) >= COALESCE(m1_emp_education, 0)
                      THEN m1_emp_public_admin + mix_group
             ELSE m1_emp_public_admin END AS x_emp_public_admin,
        CASE WHEN mix_wins THEN 0
             WHEN pub_wins AND COALESCE(m1_emp_education, 0) > COALESCE(m1_emp_public_admin, 0)
                      THEN m1_emp_education + mix_group
             ELSE m1_emp_education END AS x_emp_education,
        m1_emp_office_services AS x_emp_office_services,
        m1_emp_medical_services AS x_emp_medical_services,
        m1_emp_agriculture AS x_emp_agriculture,
        m1_emp_extraction AS x_emp_extraction
    FROM emp_pub_wins
)


SELECT
    r.parcel_id,
    r.parcel_id AS geometry_key,
    NULL::text AS id_source,
    NULL::integer AS geography_id,
    r.geometry,
    r.county,
    r.land_development_category,
    r.built_form_key,
    r.intersection_density,
    r.area_gross,
    r.area_gross_acres,
    r.area_parcel_acres,
    r.area_parcel_acres AS area_parcel,
    r.area_dev_condition_acres,
    r.area_dev_condition_acres AS area_dev_condition,
    r.area_row_acres,
    r.area_row_acres AS area_row,
    r.area_parcel_res,
    r.area_parcel_res_acres,
    -- Residential sub-type area breakdown is not yet allocated by this
    -- pipeline (the legacy Python ETL never populated it either) — these
    -- are explicit zero placeholders, not real per-subtype allocations.
    0.0::double precision AS area_parcel_res_detsf,
    0.0::double precision AS area_parcel_res_detsf_sl,
    0.0::double precision AS area_parcel_res_detsf_ll,
    0.0::double precision AS area_parcel_res_attsf,
    0.0::double precision AS area_parcel_res_mf,
    r.area_parcel_emp_ag,
    r.area_parcel_emp_ag_acres,
    r.area_parcel_emp,
    r.area_parcel_emp_acres,
    -- Employment sub-type area breakdown — same caveat as residential above.
    0.0::double precision AS area_parcel_emp_ret,
    0.0::double precision AS area_parcel_emp_off,
    0.0::double precision AS area_parcel_emp_pub,
    0.0::double precision AS area_parcel_emp_ind,
    0.0::double precision AS area_parcel_emp_military,
    r.area_parcel_mixed_use,
    r.area_parcel_mixed_use_acres,
    r.area_parcel_no_use,
    r.area_parcel_no_use_acres,
    r.land_use,
    r.assessor_use_code,
    r.pop,
    r.pop_groupquarter,
    r.hh,
    r.du AS du,
    ROUND((r.x_du_detsf_sl * r.du_scale)::numeric, 4) AS du_detsf_sl,
    ROUND((r.x_du_detsf_ll * r.du_scale)::numeric, 4) AS du_detsf_ll,
    ROUND((r.raw_detsf * r.du_scale)::numeric, 4) AS du_detsf,
    ROUND((r.x_du_attsf * r.du_scale)::numeric, 4) AS du_attsf,
    ROUND((r.x_du_mf2to4 * r.du_scale)::numeric, 4) AS du_mf2to4,
    ROUND((r.x_du_mf5p * r.du_scale)::numeric, 4) AS du_mf5p,
    ROUND((r.raw_mf * r.du_scale)::numeric, 4) AS du_mf,
    r.du_subtype,
    r.is_residential,
    r.residential_building_sqft,
    r.commercial_building_sqft,
    r.industrial_building_sqft,
    r.other_building_sqft,
    r.total_footprint_sqft,
    r.building_count,
    r.footprint_ratio,
    r.max_levels,
    e.x_emp_retail_services + e.x_emp_restaurant + e.x_emp_accommodation
        + e.x_emp_arts_entertainment + e.x_emp_other_services AS emp_ret,
    e.x_emp_retail_services AS emp_retail_services,
    e.x_emp_restaurant AS emp_restaurant,
    e.x_emp_accommodation AS emp_accommodation,
    e.x_emp_arts_entertainment AS emp_arts_entertainment,
    e.x_emp_other_services AS emp_other_services,
    e.x_emp_office_services + e.x_emp_medical_services AS emp_off,
    e.x_emp_office_services AS emp_office_services,
    e.x_emp_medical_services AS emp_medical_services,
    e.x_emp_public_admin + e.x_emp_education AS emp_pub,
    e.x_emp_public_admin AS emp_public_admin,
    e.x_emp_education AS emp_education,
    e.x_emp_manufacturing + e.x_emp_wholesale + e.x_emp_transport_warehousing
        + e.x_emp_utilities + e.x_emp_construction AS emp_ind,
    e.x_emp_manufacturing AS emp_manufacturing,
    e.x_emp_wholesale AS emp_wholesale,
    e.x_emp_transport_warehousing AS emp_transport_warehousing,
    e.x_emp_utilities AS emp_utilities,
    e.x_emp_construction AS emp_construction,
    e.x_emp_agriculture + e.x_emp_extraction AS emp_ag,
    e.x_emp_agriculture AS emp_agriculture,
    e.x_emp_extraction AS emp_extraction,
    e.x_emp_retail_services + e.x_emp_restaurant + e.x_emp_accommodation
        + e.x_emp_arts_entertainment + e.x_emp_other_services
        + e.x_emp_office_services + e.x_emp_medical_services
        + e.x_emp_public_admin + e.x_emp_education
        + e.x_emp_manufacturing + e.x_emp_wholesale + e.x_emp_transport_warehousing
        + e.x_emp_utilities + e.x_emp_construction
        + e.x_emp_agriculture + e.x_emp_extraction
        + e.x_emp_military AS emp,
    e.x_emp_military AS emp_military,
    r.bldg_area_detsf_sl,
    r.bldg_area_detsf_ll,
    r.bldg_area_attsf,
    r.bldg_area_mf,
    r.bldg_area_retail_services,
    r.bldg_area_restaurant,
    r.bldg_area_accommodation,
    r.bldg_area_arts_entertainment,
    r.bldg_area_other_services,
    r.bldg_area_office_services,
    r.bldg_area_public_admin,
    r.bldg_area_education,
    r.bldg_area_medical_services,
    r.bldg_area_transport_warehousing,
    r.bldg_area_wholesale,
    r.residential_irrigated_area,
    r.commercial_irrigated_area,
    r.median_income,
    r.rent_burden_pct,
    r.pct_minority,
    r.pct_college_educated,
    r.cost_burden_pct,
    r.vacancy_rate,
    r.occupied_du
FROM du_reconciled r
JOIN employment_exclusive e ON e.parcel_id = r.parcel_id;

-- geometry_key is the integer parcel_id reused as the geometry join key, not a
-- geometry, so the linter's missinggeometryindex rule matches it by name only:
-- Postgres has no GiST opclass for an integer, only geometry is indexed here.
-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_reconciled_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_reconciled_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
