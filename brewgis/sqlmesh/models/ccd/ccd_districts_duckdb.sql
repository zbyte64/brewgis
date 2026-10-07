MODEL (
  name duckdb.@{region}.ccd_districts,
  kind VIEW,
  description 'DuckDB staging VIEW of the NCES Common Core of Data school district (LEA) directory and staff counts (Urban Institute Education Data Portal full-file CSV) for the region''s state in the school year its LODES year falls in, one row per district.',
  column_descriptions (
    leaid = 'NCES 7-digit local education agency (school district) identifier.',
    lea_name = 'District name as reported to the CCD.',
    school_year = 'Fall year of the CCD school year (2007 is 2007-08), the year before the region''s lodes_year.',
    teachers_fte = 'Full-time-equivalent classroom teachers across the district (FTE).',
    staff_fte = 'Full-time-equivalent staff of every CCD category across the district: the reported staff total, else the sum of the reported categories (FTE).',
    office_staff_fte = 'Full-time-equivalent district-level staff (LEA administrators, their support staff and instructional coordinators): the reported LEA staff total, else the sum of those categories (FTE).',
    geometry = 'District office location point in EPSG:4326 from the CCD latitude and longitude, null when unreported.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    leaid VARCHAR,
    lea_name VARCHAR,
    school_year INTEGER,
    teachers_fte DOUBLE,
    staff_fte DOUBLE,
    office_staff_fte DOUBLE,
    geometry GEOMETRY
  ),
  blueprints @region_blueprints()
);

-- NCES Common Core of Data — school district directory and staff counts.
--
-- The school directory (ccd_schools_duckdb.sql) counts only teachers per
-- school; the district file counts every staff category (aides, counselors,
-- librarians, school and district administrators, student and other support
-- staff), so the ratio of a district's school-based staff to its teachers
-- scales a school's teachers to its jobs. The district office location is
-- where LODES piles the jobs of a district that reports one address.
--
-- Source and coding as in ccd_schools_duckdb.sql: the Urban Institute
-- Education Data Portal full-file CSV (every year 1986 onward), read as text,
-- negative codes (-1 missing, -2 not applicable, -3 suppressed) dropped to
-- null.
--
-- Staff totals: the CCD publishes staff_total_fte and lea_staff_total_fte only
-- from 2014-15 on; earlier years carry the categories alone. Where a total is
-- missing it is rebuilt from the categories it is the sum of — checked
-- against 2020-21 California, where the categories below add up to the
-- reported staff total (609,668 FTE) and the LEA categories to the reported
-- LEA staff total (12,460 FTE) exactly.
--
-- The whole state is kept, not just the region's counties: a district's
-- office can sit in another county than some of its schools.
--
-- Variables:
--   @state_fips    — two-digit state FIPS code (config default)
--   @lodes_year    — the region's LODES year

WITH districts AS (
    SELECT
        leaid,
        lea_name,
        TRY_CAST(year AS INTEGER) AS school_year,
        TRY_CAST(latitude AS DOUBLE) AS latitude,
        TRY_CAST(longitude AS DOUBLE) AS longitude,
        -- Every staff column, negative codes dropped to null.
        CASE WHEN TRY_CAST(teachers_total_fte AS DOUBLE) >= 0 THEN TRY_CAST(teachers_total_fte AS DOUBLE) END AS teachers,
        CASE WHEN TRY_CAST(staff_total_fte AS DOUBLE) >= 0 THEN TRY_CAST(staff_total_fte AS DOUBLE) END AS staff_total,
        CASE WHEN TRY_CAST(lea_staff_total_fte AS DOUBLE) >= 0 THEN TRY_CAST(lea_staff_total_fte AS DOUBLE) END AS lea_staff_total,
        CASE WHEN TRY_CAST(instructional_aides_fte AS DOUBLE) >= 0 THEN TRY_CAST(instructional_aides_fte AS DOUBLE) END AS aides,
        CASE WHEN TRY_CAST(coordinators_fte AS DOUBLE) >= 0 THEN TRY_CAST(coordinators_fte AS DOUBLE) END AS coordinators,
        CASE WHEN TRY_CAST(guidance_counselors_total_fte AS DOUBLE) >= 0 THEN TRY_CAST(guidance_counselors_total_fte AS DOUBLE) END AS counselors,
        CASE WHEN TRY_CAST(librarian_specialists_fte AS DOUBLE) >= 0 THEN TRY_CAST(librarian_specialists_fte AS DOUBLE) END AS librarians,
        CASE WHEN TRY_CAST(librarian_support_staff_fte AS DOUBLE) >= 0 THEN TRY_CAST(librarian_support_staff_fte AS DOUBLE) END AS library_support,
        CASE WHEN TRY_CAST(lea_administrators_fte AS DOUBLE) >= 0 THEN TRY_CAST(lea_administrators_fte AS DOUBLE) END AS lea_administrators,
        CASE WHEN TRY_CAST(lea_admin_support_staff_fte AS DOUBLE) >= 0 THEN TRY_CAST(lea_admin_support_staff_fte AS DOUBLE) END AS lea_admin_support,
        CASE WHEN TRY_CAST(school_administrators_fte AS DOUBLE) >= 0 THEN TRY_CAST(school_administrators_fte AS DOUBLE) END AS school_administrators,
        CASE WHEN TRY_CAST(school_admin_support_staff_fte AS DOUBLE) >= 0 THEN TRY_CAST(school_admin_support_staff_fte AS DOUBLE) END AS school_admin_support,
        CASE WHEN TRY_CAST(support_staff_students_fte AS DOUBLE) >= 0 THEN TRY_CAST(support_staff_students_fte AS DOUBLE) END AS student_support,
        CASE WHEN TRY_CAST(support_staff_other_fte AS DOUBLE) >= 0 THEN TRY_CAST(support_staff_other_fte AS DOUBLE) END AS other_support
    FROM read_csv(
        'https://educationdata.urban.org/csv/ccd/school-districts_lea_directory.csv',
        header = true,
        all_varchar = true
    )
    WHERE year = CAST(@lodes_year - 1 AS VARCHAR)
      AND fips = CAST(CAST(@state_fips AS INTEGER) AS VARCHAR)
)

SELECT
    leaid,
    lea_name,
    school_year,
    teachers AS teachers_fte,
    COALESCE(
        staff_total,
        COALESCE(teachers, 0) + COALESCE(aides, 0) + COALESCE(coordinators, 0)
        + COALESCE(counselors, 0) + COALESCE(librarians, 0) + COALESCE(library_support, 0)
        + COALESCE(lea_administrators, 0) + COALESCE(lea_admin_support, 0)
        + COALESCE(school_administrators, 0) + COALESCE(school_admin_support, 0)
        + COALESCE(student_support, 0) + COALESCE(other_support, 0)
    ) AS staff_fte,
    COALESCE(
        lea_staff_total,
        COALESCE(lea_administrators, 0) + COALESCE(lea_admin_support, 0) + COALESCE(coordinators, 0)
    ) AS office_staff_fte,
    CASE
        WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN ST_Point(longitude, latitude)
    END AS geometry
FROM districts;
