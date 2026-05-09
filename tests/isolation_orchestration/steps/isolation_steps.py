"""Step definitions for orchestration-level isolation BDD scenarios.

These steps translate the PostGIS-level isolation feature file
(tests/features/dbt_isolation.feature) to orchestration-level assertions.
Instead of creating real schemas/views via psycopg, they create
Workspace/AnalysisRun records with mocked Celery dispatch and verify
model-level isolation contracts.

Each step receives the same scenario_context dict, allowing state to
flow from Given → When → Then steps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pytest_bdd import given
from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from typing import Any


logger = logging.getLogger(__name__)

# Register the same feature file used by the real (psycopg-level) BDD tests.
scenarios(str(Path(__file__).parent.parent / ".." / "features" / "dbt_isolation.feature"))


# ── Helpers ──────────────────────────────────────────────────────────────


def _require(
    ctx: dict[str, Any],
    key: str,
    msg: str | None = None,
) -> Any:
    """Get a required key from scenario_context or raise."""
    if key not in ctx:
        raise AssertionError(
            msg or f"Scenario context missing required key '{key}'",
        )
    return ctx[key]


def _resolve_workspace(
    ctx: dict[str, Any],
    schema: str,
) -> Any:
    """Look up a workspace by db_schema from scenario_context."""
    workspaces = ctx.get("workspaces", {})
    if schema in workspaces:
        return workspaces[schema]

    # If the schema matches the default workspace from Background, use that
    for ws in workspaces.values():
        if ws.db_schema == schema:
            return ws

    msg = (
        f"No workspace found with db_schema '{schema}'. "
        f"Available schemas: {list(workspaces)}"
    )
    raise AssertionError(msg)


def _assert_run_matches(
    run: AnalysisRun,
    workspace_id: int,
    scenario_id: str,
    module: str,
) -> None:
    """Assert an AnalysisRun record matches the expected isolation properties."""
    msg = (
        f"AnalysisRun workspace_id={run.workspace_id} "
        f"does not match expected workspace_id={workspace_id}"
    )
    assert run.workspace_id == workspace_id, msg
    msg = (
        f"AnalysisRun vars.scenario_id={run.vars.get('scenario_id')} "
        f"does not match expected '{scenario_id}'"
    )
    assert run.vars.get("scenario_id") == scenario_id, msg
    ordered = resolve_module_order([module])
    for expected_mod in ordered:
        msg = (
            f"Expected module '{expected_mod}' not found in "
            f"AnalysisRun modules: {run.modules}"
        )
        assert expected_mod in run.modules, msg



def _find_module_by_table_prefix(view_name: str) -> str | None:
    """Find a module that produces a table whose name starts with ``view_name``.

    For bare view names like ``"end_state"`` (without a scenario_id suffix),
    this looks up which module's result table template starts with the
    given prefix. Returns None if no module matches (indicating the view
    name is a fully-scoped table name like ``env_constraint_bdd_scenario_a``).
    """
    known_prefix_to_module = {
        "env_constraint": "env_constraint",
        "end_state": "core",
        "increment": "core",
        "water_demand_residential": "water_demand",
        "water_demand_nonresidential": "water_demand",
        "energy_demand_residential": "energy_demand",
        "energy_demand_nonresidential": "energy_demand",
        "land_consumption": "land_consumption",
        "fiscal_revenue": "fiscal",
        "fiscal_cost": "fiscal",
        "agriculture": "agriculture",
        "trip_generation": "trip_generation",
        "trip_distribution": "trip_distribution",
        "mode_choice": "mode_choice",
        "vmt": "vmt",
    }
    return known_prefix_to_module.get(view_name)
# ── Given steps ──────────────────────────────────────────────────────────


@given("idle dbt connections are terminated")
def idle_connections_terminated() -> None:
    """No-op at orchestration level — no real dbt connections exist."""


@given(parsers.parse('schema "{schema_name}" exists'))
def schema_exists(schema_name: str, scenario_context: dict[str, Any], db) -> None:  # type: ignore[no-untyped-def]
    """Create a workspace with the given db_schema for isolation testing."""
    workspaces = scenario_context.setdefault("workspaces", {})
    ws = WorkspaceFactory(
        db_schema=schema_name,
        name=f"BDD Workspace ({schema_name})",
    )
    workspaces[schema_name] = ws


@given(parsers.parse('schema "{schema_name}" does not exist'))
def schema_does_not_exist(schema_name: str, scenario_context: dict[str, Any], db) -> None:  # type: ignore[no-untyped-def]
    """Create a reference workspace to verify no runs leaked into it.

    Despite the Gherkin phrasing (which describes the PostGIS-level
    expectation that the schema remains empty), we create a workspace
    with this db_schema so that we can positively verify zero
    AnalysisRun records were created for it during the test.
    """
    workspaces = scenario_context.setdefault("workspaces", {})
    ws = WorkspaceFactory(
        db_schema=schema_name,
        name=f"BDD Workspace ({schema_name} — empty expected)",
    )
    workspaces[schema_name] = ws


@given(
    parsers.parse(
        'a parcel table "{name}" exists in schema "{schema}"',
    ),
)
def parcel_table_exists() -> None:
    """No-op at orchestration level — mocked dispatch doesn't read tables."""


# ── When steps ───────────────────────────────────────────────────────────


@when(
    parsers.parse(
        'I run dbt module "{module}" with scenario_id "{sid}" in schema '
        '"{schema}"',
    ),
)
def run_dbt_module(  # noqa: PLR0913
    scenario_context: dict[str, Any],
    module: str,
    sid: str,
    schema: str,
    mock_module_tasks,  # type: ignore[no-untyped-def]
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Invoke the analysis pipeline with the given module and scenario_id.

    MODULE_TASKS are already patched to MagicMock by the ``mock_module_tasks``
    fixture in conftest.py, so Celery dispatch is a no-op. The AnalysisRun
    record is created synchronously and stored in scenario_context.
    """
    workspace = _resolve_workspace(scenario_context, schema)
    vars_ = {
        "scenario_id": sid,
        "target_schema": schema,
        "parcel_table": "parcels",
    }

    run = run_analysis_pipeline(
        workspace_id=workspace.pk,
        module_names=[module],
        vars_=vars_,
    )

    runs = scenario_context.setdefault("runs", [])
    runs.append(run)
    scenario_context["last_run"] = run
    scenario_context["last_module"] = module
    scenario_context["last_scenario_id"] = sid
    scenario_context["last_schema"] = schema


@when(
    parsers.parse(
        'I run dbt module "{module}" with scenario_id "{sid}" in schema '
        '"{schema}" a second time',
    ),
)
def run_dbt_module_second(  # noqa: PLR0913
    scenario_context: dict[str, Any],
    module: str,
    sid: str,
    schema: str,
    mock_module_tasks,  # type: ignore[no-untyped-def]
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Run the same module a second time (idempotency check).

    Identical to ``run_dbt_module`` but stores the result separately
    so the Then-step can compare both runs.
    """
    run_dbt_module(scenario_context, module, sid, schema, mock_module_tasks, db)
    scenario_context["second_run"] = scenario_context["last_run"]


# ── Then steps ───────────────────────────────────────────────────────────


@then(parsers.parse("the dbt run should have succeeded"))
def dbt_run_succeeded(scenario_context: dict[str, Any], db) -> None:  # type: ignore[no-untyped-def]
    """Verify that the analysis pipeline created an AnalysisRun.

    At the orchestration level, a successful dispatch means the
    AnalysisRun record was created with a non-null pk.
    """
    run = _require(scenario_context, "last_run", "No last_run in context")
    assert run.pk is not None, "AnalysisRun record was not created"


@then(parsers.parse("the dbt run should have failed"))
def dbt_run_failed(scenario_context: dict[str, Any]) -> None:
    """Verify the last pipeline invocation raised an error.

    At the orchestration level, this should never happen for the
    defined scenarios (known modules, valid workspaces). This step
    is defined for completeness but will fail if reached.
    """
    msg = (
        "Orchestration-level tests use mocked modules — "
        "a 'failed' state should not occur. If this step was "
        "reached, verify the test scenario is appropriate."
    )
    raise AssertionError(msg)


@then(parsers.parse('a view named "{view_name}" should exist in schema "{schema}"'))
def view_exists(
    view_name: str,
    schema: str,
    scenario_context: dict[str, Any],
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Assert that an AnalysisRun was created with the expected isolation.

    At the orchestration level, ``view_name`` encodes the module output
    table name (e.g. ``env_constraint_bdd_scenario_a``). We verify:
    - An AnalysisRun exists for the workspace with ``db_schema={schema}``
    - The run's vars contain the correct scenario_id (derived from view_name)
    - The run's modules include the module that produces this view
    """
    workspace = _resolve_workspace(scenario_context, schema)
    scenario_id = _derive_scenario_id_from_view(view_name)
    module = _derive_module_from_view(view_name)

    run = _require(scenario_context, "last_run", "No last_run in context")
    _assert_run_matches(run, workspace.pk, scenario_id, module)


@then(
    parsers.parse(
        'no view named "{view_name}" should exist in schema "{schema}"',
    ),
)
def view_does_not_exist(
    view_name: str,
    schema: str,
    scenario_context: dict[str, Any],
    db,  # type: ignore[no-untyped-def]
) -> None:
    """Assert that NO AnalysisRun was created for the given schema.

    At the orchestration level, this verifies that the isolation
    boundary held — the workspace with ``db_schema={schema}`` has
    zero AnalysisRun records that match the given view/module.
    """
    workspace = _resolve_workspace(scenario_context, schema)

    # Check if view_name is a bare module prefix (no scenario_id)
    # e.g. "end_state" — assert no run dispatched that module
    bare_module = _find_module_by_table_prefix(view_name)
    if bare_module is not None:
        logger.info(
            "Interpreting bare view name '%s' as module '%s' "
            "(no scenario_id suffix)",
            view_name,
            bare_module,
        )
        matching_runs = AnalysisRun.objects.filter(
            workspace=workspace,
            modules__contains=[bare_module],
        )
        msg = (
            f"Expected zero AnalysisRun records for workspace "
            f"'{workspace.db_schema}' containing module "
            f"'{bare_module}', found {matching_runs.count()}"
        )
        assert matching_runs.count() == 0, msg
    else:
        # Full view name with scenario_id (e.g. env_constraint_bdd_ws_test)
        scenario_id = _derive_scenario_id_from_view(view_name)
        module = _derive_module_from_view(view_name)
        matching_runs = AnalysisRun.objects.filter(
            workspace=workspace,
            vars__scenario_id=scenario_id,
            modules__contains=[module],
        )
        msg = (
            f"Expected zero AnalysisRun records for workspace "
            f"'{workspace.db_schema}' with scenario_id='{scenario_id}' "
            f"and module='{module}', found {matching_runs.count()}"
        )
        assert matching_runs.count() == 0, msg


# ── View name parsing helpers ────────────────────────────────────────────


def _derive_scenario_id_from_view(view_name: str) -> str:
    """Extract the scenario_id from a dbt output table name.

    Module result tables follow the template ``{module}_{scenario_id}``.
    For example, ``env_constraint_bdd_scenario_a`` → ``bdd_scenario_a``.
    The longest known module prefix is stripped to reveal the scenario_id.
    """
    # Try known prefixes in order of length (longest first to avoid
    # truncation like stripping only "env_" from "env_constraint_...").
    known_prefixes = sorted(
        [
            "env_constraint_",
            "end_state_",
            "increment_",
            "water_demand_residential_",
            "water_demand_nonresidential_",
            "energy_demand_residential_",
            "energy_demand_nonresidential_",
            "land_consumption_",
            "fiscal_revenue_",
            "fiscal_cost_",
            "agriculture_",
            "trip_generation_",
            "trip_distribution_",
            "mode_choice_",
            "vmt_",
        ],
        key=len,
        reverse=True,
    )
    for prefix in known_prefixes:
        if view_name.startswith(prefix):
            return view_name[len(prefix):]

    msg = (
        f"Cannot derive scenario_id from view name '{view_name}'. "
        f"No known module prefix matched."
    )
    raise AssertionError(msg)


def _derive_module_from_view(view_name: str) -> str:
    """Map a dbt output view name back to the module that produces it.

    Uses MODULE_RESULT_TABLES to find the module whose table template
    matches the given view name.
    """
    scenario_id = _derive_scenario_id_from_view(view_name)
    for module_name in [
        "env_constraint",
        "core",
        "water_demand",
        "energy_demand",
        "land_consumption",
        "fiscal",
        "agriculture",
        "trip_generation",
        "trip_distribution",
        "mode_choice",
        "vmt",
    ]:
        expected_tables = get_result_table_names(module_name, scenario_id)
        if view_name in expected_tables:
            return module_name

    msg = (
        f"No registered module produces a view named '{view_name}'. "
        f"Check MODULE_RESULT_TABLES in module_registry.py."
    )
    raise AssertionError(msg)
