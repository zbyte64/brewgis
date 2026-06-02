-- Bootstrap empty source tables for dbt test pipeline
-- Creates the census and lehd schemas with empty tables matching
-- the column types that base_canvas_demographics and
-- base_canvas_employment expect.
--
-- These tables are normally populated by the acs_block_group and
-- wac_block dbt models from real ACS/LEHD data.  For the seed-based
-- test run they need to exist but can be empty — the downstream
-- models use LEFT JOIN + COALESCE and produce valid NULL/zero output
-- from empty sources.

CREATE SCHEMA IF NOT EXISTS census;
CREATE TABLE IF NOT EXISTS census.acs_block_group (
    geoid                    TEXT,
    geometry                 GEOMETRY(MULTIPOLYGON, 4326),
    pop                      DOUBLE PRECISION,
    hh                       DOUBLE PRECISION,
    du                       DOUBLE PRECISION,
    du_detsf                 DOUBLE PRECISION,
    du_detsf_sl              DOUBLE PRECISION,
    du_detsf_ll              DOUBLE PRECISION,
    du_attsf                 DOUBLE PRECISION,
    du_mf                    DOUBLE PRECISION,
    du_mf2to4                DOUBLE PRECISION,
    du_mf5p                  DOUBLE PRECISION,
    median_income            DOUBLE PRECISION,
    rent_burden_pct          DOUBLE PRECISION,
    pct_minority             DOUBLE PRECISION,
    pct_college_educated     DOUBLE PRECISION,
    cost_burden_pct          DOUBLE PRECISION
);

CREATE SCHEMA IF NOT EXISTS lehd;
CREATE TABLE IF NOT EXISTS lehd.wac_block (
    geoid                       TEXT,
    geometry                    GEOMETRY(MULTIPOLYGON, 4326),
    emp                         DOUBLE PRECISION,
    emp_retail_services         DOUBLE PRECISION,
    emp_restaurant              DOUBLE PRECISION,
    emp_accommodation           DOUBLE PRECISION,
    emp_arts_entertainment      DOUBLE PRECISION,
    emp_other_services          DOUBLE PRECISION,
    emp_office_services         DOUBLE PRECISION,
    emp_medical_services        DOUBLE PRECISION,
    emp_public_admin            DOUBLE PRECISION,
    emp_education               DOUBLE PRECISION,
    emp_manufacturing           DOUBLE PRECISION,
    emp_wholesale               DOUBLE PRECISION,
    emp_transport_warehousing   DOUBLE PRECISION,
    emp_utilities               DOUBLE PRECISION,
    emp_construction            DOUBLE PRECISION,
    emp_agriculture             DOUBLE PRECISION,
    emp_extraction              DOUBLE PRECISION,
    emp_military                DOUBLE PRECISION,
    emp_ret                     DOUBLE PRECISION,
    emp_off                     DOUBLE PRECISION,
    emp_pub                     DOUBLE PRECISION,
    emp_ind                     DOUBLE PRECISION,
    emp_ag                      DOUBLE PRECISION
);

-- Bootstrap table for Overture building footprints (may be empty for
-- tests that compile parcel_dasymetric_weights without footprint data).
CREATE TABLE IF NOT EXISTS public.overture_buildings (
    geometry     GEOMETRY(GEOMETRY, 4326),
    height       DOUBLE PRECISION,
    levels       INTEGER,
    class        TEXT,
    source       TEXT,
    id           TEXT
);

-- Bootstrap table for VIDA combined building footprints
CREATE TABLE IF NOT EXISTS public.vida_combined_buildings (
    geometry       GEOMETRY(GEOMETRY, 4326),
    confidence     DOUBLE PRECISION,
    bf_source      TEXT,
    area_in_meters DOUBLE PRECISION
);
