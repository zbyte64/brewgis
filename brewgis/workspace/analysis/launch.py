"""The one way to start an analysis run.

Every launcher — the map view's per-analysis form and its Rerun button, the
full-page multi-module form, the MCP ``run_analysis`` tool and the SACOG demo
loader — reduces its request to a module list plus :class:`AnalysisInputs` and
calls :func:`launch_analysis`. Validation, the rules for storing the inputs on
the Scenario (where the scenario's model blueprints read them from, see
``sqlmesh/macros/analysis_blueprints.py``) and the Celery dispatch live only
here, so no launcher can accept a configuration another would refuse, store it
differently, or execute it differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

from django.db import connection

from brewgis.workspace.analysis.data_export import ensure_export_exists_isolated
from brewgis.workspace.analysis.module_registry import ANALYSIS_PARAMETERS
from brewgis.workspace.analysis.module_registry import CANONICAL_COLUMN_NAMES
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import launch_analysis_run
from brewgis.workspace.services.preflight import PreflightError
from brewgis.workspace.services.preflight import check_analysis_prerequisites

if TYPE_CHECKING:
    from brewgis.workspace.models import AnalysisRun
    from brewgis.workspace.models import Scenario

BUILT_FORMS_TABLE = "built_forms"
"""Table the analysis models read BuildingType definitions from.

Schema-qualified with ``Workspace.db_schema`` on both sides — here and in
``sqlmesh/macros/analysis_blueprints.py``, which bakes the same name into the
scenario's model blueprints.
"""

# The defaults ``macros/spatial_ops.py:constraint_geometries`` applies to an
# entry that omits them; a bare table name resolves in ``public`` there too.
DEFAULT_CONSTRAINT_GEOM_COL = "geom"
DEFAULT_CONSTRAINT_DISCOUNT_PCT = 100
_BARE_TABLE_SCHEMA = "public"
_MAX_DISCOUNT_PCT = 100
_MAX_TABLE_NAME_PARTS = 3

_PARAMETER_TYPES: dict[str, tuple[type, ...]] = {
    "float": (int, float),
    "bool": (bool,),
    "str": (str,),
}


@dataclass(frozen=True)
class AnalysisInputs:
    """The per-scenario inputs a launch may set before its run.

    ``constraints`` (``[{table, discount_pct, geom_col}]``) and
    ``column_mapping`` (``{canonical_name: source_column}``) replace the
    scenario's stored value; ``None`` keeps it, which is how a rerun reuses the
    inputs of the run before it. ``params`` (``module_registry
    .ANALYSIS_PARAMETERS`` names) are merged into ``Scenario.analysis_params``:
    a module's form only carries its own parameters, so storing them must not
    discard another module's.
    """

    constraints: list[dict[str, Any]] | None = None
    column_mapping: dict[str, str] | None = None
    params: dict[str, Any] = field(default_factory=dict)


class AnalysisLaunchError(Exception):
    """The launch was refused before anything was stored or dispatched."""

    def __init__(self, errors: list[PreflightError]) -> None:
        self.errors = errors
        super().__init__("; ".join(error.message for error in errors))


def launch_analysis(
    *,
    scenario: Scenario,
    modules: list[str],
    inputs: AnalysisInputs | None = None,
) -> AnalysisRun:
    """Validate *inputs*, store them on *scenario* and dispatch the run to Celery.

    Returns the ``pending`` AnalysisRun (already finished where
    ``CELERY_TASK_ALWAYS_EAGER`` is on); the run's own status reports how the
    plan went.

    Raises:
        AnalysisLaunchError: the modules, the inputs or the scenario's
            prerequisites are invalid. Nothing has been stored or dispatched.
    """
    inputs = inputs or AnalysisInputs()
    errors = _module_errors(modules)
    constraints = (
        None
        if inputs.constraints is None
        else _normalized_constraints(inputs.constraints, errors)
    )
    errors += _column_mapping_errors(inputs.column_mapping)
    errors += _parameter_errors(inputs.params)
    if errors:
        raise AnalysisLaunchError(errors)

    errors = scenario_analysis_errors(scenario)
    if "env_constraint" in resolve_module_order(modules):
        effective = constraints if constraints is not None else scenario.constraints
        errors += _constraint_table_errors(effective or [])
    if errors:
        raise AnalysisLaunchError(errors)

    update_fields = []
    if constraints is not None:
        scenario.constraints = constraints
        update_fields.append("constraints")
    if inputs.column_mapping is not None:
        scenario.column_mapping = dict(inputs.column_mapping)
        update_fields.append("column_mapping")
    if inputs.params:
        scenario.analysis_params = {**scenario.analysis_params, **inputs.params}
        update_fields.append("analysis_params")
    if update_fields:
        scenario.save(update_fields=update_fields)

    return launch_analysis_run(scenario_id=scenario.pk, module_names=modules)


def scenario_analysis_errors(scenario: Scenario) -> list[PreflightError]:
    """Return the blocking prerequisite errors for analyzing *scenario*.

    The analysis models derive everything they read from the scenario and its
    workspace (see ``sqlmesh/macros/analysis_blueprints.py``), so those derived
    inputs are what a launch is validated against:

    - the scenario's own parcel source: its canvas view for an ALTERNATIVE
      scenario (base canvas + painted edits), the workspace's base canvas
      otherwise (``Scenario.base_layer_table``);
    - the workspace's exported built-forms table, which is mechanically
      re-synced from the configured ``BuildingType`` rows first. That sync never
      invents data — a workspace with no BuildingType rows still produces an
      empty table, which the check below reports.

    The export sync uses its own DB connection (not Django's request-scoped
    one) so the write commits immediately: under ATOMIC_REQUESTS a view runs in
    one transaction, but SQLMesh's engine adapter opens a separate connection to
    run the plan — it can't see this table until it's actually committed.
    """
    workspace = scenario.workspace
    ensure_export_exists_isolated(
        workspace, schema=workspace.db_schema, table=BUILT_FORMS_TABLE
    )
    return check_analysis_prerequisites(
        schema=workspace.db_schema,
        parcel_table=scenario.base_layer_table,
        built_form_table=BUILT_FORMS_TABLE,
        base_canvas_table=workspace.effective_base_table(),
    )


def _module_errors(modules: list[str]) -> list[PreflightError]:
    if not modules:
        return [
            PreflightError(field="modules", message="No analysis modules selected.")
        ]
    try:
        resolve_module_order(modules)
    except ValueError as exc:
        return [PreflightError(field="modules", message=str(exc))]
    return []


def _normalized_constraints(
    constraints: list[Any], errors: list[PreflightError]
) -> list[dict[str, Any]]:
    """Return *constraints* as complete ``{table, discount_pct, geom_col}`` entries.

    Appends one error to *errors* per malformed entry; the returned list is only
    stored when *errors* stays empty.
    """
    normalized: list[dict[str, Any]] = []
    for position, entry in enumerate(constraints, start=1):
        label = f"Constraint {position}"
        if not isinstance(entry, dict):
            errors.append(
                PreflightError("constraints", f"{label} is not an object: {entry!r}")
            )
            continue
        unknown = set(entry) - {"table", "discount_pct", "geom_col"}
        table = entry.get("table")
        geom_col = entry.get("geom_col") or DEFAULT_CONSTRAINT_GEOM_COL
        discount = entry.get("discount_pct", DEFAULT_CONSTRAINT_DISCOUNT_PCT)
        if unknown:
            errors.append(
                PreflightError(
                    "constraints",
                    f"{label} has unknown keys: {', '.join(sorted(unknown))}",
                )
            )
        if not isinstance(table, str) or not table:
            errors.append(PreflightError("constraints", f"{label} names no table."))
        if not isinstance(geom_col, str):
            errors.append(
                PreflightError("constraints", f"{label} geom_col is not a column name.")
            )
        if (
            isinstance(discount, bool)
            or not isinstance(discount, (int, float))
            or not 0 <= discount <= _MAX_DISCOUNT_PCT
        ):
            errors.append(
                PreflightError(
                    "constraints",
                    f"{label} discount_pct must be a number from 0 to 100: {discount!r}",
                )
            )
        normalized.append(
            {"table": table, "discount_pct": discount, "geom_col": geom_col}
        )
    return normalized


def _constraint_table_errors(constraints: list[dict[str, Any]]) -> list[PreflightError]:
    """Report every constraint whose table or geometry column does not exist.

    Resolved the way ``constraint_geometries`` renders the name — a bare table
    in ``public``, ``schema.table`` as given (a leading catalog is the database
    itself) — because a missing relation otherwise surfaces only as an
    ``UndefinedTable`` deep inside the run's SQLMesh plan.
    """
    errors: list[PreflightError] = []
    with connection.cursor() as cursor:
        for entry in constraints:
            table = str(entry.get("table") or "")
            geom_col = str(entry.get("geom_col") or DEFAULT_CONSTRAINT_GEOM_COL)
            parts = table.split(".")
            if len(parts) > _MAX_TABLE_NAME_PARTS:
                errors.append(
                    PreflightError(
                        "constraints",
                        f"Constraint table {table!r} is not a table name.",
                    )
                )
                continue
            schema, name = (
                parts[-2:] if len(parts) > 1 else (_BARE_TABLE_SCHEMA, parts[0])
            )
            cursor.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = %s AND table_name = %s",
                [schema, name],
            )
            columns = {row[0] for row in cursor.fetchall()}
            if not columns:
                errors.append(
                    PreflightError(
                        "constraints",
                        f"Constraint table {schema}.{name} does not exist.",
                    )
                )
            elif geom_col not in columns:
                errors.append(
                    PreflightError(
                        "constraints",
                        f"Constraint table {schema}.{name} has no geometry column {geom_col!r}.",
                    )
                )
    return errors


def _column_mapping_errors(column_mapping: object) -> list[PreflightError]:
    if column_mapping is None:
        return []
    if not isinstance(column_mapping, dict):
        return [PreflightError("column_mapping", "column_mapping must be an object.")]
    errors = [
        PreflightError("column_mapping", f"Unknown canonical column: {name!r}")
        for name in column_mapping
        if name not in CANONICAL_COLUMN_NAMES
    ]
    errors += [
        PreflightError(
            "column_mapping", f"Column mapping for {name!r} must name a column."
        )
        for name, source in column_mapping.items()
        if not isinstance(source, str) or not source
    ]
    return errors


def _parameter_errors(params: dict[str, Any]) -> list[PreflightError]:
    kinds = {param.name: param.kind for param in ANALYSIS_PARAMETERS}
    errors: list[PreflightError] = []
    for name, value in params.items():
        if name not in kinds:
            errors.append(
                PreflightError("params", f"Unknown analysis parameter: {name!r}")
            )
            continue
        accepted = _PARAMETER_TYPES[kinds[name]]
        if not isinstance(value, accepted) or (
            kinds[name] == "float" and isinstance(value, bool)
        ):
            errors.append(
                PreflightError(
                    "params",
                    f"Analysis parameter {name!r} must be a {kinds[name]}: {value!r}",
                )
            )
    return errors
