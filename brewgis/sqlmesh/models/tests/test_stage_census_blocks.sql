MODEL (
  name brewgis.tests.test_stage_census_blocks,
  kind VIEW,
  description 'Test fixture: staging VIEW matching the census_2020_block schema with three synthetic blocks.',
  column_descriptions (
    geoid = 'Synthetic census block GEOID (15-digit FIPS), three hand-written blocks here.',
    total_population = 'Total population of the block (people), synthetic values in this fixture.',
    total_housing_units = 'Total housing units in the block (count), synthetic values in this fixture.',
    total_group_quarters = 'Group quarters population of the block (people), zero in this fixture.',
    geometry = 'Block geometry (EPSG:4326), a seed parcel extent or a hand-written envelope.'
  ),
  audits (
    not_null(columns := (geoid))
  )
);

-- Test staging model: produces output matching census_2020_block schema
-- with 3 test block geometries covering the seed parcel data.

SELECT
    geoid,
    total_population,
    total_housing_units,
    0.0::double precision AS total_group_quarters,
    geometry
FROM (
    SELECT
        '060670011001001' AS geoid,
        5000::double precision AS total_population,
        2100::double precision AS total_housing_units,
        ST_MakeEnvelope(
            ST_XMin(ST_Extent(geometry)),
            ST_YMin(ST_Extent(geometry)),
            ST_XMax(ST_Extent(geometry)),
            ST_YMax(ST_Extent(geometry)),
            4326
        ) AS geometry
    FROM brewgis.seeds.test_assessor_parcels
    WHERE apn IN ('APN001', 'APN002', 'APN003', 'APN004', 'APN005', 'APN006',
                  'APN007', 'APN010', 'APN011', 'APN012', 'APN013', 'APN014',
                  'APN020', 'APN021', 'APN022', 'APN023', 'APN024', 'APN025',
                  'APN026', 'APN027', 'APN028', 'APN029', 'APN030', 'APN031',
                  'APN032', 'APN033', 'APN034', 'APN035', 'APN036', 'APN037',
                  'APN038', 'APN039', 'APN040', 'APN041')
) blocks
UNION ALL
SELECT
    '060670011002002' AS geoid,
    800::double precision AS total_population,
    350::double precision AS total_housing_units,
    0.0::double precision AS total_group_quarters,
    ST_MakeEnvelope(-121.22, 38.43, -121.12, 38.47, 4326) AS geometry
UNION ALL
SELECT
    '060670011003003' AS geoid,
    200::double precision AS total_population,
    100::double precision AS total_housing_units,
    0.0::double precision AS total_group_quarters,
    ST_MakeEnvelope(-121.16, 38.43, -121.08, 38.47, 4326) AS geometry;
