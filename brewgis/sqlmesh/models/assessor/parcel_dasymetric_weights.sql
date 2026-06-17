MODEL (
  name brewgis.assessor.parcel_dasymetric_weights,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_parcel_dasymetric_weights_row_count
  )
);

-- Dasymetric Weights — per-parcel built_form_key, weights, and classification.
WITH assessor_parcels AS (
    SELECT
        apn,
        geometry,
        COALESCE(NULLIF(lot_size_acres, 0), 0.01) AS lot_size_acres,
        landuse
    FROM brewgis.assessor.sacog_assessor_parcels
),

sacog_category AS (
    SELECT
        apn,
        CASE
            WHEN landuse IS NULL OR landuse = '' THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'A' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'B' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'C' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'D' THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'E' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'F' THEN 'agricultural'
            WHEN LEFT(landuse, 1) = 'G' THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'H' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'I' THEN 'industrial'
            WHEN LEFT(landuse, 2) IN ('MP', 'MR', 'MW', 'MD', 'MF', 'MG', 'ML') THEN 'undeveloped'
            WHEN LEFT(landuse, 1) = 'M' THEN 'urban'
            WHEN LEFT(landuse, 1) = 'W' THEN 'undeveloped'
            ELSE 'undeveloped'
        END AS land_development_category
    FROM assessor_parcels
),

classified AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        COALESCE(auc.category, sc.land_development_category, 'urban') AS land_development_category
    FROM assessor_parcels ap
    LEFT JOIN brewgis.seeds.assessor_use_codes auc
        ON LEFT(COALESCE(ap.landuse::text, ''), 2) = auc.use_code::text
    LEFT JOIN sacog_category sc ON ap.apn = sc.apn
),

sales_data AS (
    SELECT
        apn,
        living_area AS actual_living_sqft,
        building_sf AS actual_building_sqft,
        property_type,
        lot_size_acres AS sales_lot_size_acres,
        units,
        ROW_NUMBER() OVER (
            PARTITION BY apn
            ORDER BY
                CASE
                    WHEN living_area IS NOT NULL AND building_sf IS NOT NULL AND units IS NOT NULL THEN 0
                    WHEN living_area IS NOT NULL THEN 1
                    WHEN building_sf IS NOT NULL THEN 2
                    ELSE 3
                END,
                year_built DESC NULLS LAST
        ) AS rn
    FROM public.sacog_assessor_sales_raw
    WHERE living_area IS NOT NULL OR building_sf IS NOT NULL
),

deduped_sales AS (
    SELECT * FROM sales_data WHERE rn = 1
),

building_sqft AS (
    SELECT
        apn,
        residential_building_sqft,
        commercial_building_sqft,
        industrial_building_sqft,
        other_building_sqft,
        total_footprint_sqft,
        building_count,
        footprint_ratio,
        max_levels
    FROM brewgis.assessor.parcel_building_sqft_by_type
),

int_density AS (
    SELECT
        apn,
        intersection_density
    FROM brewgis.assessor.overture_intersection_density
),

tier1_built_form_key AS (
    SELECT
        apn,
        CASE
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, 0) < 0.15 THEN 'detsf_sl'
            WHEN (property_type IN ('SFR', 'Single Family Residence') OR property_type LIKE 'Single Family%')
                AND COALESCE(sales_lot_size_acres, 0) >= 0.15 THEN 'detsf_ll'
            WHEN property_type IN ('Condo', 'Condominium') THEN 'attsf'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
            WHEN (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
                AND COALESCE(units, 0) >= 5 THEN 'mf5p'
            WHEN (property_type IN ('Commercial', 'Retail', 'Office', 'Restaurant', 'Hotel', 'Medical',
                  'Retail/Commercial', 'Commercial/Office')) THEN 'commercial'
            WHEN (property_type IN ('Industrial', 'Manufacturing', 'Warehouse', 'Industrial/Manufacturing',
                  'Transport/Warehouse', 'Construction')) THEN 'industrial'
            WHEN (property_type IN ('Agricultural', 'Farm/Ranch', 'Vacant Agricultural')) THEN 'agricultural'
            WHEN (property_type IN ('Civic', 'Institutional', 'Church', 'School', 'Government', 'Education',
                  'Public', 'Hospital', 'Medical Facility'))
                OR property_type LIKE '%Church%' OR property_type LIKE '%School%'
                OR property_type LIKE '%Government%' THEN 'civic'
            ELSE NULL
        END AS built_form_key,
        property_type,
        units,
        sales_lot_size_acres
    FROM deduped_sales
),

tier2_built_form_key AS (
    SELECT DISTINCT ON (ap.apn)
        ap.apn,
        CASE
            WHEN bs.residential_building_sqft > 0
                 AND COALESCE(bs.max_levels, 1) < 3 THEN 'detsf_sl'
            WHEN bs.residential_building_sqft > 0
                 AND COALESCE(bs.max_levels, 1) >= 3 THEN 'mf5p'
            WHEN bs.commercial_building_sqft > 0 THEN 'commercial'
            WHEN bs.industrial_building_sqft > 0 THEN 'industrial'
            WHEN bs.other_building_sqft > 0 THEN 'civic'
            ELSE NULL
        END AS built_form_key
    FROM assessor_parcels ap
    JOIN building_sqft bs ON ap.apn = bs.apn
    WHERE bs.total_footprint_sqft > 0
      AND NOT EXISTS (SELECT 1 FROM tier1_built_form_key t1 WHERE t1.apn = ap.apn AND t1.built_form_key IS NOT NULL)
),

known_parcels AS (
    SELECT
        t1.apn,
        p.geometry,
        p.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        COALESCE(id.intersection_density, 0) AS intersection_density,
        t1.built_form_key,
        cl.land_development_category
    FROM tier1_built_form_key t1
    JOIN assessor_parcels p ON t1.apn = p.apn
    LEFT JOIN building_sqft bs ON t1.apn = bs.apn
    LEFT JOIN int_density id ON t1.apn = id.apn
    LEFT JOIN classified cl ON t1.apn = cl.apn
    WHERE t1.built_form_key IS NOT NULL
      AND t1.built_form_key IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p', 'commercial', 'industrial')
),

unknown_parcels AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
        COALESCE(id.intersection_density, 0) AS intersection_density,
        t2.built_form_key AS t2_bft,
        cl.land_development_category
    FROM assessor_parcels ap
    LEFT JOIN building_sqft bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    LEFT JOIN classified cl ON ap.apn = cl.apn
    LEFT JOIN tier2_built_form_key t2 ON ap.apn = t2.apn
    WHERE NOT EXISTS (SELECT 1 FROM tier1_built_form_key t1 WHERE t1.apn = ap.apn AND t1.built_form_key IS NOT NULL)
),

partition_stats AS (
    SELECT
        COALESCE(k.land_development_category, '') AS land_development_category,
        STDDEV_POP(k.intersection_density) AS s_int_dens,
        STDDEV_POP(k.lot_size_acres) AS s_ls,
        STDDEV_POP(k.footprint_ratio) AS s_fr,
        AVG(k.intersection_density) AS m_int_dens,
        AVG(k.lot_size_acres) AS m_ls,
        AVG(k.footprint_ratio) AS m_fr
    FROM known_parcels k
    GROUP BY k.land_development_category
),

tier3_candidates AS (
    SELECT
        u.apn,
        k.apn AS neighbor_apn,
        k.built_form_key,
        POWER(COALESCE((u.intersection_density - k.intersection_density) / NULLIF(ps.s_int_dens, 0), 0), 2)
            + POWER(COALESCE((u.lot_size_acres - k.lot_size_acres) / NULLIF(ps.s_ls, 0), 0), 2)
            + POWER(COALESCE((u.footprint_ratio - k.footprint_ratio) / NULLIF(ps.s_fr, 0), 0), 2)
            AS distance_sq
    FROM unknown_parcels u
    JOIN known_parcels k
        ON u.land_development_category = k.land_development_category
    LEFT JOIN partition_stats ps
        ON COALESCE(u.land_development_category, '') = ps.land_development_category
    WHERE u.t2_bft IS NULL
),

tier3_ranked AS (
    SELECT
        u.apn,
        u.neighbor_apn,
        u.built_form_key,
        u.distance_sq,
        ROW_NUMBER() OVER (
            PARTITION BY u.apn ORDER BY u.distance_sq
        ) AS rn
    FROM tier3_candidates u
),

tier3_built_form_key AS (
    SELECT
        apn,
        MODE() WITHIN GROUP (ORDER BY built_form_key) AS built_form_key
    FROM tier3_ranked
    WHERE rn <= 5
      AND distance_sq IS NOT NULL
    GROUP BY apn
),

tier4_built_form_key AS (
    SELECT
        u.apn,
        CASE
            WHEN u.lot_size_acres > 3.0 THEN
                CASE (u.apn::bigint % 2)
                    WHEN 0 THEN 'commercial'
                    WHEN 1 THEN 'civic'
                END
            WHEN u.lot_size_acres > 1.5 THEN 'commercial'
            WHEN u.lot_size_acres > 0.4 THEN 'detsf_ll'
            WHEN u.lot_size_acres > 0.15 THEN 'detsf_sl'
            ELSE
                CASE (u.apn::bigint % 2)
                    WHEN 0 THEN 'mf2to4'
                    WHEN 1 THEN 'attsf'
                END
        END AS built_form_key
    FROM unknown_parcels u
    WHERE u.t2_bft IS NULL
      AND NOT EXISTS (SELECT 1 FROM tier3_built_form_key t3 WHERE t3.apn = u.apn)
),

final_built_form_key AS (
    SELECT apn, built_form_key AS bft
    FROM tier1_built_form_key WHERE built_form_key IS NOT NULL
    UNION ALL
    SELECT apn, built_form_key FROM tier2_built_form_key WHERE built_form_key IS NOT NULL
    UNION ALL
    SELECT apn, built_form_key FROM tier3_built_form_key WHERE built_form_key IS NOT NULL
    UNION ALL
    SELECT apn, built_form_key FROM tier4_built_form_key WHERE built_form_key IS NOT NULL
),

du_subtype_from_bft AS (
    SELECT
        apn,
        CASE
            WHEN bft IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p') THEN bft
            ELSE NULL
        END AS du_subtype,
        CASE WHEN bft IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p') THEN 1 ELSE 0 END AS is_residential
    FROM final_built_form_key
),

auth_res_area AS (
    SELECT apn, authoritative_residential_sqft, authoritative_non_residential_sqft
    FROM brewgis.assessor.authoritative_residential_area
),

nlcd_join AS (
    SELECT
        apn,
        MAX(impervious_fraction) AS impervious_fraction
    FROM (
        SELECT
            ap.apn,
            nlcd.impervious_fraction,
            ROW_NUMBER() OVER (
                PARTITION BY ap.apn
                ORDER BY ST_Area(ST_Intersection(ST_Envelope(ap.geometry), ST_Envelope(sp.geometry))) DESC NULLS LAST
            ) AS rn
        FROM assessor_parcels ap
        LEFT JOIN brewgis.comparison.sacog_parcel_shim sp
            ON ST_Intersects(ap.geometry, sp.geometry)
        LEFT JOIN brewgis.nlcd.nlcd_parcel_stats nlcd
            ON sp.parcel_id = nlcd.parcel_id
    ) ranked
    WHERE rn = 1
    GROUP BY apn
),

final_select AS (
    SELECT
        ap.apn,
        ap.geometry,
        ap.lot_size_acres,
        COALESCE(cl.land_development_category, 'urban') AS land_development_category,
        bft.bft AS built_form_key,
        du.du_subtype,
        du.is_residential,
        COALESCE(sd.actual_living_sqft, 0)::double precision AS actual_living_sqft,
        COALESCE(sd.actual_building_sqft, 0)::double precision AS actual_building_sqft,
        COALESCE(bs.residential_building_sqft, 0)::double precision AS residential_building_sqft,
        COALESCE(bs.commercial_building_sqft, 0)::double precision AS commercial_building_sqft,
        COALESCE(bs.industrial_building_sqft, 0)::double precision AS industrial_building_sqft,
        COALESCE(bs.other_building_sqft, 0)::double precision AS other_building_sqft,
        COALESCE(bs.total_footprint_sqft, 0)::double precision AS total_footprint_sqft,
        COALESCE(bs.building_count, 0)::integer AS building_count,
        COALESCE(bs.footprint_ratio, 0)::double precision AS footprint_ratio,
        COALESCE(bs.max_levels, 0)::integer AS max_levels,
        COALESCE(id.intersection_density, 0)::double precision AS intersection_density,
        COALESCE(nj.impervious_fraction, 0.0)::double precision AS impervious_fraction,
        COALESCE(
            ar.authoritative_residential_sqft,
            bs.residential_building_sqft,
            ap.lot_size_acres * COALESCE(nj.impervious_fraction, 1.0) * 43560 * 0.3,
            ap.lot_size_acres * 43560 * 0.15
        ) AS pop_dasym_weight,
        COALESCE(
            ar.authoritative_non_residential_sqft,
            bs.commercial_building_sqft + bs.industrial_building_sqft + bs.other_building_sqft,
            ap.lot_size_acres * COALESCE(nj.impervious_fraction, 1.0) * 43560 * 0.5,
            ap.lot_size_acres * 43560 * 0.1
        ) * (1.0 + COALESCE(id.intersection_density, 0.0) / 200.0) AS emp_dasym_weight
    FROM assessor_parcels ap
    LEFT JOIN classified cl ON ap.apn = cl.apn
    LEFT JOIN final_built_form_key bft ON ap.apn = bft.apn
    LEFT JOIN du_subtype_from_bft du ON ap.apn = du.apn
    LEFT JOIN deduped_sales sd ON ap.apn = sd.apn
    LEFT JOIN building_sqft bs ON ap.apn = bs.apn
    LEFT JOIN int_density id ON ap.apn = id.apn
    LEFT JOIN nlcd_join nj ON ap.apn = nj.apn
    LEFT JOIN auth_res_area ar ON ap.apn = ar.apn
)

SELECT
    f.apn,
    f.geometry,
    f.lot_size_acres,
    f.land_development_category,
    f.built_form_key,
    f.du_subtype,
    f.is_residential,
    f.actual_living_sqft,
    f.actual_building_sqft,
    f.residential_building_sqft,
    f.commercial_building_sqft,
    f.industrial_building_sqft,
    f.other_building_sqft,
    f.total_footprint_sqft,
    f.building_count,
    f.footprint_ratio,
    f.max_levels,
    f.intersection_density,
    f.impervious_fraction,
    f.pop_dasym_weight,
    f.emp_dasym_weight
FROM final_select f;
