{#
    Assert that sacog_summary contains exactly one row.

    The sacog_summary view is built from a CROSS JOIN of four single-row
    models (reference_totals, brewgis_totals, correlations, weighted_means).
    Any data issue causing zero or multiple rows in any component model
    would propagate as zero or unexpected row counts. This test catches
    such failures.
#}

SELECT
    COUNT(*) AS row_count,
    'sacog_summary must have exactly 1 row, found ' || COUNT(*) AS failure_message
FROM {{ ref('sacog_summary') }}
HAVING COUNT(*) != 1;
