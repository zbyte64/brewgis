# ruff: noqa: ARG002
"""Tests for the base-canvas picker form — the fill and the canvases it drives.

Requires a PostgreSQL+PostGIS database: the form's source list is read from the
database and ``scenario_canvas_profiles`` introspects the base table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import settings
from django.urls import reverse

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.models import Layer
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.scenario_canvas import canvas_model_selector
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_link_for_table
from brewgis.workspace.services.sqlmesh_tables import sqlmesh_links_for_tables
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

BASE_TABLE = "public.base_canvas"
VIEW_MODULE = "brewgis.workspace.views.base_canvas"


@dataclass
class _Spy:
    """What the form asked SQLMesh to do, instead of doing it."""

    plans: list[dict[str, Any]] = field(default_factory=list)
    purged: list[list[str]] = field(default_factory=list)


@dataclass
class _TileRequests:
    """What the form asked of the tile server: cache purges, catalog reads."""

    deletes: list[str] = field(default_factory=list)
    catalog_reads: int = 0


@pytest.fixture
def chosen_source(monkeypatch) -> None:
    """Offer the test database's base canvas as the form's only choice.

    The real list is every SQLMesh-managed table with the required columns,
    which the test database has none of.
    """
    monkeypatch.setattr(
        f"{VIEW_MODULE}.list_base_canvas_candidates",
        lambda: [SimpleNamespace(qualified=BASE_TABLE)],
    )


@pytest.fixture
def spy(monkeypatch) -> _Spy:
    captured = _Spy()
    monkeypatch.setattr(
        f"{VIEW_MODULE}.run_sqlmesh_plan",
        lambda **kwargs: captured.plans.append(kwargs),
    )
    monkeypatch.setattr(
        f"{VIEW_MODULE}.ensure_export_exists_isolated", lambda *_, **__: 1
    )
    monkeypatch.setattr(
        f"{VIEW_MODULE}.purge_models_from_environments",
        lambda fqns: captured.purged.append(list(fqns)) or [],
    )
    return captured


def _submit(client: Any, workspace: Any, *, fill: bool) -> Any:
    client.force_login(UserFactory())
    data: dict[str, str] = {"base_table": BASE_TABLE}
    if fill:
        data["fill_built_form"] = "on"
    return client.post(
        reverse("workspace:select_base_canvas", args=[workspace.pk]), data
    )


def _alternative_scenario(workspace: Any, slug: str) -> Any:
    return ScenarioFactory(
        workspace=workspace,
        slug=slug,
        scenario_type=ScenarioType.ALTERNATIVE,
    )


@pytest.mark.views
class TestFillAndCanvasPlans:
    """The form plans the fill *and* the canvas models over it in one plan.

    Any plan promotes the whole environment's virtual layer, which recreates
    every snapshot's view — including the canvas models, whose base this form
    just changed. A canvas a plan selects but does not *build* is promoted
    anyway, with its view pointed at a physical object that does not exist:
    that fails the promotion, fails the request that triggered it, and leaves
    the environment broken for every later plan. Putting both models in one
    plan is what keeps them in step, so the selection is the thing pinned here.
    """

    def test_the_fill_and_the_canvases_share_one_plan(
        self, client, chosen_source, spy, base_canvas_table
    ) -> None:
        workspace = WorkspaceFactory(base_table=BASE_TABLE)
        scenario = _alternative_scenario(workspace, "fill-canvas")
        fill_fqn = f'brewgis."built_form_fill"."fill_{workspace.pk}"'

        response = _submit(client, workspace, fill=True)

        assert response.status_code == 302
        assert len(spy.plans) == 1
        assert spy.plans[0]["environment"] == "prod"
        assert spy.plans[0]["select"] == [fill_fqn, canvas_model_selector(scenario)]

        workspace.refresh_from_db()
        assert workspace.fill_built_form is True
        assert workspace.base_table == BASE_TABLE
        assert (
            workspace.effective_base_table() == f"built_form_fill.fill_{workspace.pk}"
        )
        layer = Layer.objects.get(workspace=workspace, key=BASE_CANVAS_LAYER_KEY)
        assert (layer.db_schema, layer.db_table) == (
            "built_form_fill",
            f"fill_{workspace.pk}",
        )

    def test_unchecking_purges_the_fill_model_and_replans_the_canvases(
        self, client, chosen_source, spy, base_canvas_table
    ) -> None:
        workspace = WorkspaceFactory(base_table=BASE_TABLE, fill_built_form=True)
        scenario = _alternative_scenario(workspace, "unfill-canvas")

        response = _submit(client, workspace, fill=False)

        assert response.status_code == 302
        assert spy.purged == [[f'brewgis."built_form_fill"."fill_{workspace.pk}"']]
        assert len(spy.plans) == 1
        assert spy.plans[0]["select"] == [canvas_model_selector(scenario)]

        workspace.refresh_from_db()
        assert workspace.fill_built_form is False
        assert workspace.effective_base_table() == BASE_TABLE

    def test_a_workspace_without_canvases_plans_the_fill_alone(
        self, client, chosen_source, spy, base_canvas_table
    ) -> None:
        workspace = WorkspaceFactory(base_table=BASE_TABLE)

        assert _submit(client, workspace, fill=True).status_code == 302

        assert spy.plans[0]["select"] == [
            f'brewgis."built_form_fill"."fill_{workspace.pk}"'
        ]

    def test_the_form_offers_the_flag_it_will_save(
        self, client, chosen_source, base_canvas_table
    ) -> None:
        workspace = WorkspaceFactory(base_table=BASE_TABLE, fill_built_form=True)
        client.force_login(UserFactory())

        response = client.get(
            reverse("workspace:select_base_canvas", args=[workspace.pk])
        )

        assert response.status_code == 200
        checkbox = re.search(
            r'<input[^>]*id="id_fill_built_form"[^>]*>', response.content.decode()
        )
        assert checkbox is not None, "the fill checkbox is not on the form"
        assert "checked" in checkbox.group(0)


@pytest.mark.views
class TestPlanInvalidatesRenderedTiles:
    """A plan's rewritten rows must not keep coming back from a tile cache.

    Regression: Martin renders tiles from the database and then keeps them,
    keyed by ``(source, z, x, y)`` with no regard for the request that asked.
    Re-running the fill rewrites rows under a view name Martin already served
    tiles for, so the map went on drawing the *previous* run's parcels — every
    one of them that run's Mixed Use — at exactly the tile extents already
    requested. Zooming in showed the new rows only because those tiles had
    never been rendered before. The form now drops the cached tiles for the
    base layer and for every canvas view over it, which is what the map reads.
    """

    def _record_tile_requests(
        self, monkeypatch: pytest.MonkeyPatch, published: set[str]
    ) -> _TileRequests:
        """Record what the form asks of the tile server, with Martin stubbed out."""
        calls = _TileRequests()

        def fake_delete(url: str, **kwargs: Any) -> Any:
            calls.deletes.append(url)
            return SimpleNamespace(status_code=200, ok=True, text="")

        def fake_catalog() -> set[str]:
            calls.catalog_reads += 1
            return set(published)

        monkeypatch.setattr(
            "brewgis.workspace.services.tile_server.martin_source_ids", fake_catalog
        )
        monkeypatch.setattr(
            "brewgis.workspace.services.tile_server.requests.delete", fake_delete
        )
        return calls

    def test_the_base_canvas_and_the_canvases_over_it_are_purged(
        self,
        client,
        chosen_source,
        spy,
        base_canvas_table,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = WorkspaceFactory(
            base_table=BASE_TABLE, tile_server_backend="martin"
        )
        scenario = _alternative_scenario(workspace, "fill-refresh")
        base_source = f"built_form_fill.fill_{workspace.pk}"
        canvas_source = f"scenario_{scenario.slug}.scenario_{scenario.slug}_canvas"
        calls = self._record_tile_requests(
            monkeypatch, published={base_source, canvas_source}
        )

        assert _submit(client, workspace, fill=True).status_code == 302

        base = settings.TILE_SERVER_MARTIN_URL
        assert calls.deletes == [
            f"{base}/cache/{canvas_source}",
            f"{base}/cache/{base_source}",
        ]

    def test_a_tipg_workspace_asks_the_tile_server_for_nothing(
        self,
        client,
        chosen_source,
        spy,
        base_canvas_table,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """tipg answers straight from the database, so there is nothing to purge."""
        workspace = WorkspaceFactory(base_table=BASE_TABLE)
        _alternative_scenario(workspace, "tipg-refresh")
        calls = self._record_tile_requests(monkeypatch, published=set())

        assert _submit(client, workspace, fill=True).status_code == 302

        assert (calls.deletes, calls.catalog_reads) == ([], 0)


@pytest.mark.views
class TestFillBackedBaseCanvasSqlmeshLink:
    """The base canvas layer links to the model it actually reads.

    Regression: with the fill on, the base canvas reads a *blueprinted* model
    — ``built_form_fill.fill_<workspace pk>``, one per opted-in workspace —
    instead of the source the user picked. That name exists nowhere but the
    database (the model it comes from is ``models/base_canvas/built_form_fill.py``
    instantiated per profile), so the layer resolved to no model: its
    ``db_schema`` is the deliberately unimportable ``built_form_fill`` and its
    table name matches no model file, while the model is sitting right there in
    the SQLMesh UI data catalog. The layer panel, the layer-groups panel and
    the symbology editor all read the link through ``sqlmesh_links_for_tables``.
    """

    def _links_for(self, workspace: Any, layer: Any) -> dict[Any, str]:
        return sqlmesh_links_for_tables(
            {layer.pk: (layer.db_schema or workspace.db_schema, layer.db_table)}
        )

    def test_the_fill_backed_base_canvas_links_to_its_fill_model(
        self, client, chosen_source, spy, base_canvas_table
    ) -> None:
        workspace = WorkspaceFactory(base_table=BASE_TABLE)
        assert _submit(client, workspace, fill=True).status_code == 302

        layer = Layer.objects.get(workspace=workspace, key=BASE_CANVAS_LAYER_KEY)
        links = self._links_for(workspace, layer)

        assert links[layer.pk].endswith(
            f"/data-catalog/models/brewgis.built_form_fill.fill_{workspace.pk}"
        )

    def test_a_fill_model_links_only_while_its_workspace_has_the_fill_on(
        self, base_canvas_table
    ) -> None:
        """The worked-through case and its boundary in one place.

        A workspace with the fill on has exactly one fill model in the project
        (that is what the blueprint macro filters on), so the link must exist;
        flipping the flag off takes the model out of the project, so a layer
        still pointing at its name must not keep a link to a model that is no
        longer defined.
        """
        workspace = WorkspaceFactory(base_table=BASE_TABLE, fill_built_form=True)
        qualified = f"built_form_fill.fill_{workspace.pk}"

        link = sqlmesh_link_for_table(*qualified.split("."))
        assert link is not None, "the fill model has no link"
        assert link.endswith(f"/data-catalog/models/brewgis.{qualified}")

        workspace.fill_built_form = False
        workspace.save(update_fields=["fill_built_form"])

        assert sqlmesh_link_for_table(*qualified.split(".")) is None
