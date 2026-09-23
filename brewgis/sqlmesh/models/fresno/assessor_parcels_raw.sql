MODEL (
  name brewgis.fresno.assessor_parcels_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Fresno assessor roll fetch, one row per situs-address feature.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the roll feature, as fetched from FC_PARCEL_SELECT.',
    use_primary = 'USE_PRIMARY assessor land-use code of the parcel (e.g. S01, A99, ALM).',
    use_secondary = 'USE_SECONDARY assessor land-use code of the parcel.',
    use_high_best = 'USE_HIGH_BEST assessor highest-and-best-use code of the parcel.',
    lot_size_acres = 'LOT_AREA assessor lot size in acres (source units).',
    assess_land_val = 'ASSESS_LAND_VAL assessed land value of the parcel (dollars).',
    assess_imp_val = 'ASSESS_IMP_VAL assessed improvement value of the parcel (dollars).',
    total_assessed_value = 'TOTAL_ASSESSED_VALUE total assessed value of the parcel (dollars).',
    tax_area_code = 'TAX_AREA_CODE county tax-area code of the parcel.',
    geometry = 'Feature geometry in EPSG:4326, ST_SetCRS-tagged so the FDW keeps the SRID.'
  ),
  gateway duckdb
);

-- Fresno Assessor Parcels Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_GeomFromGeoJSON emits EPSG:4326 geometry (GeoJSON lon/lat).
-- ST_SetCRS records the SRID explicitly because the DuckDB→PostGIS FDW drops
-- SRID metadata (all geometries arrive as SRID 0), mirroring
-- fresno/parcels_raw.sql and sacog/assessor_parcels_raw.sql.
--
-- Grain is one row per situs-address feature; brewgis.fresno.assessor_parcels
-- (the adapter) collapses to one row per APN. PostGIS models should use that
-- adapter rather than referencing this table directly.

SELECT
    apn,
    use_primary,
    use_secondary,
    use_high_best,
    lot_size_acres,
    assess_land_val,
    assess_imp_val,
    total_assessed_value,
    tax_area_code,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.assessor_parcels;
