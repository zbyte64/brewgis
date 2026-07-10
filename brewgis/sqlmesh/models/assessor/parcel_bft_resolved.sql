MODEL (
  name brewgis.assessor.parcel_bft_resolved,
  kind VIEW,
  audits (
    assert_parcel_bft_classification_row_count(parcel_table := 'brewgis.assessor.sacog_assessor_parcels'),
    assert_bft_tier_priority,
    assert_bft_landuse_A2_falls_through,
    assert_bft_landuse_AT_to_mf
  )
);

-- Priority-chain resolver: tier1 → tier0 → LightGBM → tier3b → tier4
-- LightGBM replaces tier2 (footprints) and tier3 (KNN) with a gradient-boosted
-- model trained on ~55k tier1 sales labels using 12+ features.
-- tier3b (agricultural) and tier4 (catchall) remain as safety nets.
-- built_form_key_source tracks which tier provided the final classification.
-- Also derives du_subtype and is_residential from the resolved built_form_key.

SELECT
    ap.apn,
    COALESCE(t1.built_form_key, t0.built_form_key, lgbm.built_form_key,
             t3b.built_form_key, t4.built_form_key) AS built_form_key,
    CASE
        WHEN t1.apn IS NOT NULL THEN 'tier1'
        WHEN t0.apn IS NOT NULL THEN 'tier0'
        WHEN lgbm.apn IS NOT NULL THEN 'lightgbm'
        WHEN t3b.apn IS NOT NULL THEN 'tier3b'
        WHEN t4.apn IS NOT NULL THEN 'tier4'
        ELSE NULL
    END AS built_form_key_source,
    CASE
        WHEN COALESCE(t1.built_form_key, t0.built_form_key, lgbm.built_form_key,
                      t3b.built_form_key, t4.built_form_key)
             IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
        THEN COALESCE(t1.built_form_key, t0.built_form_key, lgbm.built_form_key,
                      t3b.built_form_key, t4.built_form_key)
        ELSE NULL
    END AS du_subtype,
    CASE
        WHEN COALESCE(t1.built_form_key, t0.built_form_key, lgbm.built_form_key,
                      t3b.built_form_key, t4.built_form_key)
             IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
        THEN 1 ELSE 0
    END AS is_residential
FROM brewgis.assessor.sacog_assessor_parcels ap
LEFT JOIN brewgis.assessor.parcel_bft_tier1_sales t1 ON ap.apn = t1.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier0_landuse t0 ON ap.apn = t0.apn
LEFT JOIN brewgis.assessor.parcel_bft_lightgbm lgbm ON ap.apn = lgbm.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier3b_agricultural t3b ON ap.apn = t3b.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier4_catchall t4 ON ap.apn = t4.apn;
