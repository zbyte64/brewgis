MODEL (
  name brewgis.fresno.overture_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id)),
    unique_values(columns := (parcel_id,)),
    assert_intersection_density_coverage
  ),
  dialect postgres
);

-- Fresno Overture Intersection Density — per-parcel intersection density.
--
-- Methodology matches brewgis.assessor.overture_intersection_density:
-- uses ST_DWithin against pre-computed Fresno intersection points to
-- count intersections within a 1/4-mile (402m) radius of each parcel's
-- centroid.
--
-- Density = intersection_count / (pi * 402^2 / 2589988.11) intersections/sq mi.

WITH parcel_centroids AS (
    SELECT
        parcel_id,
        ST_Centroid(local_geometry) AS centroid_local
    FROM brewgis.fresno.parcel_shim
    WHERE local_geometry IS NOT NULL
),

density AS (
    SELECT
        pc.parcel_id,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS intersection_density
    FROM parcel_centroids pc
    LEFT JOIN brewgis.fresno.overture_intersection_points i
        ON ST_DWithin(pc.centroid_local, i.geometry, 402.0)
    GROUP BY pc.parcel_id
)
SELECT
    d.parcel_id,
    COALESCE(d.intersection_density, 0.0) AS intersection_density
FROM density d;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fresno_intersection_density_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  DROP TABLE IF EXISTS public.fresno_intersection_density CASCADE;
  CREATE TABLE public.fresno_intersection_density AS
  SELECT parcel_id, intersection_density FROM @this_model;
  CREATE INDEX IF NOT EXISTS idx_fresno_intersection_density_pid
  ON public.fresno_intersection_density USING btree (parcel_id);
ANALYZE @this_model;
ANALYZE public.fresno_intersection_density;
