"""Transport preprocessors — build input tables consumed by dbt models.

Preprocessors run outside dbt as Celery tasks before the corresponding
dbt module executes. They write to well-known table names following the
convention::

    {target_schema}.{module}_inputs_{scenario_id}

Examples:
    - ``trip_distribution_inputs_42`` — OD distance matrix for T2
    - ``transit_access_inputs_42`` — Transit proximity for T3

All preprocessors are idempotent: they ``DROP`` and recreate their output
table on each run, and scenario teardown drops them via the scenario
cleanup lifecycle.
"""

from brewgis.workspace.analysis.transport.preprocessors.distance_matrix import (
    DistanceMatrixPreprocessor,
)

__all__ = [
    "DistanceMatrixPreprocessor",
]
