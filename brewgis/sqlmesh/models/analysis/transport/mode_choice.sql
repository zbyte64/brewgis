MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Daily mode split per parcel: auto, transit, walk and bike trips and shares from a multinomial logit over outbound trips.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    trips_auto = 'Auto trips per day: outbound trips times the auto mode share.',
    trips_transit = 'Transit trips per day: outbound trips times the transit mode share.',
    trips_walk = 'Walk trips per day: outbound trips times the walk mode share.',
    trips_bike = 'Bike trips per day: outbound trips times the bike mode share.',
    mode_share_auto = 'Auto mode share (0-1).',
    mode_share_transit = 'Transit mode share (0-1).',
    mode_share_walk = 'Walk mode share (0-1).',
    mode_share_bike = 'Bike mode share (0-1).'
  ),
  blueprints @analysis_blueprints('mode_choice'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,)),
    assert_mode_share_sum
  )
);

-- T3 — Mode Choice (multinomial logit).
--
-- Splits each parcel's outbound trips (from T2 trip_distribution) across four
-- modes: auto (the reference alternative, u_auto = 0), transit, walk and bike.
--
-- Utilities (docs/sqlmesh-parameters.md §3.2, untuned literature defaults):
--   u_transit = asc_transit + beta_density * ln(density + 1) + beta_transit_dist * transit_access
--   u_walk    = asc_walk    + beta_density * ln(density + 1) + beta_design_walk * intersection_density
--   u_bike    = asc_bike    + beta_density * ln(density + 1) + beta_design_walk * intersection_density
-- with asc_transit = -2.0, asc_walk = -1.5, asc_bike = -2.5, beta_density = 0.15,
-- beta_design_walk = 0.05, beta_transit_dist = 0.02.
--
-- Transit access proxy (no transit network yet): 1.0 where the parcel's land
-- development category is urban or compact, 0.0 otherwise.
--
-- The softmax subtracts the largest utility before exponentiating, so a dense
-- parcel's large ln(density) term cannot overflow EXP.
--
-- Dependencies: trip_distribution, core_end_state

WITH attrs AS (
    SELECT
        td.parcel_id,
        td.trips_outbound,
        -- COALESCE because ``du`` is NULL, not 0, for a parcel the end state
        -- gave no built form: NULL would propagate into every utility and leave
        -- the whole row's shares NULL, which the mode-share audit reads as a
        -- split of 0 instead of a missing one.
        LN(COALESCE(
            CASE
                WHEN es.area_gross_acres > 0
                THEN es.du / es.area_gross_acres
                ELSE 0.0
            END,
            0.0
        ) + 1.0) AS ln_density,
        CASE
            WHEN es.land_development_category IN ('urban', 'compact')
            THEN 1.0
            ELSE 0.0
        END AS transit_access,
        COALESCE(es.intersection_density, 0.0) AS intersection_density
    FROM @{scenario_schema}.trip_distribution AS td
    LEFT JOIN @{scenario_schema}.core_end_state AS es
        ON td.parcel_id = es.parcel_id
),

-- The non-reference utilities. Auto is the reference alternative (u_auto =
-- 0), so only these three are ever computed.
utilities AS (
    SELECT
        parcel_id,
        trips_outbound,
        -2.0 + 0.15 * ln_density + 0.02 * transit_access AS u_transit,
        -1.5 + 0.15 * ln_density + 0.05 * intersection_density AS u_walk,
        -2.5 + 0.15 * ln_density + 0.05 * intersection_density AS u_bike
    FROM attrs
),

-- The softmax shift: subtracting the largest utility before exponentiating is
-- what keeps a dense parcel's large ln(density) term from overflowing EXP.
-- u_auto (0.0) leads the GREATEST because it is the reference.
softmax AS (
    SELECT
        parcel_id,
        trips_outbound,
        u_transit,
        u_walk,
        u_bike,
        GREATEST(0.0, u_transit, u_walk, u_bike) AS max_utility
    FROM utilities
),

weights AS (
    SELECT
        parcel_id,
        trips_outbound,
        EXP(-max_utility) AS e_auto,
        EXP(u_transit - max_utility) AS e_transit,
        EXP(u_walk - max_utility) AS e_walk,
        EXP(u_bike - max_utility) AS e_bike
    FROM softmax
),

totals AS (
    SELECT
        parcel_id,
        trips_outbound,
        e_auto,
        e_transit,
        e_walk,
        e_bike,
        -- Never zero: e_auto is EXP of a non-positive number, so the largest
        -- utility's weight is 1 and the denominator is at least 1.
        e_auto + e_transit + e_walk + e_bike AS denom
    FROM weights
)

SELECT
    parcel_id,
    trips_outbound * e_auto / denom AS trips_auto,
    trips_outbound * e_transit / denom AS trips_transit,
    trips_outbound * e_walk / denom AS trips_walk,
    trips_outbound * e_bike / denom AS trips_bike,
    e_auto / denom AS mode_share_auto,
    e_transit / denom AS mode_share_transit,
    e_walk / denom AS mode_share_walk,
    e_bike / denom AS mode_share_bike
FROM totals
ORDER BY parcel_id;

-- post_statements
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
