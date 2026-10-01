MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Parcel-level residential and non-residential energy demand in kWh per year from end-state floor area and dwelling units at CEC climate-zone baselines.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    acres_developed = 'Developed acres from the end state (acres).',
    energy_electricity_res = 'Residential electricity demand (kWh per year): end-state dwelling units by housing class at the parcel''s CEC Building Climate Zone site intensity.',
    energy_gas_res = 'Residential gas demand (kWh per year): dwelling units by housing class at the zone''s site gas intensity (therms), converted at 29.3071 kWh per therm.',
    energy_electricity_nonres = 'Non-residential electricity demand (kWh per year): end-state floor area by use at the zone''s commercial site intensity.',
    energy_gas_nonres = 'Non-residential gas demand (kWh per year): floor area by use at the zone''s commercial gas intensity (therms), converted at 29.3071 kWh per therm.',
    energy_total = 'Total energy demand, residential plus non-residential (kWh per year).',
    energy_intensity_kwh_per_sqft = 'Energy demand per unit floor area (kWh per sq ft per year); zero without area.',
    du = 'Dwelling units from the end state (units).',
    building_sqft_total = 'Total building floor area from the end state (sq ft).',
    pop = 'Population allocated to the parcel (people).',
    emp = 'Employment allocated to the parcel (jobs).',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('energy_demand'),
);

-- Energy Demand — per-parcel kWh/year, keyed on the CEC Building Climate Zone.
--
-- Residential demand is the end state's dwelling-unit counts by housing class
-- (du_detsf_ll, du_detsf_sl, du_attsf, du_mf2to4 + du_mf5p) at the zone's
-- per-dwelling-unit site intensity from brewgis.seeds.residential_energy_baseline;
-- non-residential demand is the end state's eleven bldg_area_* uses at the
-- zone's per-square-foot intensities from brewgis.seeds.commercial_energy_baseline.
-- Gas is published in therms and emitted in kWh at 29.3071 kWh/therm, so this
-- model's output stays all-kWh as it has always been.
--
-- Both seeds are keyed on the CEC Building Climate Zone (CZ1-16), which is the
-- zone their sources publish per building prototype, and the zone
-- core_end_state assigns each parcel as title24_zone. fcz_zone is assigned on
-- every parcel too, but keys no rate: neither DEER nor the CalBEM prototypes
-- publish an intensity per CEC forecasting (utility planning) zone.
--
-- Fallback: a parcel with no zone, or whose zone the seed does not cover, keeps
-- the previous built-form behavior — its residential and commercial floor area
-- converted sq ft -> m2 and scaled by the built form's electricity_eui /
-- gas_eui. The zone expression is NULL exactly when the zone baseline does not
-- apply (title24_zone is NULL, or the pivot has no row for it), so the
-- COALESCE picks the built-form branch there; a parcel whose zone *is* covered
-- but which has no dwelling units keeps the zone branch's legitimate zero.
--
-- Source (dbt): brewgis/dbt_project/models/energy_demand.sql

WITH res_rates AS (
    -- One row per zone: the long-format seed pivoted to per-class columns.
    SELECT
        zone,
        MAX(elec_kwh_per_du_yr) FILTER (WHERE du_type = 'detsf_ll') AS elec_detsf_ll,
        MAX(elec_kwh_per_du_yr) FILTER (WHERE du_type = 'detsf_sl') AS elec_detsf_sl,
        MAX(elec_kwh_per_du_yr) FILTER (WHERE du_type = 'attsf') AS elec_attsf,
        MAX(elec_kwh_per_du_yr) FILTER (WHERE du_type = 'mf') AS elec_mf,
        MAX(gas_therm_per_du_yr) FILTER (WHERE du_type = 'detsf_ll') AS gas_detsf_ll,
        MAX(gas_therm_per_du_yr) FILTER (WHERE du_type = 'detsf_sl') AS gas_detsf_sl,
        MAX(gas_therm_per_du_yr) FILTER (WHERE du_type = 'attsf') AS gas_attsf,
        MAX(gas_therm_per_du_yr) FILTER (WHERE du_type = 'mf') AS gas_mf
    FROM @ref_model('brewgis.seeds.residential_energy_baseline')
    GROUP BY zone
),

com_rates AS (
    -- One row per zone: the long-format seed pivoted to per-use columns.
    SELECT
        zone,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'retail_services') AS elec_retail_services,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'restaurant') AS elec_restaurant,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'accommodation') AS elec_accommodation,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'arts_entertainment') AS elec_arts_entertainment,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'other_services') AS elec_other_services,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'office_services') AS elec_office_services,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'public_admin') AS elec_public_admin,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'education') AS elec_education,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'medical_services') AS elec_medical_services,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'transport_warehousing') AS elec_transport_warehousing,
        MAX(elec_kwh_per_sqft_yr) FILTER (WHERE use_type = 'wholesale') AS elec_wholesale,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'retail_services') AS gas_retail_services,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'restaurant') AS gas_restaurant,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'accommodation') AS gas_accommodation,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'arts_entertainment') AS gas_arts_entertainment,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'other_services') AS gas_other_services,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'office_services') AS gas_office_services,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'public_admin') AS gas_public_admin,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'education') AS gas_education,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'medical_services') AS gas_medical_services,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'transport_warehousing') AS gas_transport_warehousing,
        MAX(gas_therm_per_sqft_yr) FILTER (WHERE use_type = 'wholesale') AS gas_wholesale
    FROM @ref_model('brewgis.seeds.commercial_energy_baseline')
    GROUP BY zone
),

demand AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.acres_developed,
        es.du,
        es.building_sqft_total,
        es.pop,
        es.emp,
        es.geometry,

        -- Residential electric (kWh/yr): dwelling units by housing class at the
        -- zone's per-unit intensity; fallback built-form EUI off CA (see header).
        COALESCE(
            es.du_detsf_ll * r.elec_detsf_ll
            + es.du_detsf_sl * r.elec_detsf_sl
            + es.du_attsf * r.elec_attsf
            + (es.du_mf2to4 + es.du_mf5p) * r.elec_mf,
            es.building_sqft_residential * 0.092903 * es.electricity_eui,
            0.0
        ) AS energy_electricity_res,

        -- Residential gas (kWh/yr): therms at 29.3071 kWh/therm.
        COALESCE(
            (
                es.du_detsf_ll * r.gas_detsf_ll
                + es.du_detsf_sl * r.gas_detsf_sl
                + es.du_attsf * r.gas_attsf
                + (es.du_mf2to4 + es.du_mf5p) * r.gas_mf
            ) * 29.3071,
            es.building_sqft_residential * 0.092903 * es.gas_eui,
            0.0
        ) AS energy_gas_res,

        -- Non-residential electric (kWh/yr): floor area by use at the zone's
        -- commercial intensity.
        COALESCE(
            es.bldg_area_retail_services * c.elec_retail_services
            + es.bldg_area_restaurant * c.elec_restaurant
            + es.bldg_area_accommodation * c.elec_accommodation
            + es.bldg_area_arts_entertainment * c.elec_arts_entertainment
            + es.bldg_area_other_services * c.elec_other_services
            + es.bldg_area_office_services * c.elec_office_services
            + es.bldg_area_public_admin * c.elec_public_admin
            + es.bldg_area_education * c.elec_education
            + es.bldg_area_medical_services * c.elec_medical_services
            + es.bldg_area_transport_warehousing * c.elec_transport_warehousing
            + es.bldg_area_wholesale * c.elec_wholesale,
            es.building_sqft_commercial * 0.092903 * es.electricity_eui,
            0.0
        ) AS energy_electricity_nonres,

        -- Non-residential gas (kWh/yr)
        COALESCE(
            (
                es.bldg_area_retail_services * c.gas_retail_services
                + es.bldg_area_restaurant * c.gas_restaurant
                + es.bldg_area_accommodation * c.gas_accommodation
                + es.bldg_area_arts_entertainment * c.gas_arts_entertainment
                + es.bldg_area_other_services * c.gas_other_services
                + es.bldg_area_office_services * c.gas_office_services
                + es.bldg_area_public_admin * c.gas_public_admin
                + es.bldg_area_education * c.gas_education
                + es.bldg_area_medical_services * c.gas_medical_services
                + es.bldg_area_transport_warehousing * c.gas_transport_warehousing
                + es.bldg_area_wholesale * c.gas_wholesale
            ) * 29.3071,
            es.building_sqft_commercial * 0.092903 * es.gas_eui,
            0.0
        ) AS energy_gas_nonres
    FROM @{scenario_schema}.core_end_state AS es
    LEFT JOIN res_rates AS r ON r.zone = es.title24_zone
    LEFT JOIN com_rates AS c ON c.zone = es.title24_zone
)

SELECT
    parcel_id,
    area_gross_acres,
    acres_developed,
    energy_electricity_res,
    energy_gas_res,
    energy_electricity_nonres,
    energy_gas_nonres,

    -- Total energy (kWh/yr): each fuel's residential plus non-residential demand.
    (energy_electricity_res + energy_gas_res + energy_electricity_nonres + energy_gas_nonres)
        AS energy_total,

    -- Energy intensity (kWh/sqft of total floor area)
    CASE WHEN building_sqft_total > 0
        THEN (energy_electricity_res + energy_gas_res + energy_electricity_nonres + energy_gas_nonres)
            / building_sqft_total
        ELSE 0.0
    END AS energy_intensity_kwh_per_sqft,

    du,
    building_sqft_total,
    pop,
    emp,
    geometry
FROM demand;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_energy_demand_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_energy_demand_parcel_id_')
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
