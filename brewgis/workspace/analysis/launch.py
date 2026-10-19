"""The one way to start an analysis run.

Every launcher — the map view's per-analysis form and its Rerun button, the
full-page multi-module form, the MCP ``run_analysis`` tool and the SACOG demo
loader — reduces its request to a module list plus analysis parameters and
calls :func:`launch_analysis`. Validation, storing the parameters on the
Scenario (where the scenario's model blueprints read them from, see
``sqlmesh/macros/analysis_blueprints.py``) and the Celery dispatch live only
here, so no launcher can accept a configuration another would refuse, store it
differently, or execute it differently.

Parameters are the only input a launch carries. What data a module reads —
the parcel source, the built forms, the region's constraint layers, road
network and reference trip lengths — is resolved by the blueprints from the
Workspace and Scenario rows and built by SQLMesh as lineage dependencies, so
there is no table or column for a launcher to name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from brewgis.workspace.analysis.data_export import ensure_export_exists_isolated
from brewgis.workspace.analysis.module_registry import ANALYSIS_PARAMETERS
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import launch_analysis_run
from brewgis.workspace.services.fetch_clone import WorkspaceRegionError
from brewgis.workspace.services.fetch_clone import workspace_region
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

_PARAMETER_TYPES: dict[str, tuple[type, ...]] = {
    "float": (int, float),
    "bool": (bool,),
    "str": (str,),
}


class AnalysisLaunchError(Exception):
    """The launch was refused before anything was stored or dispatched."""

    def __init__(self, errors: list[PreflightError]) -> None:
        self.errors = errors
        super().__init__("; ".join(error.message for error in errors))


def launch_analysis(
    *,
    scenario: Scenario,
    modules: list[str],
    params: dict[str, Any] | None = None,
) -> AnalysisRun:
    """Validate *params*, store them on *scenario* and dispatch the run to Celery.

    *params* (``module_registry.ANALYSIS_PARAMETERS`` names) are merged into
    ``Scenario.analysis_params``: a module's form only carries its own
    parameters, so storing them must not discard another module's, and a rerun
    passes none.

    Returns the ``pending`` AnalysisRun (already finished where
    ``CELERY_TASK_ALWAYS_EAGER`` is on); the run's own status reports how the
    plan went.

    Raises:
        AnalysisLaunchError: the modules, the parameters or the scenario's
            prerequisites are invalid. Nothing has been stored or dispatched.
    """
    params = params or {}
    errors = _module_errors(modules) + _parameter_errors(params)
    if errors:
        raise AnalysisLaunchError(errors)
    errors = scenario_analysis_errors(scenario)
    if errors:
        raise AnalysisLaunchError(errors)

    if params:
        scenario.analysis_params = {**scenario.analysis_params, **params}
        scenario.save(update_fields=["analysis_params"])

    return launch_analysis_run(scenario_id=scenario.pk, module_names=modules)


def scenario_analysis_errors(scenario: Scenario) -> list[PreflightError]:
    """Return the blocking prerequisite errors for analyzing *scenario*.

    The analysis models derive everything they read from the scenario and its
    workspace (see ``sqlmesh/macros/analysis_blueprints.py``), so those derived
    inputs are what a launch is validated against:

    - the workspace's region (``fetch_clone.workspace_region``): a workspace
      whose base table is in no region schema has no constraint layers,
      trip-length zones or road network, gets no analysis models, and is
      reported as not configured for analysis — no region is substituted;

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
    try:
        workspace_region(workspace)
    except WorkspaceRegionError as error:
        return [PreflightError(field="base_table", message=str(error))]
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
