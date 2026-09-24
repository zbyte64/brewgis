"""Built-form fill — Python SQL model (blueprinted, one per opted-in workspace).

A workspace with ``Workspace.fill_built_form`` on reads this model instead of
its ``base_table`` (see ``Workspace.effective_base_table``): the same rows and
the same column set, but every parcel that has a built-form *signal* and no
built-form attributes yet comes out with the closest-matching ``BuildingType``
applied to ``built_form_key``/``du``/``pop``/``hh``/``emp``.

The source is never written to: this model materializes a table of its own, so
the import stays reversible (unchecking the box drops the model and the
workspace reads its source again). ``models/base_canvas/`` is where the other
Python models over derived base canvases live (``du_regressor.py`` and
friends).

Matching semantics — the SQL counterpart of the paint surfaces' two entries,
``views/paint.py:run_match_built_form`` (density match) and
``run_fill_built_form`` (built-form-key lookup), applied per parcel in one
pass, priority-ordered:

1. the source has dwelling units — closest ``du_per_acre`` to ``du / acres``;
2. else the source has employment — closest ``emp_per_acre`` to ``emp / acres``;
3. else an exact normalized ``built_form_key`` match (the fill's own fallback
   for the parcels neither density basis can place);
4. else no match at all — every ``_bf_*`` value stays NULL and the COALESCE
   leaves the source's NULLs as they were.

``du``/``emp`` are read through ``COALESCE(..., 0)`` so a NULL (the case this
feature exists for) compares as "no density basis" rather than poisoning the
comparison with SQL's three-valued logic, exactly as the Python matcher's
``float(row.get("du") or 0.0)`` does. Ties break on ``bf.id``, the same
deterministic order ``min()`` gives the Python matcher over an unordered
queryset.

A matched row's ``pop``/``hh`` come from the Building Type's ``household_size``
and ``vacancy_rate`` with the same defaults the analysis models use
(``COALESCE(household_size, 2.5)``, ``COALESCE(vacancy_rate, 5.0) / 100``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.macros.built_form_fill_blueprints import MODEL_SCHEMA
from brewgis.sqlmesh.macros.built_form_fill_blueprints import built_form_fill_profiles
from brewgis.sqlmesh.macros.built_form_keys import _PREFIX_ALTERNATION
from brewgis.sqlmesh.macros.built_form_keys import _SEPARATOR_CLASS

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per workspace with the fill enabled at that moment.
_PROFILES = built_form_fill_profiles()

# Parcel acres a built-form allocation is computed against. Mirrors the paint
# surfaces' ``area_gross or area_parcel or 0.0``: 0 is treated as missing, not
# as a real (zero-acre) parcel. ``{p}`` is the table alias prefix.
_ACRES = "COALESCE(NULLIF({p}area_gross, 0), NULLIF({p}area_parcel, 0), 0.0)"


def _normalize_sql(expression: str) -> str:
    """Return the normalized-key SQL for *expression*.

    Textually identical to ``macros/built_form_keys.normalize_built_form_key``
    — the constants that define the rule are imported from that module so the
    two cannot drift (``tests/workspace/test_built_form_keys.py`` pins the rule
    itself). Spelled out here because this model's SQL is *returned*, not
    rendered, so it cannot call the macro.
    """
    return (
        "btrim(regexp_replace("
        f"regexp_replace(lower(btrim(CAST({expression} AS TEXT))), "
        f"'^({_PREFIX_ALTERNATION})', ''), "
        f"'{_SEPARATOR_CLASS}', ' ', 'g'))"
    )


def _fill_expression(column: str, acres: str) -> str:
    """Return the output expression for one source column.

    Only the five built-form columns can differ from the source; every other
    column is selected verbatim, so the output keeps the source's column set,
    order and values. A built-form column is filled only where the source value
    is a literal NULL — 0 and the empty string are real values and are kept.
    """
    if column == "built_form_key":
        return "COALESCE(built_form_key, _bf_key) AS built_form_key"
    if column == "du":
        return f"COALESCE(du, {acres} * _bf_du_per_acre) AS du"
    if column == "pop":
        return (
            "COALESCE(pop, "
            f"{acres} * _bf_du_per_acre * COALESCE(_bf_household_size, 2.5)) AS pop"
        )
    if column == "hh":
        return (
            "COALESCE(hh, "
            f"{acres} * _bf_du_per_acre"
            " * (1.0 - COALESCE(_bf_vacancy_rate, 5.0) / 100.0)) AS hh"
        )
    if column == "emp":
        return f"COALESCE(emp, {acres} * _bf_emp_per_acre) AS emp"
    return column


@model(
    name=f"brewgis.{MODEL_SCHEMA}.@{{model_table}}",
    kind=ModelKindName.FULL,
    description=(
        "One workspace's built-form-filled base canvas: the source base canvas"
        " with built_form_key, du, pop, hh and emp filled from the"
        " closest-matching Building Type where the source value is NULL."
    ),
    audits=[
        ("not_null", {"columns": [exp.to_column("parcel_id")]}),
        ("number_of_rows", {"threshold": 1}),
    ],
    post_statements=[
        (
            "CREATE INDEX IF NOT EXISTS "
            "@snapshot_hash('idx_built_form_fill_geometry_') "
            "ON @this_model USING GIST (geometry)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS "
            "@snapshot_hash('idx_built_form_fill_parcel_id_') "
            "ON @this_model USING btree (parcel_id)"
        ),
    ],
    blueprints=[dict(profile) for profile in _PROFILES],
    is_sql=True,
)
def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the workspace's fill SELECT.

    The returned string is not macro-rendered again by SQLMesh, so the
    blueprint variables are resolved here through the evaluator and the
    ``built_forms`` export is referenced as the physical table it is
    (double-quoted per part; see ``canvas_view_manager._qi``).

    No ``columns`` declaration and no ``column_descriptions``: the output's
    column set is the per-workspace source's, which SQLMesh infers through
    lineage (same rationale as ``models/scenarios/scenario_canvas.py``).
    """
    from brewgis.workspace.services.canvas_view_manager import _qi

    source_ref = str(evaluator.blueprint_var("source_ref"))
    built_form_table = str(evaluator.blueprint_var("built_form_table"))
    all_columns = [str(column) for column in evaluator.blueprint_var("all_columns", [])]

    acres = _ACRES.format(p="")
    source_acres = _ACRES.format(p="s.")
    du_basis = f"(COALESCE(s.du, 0) > 0 AND {source_acres} > 0 AND bf.du_per_acre > 0)"
    emp_basis = (
        f"(COALESCE(s.du, 0) <= 0 AND COALESCE(s.emp, 0) > 0"
        f" AND {source_acres} > 0 AND bf.emp_per_acre > 0)"
    )
    key_basis = (
        f"(s.built_form_key IS NOT NULL AND"
        f" {_normalize_sql('s.built_form_key')} = {_normalize_sql('bf.key')})"
    )
    columns = ", ".join(_fill_expression(column, acres) for column in all_columns)

    return f"""
WITH source AS (
    SELECT * FROM {source_ref}
),
matched AS (
    SELECT
        s.*,
        bf.key AS _bf_key,
        bf.du_per_acre AS _bf_du_per_acre,
        bf.emp_per_acre AS _bf_emp_per_acre,
        bf.household_size AS _bf_household_size,
        bf.vacancy_rate AS _bf_vacancy_rate
    FROM source s
    LEFT JOIN LATERAL (
        SELECT *
        FROM {_qi(built_form_table)} bf
        WHERE {du_basis}
           OR {emp_basis}
           OR {key_basis}
        ORDER BY
            CASE
                WHEN {du_basis} THEN 1
                WHEN {emp_basis} THEN 2
                WHEN s.built_form_key IS NOT NULL THEN 3
                ELSE 4
            END,
            CASE
                WHEN {du_basis}
                    THEN ABS(bf.du_per_acre - (s.du / {source_acres}))
                WHEN {emp_basis}
                    THEN ABS(bf.emp_per_acre - (s.emp / {source_acres}))
                ELSE 0.0
            END,
            bf.id
        LIMIT 1
    ) bf ON TRUE
)
SELECT
    {columns}
FROM matched
"""
