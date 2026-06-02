from __future__ import annotations

from sqlmesh import macro


@macro()
def test_non_negative(evaluator, model: str, column_name: str) -> str:
    """Assert that a column contains only non-negative values.

    Returns SQL that selects rows where column < 0 (violations).

    Note: These are defined as macros for backward compat with dbt-style
    references. They will be superseded by inline SQLMesh audits.

    Args:
        model: Table or subquery to test.
        column_name: Column to check for negative values.

    Returns:
        SQL query selecting violating rows.
    """
    return f"""
SELECT *
FROM {model}
WHERE {column_name} < 0
"""


@macro()
def test_proportion_sum(evaluator, model: str, columns, tolerance: str = "0.01") -> str:
    """Assert that proportion columns sum to approximately 1.0 per row.

    Each row's non-null columns are summed; rows whose total differs from
    1.0 by more than tolerance are returned as violations.

    Usage in model SQL::

        @test_proportion_sum('ref_model', 'share_a,share_b,share_c', 0.01)

    When called from Python code, pass columns as a list of strings.

    Args:
        model: Table or subquery to test.
        columns: List of proportion column names (Python list or comma-separated string).
        tolerance: Maximum allowed deviation from 1.0 (default: 0.01).

    Returns:
        SQL query selecting violating rows.
    """
    if isinstance(columns, str):
        columns = [c.strip() for c in columns.split(",")]
    sum_expr = "0" + "".join(f" + COALESCE({c}, 0)" for c in columns)
    return f"""
SELECT *
FROM (
    SELECT *,
        ({sum_expr}) AS _total
    FROM {model}
) t
WHERE abs(_total - 1.0) > {tolerance}
"""


@macro()
def test_acres_consumed_le_gross(evaluator, model: str) -> str:
    """Assert that acres_consumed does not exceed area_gross in land consumption models.

    Returns SQL that selects rows where acres_consumed > gross_acres (violations).

    Args:
        model: Table or subquery to test.

    Returns:
        SQL query selecting violating rows.
    """
    return f"""
SELECT *
FROM {model}
WHERE acres_consumed > gross_acres
"""


@macro()
def test_column_between(
    evaluator, model: str, column_name: str, min_value: str, max_value: str
) -> str:
    """Assert that a column falls within the specified inclusive range.

    Returns SQL that selects rows where column < min_value or column > max_value.

    Usage::

        @test_column_between('env_constraint', 'developable_proportion', '0', '1')

    Args:
        model: Table or subquery to test.
        column_name: Column to check.
        min_value: Minimum inclusive bound.
        max_value: Maximum inclusive bound.

    Returns:
        SQL query selecting violating rows.
    """
    return f"""
SELECT *
FROM {model}
WHERE {column_name} < {min_value} OR {column_name} > {max_value}
"""
