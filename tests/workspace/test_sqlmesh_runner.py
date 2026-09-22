"""Tests for ``run_sqlmesh_plan`` — how a plan is asked for, and what it does
when SQLMesh refuses it.

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

from brewgis.workspace.analysis import sqlmesh_runner
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

RUNNER = "brewgis.workspace.analysis.sqlmesh_runner"

CONFLICT = ConflictingPlanError(
    "Another plan deployed new versions of 2 models while they were being restated"
)


class _Builder:
    """Stands in for SQLMesh's ``PlanBuilder``."""

    def __init__(self, *, conflict: bool) -> None:
        self._conflict = conflict
        self.applied = False

    def apply(self) -> None:
        if self._conflict:
            raise CONFLICT
        self.applied = True

    def build(self) -> str:
        return "plan"


class _Context:
    """Stands in for SQLMesh's ``Context``."""

    def __init__(self, *, conflict: bool) -> None:
        self._conflict = conflict
        self.plan_calls: list[dict[str, Any]] = []
        self.builders: list[dict[str, Any]] = []

    def plan(self, **kwargs: Any) -> str:
        self.plan_calls.append(kwargs)
        return "plan"

    def plan_builder(self, **kwargs: Any) -> _Builder:
        self.builders.append(kwargs)
        return _Builder(conflict=self._conflict)


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A context factory that records how the plan was asked for."""

    def _install(*, conflict: bool = False) -> _Context:
        ctx = _Context(conflict=conflict)
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
