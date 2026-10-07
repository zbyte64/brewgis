MODEL (
  name duckdb.@{region}.ccd_schools,
  kind VIEW,
  description 'DuckDB staging VIEW of the NCES Common Core of Data public school directory (Urban Institute Education Data Portal full-file CSV) for the region''s counties in the school year its LODES year falls in, one row per school with teachers on staff.',
  column_descriptions (
    ncessch = 'NCES 12-digit school identifier.',
    leaid = 'NCES 7-digit identifier of the local education agency (school district) running the school.',
    school_name = 'School name as reported to the CCD.',
    school_year = 'Fall year of the CCD school year (2007 is 2007-08), the year before the region''s lodes_year.',
    teachers_fte = 'Full-time-equivalent classroom teachers at the school (FTE).',
    enrollment = 'Students enrolled at the school on the CCD count date (students), null when unreported.',
    geometry = 'School location point in EPSG:4326 from the CCD latitude and longitude.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    ncessch VARCHAR,
    leaid VARCHAR,
    school_name VARCHAR,
    school_year INTEGER,
    teachers_fte DOUBLE,
    enrollment INTEGER,
    geometry GEOMETRY
  ),
  blueprints @region_blueprints()
);

-- NCES Common Core of Data — public school directory for the region.
--
-- LODES assigns every job to the address its employer reports to the state UI
-- program, and school districts commonly report one address for the whole
-- district (LODES Design and Methodology Report, CES-WP-25-52: "Nonreporting
-- of multiple worksites is especially common with state and local governments
-- and school districts ... LEHD infrastructure files assign all workers for
-- that employer (within the state) to the main address provided"). The CCD
-- places each school at its own campus with its own teacher count, so it is
-- what puts those jobs back on the schools (base_canvas/school_override.sql).
--
-- Source: the Urban Institute Education Data Portal's full-file CSV of the CCD
-- school directory (every year 1986 onward, ~1 GB), the one CCD distribution
-- whose layout is the same in every year — NCES's own flat files change
-- layout year to year and its EDGE ArcGIS layers start in 2017-18. DuckDB
-- streams it over httpfs; cache_httpfs keeps the download for later reads.
-- Read as text: the portal codes missing / not applicable / suppressed values
-- as -1 / -2 / -3, which are dropped to null here (a negative FTE or
-- enrollment is not a count).
--
-- School year: LODES counts the jobs held on April 1 of lodes_year (its Q2
-- reference), inside the school year that started the previous fall, which the
-- portal files under that fall's year — hence lodes_year - 1.
--
-- Kept: schools in the region's counties with teachers on staff and a
-- location. Dropped: schools reporting no teachers (closed, future, or
-- reporting their staff elsewhere) and schools the CCD flags as fully virtual
-- (virtual = 1), whose teachers do not work at the campus point.
--
-- Variables:
--   @state_fips    — two-digit state FIPS code (config default)
--   @county_fips   — the region's comma-separated three-digit county codes
--   @lodes_year    — the region's LODES year

WITH region_counties AS (
    SELECT CAST(CAST(@state_fips AS INTEGER) * 1000 + CAST(trim(c) AS INTEGER) AS VARCHAR) AS county_code
    FROM unnest(string_split(@county_fips, ',')) AS t(c)
),

schools AS (
    SELECT
        ncessch,
        leaid,
        school_name,
        TRY_CAST(year AS INTEGER) AS school_year,
        TRY_CAST(teachers_fte AS DOUBLE) AS teachers_fte,
        TRY_CAST(enrollment AS INTEGER) AS enrollment,
        TRY_CAST(latitude AS DOUBLE) AS latitude,
        TRY_CAST(longitude AS DOUBLE) AS longitude,
        virtual
    FROM read_csv(
        'https://educationdata.urban.org/csv/ccd/schools_ccd_directory.csv',
        header = true,
        all_varchar = true
    )
    WHERE year = CAST(@lodes_year - 1 AS VARCHAR)
      AND fips = CAST(CAST(@state_fips AS INTEGER) AS VARCHAR)
      AND county_code IN (SELECT county_code FROM region_counties)
)

SELECT
    ncessch,
    leaid,
    school_name,
    school_year,
    teachers_fte,
    CASE WHEN enrollment >= 0 THEN enrollment END AS enrollment,
    ST_Point(longitude, latitude) AS geometry
FROM schools
WHERE teachers_fte > 0
  AND latitude IS NOT NULL
  AND longitude IS NOT NULL
  AND COALESCE(virtual, '') <> '1';
