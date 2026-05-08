{#
    Assert that total trips are conserved through the trip distribution step.

    The gravity model distributes trips from each origin to all destinations.
    The sum of trips_outbound across all parcels should approximately equal
    the sum of trips_inbound across all parcels (trip conservation principle).
    Additionally, the total trips_internal should not exceed total trips
    outbound/inbound.

    Uses a tolerance of 1% to account for floating-point accumulation.
#}

{% set tolerance = 0.01 %}

WITH trip_totals AS (
    SELECT
        SUM(trips_outbound) AS total_outbound,
        SUM(trips_inbound) AS total_inbound,
        SUM(trips_internal) AS total_internal
    FROM {{ ref('trip_distribution') }}
),

trip_gen_totals AS (
    SELECT SUM(trips_total) AS total_trips_gen
    FROM {{ ref('trip_generation') }}
)

SELECT
    tt.*,
    tg.total_trips_gen,
    ABS(tt.total_outbound - tt.total_inbound) AS outbound_inbound_diff,
    ABS(1.0 - (tt.total_outbound + tt.total_internal) / NULLIF(tg.total_trips_gen, 0)) AS conservation_ratio
FROM trip_totals tt
CROSS JOIN trip_gen_totals tg
WHERE
    -- Outbound and inbound totals must substantially agree
    ABS(tt.total_outbound - tt.total_inbound) / NULLIF(GREATEST(tt.total_outbound, tt.total_inbound), 0) > {{ tolerance }}
    -- Outbound + internal should approximately equal total trip generation
    OR (tg.total_trips_gen > 0
        AND ABS(1.0 - (tt.total_outbound + tt.total_internal) / tg.total_trips_gen) > {{ tolerance }})
    -- Inbound + internal should approximately equal total trip generation
    OR (tg.total_trips_gen > 0
        AND ABS(1.0 - (tt.total_inbound + tt.total_internal) / tg.total_trips_gen) > {{ tolerance }})
