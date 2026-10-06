MODEL (
  name duckdb.california.eto_zones,
  kind VIEW,
  description 'DuckDB staging VIEW reading the CIMIS/DWR Reference Evapotranspiration Zones MapServer for all of California through arcgis_query.',
  column_descriptions (
    eto_zone = 'Reference Evapotranspiration Zone number (the layer''s Zone attribute, 1-18) the polygon belongs to.',
    annual_eto_in = 'Annual reference evapotranspiration of the zone: the sum of the layer''s twelve monthly average ETo depths (inches per year).',
    geometry = 'Zone polygon returned by arcgis_query in EPSG:4326 lon/lat; the layer mixes Polygon and MultiPolygon features.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    eto_zone INTEGER,
    annual_eto_in DOUBLE,
    geometry GEOMETRY
  )
);

-- CIMIS Reference Evapotranspiration (ETo) Zones — DuckDB VIEW over the whole
-- statewide layer. arcgis_query (the arcgis extension) returns the layer's
-- fields as typed columns plus an EPSG:4326 geometry. The layer held 392
-- polygons (18 zones, 1-18, many fragments each) when this was written
-- (2026-10-01, verified against the service's returnCountOnly).
--
-- No envelope: the zones are statewide reference geography shared by every
-- region (see building_climate_zones_duckdb.sql).
--
-- The layer publishes one row per *polygon*, and every polygon of a zone repeats
-- that zone's twelve monthly averages (verified: all fragments of a zone carry
-- the same monthly values), so annual_eto_in is the same for each fragment of a
-- zone. The fragments are kept rather than collapsed to one row per zone because
-- the parcel assignment is a point-in-polygon test: a single merged row per zone
-- would leave every parcel outside that fragment unmatched.
--
-- Source: "i04 CIMIS Reference Evapotranspiration Zones v1999"
-- (https://data.ca.gov/dataset/i04-cimis-reference-evapotranspiration-zones-v1999),
-- the CNRA MapServer behind that dataset. The monthly averages are published in
-- *inches* of reference ET, so annual_eto_in is a depth: 1 inch = 25.4 mm =
-- 25.4 L/m², the conversion core_end_state applies when it derives
-- annual_eto_mm.

SELECT
    Zone AS eto_zone,
    (
        January_Monthly_Avg_ETo
        + February_Monthly_Avg_ETo
        + March_Monthly_Avg_ETo
        + April_Monthly_Avg_ETo
        + May_Monthly_Avg_ETo
        + June_Monthly_Avg_ETo
        + July_Monthly_Avg_ETo
        + August_Monthly_Avg_ETo
        + September_Monthly_Avg_ETo
        + October_Monthly_Avg_ETo
        + November_Monthly_Avg_ETo
        + December_Monthly_Avg_ETo
    ) AS annual_eto_in,
    geometry
FROM arcgis_query(
    'https://utility.arcgis.com/usrsvcs/servers/bc6b44c93b824ba1883d07cd139d9324/rest/services/Climatology/i04_CIMIS_Reference_Evapotranspiration_Zones_v1999/MapServer/0'
);
