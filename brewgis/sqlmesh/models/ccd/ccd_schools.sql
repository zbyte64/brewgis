MODEL (
  name brewgis.@{region}.ccd_schools,
  kind VIEW,
  description 'PostGIS VIEW over the region''s CCD school bridge that restores SRID metadata with ST_SetSRID: NCES public schools with teachers on staff in the school year of the region''s LODES year, one row per school.',
  column_descriptions (
    ncessch = 'NCES 12-digit school identifier.',
    leaid = 'NCES 7-digit identifier of the local education agency (school district) running the school.',
    school_name = 'School name as reported to the CCD.',
    school_year = 'Fall year of the CCD school year (2007 is 2007-08), the year before the region''s lodes_year.',
    teachers_fte = 'Full-time-equivalent classroom teachers at the school (FTE).',
    enrollment = 'Students enrolled at the school on the CCD count date (students), null when unreported.',
    geometry = 'School location point re-tagged as SRID 4326 (degrees, EPSG:4326).'
  ),
  columns (
    ncessch TEXT,
    leaid TEXT,
    school_name TEXT,
    school_year INTEGER,
    teachers_fte DOUBLE PRECISION,
    enrollment INTEGER,
    geometry GEOMETRY(Point, 4326)
  ),
  blueprints @region_blueprints()
);

-- CCD public schools for the region — PostGIS VIEW wrapping the bridge
-- (brewgis.<region>.ccd_schools_raw) with a real SRID, the repair
-- osm/poi_region.sql makes for the POI bridge.

SELECT
    ncessch,
    leaid,
    school_name,
    school_year,
    teachers_fte,
    enrollment,
    ST_SetSRID(geometry, 4326) AS geometry
FROM brewgis.@{region}.ccd_schools_raw;
