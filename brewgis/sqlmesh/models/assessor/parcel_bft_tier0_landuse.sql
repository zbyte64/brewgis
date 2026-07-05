MODEL (
  name brewgis.assessor.parcel_bft_tier0_landuse,
  kind VIEW,
  audits (
    assert_bft_landuse_A1_to_detsf,
    assert_bft_landuse_A3_to_attsf,
    assert_bft_landuse_A4_to_detsf,
    assert_bft_landuse_AE_to_commercial,
    assert_bft_landuse_AF_to_industrial,
    assert_bft_landuse_AG_to_agricultural,
    assert_bft_landuse_AHAJ_to_civic,
    assert_bft_landuse_AD_to_undeveloped,
    assert_bft_landuse_AQ_to_undeveloped,
    assert_bft_landuse_commercial_codes_to_commercial,
    assert_bft_landuse_civic_codes_to_civic,
    assert_bft_landuse_industrial_codes_to_industrial
  )
);

-- Tier 0: from landuse code. Returns one row per parcel successfully classified
-- by landuse alone. Only outputs (apn, built_form_key) — callers JOIN the
-- assessor table for additional parcel attributes.

WITH assessor_parcels AS (
    SELECT
        apn,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse,
        LEFT(landuse::text, 2) AS landuse_prefix
    FROM brewgis.assessor.sacog_assessor_parcels
    WHERE landuse IS NOT NULL
)
SELECT
    ap.apn,
    CASE
        WHEN ap.landuse_prefix LIKE 'A1' THEN
            CASE
                WHEN 1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) > 0.5
                    THEN 'detsf_sl'
                ELSE 'detsf_ll'
            END
        -- A2% (multi-family): no tier0 classification. Falls through to tier2
        -- (Overture footprints, which distinguish mf2to4 vs mf5p from building
        -- square footage and height), then to tier3 landuse-constrained KNN.
        WHEN ap.landuse_prefix LIKE 'A2' THEN NULL
        WHEN ap.landuse_prefix LIKE 'A3' THEN 'attsf'
        WHEN ap.landuse_prefix LIKE 'A4' THEN 'detsf_sl'
        WHEN ap.landuse_prefix LIKE 'AE' THEN 'commercial'
        WHEN ap.landuse_prefix LIKE 'AF' THEN 'industrial'
        WHEN ap.landuse_prefix LIKE 'AG' THEN 'agricultural'
        WHEN ap.landuse_prefix IN ('AH', 'AJ') THEN 'civic'
        -- AT% (apartments): no tier0 classification. Falls through to tier2
        -- so building footprints can distinguish mf2to4 vs mf5p.
        WHEN ap.landuse_prefix IN ('AT') THEN NULL
        WHEN ap.landuse_prefix IN ('CA', 'BA', 'BF', 'BC', 'BB', 'BE', 'BD', 'CG') THEN 'commercial'
        WHEN ap.landuse_prefix IN ('GC', 'GA', 'HJ') THEN 'civic'
        WHEN ap.landuse_prefix IN ('MS', 'MU', 'MP') THEN 'commercial'
        WHEN ap.landuse_prefix IN ('IA', 'IG', 'IB') THEN 'industrial'
        WHEN ap.landuse_prefix IN ('AQ') THEN 'undeveloped'
        WHEN ap.landuse_prefix LIKE 'AD' THEN 'undeveloped'
        ELSE NULL
    END AS built_form_key
FROM assessor_parcels ap
LEFT JOIN brewgis.assessor.overture_intersection_density id ON ap.apn = id.apn
WHERE ap.landuse IS NOT NULL
  AND CASE
        WHEN ap.landuse_prefix LIKE 'A1' THEN
            CASE
                WHEN 1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0))) > 0.5
                    THEN 'detsf_sl'
                ELSE 'detsf_ll'
            END
        WHEN ap.landuse_prefix LIKE 'A2' THEN NULL
        WHEN ap.landuse_prefix LIKE 'A3' THEN 'attsf'
        WHEN ap.landuse_prefix LIKE 'A4' THEN 'detsf_sl'
        WHEN ap.landuse_prefix LIKE 'AE' THEN 'commercial'
        WHEN ap.landuse_prefix LIKE 'AF' THEN 'industrial'
        WHEN ap.landuse_prefix LIKE 'AG' THEN 'agricultural'
        WHEN ap.landuse_prefix IN ('AH', 'AJ') THEN 'civic'
        WHEN ap.landuse_prefix IN ('AT') THEN NULL
        WHEN ap.landuse_prefix IN ('CA', 'BA', 'BF', 'BC', 'BB', 'BE', 'BD', 'CG') THEN 'commercial'
        WHEN ap.landuse_prefix IN ('GC', 'GA', 'HJ') THEN 'civic'
        WHEN ap.landuse_prefix IN ('MS', 'MU', 'MP') THEN 'commercial'
        WHEN ap.landuse_prefix IN ('IA', 'IG', 'IB') THEN 'industrial'
        WHEN ap.landuse_prefix IN ('AQ') THEN 'undeveloped'
        WHEN ap.landuse_prefix LIKE 'AD' THEN 'undeveloped'
        ELSE NULL
    END IS NOT NULL;
