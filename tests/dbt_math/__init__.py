# ruff: noqa: ANN201
"""Property-based tests for SQL model math — pure reference + SQL parity.

Each SQLMesh model with compound formulas gets:

1. A pure Python reference function (``tests/dbt_math/reference.py``) that
   mirrors the exact SQL formula. Decorated with ``@deal.pre``/``@deal.post``
   to document and enforce mathematical invariants.

2. A property-based test (``tests/dbt_math/test_reference_contracts.py``)
   using Hypothesis to drive the reference function with generated inputs.
   These are fast — no database required — and run hundreds of cases.

3. An SQL parity integration test (``tests/dbt_math/test_sql_parity.py``)
   that writes synthetic data to PostGIS, runs the actual model SQL, and
   asserts the results match the Python reference to within floating-point
   tolerance.

Architecture::

    reference.py              Pure Python reference + @deal contracts
    strategies.py             Hypothesis generators for input shapes
    sql_templates.py          Parameterized SQL strings mirroring SQL models
    test_reference_contracts.py   @pytest.mark.slow property-based tests
    test_sql_parity.py            @pytest.mark.integration SQL parity checks
"""
