MODEL (
  name brewgis.staging.wac_block,
  kind FULL,
  audits (
    not_null(columns := (geoid))
  )
);

-- LEHD LODES WAC → Block Group Employment (CBP County Scaling)
--
-- Reads CNS-split sub-sector employment from wac_block_raw and applies
-- two corrections:
--
-- 1. C000 gap distribution — LODES disclosure suppression means
--    SUM(CNS01..CNS17) < C000 for many blocks.  This distributes the
--    gap (C000 - SUM(sub-sectors)) proportionally across sub-sectors
--    so that emp = SUM(sub-sectors) before CBP scaling begins.
--
-- 2. CBP county-level scaling — Census County Business Patterns (CBP)
--    provides county-level employment totals that are not subject to
--    disclosure suppression.  When CBP total > LODES total for a
--    sub-sector, blocks are scaled up to match the CBP control total.
--    The hybrid preserve fraction keeps a portion of the original LODES
--    spatial distribution while distributing the remainder proportional
--    to total employment.
--
--    All cbp_county_* variables default to 0.0 (no scaling applied;
--    the CASE expressions are passthrough).
--
-- Aggregate columns (emp_ret, emp_off, emp_pub, emp_ind, emp_ag) and
-- total emp are recomputed from scaled sub-sectors — ensuring internal
-- consistency.

-- Compute total_sub (sum of all 17 sub-sectors pre-gap) and C000 gap.
-- The gap is C000 - SUM(sub-sectors), caused by LODES disclosure suppression
-- where a block has a C000 total but some CNS columns are suppressed to zero.
WITH raw_with_gap AS (
    SELECT
        *,
        (
            COALESCE(emp_agriculture, 0)
            + COALESCE(emp_extraction, 0)
            + COALESCE(emp_construction, 0)
            + COALESCE(emp_manufacturing, 0)
            + COALESCE(emp_transport_warehousing, 0)
            + COALESCE(emp_utilities, 0)
            + COALESCE(emp_wholesale, 0)
            + COALESCE(emp_retail_services, 0)
            + COALESCE(emp_office_services, 0)
            + COALESCE(emp_education, 0)
            + COALESCE(emp_medical_services, 0)
            + COALESCE(emp_arts_entertainment, 0)
            + COALESCE(emp_accommodation, 0)
            + COALESCE(emp_restaurant, 0)
            + COALESCE(emp_other_services, 0)
            + COALESCE(emp_public_admin, 0)
            + COALESCE(emp_military, 0)
        ) AS total_sub,
        emp - (
            COALESCE(emp_agriculture, 0)
            + COALESCE(emp_extraction, 0)
            + COALESCE(emp_construction, 0)
            + COALESCE(emp_manufacturing, 0)
            + COALESCE(emp_transport_warehousing, 0)
            + COALESCE(emp_utilities, 0)
            + COALESCE(emp_wholesale, 0)
            + COALESCE(emp_retail_services, 0)
            + COALESCE(emp_office_services, 0)
            + COALESCE(emp_education, 0)
            + COALESCE(emp_medical_services, 0)
            + COALESCE(emp_arts_entertainment, 0)
            + COALESCE(emp_accommodation, 0)
            + COALESCE(emp_restaurant, 0)
            + COALESCE(emp_other_services, 0)
            + COALESCE(emp_public_admin, 0)
            + COALESCE(emp_military, 0)
        ) AS c000_gap
    FROM brewgis.staging.wac_block_raw
),

-- Apply C000 gap distribution: when c000_gap > 0, distribute the gap across
-- all 17 sub-sectors proportional to their current values. When total_sub = 0
-- (fully suppressed block), distribute equally.
gap_distributed AS (
    SELECT
        geoid,
        geometry,
        emp,
        emp_ag,
        emp_ret,
        emp_off,
        emp_pub,
        emp_ind,
        COALESCE(emp_agriculture, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_agriculture, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_agriculture,
        COALESCE(emp_extraction, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_extraction, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_extraction,
        COALESCE(emp_construction, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_construction, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_construction,
        COALESCE(emp_manufacturing, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_manufacturing, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_manufacturing,
        COALESCE(emp_transport_warehousing, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_transport_warehousing, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_transport_warehousing,
        COALESCE(emp_utilities, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_utilities, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_utilities,
        COALESCE(emp_wholesale, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_wholesale, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_wholesale,
        COALESCE(emp_retail_services, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_retail_services, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_retail_services,
        COALESCE(emp_office_services, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_office_services, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_office_services,
        COALESCE(emp_education, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_education, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_education,
        COALESCE(emp_medical_services, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_medical_services, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_medical_services,
        COALESCE(emp_arts_entertainment, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_arts_entertainment, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_arts_entertainment,
        COALESCE(emp_accommodation, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_accommodation, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_accommodation,
        COALESCE(emp_restaurant, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_restaurant, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_restaurant,
        COALESCE(emp_other_services, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_other_services, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_other_services,
        COALESCE(emp_public_admin, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_public_admin, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_public_admin,
        COALESCE(emp_military, 0) + CASE
            WHEN c000_gap > 0 AND total_sub > 0
            THEN c000_gap * COALESCE(emp_military, 0) / total_sub
            WHEN c000_gap > 0 AND total_sub = 0
            THEN c000_gap / 17.0
            ELSE 0
        END AS emp_military
    FROM raw_with_gap
),

-- County-level LODES totals computed from gap_distributed (post-gap, pre-scaling).
-- These are the baseline against which CBP totals are compared.
county_lodes_totals AS (
    SELECT
        COALESCE(SUM(emp_agriculture), 0) AS lodes_emp_agriculture,
        COALESCE(SUM(emp_extraction), 0) AS lodes_emp_extraction,
        COALESCE(SUM(emp_construction), 0) AS lodes_emp_construction,
        COALESCE(SUM(emp_manufacturing), 0) AS lodes_emp_manufacturing,
        COALESCE(SUM(emp_transport_warehousing), 0) AS lodes_emp_transport_warehousing,
        COALESCE(SUM(emp_utilities), 0) AS lodes_emp_utilities,
        COALESCE(SUM(emp_wholesale), 0) AS lodes_emp_wholesale,
        COALESCE(SUM(emp_retail_services), 0) AS lodes_emp_retail_services,
        COALESCE(SUM(emp_office_services), 0) AS lodes_emp_office_services,
        COALESCE(SUM(emp_education), 0) AS lodes_emp_education,
        COALESCE(SUM(emp_medical_services), 0) AS lodes_emp_medical_services,
        COALESCE(SUM(emp_arts_entertainment), 0) AS lodes_emp_arts_entertainment,
        COALESCE(SUM(emp_accommodation), 0) AS lodes_emp_accommodation,
        COALESCE(SUM(emp_restaurant), 0) AS lodes_emp_restaurant,
        COALESCE(SUM(emp_other_services), 0) AS lodes_emp_other_services,
        COALESCE(SUM(emp_public_admin), 0) AS lodes_emp_public_admin,
        COALESCE(SUM(emp_military), 0) AS lodes_emp_military,
        COALESCE(SUM(emp), 0) AS total_proxy
    FROM gap_distributed
),

-- Apply CBP county-level scaling to each sub-sector.
-- CBP totals are provided via SQLMesh @VAR variables:
--   @VAR('cbp_county_emp_<sector>', 0.0) = CBP county total for each sub-sector
--   @VAR('cbp_preserve_fraction', 0.5)    = fraction of spatial distribution to preserve
--
-- Formula (per sub-sector, per the plan):
--   C = CBP county total, L = LODES county total,
--   v = block value, e = total proxy employment, T = total_proxy, p = preserve_fraction
--   - C <= L or C <= 0: v (no scaling)
--   - L > 0 and C > L: v * (C*p/L) + C*(1-p) * e/T
--   - L = 0 and C > 0 and T > 0: C * e/T
--   - T = 0: v (no data to scale against)
scaled AS (
    SELECT
        c.geoid,
        c.geometry,
        c.emp,
        CASE
            WHEN @VAR('cbp_county_emp_agriculture', 0.0) <= t.lodes_emp_agriculture OR @VAR('cbp_county_emp_agriculture', 0.0) <= 0 THEN c.emp_agriculture
            WHEN t.lodes_emp_agriculture > 0 AND @VAR('cbp_county_emp_agriculture', 0.0) > t.lodes_emp_agriculture THEN
                CASE WHEN c.emp_agriculture > 0
                    THEN c.emp_agriculture * (@VAR('cbp_county_emp_agriculture', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_agriculture)
                        + @VAR('cbp_county_emp_agriculture', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_agriculture', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_agriculture = 0 AND @VAR('cbp_county_emp_agriculture', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_agriculture', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_agriculture
        END AS emp_agriculture,
        CASE
            WHEN @VAR('cbp_county_emp_extraction', 0.0) <= t.lodes_emp_extraction OR @VAR('cbp_county_emp_extraction', 0.0) <= 0 THEN c.emp_extraction
            WHEN t.lodes_emp_extraction > 0 AND @VAR('cbp_county_emp_extraction', 0.0) > t.lodes_emp_extraction THEN
                CASE WHEN c.emp_extraction > 0
                    THEN c.emp_extraction * (@VAR('cbp_county_emp_extraction', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_extraction)
                        + @VAR('cbp_county_emp_extraction', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_extraction', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_extraction = 0 AND @VAR('cbp_county_emp_extraction', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_extraction', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_extraction
        END AS emp_extraction,
        CASE
            WHEN @VAR('cbp_county_emp_construction', 0.0) <= t.lodes_emp_construction OR @VAR('cbp_county_emp_construction', 0.0) <= 0 THEN c.emp_construction
            WHEN t.lodes_emp_construction > 0 AND @VAR('cbp_county_emp_construction', 0.0) > t.lodes_emp_construction THEN
                CASE WHEN c.emp_construction > 0
                    THEN c.emp_construction * (@VAR('cbp_county_emp_construction', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_construction)
                        + @VAR('cbp_county_emp_construction', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_construction', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_construction = 0 AND @VAR('cbp_county_emp_construction', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_construction', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_construction
        END AS emp_construction,
        CASE
            WHEN @VAR('cbp_county_emp_manufacturing', 0.0) <= t.lodes_emp_manufacturing OR @VAR('cbp_county_emp_manufacturing', 0.0) <= 0 THEN c.emp_manufacturing
            WHEN t.lodes_emp_manufacturing > 0 AND @VAR('cbp_county_emp_manufacturing', 0.0) > t.lodes_emp_manufacturing THEN
                CASE WHEN c.emp_manufacturing > 0
                    THEN c.emp_manufacturing * (@VAR('cbp_county_emp_manufacturing', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_manufacturing)
                        + @VAR('cbp_county_emp_manufacturing', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_manufacturing', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_manufacturing = 0 AND @VAR('cbp_county_emp_manufacturing', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_manufacturing', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_manufacturing
        END AS emp_manufacturing,
        CASE
            WHEN @VAR('cbp_county_emp_transport_warehousing', 0.0) <= t.lodes_emp_transport_warehousing OR @VAR('cbp_county_emp_transport_warehousing', 0.0) <= 0 THEN c.emp_transport_warehousing
            WHEN t.lodes_emp_transport_warehousing > 0 AND @VAR('cbp_county_emp_transport_warehousing', 0.0) > t.lodes_emp_transport_warehousing THEN
                CASE WHEN c.emp_transport_warehousing > 0
                    THEN c.emp_transport_warehousing * (@VAR('cbp_county_emp_transport_warehousing', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_transport_warehousing)
                        + @VAR('cbp_county_emp_transport_warehousing', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_transport_warehousing', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_transport_warehousing = 0 AND @VAR('cbp_county_emp_transport_warehousing', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_transport_warehousing', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_transport_warehousing
        END AS emp_transport_warehousing,
        CASE
            WHEN @VAR('cbp_county_emp_utilities', 0.0) <= t.lodes_emp_utilities OR @VAR('cbp_county_emp_utilities', 0.0) <= 0 THEN c.emp_utilities
            WHEN t.lodes_emp_utilities > 0 AND @VAR('cbp_county_emp_utilities', 0.0) > t.lodes_emp_utilities THEN
                CASE WHEN c.emp_utilities > 0
                    THEN c.emp_utilities * (@VAR('cbp_county_emp_utilities', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_utilities)
                        + @VAR('cbp_county_emp_utilities', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_utilities', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_utilities = 0 AND @VAR('cbp_county_emp_utilities', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_utilities', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_utilities
        END AS emp_utilities,
        CASE
            WHEN @VAR('cbp_county_emp_wholesale', 0.0) <= t.lodes_emp_wholesale OR @VAR('cbp_county_emp_wholesale', 0.0) <= 0 THEN c.emp_wholesale
            WHEN t.lodes_emp_wholesale > 0 AND @VAR('cbp_county_emp_wholesale', 0.0) > t.lodes_emp_wholesale THEN
                CASE WHEN c.emp_wholesale > 0
                    THEN c.emp_wholesale * (@VAR('cbp_county_emp_wholesale', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_wholesale)
                        + @VAR('cbp_county_emp_wholesale', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_wholesale', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_wholesale = 0 AND @VAR('cbp_county_emp_wholesale', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_wholesale', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_wholesale
        END AS emp_wholesale,
        CASE
            WHEN @VAR('cbp_county_emp_retail_services', 0.0) <= t.lodes_emp_retail_services OR @VAR('cbp_county_emp_retail_services', 0.0) <= 0 THEN c.emp_retail_services
            WHEN t.lodes_emp_retail_services > 0 AND @VAR('cbp_county_emp_retail_services', 0.0) > t.lodes_emp_retail_services THEN
                CASE WHEN c.emp_retail_services > 0
                    THEN c.emp_retail_services * (@VAR('cbp_county_emp_retail_services', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_retail_services)
                        + @VAR('cbp_county_emp_retail_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_retail_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_retail_services = 0 AND @VAR('cbp_county_emp_retail_services', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_retail_services', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_retail_services
        END AS emp_retail_services,
        CASE
            WHEN @VAR('cbp_county_emp_office_services', 0.0) <= t.lodes_emp_office_services OR @VAR('cbp_county_emp_office_services', 0.0) <= 0 THEN c.emp_office_services
            WHEN t.lodes_emp_office_services > 0 AND @VAR('cbp_county_emp_office_services', 0.0) > t.lodes_emp_office_services THEN
                CASE WHEN c.emp_office_services > 0
                    THEN c.emp_office_services * (@VAR('cbp_county_emp_office_services', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_office_services)
                        + @VAR('cbp_county_emp_office_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_office_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_office_services = 0 AND @VAR('cbp_county_emp_office_services', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_office_services', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_office_services
        END AS emp_office_services,
        CASE
            WHEN @VAR('cbp_county_emp_education', 0.0) <= t.lodes_emp_education OR @VAR('cbp_county_emp_education', 0.0) <= 0 THEN c.emp_education
            WHEN t.lodes_emp_education > 0 AND @VAR('cbp_county_emp_education', 0.0) > t.lodes_emp_education THEN
                CASE WHEN c.emp_education > 0
                    THEN c.emp_education * (@VAR('cbp_county_emp_education', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_education)
                        + @VAR('cbp_county_emp_education', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_education', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_education = 0 AND @VAR('cbp_county_emp_education', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_education', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_education
        END AS emp_education,
        CASE
            WHEN @VAR('cbp_county_emp_medical_services', 0.0) <= t.lodes_emp_medical_services OR @VAR('cbp_county_emp_medical_services', 0.0) <= 0 THEN c.emp_medical_services
            WHEN t.lodes_emp_medical_services > 0 AND @VAR('cbp_county_emp_medical_services', 0.0) > t.lodes_emp_medical_services THEN
                CASE WHEN c.emp_medical_services > 0
                    THEN c.emp_medical_services * (@VAR('cbp_county_emp_medical_services', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_medical_services)
                        + @VAR('cbp_county_emp_medical_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_medical_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_medical_services = 0 AND @VAR('cbp_county_emp_medical_services', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_medical_services', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_medical_services
        END AS emp_medical_services,
        CASE
            WHEN @VAR('cbp_county_emp_arts_entertainment', 0.0) <= t.lodes_emp_arts_entertainment OR @VAR('cbp_county_emp_arts_entertainment', 0.0) <= 0 THEN c.emp_arts_entertainment
            WHEN t.lodes_emp_arts_entertainment > 0 AND @VAR('cbp_county_emp_arts_entertainment', 0.0) > t.lodes_emp_arts_entertainment THEN
                CASE WHEN c.emp_arts_entertainment > 0
                    THEN c.emp_arts_entertainment * (@VAR('cbp_county_emp_arts_entertainment', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_arts_entertainment)
                        + @VAR('cbp_county_emp_arts_entertainment', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_arts_entertainment', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_arts_entertainment = 0 AND @VAR('cbp_county_emp_arts_entertainment', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_arts_entertainment', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_arts_entertainment
        END AS emp_arts_entertainment,
        CASE
            WHEN @VAR('cbp_county_emp_accommodation', 0.0) <= t.lodes_emp_accommodation OR @VAR('cbp_county_emp_accommodation', 0.0) <= 0 THEN c.emp_accommodation
            WHEN t.lodes_emp_accommodation > 0 AND @VAR('cbp_county_emp_accommodation', 0.0) > t.lodes_emp_accommodation THEN
                CASE WHEN c.emp_accommodation > 0
                    THEN c.emp_accommodation * (@VAR('cbp_county_emp_accommodation', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_accommodation)
                        + @VAR('cbp_county_emp_accommodation', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_accommodation', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_accommodation = 0 AND @VAR('cbp_county_emp_accommodation', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_accommodation', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_accommodation
        END AS emp_accommodation,
        CASE
            WHEN @VAR('cbp_county_emp_restaurant', 0.0) <= t.lodes_emp_restaurant OR @VAR('cbp_county_emp_restaurant', 0.0) <= 0 THEN c.emp_restaurant
            WHEN t.lodes_emp_restaurant > 0 AND @VAR('cbp_county_emp_restaurant', 0.0) > t.lodes_emp_restaurant THEN
                CASE WHEN c.emp_restaurant > 0
                    THEN c.emp_restaurant * (@VAR('cbp_county_emp_restaurant', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_restaurant)
                        + @VAR('cbp_county_emp_restaurant', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_restaurant', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_restaurant = 0 AND @VAR('cbp_county_emp_restaurant', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_restaurant', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_restaurant
        END AS emp_restaurant,
        CASE
            WHEN @VAR('cbp_county_emp_other_services', 0.0) <= t.lodes_emp_other_services OR @VAR('cbp_county_emp_other_services', 0.0) <= 0 THEN c.emp_other_services
            WHEN t.lodes_emp_other_services > 0 AND @VAR('cbp_county_emp_other_services', 0.0) > t.lodes_emp_other_services THEN
                CASE WHEN c.emp_other_services > 0
                    THEN c.emp_other_services * (@VAR('cbp_county_emp_other_services', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_other_services)
                        + @VAR('cbp_county_emp_other_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_other_services', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_other_services = 0 AND @VAR('cbp_county_emp_other_services', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_other_services', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_other_services
        END AS emp_other_services,
        CASE
            WHEN @VAR('cbp_county_emp_public_admin', 0.0) <= t.lodes_emp_public_admin OR @VAR('cbp_county_emp_public_admin', 0.0) <= 0 THEN c.emp_public_admin
            WHEN t.lodes_emp_public_admin > 0 AND @VAR('cbp_county_emp_public_admin', 0.0) > t.lodes_emp_public_admin THEN
                CASE WHEN c.emp_public_admin > 0
                    THEN c.emp_public_admin * (@VAR('cbp_county_emp_public_admin', 0.0) * @VAR('cbp_preserve_fraction', 0.5) / t.lodes_emp_public_admin)
                        + @VAR('cbp_county_emp_public_admin', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                    ELSE @VAR('cbp_county_emp_public_admin', 0.0) * (1.0 - @VAR('cbp_preserve_fraction', 0.5)) * c.emp / t.total_proxy
                END
            WHEN t.lodes_emp_public_admin = 0 AND @VAR('cbp_county_emp_public_admin', 0.0) > 0 AND t.total_proxy > 0
            THEN @VAR('cbp_county_emp_public_admin', 0.0) * c.emp / t.total_proxy
            ELSE c.emp_public_admin
        END AS emp_public_admin,
        c.emp_military AS emp_military,
        c.emp_ag,
        c.emp_ret,
        c.emp_off,
        c.emp_pub,
        c.emp_ind,
        t.total_proxy
    FROM gap_distributed c
    CROSS JOIN county_lodes_totals t
)

-- Final output: recompute all aggregate columns from scaled sub-sectors
-- to ensure internal consistency. emp is the sum of all 17 sub-sectors.
SELECT
    geoid,
    geometry,
    -- Total employment: sum of all 17 scaled sub-sectors
    (
        COALESCE(emp_agriculture, 0)
        + COALESCE(emp_extraction, 0)
        + COALESCE(emp_construction, 0)
        + COALESCE(emp_manufacturing, 0)
        + COALESCE(emp_transport_warehousing, 0)
        + COALESCE(emp_utilities, 0)
        + COALESCE(emp_wholesale, 0)
        + COALESCE(emp_retail_services, 0)
        + COALESCE(emp_office_services, 0)
        + COALESCE(emp_education, 0)
        + COALESCE(emp_medical_services, 0)
        + COALESCE(emp_arts_entertainment, 0)
        + COALESCE(emp_accommodation, 0)
        + COALESCE(emp_restaurant, 0)
        + COALESCE(emp_other_services, 0)
        + COALESCE(emp_public_admin, 0)
        + COALESCE(emp_military, 0)
    ) AS emp,
    -- Sub-sectors (scaled)
    emp_agriculture,
    emp_extraction,
    emp_construction,
    emp_manufacturing,
    emp_transport_warehousing,
    emp_utilities,
    emp_wholesale,
    emp_retail_services,
    emp_office_services,
    emp_education,
    emp_medical_services,
    emp_arts_entertainment,
    emp_accommodation,
    emp_restaurant,
    emp_other_services,
    emp_public_admin,
    emp_military,
    -- Aggregate columns recomputed from scaled sub-sectors
    (
        COALESCE(emp_retail_services, 0)
        + COALESCE(emp_restaurant, 0)
        + COALESCE(emp_accommodation, 0)
        + COALESCE(emp_arts_entertainment, 0)
        + COALESCE(emp_other_services, 0)
    ) AS emp_ret,
    (
        COALESCE(emp_office_services, 0)
        + COALESCE(emp_medical_services, 0)
    ) AS emp_off,
    (
        COALESCE(emp_education, 0)
        + COALESCE(emp_public_admin, 0)
    ) AS emp_pub,
    (
        COALESCE(emp_manufacturing, 0)
        + COALESCE(emp_wholesale, 0)
        + COALESCE(emp_transport_warehousing, 0)
        + COALESCE(emp_utilities, 0)
        + COALESCE(emp_construction, 0)
        + COALESCE(emp_extraction, 0)
        + COALESCE(emp_agriculture, 0)
    ) AS emp_ind,
    COALESCE(emp_agriculture, 0) AS emp_ag
FROM scaled;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_wac_block_geometry
  ON brewgis.staging.wac_block USING GIST (geometry)
);
