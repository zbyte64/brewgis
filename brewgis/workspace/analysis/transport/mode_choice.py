"""Standalone multinomial logit mode choice runner.

Replicates the ``model(dbt, session)`` function from ``brewgis/dbt_project/models/mode_choice.py``
but reads/writes Postgres directly via ``django.db.connection`` — no dbt involved.

Data flow:
    1. Read trip_distribution + end_state from Postgres
    2. Compute density, transit_access, log-density from D-variables
    3. Call ``_multinomial_logit()`` (the pure function shared with the dbt model)
    4. Write results to ``{schema}.mode_choice_{scenario_id}`` via ``cursor.executemany``
"""

from __future__ import annotations

import logging

import numpy as np
from django.db import connection

from brewgis.dbt_project.models.mode_choice import _multinomial_logit

logger = logging.getLogger(__name__)

# Default column names derived from dbt model output
OUTPUT_COLUMNS = (
    "parcel_id",
    "trips_auto",
    "trips_transit",
    "trips_walk",
    "trips_bike",
)


def run_mode_choice(  # noqa: PLR0913 — all params are configurable logit coefficients
    schema: str,
    scenario_id: str,
    *,
    asc_transit: float = -2.0,
    asc_walk: float = -1.5,
    asc_bike: float = -2.5,
    beta_density: float = 0.15,
    beta_design_walk: float = 0.05,
    beta_transit_dist: float = 0.02,
) -> int:
    """Run multinomial logit mode split.

    Reads: ``{schema}.trip_distribution_{scenario_id}``
    Writes: ``{schema}.mode_choice_{scenario_id}``

    Args:
        schema: Database schema name (e.g. ``sacog_demo``).
        scenario_id: Scenario identifier (e.g. ``base``).
        asc_transit: ASC for transit (default -2.0).
        asc_walk: ASC for walk (default -1.5).
        asc_bike: ASC for bike (default -2.5).
        beta_density: Coefficient for ln(density) in utility (default 0.15).
        beta_design_walk: Coefficient for intersection density in walk/bike (default 0.05).
        beta_transit_dist: Coefficient for transit access (default 0.02).

    Returns:
        Number of rows written.
    """
    trip_dist_table = f"{schema}.trip_distribution_{scenario_id}"
    end_state_table = f"{schema}.end_state_{scenario_id}"
    output_table = f"{schema}.mode_choice_{scenario_id}"

    # Read input data
    query = f"""
        SELECT
            td.parcel_id,
            td.trips_outbound,
            COALESCE(es.dwelling_units_total, 0.0) AS dwelling_units_total,
            COALESCE(es.gross_acres, 0.0) AS gross_acres,
            COALESCE(es.land_dev_category, '') AS land_dev_category,
            COALESCE(es.intersection_density, 0.0) AS intersection_density
        FROM {trip_dist_table} td
        LEFT JOIN {end_state_table} es ON td.parcel_id = es.parcel_id
    """  # noqa: S608 — schema/table names from controlled constants

    with connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()

    if not rows:
        logger.warning("No rows returned from %s", trip_dist_table)
        _create_empty_output(schema, scenario_id)
        return 0

    # Unpack into numpy arrays
    parcel_ids = np.array([r[0] for r in rows], dtype=np.int64)
    trips_outbound = np.array([r[1] for r in rows], dtype=float)
    du = np.array([r[2] for r in rows], dtype=float)
    gross_acres = np.array([r[3] for r in rows], dtype=float)
    land_dev_category = np.array([r[4] for r in rows], dtype=object)
    intersection_density = np.array([r[5] for r in rows], dtype=float)

    # Compute density (du/acre), guard against zero acres
    density = np.where(gross_acres > 0, du / gross_acres, 0.0)

    # Transit access proxy: urban/compact areas have transit
    urban_compact = np.isin(land_dev_category, ["urban", "compact"])
    transit_access = np.where(urban_compact, 1.0, 0.0)

    # Log-transformed density: ln(density + 1) to handle zero density
    ln_density = np.log(density + 1.0)

    logger.info(
        "Running multinomial logit on %d parcels (asc_t=%s, asc_w=%s, asc_b=%s)",
        len(parcel_ids),
        asc_transit,
        asc_walk,
        asc_bike,
    )

    # Run the pure multinomial logit function
    ta, tt, tw, tb, *_ = _multinomial_logit(
        trips_outbound=trips_outbound,
        ln_density=ln_density,
        intersection_density=intersection_density,
        transit_access=transit_access,
        asc_transit=asc_transit,
        asc_walk=asc_walk,
        asc_bike=asc_bike,
        beta_density=beta_density,
        beta_design_walk=beta_design_walk,
        beta_transit_dist=beta_transit_dist,
    )

    # Write results to Postgres
    _create_output_table(schema, scenario_id)

    data = [
        (int(pid), float(t_auto), float(t_transit), float(t_walk), float(t_bike))
        for pid, t_auto, t_transit, t_walk, t_bike in zip(
            parcel_ids, ta, tt, tw, tb, strict=True
        )
    ]

    columns = ", ".join(OUTPUT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(OUTPUT_COLUMNS))
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {output_table} ({columns}) VALUES ({placeholders})",  # noqa: S608
            data,
        )

    row_count = len(data)
    logger.info("Wrote %d rows to %s", row_count, output_table)
    return row_count


def _create_output_table(schema: str, scenario_id: str) -> None:
    """Create the output table if it does not exist (will be truncated if it does)."""
    output_table = f"{schema}.mode_choice_{scenario_id}"
    cols = (
        "parcel_id BIGINT PRIMARY KEY, "
        "trips_auto DOUBLE PRECISION NOT NULL DEFAULT 0.0, "
        "trips_transit DOUBLE PRECISION NOT NULL DEFAULT 0.0, "
        "trips_walk DOUBLE PRECISION NOT NULL DEFAULT 0.0, "
        "trips_bike DOUBLE PRECISION NOT NULL DEFAULT 0.0"
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {output_table} ({cols})")
        cursor.execute(f"TRUNCATE {output_table}")


def _create_empty_output(schema: str, scenario_id: str) -> None:
    """Create an empty output table when there is no input data."""
    _create_output_table(schema, scenario_id)
