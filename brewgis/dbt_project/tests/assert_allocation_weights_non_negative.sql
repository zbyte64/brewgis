{#
    Assert that allocation weights are in [0, 1].

    Allocation weights represent the fraction of source area intersecting
    a target feature and must be between 0 (exclusive, filtered) and 1
    (inclusive — source fully contained within target).

    Returns rows where weight is outside the valid range.
#}

SELECT
    source_id,
    target_id,
    weight
FROM {{ ref('allocation_factors') }}
WHERE weight < 0 OR weight > 1.0001
