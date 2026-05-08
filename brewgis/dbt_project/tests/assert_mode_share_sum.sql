{#
    Assert that mode shares sum to approximately 1.0 for every parcel.

    Mode share fractions from the multinomial logit model should sum to
    1.0 (i.e., 100%) for each parcel. Returns parcels where the sum
    deviates from 1.0 by more than the tolerance.

    Columns checked: mode_share_auto, mode_share_transit, mode_share_walk, mode_share_bike
#}

{% set tolerance = 0.01 %}

SELECT
    parcel_id,
    mode_share_auto,
    mode_share_transit,
    mode_share_walk,
    mode_share_bike,
    (COALESCE(mode_share_auto, 0)
        + COALESCE(mode_share_transit, 0)
        + COALESCE(mode_share_walk, 0)
        + COALESCE(mode_share_bike, 0)) AS mode_share_sum
FROM {{ ref('mode_choice') }}
WHERE ABS(
    COALESCE(mode_share_auto, 0)
    + COALESCE(mode_share_transit, 0)
    + COALESCE(mode_share_walk, 0)
    + COALESCE(mode_share_bike, 0)
    - 1.0
) > {{ tolerance }}
