MODEL (
  name brewgis.@{region}.school_parcels,
  kind FULL,
  description 'The base canvas parcel holding each NCES public school''s location point, with the school''s district and estimated jobs, one row per school that falls in a parcel.',
  column_descriptions (
    ncessch = 'NCES 12-digit school identifier.',
    leaid = 'NCES 7-digit identifier of the school district running the school.',
    staff = 'Estimated jobs at the school from brewgis.<region>.school_staff (jobs).',
    parcel_id = 'Base canvas parcel whose boundary contains the school''s location point.'
  ),
  audits (
    not_null(columns := (ncessch, parcel_id)),
    unique_values(columns := (ncessch))
  ),
  blueprints @region_blueprints()
);

-- School Parcels — which base canvas parcel each CCD school stands on.
--
-- A school point on a boundary shared by two parcels belongs to the lower
-- parcel_id, so every school lands on one parcel; a parcel can hold several
-- schools (a shared campus). A school whose point falls in no parcel is not
-- here: its jobs stay wherever LODES put them.
--
-- The predicate probes base_canvas_combined's GiST index on geometry once per
-- school.

SELECT DISTINCT ON (s.ncessch)
    s.ncessch,
    s.leaid,
    s.staff,
    c.parcel_id
FROM brewgis.@{region}.school_staff s
JOIN brewgis.@{region}.base_canvas_combined c
    ON ST_Intersects(c.geometry, s.geometry)
ORDER BY s.ncessch, c.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_school_parcels_parcel_id_')
  ON @this_model USING btree (parcel_id);
ANALYZE @this_model;
