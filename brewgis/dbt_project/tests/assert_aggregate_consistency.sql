{#
    Assert that aggregate employment columns equal the sum of their sub-sectors.

    For each row in base_canvas_employment, verifies:
    - emp_ret = emp_retail_services + emp_restaurant + emp_accommodation + emp_arts_entertainment + emp_other_services
    - emp_off = emp_office_services + emp_medical_services
    - emp_pub = emp_public_admin + emp_education
    - emp_ind = emp_manufacturing + emp_wholesale + emp_transport_warehousing + emp_utilities + emp_construction + emp_agriculture + emp_extraction
    - emp_ag  = emp_agriculture

    May fail because: aggregate columns come directly from wac_block (via
    area-weighted allocation) while sub-sectors are independently allocated.
    Rounding and the ClipByBox2D area approximation can cause column-level drift.
#}

SELECT
    parcel_id,
    emp_ret,
    COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0)
        + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0)
        + COALESCE(emp_other_services, 0) AS emp_ret_sum,
    emp_off,
    COALESCE(emp_office_services, 0) + COALESCE(emp_medical_services, 0) AS emp_off_sum,
    emp_pub,
    COALESCE(emp_public_admin, 0) + COALESCE(emp_education, 0) AS emp_pub_sum,
    emp_ind,
    COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
        + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
        + COALESCE(emp_construction, 0) + COALESCE(emp_agriculture, 0)
        + COALESCE(emp_extraction, 0) AS emp_ind_sum,
    emp_ag,
    COALESCE(emp_agriculture, 0) AS emp_ag_sum
FROM {{ ref('base_canvas_employment') }}
WHERE
    ABS(emp_ret - (COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0)
        + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0)
        + COALESCE(emp_other_services, 0))) > 0.5
    OR ABS(emp_off - (COALESCE(emp_office_services, 0) + COALESCE(emp_medical_services, 0))) > 0.5
    OR ABS(emp_pub - (COALESCE(emp_public_admin, 0) + COALESCE(emp_education, 0))) > 0.5
    OR ABS(emp_ind - (COALESCE(emp_manufacturing, 0) + COALESCE(emp_wholesale, 0)
        + COALESCE(emp_transport_warehousing, 0) + COALESCE(emp_utilities, 0)
        + COALESCE(emp_construction, 0) + COALESCE(emp_agriculture, 0)
        + COALESCE(emp_extraction, 0))) > 0.5
    OR ABS(emp_ag - COALESCE(emp_agriculture, 0)) > 0.5
