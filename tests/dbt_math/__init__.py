"""Differential tests between the analysis SQL models and a Python reference.

Each SQLMesh model with a compound formula gets:

1. A pure Python reference function (``tests/dbt_math/reference.py``) that
   mirrors the exact SQL formula, decorated with ``@deal.pre``/``@deal.post``
   to document and enforce mathematical invariants.

2. An SQL parity integration test (``tests/dbt_math/test_sql_parity.py``) that
   writes synthetic upstream data to PostGIS, runs the *actual* model SQL
   through ``run_model()``, and asserts the output matches the reference to
   within floating-point tolerance. The SQLMesh model file is the single source
   of truth — no SQL is duplicated — and the reference is only ever an oracle
   for what that SQL does, never tested against itself.

The other two modules are structural/textural contracts over the loaded models
(``test_bridge_srid.py``, ``test_result_view_geometry.py``).

Architecture::

    reference.py                  Pure Python oracle + @deal contracts
    sqlmesh_model_runner.py       Runs a real model against synthetic inputs
    test_sql_parity.py            @pytest.mark.integration SQL parity checks
    test_bridge_srid.py           Published DuckDB bridges carry their CRS
    test_result_view_geometry.py  Result views expose the parcel geometry
"""
