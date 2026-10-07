MODEL (
  name brewgis.@{region}.ccd_districts,
  kind VIEW,
  description 'PostGIS VIEW over the region''s CCD district bridge that restores SRID metadata with ST_SetSRID: NCES school districts of the region''s state with their staff counts and office location, one row per district.',
  column_descriptions (
    leaid = 'NCES 7-digit local education agency (school district) identifier.',
    lea_name = 'District name as reported to the CCD.',
    school_year = 'Fall year of the CCD school year (2007 is 2007-08), the year before the region''s lodes_year.',
    teachers_fte = 'Full-time-equivalent classroom teachers across the district (FTE).',
    staff_fte = 'Full-time-equivalent staff of every CCD category across the district: the reported staff total, else the sum of the reported categories (FTE).',
    office_staff_fte = 'Full-time-equivalent district-level staff (LEA administrators, their support staff and instructional coordinators): the reported LEA staff total, else the sum of those categories (FTE).',
    geometry = 'District office location point re-tagged as SRID 4326 (degrees, EPSG:4326), null when unreported.'
  ),
  columns (
    leaid TEXT,
    lea_name TEXT,
    school_year INTEGER,
    teachers_fte DOUBLE PRECISION,
    staff_fte DOUBLE PRECISION,
    office_staff_fte DOUBLE PRECISION,
    geometry GEOMETRY(Point, 4326)
  ),
  blueprints @region_blueprints()
);

-- CCD school districts — PostGIS VIEW wrapping the bridge
-- (brewgis.<region>.ccd_districts_raw) with a real SRID, the repair
-- osm/poi_region.sql makes for the POI bridge.

SELECT
    leaid,
    lea_name,
    school_year,
    teachers_fte,
    staff_fte,
    office_staff_fte,
    ST_SetSRID(geometry, 4326) AS geometry
FROM brewgis.@{region}.ccd_districts_raw;
