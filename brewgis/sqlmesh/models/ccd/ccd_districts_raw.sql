MODEL (
  name brewgis.@{region}.ccd_districts_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the region''s DuckDB CCD school district directory and staff counts for its state, one row per district; the geometry column lands as SRID 0.',
  column_descriptions (
    leaid = 'NCES 7-digit local education agency (school district) identifier.',
    lea_name = 'District name as reported to the CCD.',
    school_year = 'Fall year of the CCD school year (2007 is 2007-08), the year before the region''s lodes_year.',
    teachers_fte = 'Full-time-equivalent classroom teachers across the district (FTE).',
    staff_fte = 'Full-time-equivalent staff of every CCD category across the district: the reported staff total, else the sum of the reported categories (FTE).',
    office_staff_fte = 'Full-time-equivalent district-level staff (LEA administrators, their support staff and instructional coordinators): the reported LEA staff total, else the sum of those categories (FTE).',
    geometry = 'District office location point in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.<region>.ccd_districts for the re-tagged column.'
  ),
  audits (
    not_null(columns := (leaid)),
    unique_values(columns := (leaid))
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- CCD district bridge for the region — materializes the DuckDB staging VIEW
-- (ccd_districts_duckdb.sql) into PostGIS. The transfer writes SRID-less WKB,
-- so PostGIS consumers read the published brewgis.<region>.ccd_districts VIEW,
-- which re-tags the column.

SELECT
    leaid,
    lea_name,
    school_year,
    teachers_fte,
    staff_fte,
    office_staff_fte,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.@{region}.ccd_districts;
