MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Daily mode split per parcel: auto, transit, walk and bike trips plus mixed-use internal capture, from UrbanFootprint''s hierarchical sigmoid over purpose trips.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    trips_auto = 'Auto trips (trips per day): the residual after internal capture, walk, transit and bike are removed from the purpose trips.',
    trips_transit = 'Transit trips (trips per day): the non-captured purpose trips times the transit sigmoid.',
    trips_walk = 'Walk trips (trips per day): the non-captured purpose trips times the walk sigmoid.',
    trips_bike = 'Bike trips (trips per day): the non-captured purpose trips times the bike sigmoid.',
    trips_internal_capture = 'Internally captured trips (trips per day): UrbanFootprint''s mixed-use internal capture (ICPM), distinct from the internal_capture module, which splits trips at the study-area boundary.',
    mode_share_auto = 'Auto mode share (0-1).',
    mode_share_transit = 'Transit mode share (0-1).',
    mode_share_walk = 'Walk mode share (0-1).',
    mode_share_bike = 'Bike mode share (0-1).',
    mode_share_internal_capture = 'Internally captured mode share (0-1).',
    geometry = 'Parcel geometry copied from the scenario end state (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('mode_choice'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,)),
    assert_column_non_negative(column_name := trips_auto),
    assert_mode_share_sum
  )
);

-- T3 — Mode Choice (UrbanFootprint hierarchical sigmoid).
--
-- Replaces the four-way softmax over untuned literature defaults. Trip
-- generation emits purpose trips (hbw / hbo / nhb), and each purpose is run
-- through UrbanFootprint's own sequence of binary logits
-- (planning/v1/urbanfootprint-og/footprint/main/models/analysis_module/
-- vmt_module/vmt_calculate_log_odds.py and vmt_calculate_final_results.py):
--
--   icpm_p    = trips_p * sigma(ICPM_p)
--   walk_p    = (trips_p - icpm_p) * sigma(WTPM_p)
--   transit_p = (trips_p - icpm_p) * sigma(TTPM_p)
--   bike_p    = (trips_p - icpm_p) * sigma(BTPM)
--   auto_p    = GREATEST(0, trips_p - icpm_p - walk_p - transit_p - bike_p)
--
-- with sigma(x) = 1 / (1 + exp(-x)). Auto is whatever is left, exactly as the
-- reference computes it — so its share falls as the walk / transit / bike /
-- capture sigmoids rise. Walk, transit and bike are applied independently to
-- the same post-capture trips, as the reference does walk and transit (it has
-- no bike); none is taken from another's remainder. They can together
-- over-claim only on a parcel whose logits are saturated; the GREATEST keeps
-- auto at zero then, and assert_mode_share_sum fails the plan. UrbanFootprint's
-- own SACOG export never exceeds a 48.5% non-auto share, and the one input
-- that did saturate them here — the quarter-mile density over zero developed
-- acres — follows the reference's zero rule below.
--
-- The coefficients below are UrbanFootprint's published constants
-- (vmt_model_constants.py), hardcoded here the way the previous model hardcoded
-- its own literature defaults. Every ln() term is guarded x > 0 (the reference
-- skips a term whose input is zero or negative). The two transit-accessibility
-- terms the reference carries — emp30m_transit and hh_within_quarter_mile_trans
-- — are dropped: BrewGIS has no transit stops or transit network to source them
-- from. Bike is a single purpose-agnostic sigmoid: only the all-road
-- intersection density is materialized on the canvas, so its design term stands
-- in for the path density the reference would use.
--
-- Context terms (mix, quarter-mile acreage, one-mile employment, population and
-- employment per square mile) come from the quarter_mile_context support model,
-- which buffers each parcel's projected centroid.
--
-- Tunable knobs (all in ANALYSIS_PARAMETERS, overridable per scenario):
--   @blueprint_var('transport_vehicles_per_capita'):  vehicles per capita (default 0.8).
--   @blueprint_var('transport_bike_asc'):             bike alternative constant (default -6.5).
--   @blueprint_var('transport_bike_beta_density'):    ln(pop+emp per sq mi) coefficient (default 0.20).
--   @blueprint_var('transport_bike_beta_design'):     ln(intersections per sq mi) coefficient (default 0.20).
--   @blueprint_var('transport_bike_beta_hhsize'):     ln(household size) coefficient (default -0.6).
--   @blueprint_var('transport_bike_beta_veh'):        ln(vehicles per capita) coefficient (default -0.9).
--
-- Dependencies: trip_generation, core_end_state, quarter_mile_context
--
-- A parcel with no trips has no split to make, and the shares divide by
-- TOTAL_TRIPS, which is NULLIF-guarded: every share is NULL there rather than a
-- fabricated 100% auto. assert_mode_share_sum skips exactly those rows.

WITH attrs AS (
    SELECT
        tg.parcel_id,
        COALESCE(tg.trips_hbw, 0.0) AS trips_hbw,
        COALESCE(tg.trips_hbo, 0.0) AS trips_hbo,
        COALESCE(tg.trips_nhb, 0.0) AS trips_nhb,
        es.geometry,
        -- UrbanFootprint's D-variables. COALESCE because a parcel the end state
        -- gave no built form has NULL pop / hh / emp, and NULL would propagate
        -- into every logit and leave the whole row's shares NULL, which the
        -- mode-share audit reads as a split of 0 instead of a missing one.
        COALESCE(es.area_gross_acres, 0.0) / 640.0 AS area_sqmi,
        -- Already intersections per square mile — the reference's
        -- intersections_qtrmi, which it reads from intersection_density_sqmi.
        -- The density adapters count intersections within 402 m and divide by
        -- that circle's area in square miles; no conversion applies.
        COALESCE(es.intersection_density, 0.0) AS int_sqmi,
        COALESCE(
            NULLIF(COALESCE(es.pop, 0.0) / NULLIF(es.hh, 0), 0.0),
            es.household_size,
            2.577
        ) AS hh_size,
        @blueprint_var('transport_vehicles_per_capita') AS veh,
        COALESCE(es.emp, 0.0) AS emp_cell,
        -- Population + jobs per square mile of developed quarter-mile acres.
        -- With no developed acres in the quarter mile the density is 0, so its
        -- log term is skipped — the reference's tMXD_pop_emp_m_sq = 0
        -- (vmt_calculate_log_odds.py). Flooring the acres instead turns
        -- undeveloped land beside a job site into ~1e15 per square mile and
        -- saturates every walk / transit / bike sigmoid.
        CASE
            WHEN COALESCE(qm.qmb_res_acres, 0.0)
                + COALESCE(qm.qmb_emp_acres, 0.0)
                + COALESCE(qm.qmb_mixed_acres, 0.0) > 0
            THEN (COALESCE(qm.qmb_pop, 0.0) + COALESCE(qm.qmb_emp, 0.0))
                / (
                    COALESCE(qm.qmb_res_acres, 0.0)
                    + COALESCE(qm.qmb_emp_acres, 0.0)
                    + COALESCE(qm.qmb_mixed_acres, 0.0)
                ) * 640.0
            ELSE 0.0
        END AS pop_emp_sqmi,
        COALESCE(qm.emp_1mile, 0.0) AS emp_1m,
        -- Land-use mix: jobs-vs-population balance over the quarter mile,
        -- floored at 0.01 (the reference's tMXD_jobs_v_pop). With neither
        -- population nor jobs in the quarter mile there is no balance to
        -- measure: the reference's tCT is 0 there, so the mix is the floor.
        CASE
            WHEN 0.2 * COALESCE(qm.qmb_pop, 0.0) + COALESCE(qm.qmb_emp, 0.0) > 0
            THEN GREATEST(
                1.0 - ABS(0.2 * COALESCE(qm.qmb_pop, 0.0) - COALESCE(qm.qmb_emp, 0.0))
                    / (0.2 * COALESCE(qm.qmb_pop, 0.0) + COALESCE(qm.qmb_emp, 0.0)),
                0.01
            )
            ELSE 0.01
        END AS mix
    FROM @{scenario_schema}.trip_generation AS tg
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON tg.parcel_id = es.parcel_id
    LEFT JOIN @{scenario_schema}.quarter_mile_context AS qm
        ON tg.parcel_id = qm.parcel_id
),

-- The guarded logs: the reference adds a log term only when its input is
-- positive, so an ln(0) is a skipped term rather than a -infinity.
dvars AS (
    SELECT
        parcel_id,
        trips_hbw,
        trips_hbo,
        trips_nhb,
        geometry,
        veh,
        CASE WHEN mix > 0 THEN LN(mix) ELSE 0.0 END AS ln_mix,
        CASE WHEN area_sqmi > 0 THEN LN(area_sqmi) ELSE 0.0 END AS ln_area_sqmi,
        CASE WHEN int_sqmi > 0 THEN LN(int_sqmi) ELSE 0.0 END AS ln_int_sqmi,
        CASE WHEN hh_size > 0 THEN LN(hh_size) ELSE 0.0 END AS ln_hh_size,
        CASE WHEN veh > 0 THEN LN(veh) ELSE 0.0 END AS ln_veh,
        CASE WHEN emp_cell > 0 THEN LN(emp_cell) ELSE 0.0 END AS ln_emp_cell,
        CASE WHEN pop_emp_sqmi > 0 THEN LN(pop_emp_sqmi) ELSE 0.0 END AS ln_pop_emp_sqmi,
        CASE WHEN emp_1m > 0 THEN LN(emp_1m) ELSE 0.0 END AS ln_emp_1m
    FROM attrs
),

-- UrbanFootprint's log-odds, per purpose.
logits AS (
    SELECT
        parcel_id,
        trips_hbw,
        trips_hbo,
        trips_nhb,
        geometry,
        -- ICPM — internal (mixed-use) capture
        -1.75 + 0.389 * ln_mix - 1.33 * ln_hh_size - 0.99 * ln_veh
            AS icpm_hbw,
        -2.43 + 0.486 * ln_area_sqmi + 0.399 * ln_mix + 0.385 * ln_int_sqmi
            - 0.867 * ln_hh_size - 0.59 * ln_veh
            AS icpm_hbo,
        -5.32 + 0.208 * ln_emp_cell + 0.468 * ln_area_sqmi + 0.638 * ln_int_sqmi
            - 0.237 * ln_hh_size - 0.163 * ln_veh
            AS icpm_nhb,
        -- WTPM — walk
        -5.55 + 0.226 * ln_mix + 0.385 * ln_emp_1m - 1.57 * ln_hh_size
            - 1.84 * ln_veh
            AS wtpm_hbw,
        -10.96 - 0.415 * ln_area_sqmi + 0.37 * ln_pop_emp_sqmi + 0.219 * ln_mix
            + 0.45 * ln_emp_1m - 0.486 * ln_hh_size - 0.768 * ln_veh
            AS wtpm_hbo,
        -15.09 + 0.377 * ln_pop_emp_sqmi + 0.803 * ln_int_sqmi + 0.44 * ln_emp_1m
            - 0.281 * ln_hh_size - 0.242 * ln_veh
            AS wtpm_nhb,
        -- TTPM — transit (the transit-accessibility terms are dropped)
        -8.05 + 1.12 * ln_int_sqmi - 1.14 * ln_hh_size - 1.68 * ln_veh
            AS ttpm_hbw,
        -6.08 + 0.324 * ln_pop_emp_sqmi - 0.958 * ln_hh_size - 1.09 * ln_veh
            AS ttpm_hbo,
        -2.69 - 0.34 * ln_veh AS ttpm_nhb,
        -- BTPM — bike (BrewGIS's own purpose-agnostic sigmoid)
        @blueprint_var('transport_bike_asc')
            + @blueprint_var('transport_bike_beta_density') * ln_pop_emp_sqmi
            + @blueprint_var('transport_bike_beta_design') * ln_int_sqmi
            + @blueprint_var('transport_bike_beta_hhsize') * ln_hh_size
            + @blueprint_var('transport_bike_beta_veh') * ln_veh
            AS btpm
    FROM dvars
),

-- The internal-capture step: 1 / (1 + exp(-x)) rather than exp(x) / (exp(x) + 1).
-- The two are the same number; the first saturates to 1.0 for a large positive
-- logit, where the second would overflow.
capture AS (
    SELECT
        parcel_id,
        trips_hbw,
        trips_hbo,
        trips_nhb,
        trips_hbw + trips_hbo + trips_nhb AS total_trips,
        geometry,
        wtpm_hbw,
        wtpm_hbo,
        wtpm_nhb,
        ttpm_hbw,
        ttpm_hbo,
        ttpm_nhb,
        btpm,
        trips_hbw * (1.0 / (1.0 + EXP(-icpm_hbw))) AS icpm_hbw,
        trips_hbo * (1.0 / (1.0 + EXP(-icpm_hbo))) AS icpm_hbo,
        trips_nhb * (1.0 / (1.0 + EXP(-icpm_nhb))) AS icpm_nhb
    FROM logits
),

-- The active-mode steps, each on whatever the internal capture left.
active AS (
    SELECT
        parcel_id,
        trips_hbw,
        trips_hbo,
        trips_nhb,
        total_trips,
        geometry,
        icpm_hbw,
        icpm_hbo,
        icpm_nhb,
        (trips_hbw - icpm_hbw) * (1.0 / (1.0 + EXP(-wtpm_hbw))) AS walk_hbw,
        (trips_hbo - icpm_hbo) * (1.0 / (1.0 + EXP(-wtpm_hbo))) AS walk_hbo,
        (trips_nhb - icpm_nhb) * (1.0 / (1.0 + EXP(-wtpm_nhb))) AS walk_nhb,
        (trips_hbw - icpm_hbw) * (1.0 / (1.0 + EXP(-ttpm_hbw))) AS transit_hbw,
        (trips_hbo - icpm_hbo) * (1.0 / (1.0 + EXP(-ttpm_hbo))) AS transit_hbo,
        (trips_nhb - icpm_nhb) * (1.0 / (1.0 + EXP(-ttpm_nhb))) AS transit_nhb,
        (trips_hbw - icpm_hbw) * (1.0 / (1.0 + EXP(-btpm))) AS bike_hbw,
        (trips_hbo - icpm_hbo) * (1.0 / (1.0 + EXP(-btpm))) AS bike_hbo,
        (trips_nhb - icpm_nhb) * (1.0 / (1.0 + EXP(-btpm))) AS bike_nhb
    FROM capture
)

SELECT
    parcel_id,
    GREATEST(0.0, trips_hbw - icpm_hbw - walk_hbw - transit_hbw - bike_hbw)
        + GREATEST(0.0, trips_hbo - icpm_hbo - walk_hbo - transit_hbo - bike_hbo)
        + GREATEST(0.0, trips_nhb - icpm_nhb - walk_nhb - transit_nhb - bike_nhb)
        AS trips_auto,
    transit_hbw + transit_hbo + transit_nhb AS trips_transit,
    walk_hbw + walk_hbo + walk_nhb AS trips_walk,
    bike_hbw + bike_hbo + bike_nhb AS trips_bike,
    icpm_hbw + icpm_hbo + icpm_nhb AS trips_internal_capture,
    (
        GREATEST(0.0, trips_hbw - icpm_hbw - walk_hbw - transit_hbw - bike_hbw)
        + GREATEST(0.0, trips_hbo - icpm_hbo - walk_hbo - transit_hbo - bike_hbo)
        + GREATEST(0.0, trips_nhb - icpm_nhb - walk_nhb - transit_nhb - bike_nhb)
    ) / NULLIF(total_trips, 0.0) AS mode_share_auto,
    (transit_hbw + transit_hbo + transit_nhb) / NULLIF(total_trips, 0.0)
        AS mode_share_transit,
    (walk_hbw + walk_hbo + walk_nhb) / NULLIF(total_trips, 0.0) AS mode_share_walk,
    (bike_hbw + bike_hbo + bike_nhb) / NULLIF(total_trips, 0.0) AS mode_share_bike,
    (icpm_hbw + icpm_hbo + icpm_nhb) / NULLIF(total_trips, 0.0)
        AS mode_share_internal_capture,
    geometry
FROM active
ORDER BY parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_mode_choice_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_mode_choice_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;


-- Publish this model's result view where the Layers, Martin and UI paths read
-- it. The view selects from this model's prod virtual view (never its physical
-- table), so promoting a non-prod environment never repoints it. See
-- sqlmesh/macros/analysis_blueprints.py.
ON_VIRTUAL_UPDATE_BEGIN;

CREATE SCHEMA IF NOT EXISTS "@{result_schema}";

CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS
SELECT * FROM @{scenario_schema}."@{model_table}";

ON_VIRTUAL_UPDATE_END;
