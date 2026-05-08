"""Standalone transport model runners.

Each runner reads input from Postgres (via ``django.db.connection``),
calls the pure computation function from the corresponding dbt Python model,
and writes results back to a Postgres output table.

This avoids the cross-adapter ``dbt.ref()`` limitation: DuckDB Python models
cannot reference Postgres-based dbt models. Instead we run the same pure
functions outside dbt, then let the downstream SQL-only ``vmt`` model read
via direct Postgres table references.
"""

from brewgis.workspace.analysis.transport.mode_choice import run_mode_choice
from brewgis.workspace.analysis.transport.trip_distribution import run_trip_distribution

__all__ = [
    "run_mode_choice",
    "run_trip_distribution",
]
