MODEL (
  name brewgis.analysis.land_consumption,
  kind FULL,
);

WITH parcel_data AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.acres_developed,
        es.building_sqft_total,
        es.du,
        es.emp,
        es.land_development_category,
        es.built_form_id,
        es.parcel_acres_developed,
        es.parcel_acres_agriculture,
        es.parcel_acres_open_space,
        es.parcel_acres_vacant,
        es.geometry
    FROM brewgis.analysis.core_end_state AS es
),

-- L1: Land use change classification
land_use AS (
    SELECT
        parcel_id,
        area_gross_acres,
        acres_developed,
        -- Classify land use transition
        CASE
            WHEN built_form_id IS NOT NULL AND acres_developed > 0 THEN
                CASE
                    WHEN land_development_category = 'urban' THEN 'vacant_to_urban'
                    WHEN land_development_category = 'compact' THEN 'vacant_to_compact'
                    WHEN land_development_category = 'standard' THEN 'vacant_to_standard'
                    WHEN land_development_category = 'rural' THEN 'vacant_to_rural'
                    ELSE 'vacant_to_developed'
                END
            ELSE 'unchanged'
        END AS land_use_transition,
        -- Acres consumed by this development
        CASE
            WHEN built_form_id IS NOT NULL AND acres_developed > 0
                THEN acres_developed
            ELSE 0.0
        END AS acres_consumed,
        -- Acres preserved (not developed)
        CASE
            WHEN built_form_id IS NOT NULL AND acres_developed > 0
                THEN GREATEST(area_gross_acres - acres_developed, 0.0)
            ELSE area_gross_acres
        END AS acres_preserved,
        COALESCE(land_development_category, 'undeveloped') AS development_type,
        building_sqft_total,
        du,
        emp,
        parcel_acres_developed,
        geometry,
        -- L2: Impervious surface estimation
        COALESCE(building_sqft_total * @ground_coverage_factor, 0.0) AS building_footprint_sqft,
        COALESCE(
            (du * @parking_per_unit
             + emp * @parking_per_employee)
            * @parking_space_sqft,
            0.0
        ) AS parking_sqft,
        COALESCE(
            acres_developed * @row_fraction * 43560.0,
            0.0
        ) AS row_sqft
    FROM parcel_data
)

SELECT
    lu.parcel_id,
    lu.land_use_transition,
    lu.acres_consumed,
    lu.acres_preserved,
    lu.development_type,
    lu.area_gross_acres,
    -- L2 impervious surface outputs
    COALESCE(lu.building_footprint_sqft, 0.0)
        + COALESCE(lu.parking_sqft, 0.0)
        + COALESCE(lu.row_sqft, 0.0)
    AS impervious_sqft,
    (COALESCE(lu.building_footprint_sqft, 0.0)
        + COALESCE(lu.parking_sqft, 0.0)
        + COALESCE(lu.row_sqft, 0.0)) / 43560.0
    AS impervious_acres,
    CASE
        WHEN lu.area_gross_acres > 0
        THEN GREATEST(
            lu.area_gross_acres
            - (COALESCE(lu.building_footprint_sqft, 0.0)
                + COALESCE(lu.parking_sqft, 0.0)
                + COALESCE(lu.row_sqft, 0.0)) / 43560.0,
            0.0
        )
        ELSE 0.0
    END AS pervious_acres,
    CASE
        WHEN lu.area_gross_acres > 0
        THEN ((COALESCE(lu.building_footprint_sqft, 0.0)
            + COALESCE(lu.parking_sqft, 0.0)
            + COALESCE(lu.row_sqft, 0.0)) / 43560.0)
            / lu.area_gross_acres * 100.0
        ELSE 0.0
    END AS impervious_pct,
    lu.geometry
FROM land_use AS lu;


-- ------------------------------------------------------------
-- Agriculture
--   Crop yield, market value, production cost, net return,
--   water consumption, labor, and truck trips for agricultural
--   parcels.
-- Source (dbt): brewgis/dbt_project/models/agriculture.sql
-- ------------------------------------------------------------

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_land_consumption_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_land_consumption_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
