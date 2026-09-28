"""Tests for ``run_sqlmesh_plan`` — how a plan is asked for, and what it does
when SQLMesh refuses it — and for the project config a plan is built from.

A plan that restates models it is also redeploying is rejected by SQLMesh and
cannot be retried as-is, so the runner has to turn it into two plans. That
split is the only reason this helper is more than a pass-through to
``Context.plan``, and it is what keeps a launch after a model edit from
failing forever.
"""

from __future__ import annotations

from types import SimpleNamespace
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

    def __init__(self, *, conflict: bool, fail: bool = False, plan: Any = None) -> None:
        self._conflict = conflict
        self._fail = fail
        self._plan = plan if plan is not None else SimpleNamespace(snapshots={})
        self.applied = False

    def apply(self) -> None:
        if self._conflict:
            raise CONFLICT
        if self._fail:
            raise PLAN_FAILED
        self.applied = True

    def build(self) -> Any:
        return self._plan


class _Adapter:
    """Stands in for a SQLMesh engine adapter (one per gateway)."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Context:
    """Stands in for SQLMesh's ``Context``."""

    def __init__(self, *, conflict: bool, fail: bool = False, plan: Any = None) -> None:
        self._conflict = conflict
        self._fail = fail
        self._plan = plan
        self.plan_calls: list[dict[str, Any]] = []
        self.builders: list[dict[str, Any]] = []
        self.builder_objects: list[_Builder] = []
        # The DuckDB gateway adapter is the one holding the shared file's lock.
        self.duckdb_adapter = _Adapter()
        self.engine_adapters: dict[str, _Adapter] = {"duckdb": self.duckdb_adapter}
        self.config = SimpleNamespace(default_gateway="postgis")
        self.state_reader = SimpleNamespace(get_environment=lambda _name: None)
        self.closed = False

    def plan(self, **kwargs: Any) -> str:
        self.plan_calls.append(kwargs)
        return "plan"

    def plan_builder(self, **kwargs: Any) -> _Builder:
        self.builders.append(kwargs)
        builder = _Builder(conflict=self._conflict, fail=self._fail, plan=self._plan)
        self.builder_objects.append(builder)
        return builder

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A context factory that records how the plan was asked for."""

    def _install(
        *, conflict: bool = False, fail: bool = False, plan: Any = None
    ) -> _Context:
        ctx = _Context(conflict=conflict, fail=fail, plan=plan)
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


class TestRepairingUnbuiltPromotions:
    """A plan that would publish a model nothing built gets it rebuilt.

    SQLMesh derives what to materialize from the plan's *selection* and what to
    publish from the *environment*, so a dependency the plan re-versions without
    selecting it (the region road network behind a routing module, say) is
    promoted into a view over a physical table that does not exist — the plan
    then dies in its promotion stage with ``UndefinedTable``, after backfilling
    everything else.
    """

    def test_restates_an_unbuilt_model_the_state_calls_built(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The table a plan recorded as built before publishing it as missing
        leaves no intervals to schedule, so widening the backfill cannot reach
        it — only restating it, which drops the intervals it holds, can."""
        unbuilt = '"brewgis"."fresno"."road_network_vertices"'
        ctx = context(plan=_plan_with({unbuilt: [(1, 2)]}))
        monkeypatch.setattr(
            sqlmesh_runner, "unbuilt_published_models", lambda _ctx, _plan: [unbuilt]
        )

        run_sqlmesh_plan(
            environment="prod",
            select=["brewgis.ascn7.core_end_state"],
            restate_models=["brewgis.ascn7.core_end_state"],
            always_include_local_changes=True,
            repair_unbuilt_promotions=True,
        )

        assert len(ctx.builders) == 2
        first, second = ctx.builders
        assert "backfill_models" not in first
        assert second["restate_models"] == sorted(
            ["brewgis.ascn7.core_end_state", unbuilt]
        )
        # ``backfill_models`` is what makes it eligible to be scheduled again, and
        # it has to name the caller's own restatements too, since passing it
        # replaces the set SQLMesh derives from them.
        assert second["backfill_models"] == sorted(
            ["brewgis.ascn7.core_end_state", unbuilt]
        )
        assert second["always_include_local_changes"] is True
        assert ctx.builder_objects[-1].applied

    def test_only_widens_a_model_that_still_has_intervals_to_build(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh version is scheduled the moment it is eligible; restating it
        would only drag its downstream — which SQLMesh already re-versions —
        into a rebuild of its own."""
        unbuilt = '"brewgis"."fresno"."road_network_vertices"'
        ctx = context(plan=_plan_with({unbuilt: []}))
        monkeypatch.setattr(
            sqlmesh_runner, "unbuilt_published_models", lambda _ctx, _plan: [unbuilt]
        )

        run_sqlmesh_plan(
            environment="prod",
            select=["brewgis.ascn7.core_end_state"],
            restate_models=["brewgis.ascn7.core_end_state"],
            always_include_local_changes=True,
            repair_unbuilt_promotions=True,
        )

        (_, second) = ctx.builders
        assert second["restate_models"] == ["brewgis.ascn7.core_end_state"]
        assert second["backfill_models"] == sorted(
            ["brewgis.ascn7.core_end_state", unbuilt]
        )

    def test_keeps_the_plan_as_it_is_when_nothing_is_missing(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = context()
        monkeypatch.setattr(
            sqlmesh_runner, "unbuilt_published_models", lambda _ctx, _plan: []
        )

        run_sqlmesh_plan(
            environment="prod",
            select=["brewgis.ascn7.vmt"],
            restate_models=["brewgis.ascn7.vmt"],
            always_include_local_changes=True,
            repair_unbuilt_promotions=True,
        )

        (builder_kwargs,) = ctx.builders
        assert "backfill_models" not in builder_kwargs
        assert ctx.builder_objects[-1].applied

    def test_requires_the_builder_path(self, context) -> None:
        """``Context.plan`` never hands the plan back, so there is nothing to
        inspect; asking for the repair there is a programming error, not a
        silent no-op."""
        ctx = context()

        with pytest.raises(ValueError, match="always_include_local_changes"):
            run_sqlmesh_plan(
                environment="prod",
                select=["brewgis.ascn7.vmt"],
                repair_unbuilt_promotions=True,
            )

        assert ctx.plan_calls == []


def _plan_with(intervals_by_name: dict[str, list[tuple[int, int]]]) -> Any:
    """The parts of a built plan the repair reads, for named snapshots."""
    return SimpleNamespace(
        snapshots={
            name: SimpleNamespace(name=name, intervals=intervals)
            for name, intervals in intervals_by_name.items()
        }
    )


def _promoted(
    name: str,
    *,
    table: str,
    gateway: str | None = None,
    is_model: bool = True,
    evaluatable: bool = True,
) -> tuple[Any, Any]:
    """A promoted snapshot table info and the plan snapshot behind it."""
    info = SimpleNamespace(name=name, snapshot_id=name)
    snapshot = SimpleNamespace(
        name=name,
        model_gateway=gateway,
        table_name=lambda: table,
        is_model=is_model,
        evaluatable=evaluatable,
    )
    return info, snapshot


def _planned_promotions(pairs: list[tuple[Any, Any]], *, restated: set[str]) -> Any:
    """The parts of a built plan ``unbuilt_published_models`` reads."""
    return SimpleNamespace(
        environment=SimpleNamespace(
            name="prod",
            promoted_snapshots=[info for info, _ in pairs],
            can_partially_promote=lambda _stored: False,
        ),
        snapshots={info.snapshot_id: snapshot for info, snapshot in pairs},
        is_selected_for_backfill=lambda name: name in restated,
    )


class TestUnbuiltPublishedModels:
    """Which published snapshots the check calls unbuildable."""

    def test_reports_a_published_model_with_no_table(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = context()
        monkeypatch.setattr(
            sqlmesh_runner, "_existing_relations", lambda _tables: set()
        )
        plan = _planned_promotions(
            [
                _promoted(
                    "brewgis.fresno.road_network_vertices",
                    table="brewgis.sqlmesh__fresno.fresno__road_network_vertices__123",
                )
            ],
            restated=set(),
        )

        assert sqlmesh_runner.unbuilt_published_models(ctx, plan) == [
            "brewgis.fresno.road_network_vertices"
        ]

    def test_ignores_a_model_the_plan_itself_backfills(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = context()
        monkeypatch.setattr(
            sqlmesh_runner, "_existing_relations", lambda _tables: set()
        )
        plan = _planned_promotions(
            [
                _promoted(
                    "brewgis.ascn7.vmt",
                    table="brewgis.sqlmesh__ascn7.ascn7__vmt__123",
                )
            ],
            restated={"brewgis.ascn7.vmt"},
        )

        assert sqlmesh_runner.unbuilt_published_models(ctx, plan) == []

    def test_ignores_a_duckdb_gateway_model(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its tables live in the DuckDB file, so Postgres cannot answer for
        them — reporting a miss would force a pointless re-fetch."""
        ctx = context()
        monkeypatch.setattr(
            sqlmesh_runner, "_existing_relations", lambda _tables: set()
        )
        plan = _planned_promotions(
            [
                _promoted(
                    "duckdb.fresno.overture_transport",
                    table="duckdb.sqlmesh__fresno.fresno__overture_transport__123",
                    gateway="duckdb",
                )
            ],
            restated=set(),
        )

        assert sqlmesh_runner.unbuilt_published_models(ctx, plan) == []

    def test_ignores_a_model_whose_table_exists(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = context()
        monkeypatch.setattr(
            sqlmesh_runner,
            "_existing_relations",
            lambda _tables: {"sqlmesh__fresno.fresno__food_pois_local__123"},
        )
        plan = _planned_promotions(
            [
                _promoted(
                    "brewgis.fresno.food_pois_local",
                    table="brewgis.sqlmesh__fresno.fresno__food_pois_local__123",
                )
            ],
            restated=set(),
        )

        assert sqlmesh_runner.unbuilt_published_models(ctx, plan) == []


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

    def test_releases_when_the_repair_pass_itself_fails(
        self, context, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The repair runs before the plan is applied, inside the same guard —
        a check that raises must not leave the shared DuckDB file locked."""
        ctx = context()

        def _boom(_ctx: Any, _plan: Any) -> list[str]:
            msg = "cannot read the environment"
            raise RuntimeError(msg)

        monkeypatch.setattr(sqlmesh_runner, "unbuilt_published_models", _boom)

        with pytest.raises(RuntimeError, match="cannot read the environment"):
            run_sqlmesh_plan(
                environment="prod",
                select=["brewgis.ascn7.vmt"],
                restate_models=["brewgis.ascn7.vmt"],
                always_include_local_changes=True,
                repair_unbuilt_promotions=True,
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
