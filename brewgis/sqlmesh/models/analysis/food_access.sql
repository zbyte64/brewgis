MODEL (
  name brewgis.@{scenario_schema}.@{model_table},
  kind FULL,
  description 'Per-parcel food environment metrics combining population with outlet counts and the mRFEI.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) of the parcel.',
    area_gross_acres = 'Gross parcel area (acres).',
    pop = 'Population allocated to the parcel (people).',
    hh = 'Households allocated to the parcel (households).',
    healthy_count = 'Grocery outlets within 1 km of the parcel (outlets).',
    unhealthy_count = 'Convenience stores and fast-food outlets within 1 km of the parcel (outlets).',
    mrfei = 'Modified Retail Food Environment Index: healthy outlets as a share of all outlets within 1 km (% as 0-100); null when the parcel has none within reach.',
    food_desert = 'True when the mRFEI is below 25, otherwise false.',
    food_access_category = 'Band from mRFEI: food_desert, low_access, moderate_access or high_access.',
    geometry = 'Parcel boundary geometry (EPSG:4326).'
  ),
  blueprints @analysis_blueprints('food_access'),
);

-- H2 — Food Access (mRFEI)
--
-- Counts the food outlets within reach of each parcel and scores them:
--
--   mRFEI = healthy / (healthy + unhealthy) * 100
--
-- The outlets are the region's Overpass fetch (``osm/food_pois_local.sql``),
-- projected to the local CRS and indexed there, which is what lets the 1 km
-- radius be a constant against a GiST index rather than a per-pair geography
-- computation. The parcel side is projected in the join: the analysis reads the
-- scenario's end state, whose geometry is EPSG:4326.
--
-- A parcel with no outlet within 1 km has a NULL mRFEI, not a zero one: the
-- metric is undefined without outlets to divide, and every downstream band and
-- the ``food_desert`` flag read null as unknown rather than as worst case.

WITH parcels AS (
    -- The scenario end state is EPSG:4326; the outlets are in local_srid, which
    -- is where the 1 km radius is a plain index-usable constant. The transform is
    -- pre-computed here rather than in the join: PostgreSQL keeps the GiST
    -- pushdown on the outlet geometry either way, but a transform inside a join
    -- condition is what the SQLMesh linter's notransforminjoinwhere flags.
    SELECT
        parcel_id,
        ST_Transform(geometry, @local_srid()) AS local_geometry
    FROM @{scenario_schema}.core_end_state
),

counts AS (
    SELECT
        p.parcel_id,
        COUNT(*) FILTER (WHERE fp.is_healthy) AS healthy_count,
        COUNT(*) FILTER (WHERE fp.is_unhealthy) AS unhealthy_count
    FROM parcels AS p
    JOIN brewgis.@{road_network_region}.food_pois_local AS fp
        ON ST_DWithin(
            p.local_geometry,
            fp.geometry,
            @metres_in_local_units(1000.0)
        )
    GROUP BY p.parcel_id
),

food_data AS (
    SELECT
        es.parcel_id,
        es.area_gross_acres,
        es.pop,
        es.hh,
        COALESCE(counts.healthy_count, 0) AS healthy_count,
        COALESCE(counts.unhealthy_count, 0) AS unhealthy_count,
        CASE
            WHEN counts.parcel_id IS NULL THEN NULL
            ELSE counts.healthy_count::DOUBLE PRECISION
                / NULLIF(counts.healthy_count + counts.unhealthy_count, 0) * 100.0
        END AS mrfei,
        es.geometry
    FROM @{scenario_schema}.core_end_state AS es
    LEFT JOIN counts
        ON counts.parcel_id = es.parcel_id
)

SELECT
    parcel_id,
    area_gross_acres,
    pop,
    hh,
    healthy_count,
    unhealthy_count,
    mrfei,
    COALESCE(mrfei < 25, FALSE) AS food_desert,
    CASE
        WHEN mrfei IS NULL THEN NULL
        WHEN mrfei < 25 THEN 'food_desert'
        WHEN mrfei < 50 THEN 'low_access'
        WHEN mrfei < 75 THEN 'moderate_access'
        ELSE 'high_access'
    END AS food_access_category,
    geometry
FROM food_data;


-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_food_access_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_food_access_parcel_id_')
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
