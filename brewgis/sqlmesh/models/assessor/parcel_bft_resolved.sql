MODEL (
  name brewgis.assessor.parcel_bft_resolved,
  kind VIEW,
  audits (
    assert_parcel_bft_classification_row_count,
    assert_bft_tier_priority,
    assert_bft_landuse_A2_falls_through,
    assert_bft_landuse_AT_to_mf
  )
);

-- Priority-chain resolver: tier1 → tier0 → tier2 → tier3 → tier3b → tier4
-- built_form_key_source tracks which tier provided the final classification.
-- Also derives du_subtype and is_residential from the resolved built_form_key.

SELECT
    ap.apn,
    COALESCE(t1.built_form_key, t0.built_form_key, t2.built_form_key,
             t3.built_form_key, t3b.built_form_key, t4.built_form_key) AS built_form_key,
    CASE
        WHEN t1.apn IS NOT NULL THEN 'tier1'
        WHEN t0.apn IS NOT NULL THEN 'tier0'
        WHEN t2.apn IS NOT NULL THEN 'tier2'
        WHEN t3.apn IS NOT NULL THEN 'tier3'
        WHEN t3b.apn IS NOT NULL THEN 'tier3b'
        WHEN t4.apn IS NOT NULL THEN 'tier4'
        ELSE NULL
    END AS built_form_key_source,
    CASE
        WHEN COALESCE(t1.built_form_key, t0.built_form_key, t2.built_form_key,
                      t3.built_form_key, t3b.built_form_key, t4.built_form_key)
             IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
        THEN COALESCE(t1.built_form_key, t0.built_form_key, t2.built_form_key,
                      t3.built_form_key, t3b.built_form_key, t4.built_form_key)
        ELSE NULL
    END AS du_subtype,
    CASE
        WHEN COALESCE(t1.built_form_key, t0.built_form_key, t2.built_form_key,
                      t3.built_form_key, t3b.built_form_key, t4.built_form_key)
             IN ('detsf_sl','detsf_ll','attsf','mf2to4','mf5p')
        THEN 1 ELSE 0
    END AS is_residential
FROM brewgis.assessor.sacog_assessor_parcels ap
LEFT JOIN brewgis.assessor.parcel_bft_tier1_sales t1 ON ap.apn = t1.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier0_landuse t0 ON ap.apn = t0.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier2_footprints t2 ON ap.apn = t2.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier3_knn t3 ON ap.apn = t3.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier3b_agricultural t3b ON ap.apn = t3b.apn
LEFT JOIN brewgis.assessor.parcel_bft_tier4_catchall t4 ON ap.apn = t4.apn;
