MODEL (
  name brewgis.@{region}.school_staff,
  kind FULL,
  description 'Estimated jobs at each NCES public school in the region: the school''s CCD teacher FTE scaled by its district''s ratio of school-based staff to teachers, one row per school.',
  column_descriptions (
    ncessch = 'NCES 12-digit school identifier.',
    leaid = 'NCES 7-digit identifier of the school district running the school.',
    school_name = 'School name as reported to the CCD.',
    teachers_fte = 'Full-time-equivalent classroom teachers at the school (FTE).',
    staff_per_teacher = 'School-based staff per teacher applied to the school: its district''s CCD staff minus district-office staff over its teachers, else the region''s pooled ratio when the district''s is missing or outside 1-4 (ratio).',
    staff = 'Estimated jobs at the school: teachers_fte times staff_per_teacher (jobs).',
    geometry = 'School location point (EPSG:4326).'
  ),
  audits (
    not_null(columns := (ncessch, staff, geometry)),
    unique_values(columns := (ncessch))
  ),
  blueprints @region_blueprints()
);

-- School staff — how many jobs each CCD school holds.
--
-- The CCD counts teachers per school but every other staff category (aides,
-- counselors, librarians, school administrators and their support staff,
-- student and other support staff) only per district. A school's jobs are its
-- teachers times its district's school-based staff per teacher, where
-- school-based staff is the district's staff total minus its district-office
-- staff (LEA administrators, their support staff and instructional
-- coordinators, who work at the office: school_override.sql keeps them
-- there). California averages 1.75 (2007-08) to 2.24 (2020-21).
--
-- A district's own ratio is used when it is between 1 (no school runs on fewer
-- staff than teachers) and 4 (an umbrella charter operator reports staff for
-- schools filed under other LEAs: Oro Grande, 4 teachers and 63 staff in
-- 2021-22). Otherwise, and for a school whose district the file lacks, the
-- region's pooled ratio — total school-based staff over total teachers of the
-- valid districts running its schools — applies.

WITH district_ratio AS (
    SELECT
        leaid,
        teachers_fte,
        staff_fte - office_staff_fte AS school_based_staff,
        (staff_fte - office_staff_fte) / NULLIF(teachers_fte, 0) AS ratio
    FROM brewgis.@{region}.ccd_districts
    WHERE leaid IN (SELECT leaid FROM brewgis.@{region}.ccd_schools)
),

valid_ratio AS (
    SELECT *
    FROM district_ratio
    WHERE ratio BETWEEN 1.0 AND 4.0
),

pooled AS (
    SELECT SUM(school_based_staff) / NULLIF(SUM(teachers_fte), 0) AS ratio
    FROM valid_ratio
)

SELECT
    s.ncessch,
    s.leaid,
    s.school_name,
    s.teachers_fte,
    COALESCE(v.ratio, p.ratio) AS staff_per_teacher,
    s.teachers_fte * COALESCE(v.ratio, p.ratio) AS staff,
    s.geometry
FROM brewgis.@{region}.ccd_schools s
LEFT JOIN valid_ratio v
    ON v.leaid = s.leaid
CROSS JOIN pooled p;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_school_staff_geometry_')
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
