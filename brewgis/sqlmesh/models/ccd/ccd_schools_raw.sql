MODEL (
  name brewgis.@{region}.ccd_schools_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the region''s DuckDB CCD public school directory, one row per school with teachers on staff; the geometry column lands as SRID 0.',
  column_descriptions (
    ncessch = 'NCES 12-digit school identifier.',
    leaid = 'NCES 7-digit identifier of the local education agency (school district) running the school.',
    school_name = 'School name as reported to the CCD.',
    school_year = 'Fall year of the CCD school year (2007 is 2007-08), the year before the region''s lodes_year.',
    teachers_fte = 'Full-time-equivalent classroom teachers at the school (FTE).',
    enrollment = 'Students enrolled at the school on the CCD count date (students), null when unreported.',
    geometry = 'School location point in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.<region>.ccd_schools for the re-tagged column.'
  ),
  audits (
    not_null(columns := (ncessch, leaid)),
    unique_values(columns := (ncessch))
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- CCD school bridge for the region — materializes the DuckDB staging VIEW
-- (ccd_schools_duckdb.sql) into PostGIS. The transfer writes SRID-less WKB, so
-- the ST_SetCRS below is not carried over; PostGIS consumers read the published
-- brewgis.<region>.ccd_schools VIEW, which re-tags the column.

SELECT
    ncessch,
    leaid,
    school_name,
    school_year,
    teachers_fte,
    enrollment,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.@{region}.ccd_schools;
