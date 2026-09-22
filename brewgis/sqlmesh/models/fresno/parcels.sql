MODEL (
  name brewgis.fresno.parcels,
  kind VIEW,
  description 'Fresno County parcel set from the county ArcGIS FeatureServer, one row per parcel_id at SRID 4326.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) from the county FeatureServer, the parcel key this VIEW collapses on.',
    apn = 'Assessor parcel number (APN); the MIN of the feature-level APNs sharing this parcel_id.',
    agency_cod = 'AGENCY_COD code of the source agency record (MIN across the collapsed features).',
    roll_year = 'ROLL_YEAR assessor roll year of the source records (MIN across the collapsed features).',
    shape_area = 'Sum of the source feature SHAPE_AREA attributes collapsed into this parcel_id (source units).',
    geometry = 'Parcel footprint at SRID 4326: ST_Union of the validated feature geometries sharing this parcel_id.'
  ),
  columns (
    parcel_id TEXT,
    apn TEXT,
    agency_cod TEXT,
    roll_year TEXT,
    shape_area DOUBLE PRECISION,
    geometry GEOMETRY(GEOMETRY, 4326)
  ),
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,)),
    assert_row_count_greater_than_zero
  )
);

-- Fresno Parcels — the PostGIS parcel set: one row per parcel_id at SRID 4326.
--
-- The DuckDB bridge (brewgis.fresno.parcels_raw) materializes the
-- fetched parcels with ST_SetCRS, then SQLMesh exposes it to PostGIS via
-- FDW. However, the FDW drops SRID metadata, so all geometries arrive as
-- SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID so parcel_shim's existing
-- ST_Transform(geometry, @default_srid) is an identity transform instead of
-- erroring on SRID 0, and downstream spatial predicates can use the indexed
-- geometry column directly.
--
-- It also collapses to one row per parcel_id. The county FeatureServer is at
-- feature grain: one APN can carry several polygons (condominium unit sets,
-- multi-part parcels, cross-agency republications) and the current fetch has
-- 50 such APNs across 106 same-key pairs. Every PostGIS consumer of this model
-- — parcel_shim, nlcd_parcel_stats, nlcd_tree_canopy_parcel_stats — is keyed
-- on parcel_id, so a parcel's extent is the union of its features, and
-- carrying the features through would emit duplicate parcel_id rows and fan
-- out base_canvas_combined's joins on parcel_id. Union, rather than "largest
-- feature wins", keeps the land and the area: 88 of those 106 pairs are
-- spatially disjoint, and the 4 overlapping pairs dissolve instead of
-- double-counting.
--
-- This is the parcel-set boundary for the region: the feature grain stops at
-- parcels_raw, so any new consumer reads the collapsed set without repeating
-- the aggregation. Only parcel_id and geometry are read downstream; the
-- remaining attributes are aggregated to keep one row per key.

WITH source_parcels AS (
    SELECT
        parcel_id,
        apn,
        agency_cod,
        roll_year,
        shape_area,
        ST_SetSRID(geometry, 4326) AS geometry
    FROM brewgis.fresno.parcels_raw
)

SELECT
    parcel_id,
    MIN(apn) AS apn,
    MIN(agency_cod) AS agency_cod,
    MIN(roll_year) AS roll_year,
    SUM(shape_area) AS shape_area,
    ST_Union(ST_MakeValid(geometry)) AS geometry
FROM source_parcels
GROUP BY parcel_id;
