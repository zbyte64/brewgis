{#
    NLCD Parcel Statistics Model

    Computes per-parcel zonal statistics from the NLCD land cover
    raster for land development classification and impervious surface
    estimation.

    Requires vars (set by orchestrator):
        nlcd_raster_table: The PostGIS raster table (schema.table)
                          populated by run_nlcd_pipeline.
        nlcd_parcel_source: The parcel source table (schema.table)
                          with geometry and parcel_id.

    Fails at compile time if required vars are missing (fail-early
    policy — empty data is never silently substituted).

    Computation:
        1.  Clip each intersecting raster tile to the parcel boundary
            via ST_Clip.
        2.  Aggregate per-tile pixel counts across all intersecting
            tiles (ST_ValueCount) to determine the majority NLCD class.
        3.  Reclassify NLCD pixel values to impervious fractions via
            ST_Reclass and compute area-weighted mean via ST_SummaryStats.

    Output columns:
        parcel_id: Unique parcel identifier (from parcel_source).
        land_development_category: 'urban', 'agricultural', 'natural',
                                   'water', 'wetland', or 'unknown'.
        impervious_fraction: Area-weighted impervious fraction (0-1).

    Materialized as: table (expensive per-parcel computation).
#}

{%- set raster_table = var('nlcd_raster_table', none) -%}
{%- set parcel_source = var('nlcd_parcel_source', none) -%}

{% if raster_table is none or parcel_source is none -%}
    {{ exceptions.raise_compiler_error(
        "nlcd_parcel_stats requires vars 'nlcd_raster_table' and 'nlcd_parcel_source'."
    ) }}
{% endif -%}

{{ config(materialized='table') }}

WITH parcel_tiles AS (
    SELECT
        p.parcel_id,
        ST_Clip(r.rast, 1, p.geometry, TRUE, TRUE) AS clipped
    FROM {{ parcel_source }} p
    JOIN {{ raster_table }} r
        ON ST_Intersects(p.geometry, r.rast::geometry)
    WHERE p.geometry IS NOT NULL
),

tile_value_counts AS (
    SELECT
        parcel_id,
        (vc).value::integer AS nlcd_class,
        (vc).count::integer AS pixel_count
    FROM (
        SELECT
            parcel_id,
            ST_ValueCount(clipped, 1) AS vc
        FROM parcel_tiles
    ) sub
    WHERE (vc).value IS NOT NULL
),

per_parcel_value_counts AS (
    SELECT
        parcel_id,
        nlcd_class,
        SUM(pixel_count) AS total_pixels
    FROM tile_value_counts
    GROUP BY parcel_id, nlcd_class
),

majority_class AS (
    SELECT DISTINCT ON (parcel_id)
        parcel_id,
        nlcd_class AS majority_nlcd_class
    FROM per_parcel_value_counts
    ORDER BY parcel_id, total_pixels DESC
),

tile_impervious AS (
    SELECT
        parcel_id,
        (ST_SummaryStats(
            ST_Reclass(
                clipped, 1,
                '[0-20]:0, [21-21]:0.10, [22-22]:0.30, [23-23]:0.60, '
                '[24-24]:0.85, [31-31]:0.50, [32-254]:0',
                '32BF', 0
            ),
            1, TRUE
        )).*
    FROM parcel_tiles
),

per_parcel_impervious AS (
    SELECT
        parcel_id,
        CASE
            WHEN SUM(count) > 0
            THEN SUM(mean * count) / SUM(count)
            ELSE 0.0
        END AS impervious_fraction
    FROM tile_impervious
    GROUP BY parcel_id
),

all_parcels AS (
    SELECT parcel_id
    FROM {{ parcel_source }}
    WHERE geometry IS NOT NULL
)

SELECT
    ap.parcel_id,
    CASE m.majority_nlcd_class
        WHEN 11 THEN 'water'
        WHEN 12 THEN 'water'
        WHEN 21 THEN 'urban'
        WHEN 22 THEN 'urban'
        WHEN 23 THEN 'urban'
        WHEN 24 THEN 'urban'
        WHEN 31 THEN 'natural'
        WHEN 41 THEN 'natural'
        WHEN 42 THEN 'natural'
        WHEN 43 THEN 'natural'
        WHEN 51 THEN 'natural'
        WHEN 52 THEN 'natural'
        WHEN 71 THEN 'natural'
        WHEN 72 THEN 'natural'
        WHEN 73 THEN 'natural'
        WHEN 74 THEN 'natural'
        WHEN 81 THEN 'agricultural'
        WHEN 82 THEN 'agricultural'
        WHEN 90 THEN 'wetland'
        WHEN 95 THEN 'wetland'
        ELSE 'unknown'
    END AS land_development_category,
    COALESCE(i.impervious_fraction, 0.0) AS impervious_fraction
FROM all_parcels ap
LEFT JOIN majority_class m ON ap.parcel_id = m.parcel_id
LEFT JOIN per_parcel_impervious i ON ap.parcel_id = i.parcel_id
