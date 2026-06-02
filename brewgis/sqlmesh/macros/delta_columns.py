from __future__ import annotations

from sqlmesh import macro


@macro()
def delta_columns(
    evaluator,
    column_names,
    end_alias: str = "es",
    base_alias: str = "b",
    default: float = 0.0,
) -> str:
    """Compute COALESCE(end_col, default) - COALESCE(base_col, default) for each column.

    Used by increment models to replace repeated COALESCE diff patterns.

    When called from Python code, column_names is a list of strings.
    When called from SQL model files via @delta_columns, pass columns
    as a comma-separated string::

        @delta_columns('population,households,du,emp', 'es', 'b', 0.0)

    Produces::

        COALESCE(es.population, 0.0) - COALESCE(b.population, 0.0) AS population,
        COALESCE(es.households, 0.0) - COALESCE(b.households, 0.0) AS households,
        ...

    Args:
        column_names: List of column names (Python list or comma-separated string).
        end_alias: Table alias for end-state values (default: es).
        base_alias: Table alias for base values (default: b).
        default: Default value for COALESCE (default: 0.0).

    Returns:
        Comma-separated SQL expressions for SELECT clause.
    """
    if isinstance(column_names, str):
        column_names = [c.strip() for c in column_names.split(",")]
    parts = []
    for col in column_names:
        parts.append(
            f"COALESCE({end_alias}.{col}, {default}) - COALESCE({base_alias}.{col}, {default}) AS {col}"
        )
    return ",\n    ".join(parts)
