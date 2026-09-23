"""Tests for ``run_sqlmesh_plan`` — how a plan is asked for, and what it does
when SQLMesh refuses it — and for the project config a plan is built from.

A plan that restates models it is also redeploying is rejected by SQLMesh and
cannot be retried as-is, so the runner has to turn it into two plans. That
split is the only reason this helper is more than a pass-through to
``Context.plan``, and it is what keeps a launch after a model edit from
failing forever.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmesh.utils.errors import ConflictingPlanError
from sqlmesh.utils.errors import PlanError

from brewgis.sqlmesh.config import config_factory
from brewgis.workspace.analysis import sqlmesh_runner
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

RUNNER = "brewgis.workspace.analysis.sqlmesh_runner"

CONFLICT = ConflictingPlanError(
    "Another plan deployed new versions of 2 models while they were being restated"
)
PLAN_FAILED = PlanError("Plan application failed.")


class _Builder:
    """Stands in for SQLMesh's ``PlanBuilder``."""

    def __init__(self, *, conflict: bool, fail: bool = False) -> None:
        self._conflict = conflict
        self._fail = fail
        self.applied = False

    def apply(self) -> None:
        if self._conflict:
            raise CONFLICT
        if self._fail:
            raise PLAN_FAILED
        self.applied = True

    def build(self) -> str:
        return "plan"


class _Adapter:
    """Stands in for a SQLMesh engine adapter (one per gateway)."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Context:
    """Stands in for SQLMesh's ``Context``."""

    def __init__(self, *, conflict: bool, fail: bool = False) -> None:
        self._conflict = conflict
        self._fail = fail
        self.plan_calls: list[dict[str, Any]] = []
        self.builders: list[dict[str, Any]] = []
        # The DuckDB gateway adapter is the one holding the shared file's lock.
        self.duckdb_adapter = _Adapter()
        self.engine_adapters: dict[str, _Adapter] = {"duckdb": self.duckdb_adapter}
        self.closed = False

    def plan(self, **kwargs: Any) -> str:
        self.plan_calls.append(kwargs)
        return "plan"

    def plan_builder(self, **kwargs: Any) -> _Builder:
        self.builders.append(kwargs)
        return _Builder(conflict=self._conflict, fail=self._fail)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A context factory that records how the plan was asked for."""

    def _install(*, conflict: bool = False, fail: bool = False) -> _Context:
        ctx = _Context(conflict=conflict, fail=fail)
        monkeypatch.setattr(sqlmesh_runner, "get_context", lambda **_kw: ctx)
        return ctx

    return _install


class TestPlanRequests:
    """What the default path asks SQLMesh for."""

    def test_uses_context_plan_by_default(self, context) -> None:
        ctx = context()

        run_sqlmesh_plan(environment="prod", select=["brewgis.ascn7.vmt"])

        (call,) = ctx.plan_calls
        assert call["select_models"] == ["brewgis.ascn7.vmt"]
        assert ctx.builders == []

    def test_passes_the_local_changes_flag_through_the_builder(self, context) -> None:
        ctx = context()

        run_sqlmesh_plan(
            environment="prod",
            select=["brewgis.ascn7.vmt"],
            restate_models=["brewgis.ascn7.vmt"],
            always_include_local_changes=True,
        )

        assert ctx.plan_calls == []
        (builder_kwargs,) = ctx.builders
        assert builder_kwargs["always_include_local_changes"] is True
        assert builder_kwargs["restate_models"] == ["brewgis.ascn7.vmt"]


class TestConflictingPlan:
    """Restating and redeploying the same model has to become two plans."""

    def test_splits_into_deploy_then_restate(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        context(conflict=True)
        plans: list[dict[str, Any]] = []
        monkeypatch.setattr(
            sqlmesh_runner, "run_sqlmesh_plan", lambda **kwargs: plans.append(kwargs)
        )

        run_sqlmesh_plan(
            environment="prod",
            select=["brewgis.ascn7.core_end_state", "brewgis.ascn7.vmt"],
            restate_models=["brewgis.ascn7.core_end_state"],
            always_include_local_changes=True,
        )

        # Deploy first — which materializes what changed — then restate what is
        # by then all deployed. Restating first is what SQLMesh rejected.
        assert [plan.get("restate_models") for plan in plans] == [
            None,
            ["brewgis.ascn7.core_end_state"],
        ]
        assert all(plan["always_include_local_changes"] is True for plan in plans)
        assert all(
            plan["select"] == ["brewgis.ascn7.core_end_state", "brewgis.ascn7.vmt"]
            for plan in plans
        )

    def test_propagates_when_there_is_nothing_to_split(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A conflict without a restatement is not ours to resolve."""
        context(conflict=True)
        plans: list[dict[str, Any]] = []
        monkeypatch.setattr(
            sqlmesh_runner, "run_sqlmesh_plan", lambda **kwargs: plans.append(kwargs)
        )

        with pytest.raises(ConflictingPlanError):
            run_sqlmesh_plan(
                environment="prod",
                select=["brewgis.ascn7.vmt"],
                always_include_local_changes=True,
            )

        assert plans == []


class TestReleasesTheSharedDuckDbFile:
    """A plan must not leave the shared ``duckdb_cache.db`` locked behind it.

    SQLMesh caches one DuckDB adapter per data file for the life of the process
    and that adapter holds the file's lock while its connection is open, so a
    plan that raises used to leave the file locked inside the long-lived Celery
    worker child that ran it — every later plan from another process then failed
    with "Could not set lock on file … duckdb_cache.db" until the worker was
    restarted, which is what the analysis failures actually looked like.
    """

    def test_releases_the_gateway_adapter_after_a_successful_plan(
        self, context
    ) -> None:
        ctx = context()

        run_sqlmesh_plan(
            environment="prod",
            select=["brewgis.ascn7.vmt"],
            restate_models=["brewgis.ascn7.vmt"],
            always_include_local_changes=True,
        )

        assert ctx.duckdb_adapter.closed
        assert ctx.closed

    def test_releases_the_gateway_adapter_when_the_plan_fails(self, context) -> None:
        ctx = context(fail=True)

        with pytest.raises(PlanError):
            run_sqlmesh_plan(
                environment="prod",
                select=["brewgis.ascn7.vmt"],
                restate_models=["brewgis.ascn7.vmt"],
                always_include_local_changes=True,
            )

        assert ctx.duckdb_adapter.closed
        assert ctx.closed

    def test_releases_on_the_context_plan_path_too(self, context) -> None:
        """The ``always_include_local_changes=None`` shortcut is a separate
        return; leaving it out would leak on every MCP/tool plan."""
        ctx = context()

        run_sqlmesh_plan(environment="prod", select=["brewgis.ascn7.vmt"])

        assert ctx.duckdb_adapter.closed
        assert ctx.closed


class TestConfigVariables:
    """How a caller's run variables reach the models."""

    def test_extra_arguments_become_config_variables(self) -> None:
        """``get_context(**variables)`` (the MCP tools, and every plan that
        passes ``variables``) forwards them here, so an argument that failed to
        merge would silently render the models with the config defaults."""
        config = config_factory(parcel_table="custom.parcels", min_sqft_per_unit=500)

        assert config.variables["parcel_table"] == "custom.parcels"
        assert config.variables["min_sqft_per_unit"] == 500
        assert config.variables["default_srid"] == 4326
        assert config.variables["transport_km_to_mi"] == 0.621371
