MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Daily trip generation per parcel from UrbanFootprint activity rates: dwelling units by housing class and jobs by employment sector.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the scenario end state (core_end_state).',
    area_gross_acres = 'Gross parcel area in acres, from the scenario end state.',
    trips_res = 'Residential trips (trips per day): dwelling units by housing class x its rate (9.57 detached, 6.65 for 2-4 units, 4.18 for 5+ units and attached).',
    trips_school = 'K-12 school trips (trips per day), derived as a share of the residential trips (9.7%), as the reference does.',
    trips_nonres = 'Employment trips (trips per day): jobs by sector x its rate (21.47 retail, 37.5 food and lodging, 10.0 arts, 3.32 office and public, 3.02 industry).',
    trips_total = 'Total primary trips (trips per day): residential plus school plus employment.',
    trips_hbw = 'Home-based work share of the parcel daily trips.',
    trips_hbo = 'Home-based other share of the parcel daily trips.',
    trips_nhb = 'Non-home-based share of the parcel daily trips.',
    geometry = 'Parcel geometry copied from the scenario end state (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('trip_generation'),
  audits (
    not_null(columns := (parcel_id,)),
    unique_values(columns := (parcel_id,)),
    assert_column_non_negative(column_name := trips_total),
    assert_column_non_negative(column_name := trips_res),
    assert_column_non_negative(column_name := trips_nonres),
    assert_trip_generation_du_type_classified
  )
);

-- Trip Generation Model — T1 Module
--
-- Trips are generated from land-use ACTIVITY, never from floor area: dwelling
-- units by housing class plus jobs by employment sector. This is
-- UrbanFootprint-OG's model (planning/v1/urbanfootprint-og/footprint/main/
-- models/analysis_module/vmt_module/vmt_raw_trip_generation.py), and the rates
-- and their provenance are documented in
-- brewgis/workspace/built_forms/trip_rates.py.
--
-- A parcel that both houses and employs people emits BOTH terms — the model
-- never decides "residential" or "non-residential" from a density being
-- non-zero, and it never multiplies a rate by square footage. (The reference's
-- 42.94 is the ITE shopping-centre rate per 1000 sq ft of *retail* floor area;
-- it becomes 21.47 per retail JOB through UF's two-jobs-per-1000-sqft
-- conversion, which is the step that makes a per-job rate possible at all.)
--
-- Variables:
--   @blueprint_var('transport_du_rate_detsf'):   Detached housing (trips/unit/day, default 9.57).
--   @blueprint_var('transport_du_rate_mf2to4'):  2-4 unit multifamily (default 6.65).
--   @blueprint_var('transport_du_rate_mf5p'):    5+ unit multifamily and attached (default 4.18).
--   @blueprint_var('transport_school_trip_share'): K-12 trips as a share of residential (default 0.097).
--   @blueprint_var('transport_emp_rate_retail'): Retail and other services (trips/job/day, default 21.47).
--   @blueprint_var('transport_emp_rate_food'):   Restaurant and accommodation (default 37.5).
--   @blueprint_var('transport_emp_rate_arts'):   Arts and entertainment (default 10.0).
--   @blueprint_var('transport_emp_rate_office'): Office and medical services (default 3.32).
--   @blueprint_var('transport_emp_rate_public'): Public administration and education (default 3.32).
--   @blueprint_var('transport_emp_rate_industry'): Manufacturing, wholesale, logistics, construction, utilities, agriculture, military (default 3.02).
--   @blueprint_var('transport_hbw_pct'): Home-based work share (default 0.18).
--   @blueprint_var('transport_hbo_pct'): Home-based other share (default 0.42).
--   @blueprint_var('transport_nhb_pct'): Non-home-based share (default 0.40).
--
-- Employment trips need a sector mix per parcel, which comes from the built
-- form's ``jobs_by_sector`` percentage shares. Those shares do not always sum
-- to 100 (SACOG leaves a residual for sectors it does not publish), so they are
-- normalized over the sectors the built form does declare — the same rule as
-- ``trip_rates.sector_jobs``. A built form that declares no mix at all, and a
-- sector name this model does not know, both fall to the retail rate, the
-- traffic-generating extreme rather than a silent zero or a blended average.

WITH activity AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.geometry,

        -- Residential: the housing class the built form declares, priced at
        -- UrbanFootprint's per-unit rate. Attached single-family rides the 5+
        -- unit rate — the reference computes it and then omits it from trip
        -- generation entirely, which would be a silent undercount here.
        (COALESCE(es.du_detsf_ll, 0.0) + COALESCE(es.du_detsf_sl, 0.0))
            * @blueprint_var('transport_du_rate_detsf')
        + COALESCE(es.du_mf2to4, 0.0) * @blueprint_var('transport_du_rate_mf2to4')
        + (COALESCE(es.du_mf5p, 0.0) + COALESCE(es.du_attsf, 0.0))
            * @blueprint_var('transport_du_rate_mf5p')
            AS trips_res,

        COALESCE(es.emp, 0.0) AS emp,
        COALESCE(es.jobs_by_sector, '{}'::jsonb) AS jobs_by_sector
    FROM @{scenario_schema}.core_end_state AS es
),

-- One row per parcel, employment bucket and positive share. A parcel whose
-- built form declares no mix yields a row with a NULL key and a zero weight,
-- which the WHERE drops so `unattributed` below can claim it.
bucket_weights AS (
    SELECT
        a.parcel_id,
        a.emp,
        CASE
            WHEN kv.key IN ('retail_services', 'other_services') THEN 'retail'
            WHEN kv.key IN ('restaurant', 'accommodation') THEN 'food'
            WHEN kv.key = 'arts_entertainment' THEN 'arts'
            WHEN kv.key IN ('office_services', 'medical_services') THEN 'office'
            WHEN kv.key IN ('public_admin', 'education') THEN 'public'
            WHEN kv.key IN (
                'manufacturing', 'wholesale', 'transport_warehousing',
                'construction', 'utilities', 'agriculture', 'military'
            ) THEN 'industry'
            -- Sector name this model does not price: the fallback rate.
            ELSE 'retail'
        END AS bucket,
        COALESCE(kv.value::DOUBLE PRECISION, 0.0) AS weight
    FROM activity AS a
    LEFT JOIN LATERAL jsonb_each_text(a.jobs_by_sector) AS kv(key, value)
        ON TRUE
    WHERE COALESCE(kv.value::DOUBLE PRECISION, 0.0) > 0
),

bucket_jobs AS (
    SELECT
        parcel_id,
        bucket,
        emp * weight / SUM(weight) OVER (PARTITION BY parcel_id) AS jobs
    FROM bucket_weights
),

unattributed AS (
    SELECT
        a.parcel_id,
        'retail' AS bucket,
        a.emp AS jobs
    FROM activity AS a
    WHERE a.emp > 0
        AND NOT EXISTS (
            SELECT 1
            FROM bucket_weights AS w
            WHERE w.parcel_id = a.parcel_id
        )
),

employment AS (
    SELECT
        parcel_id,
        SUM(
            jobs * CASE bucket
                WHEN 'retail' THEN @blueprint_var('transport_emp_rate_retail')
                WHEN 'food' THEN @blueprint_var('transport_emp_rate_food')
                WHEN 'arts' THEN @blueprint_var('transport_emp_rate_arts')
                WHEN 'office' THEN @blueprint_var('transport_emp_rate_office')
                WHEN 'public' THEN @blueprint_var('transport_emp_rate_public')
                ELSE @blueprint_var('transport_emp_rate_industry')
            END
        ) AS trips_nonres
    FROM (
        SELECT parcel_id, bucket, jobs FROM bucket_jobs
        UNION ALL
        SELECT parcel_id, bucket, jobs FROM unattributed
    ) AS parcel_buckets
    GROUP BY parcel_id
)

SELECT
    a.parcel_id,
    a.area_gross_acres,
    a.trips_res,
    -- School trips are driven by households rather than by a school land use,
    -- so they scale with the residential term.
    a.trips_res * @blueprint_var('transport_school_trip_share') AS trips_school,
    COALESCE(e.trips_nonres, 0.0) AS trips_nonres,
    a.trips_res
        + a.trips_res * @blueprint_var('transport_school_trip_share')
        + COALESCE(e.trips_nonres, 0.0) AS trips_total,
    -- Trip purpose split
    (
        a.trips_res
        + a.trips_res * @blueprint_var('transport_school_trip_share')
        + COALESCE(e.trips_nonres, 0.0)
    ) * @blueprint_var('transport_hbw_pct') AS trips_hbw,
    (
        a.trips_res
        + a.trips_res * @blueprint_var('transport_school_trip_share')
        + COALESCE(e.trips_nonres, 0.0)
    ) * @blueprint_var('transport_hbo_pct') AS trips_hbo,
    (
        a.trips_res
        + a.trips_res * @blueprint_var('transport_school_trip_share')
        + COALESCE(e.trips_nonres, 0.0)
    ) * @blueprint_var('transport_nhb_pct') AS trips_nhb,
    a.geometry
FROM activity AS a
LEFT JOIN employment AS e
    ON e.parcel_id = a.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_trip_generation_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_trip_generation_parcel_id_')
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
