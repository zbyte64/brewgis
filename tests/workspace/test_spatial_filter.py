"""Tests for geospatial layer filters.

A ``spatial`` node cannot be evaluated client-side, so it is compiled to SQL
(``services.spatial_filter``) and materialized by two blueprinted SQLMesh models:
a projection per filter source (``spatial_filter_source``) and a copy of the
filtered layer that probes it (``spatial_filter``). These tests pin the
predicate's shape, the client-side compiler's decision to ignore the node, the
profiles SQLMesh instantiates each model from, and the source resolution that
decides whether a layer can have one at all.
"""

from __future__ import annotations

import json
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.urls import reverse

from brewgis.sqlmesh.macros.spatial_filter_blueprints import MODEL_SCHEMA
from brewgis.sqlmesh.macros.spatial_filter_blueprints import spatial_filter_model_fqns
from brewgis.sqlmesh.macros.spatial_filter_blueprints import spatial_filter_profiles
from brewgis.sqlmesh.macros.spatial_filter_blueprints import (
    spatial_filter_source_profiles,
)
from brewgis.workspace.models import LayerFilter
from brewgis.workspace.services.filter_compiler import FilterCompiler
from brewgis.workspace.services.spatial_filter import SPATIAL_FILTER_SCHEMA
from brewgis.workspace.services.spatial_filter import all_filter_sources
from brewgis.workspace.services.spatial_filter import compile_spatial_predicate
from brewgis.workspace.services.spatial_filter import filter_model_fqn
from brewgis.workspace.services.spatial_filter import filter_model_table
from brewgis.workspace.services.spatial_filter import filter_source_model_fqn
from brewgis.workspace.services.spatial_filter import filter_source_model_table
from brewgis.workspace.services.spatial_filter import filter_source_of_node
from brewgis.workspace.services.spatial_filter import filter_source_ref
from brewgis.workspace.services.spatial_filter import geometry_column
from brewgis.workspace.services.spatial_filter import has_spatial_node
from brewgis.workspace.services.spatial_filter import layer_filter_sources
from brewgis.workspace.services.spatial_filter import layer_has_active_spatial_filter
from brewgis.workspace.services.spatial_filter import model_backed_table_ref
from brewgis.workspace.services.spatial_filter import registered_geometry_column
from brewgis.workspace.services.spatial_filter import source_ref_for_layer
from brewgis.workspace.services.spatial_filter import spatial_nodes
from tests.factories import LayerFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.http import HttpResponse
    from django.test import Client

    from brewgis.workspace.models import Layer

# A projected CRS (CA Albers) — the predicate only ever embeds the number.
_LOCAL_SRID = 3310

# A resolved projection FQN, as the blueprint macro injects it into a profile's
# copy of a condition.
_FILTER_REF = 'brewgis."spatial_filter"."src_deadbeef"'


def _node(**overrides: object) -> dict:
    """Build a ``spatial`` node with a buffer-less intersection's defaults."""
    node: dict = {
        "type": "spatial",
        "mode": "intersects",
        "source": "poi.points",
        "source_geom": "geometry",
        "buffer_meters": None,
        "filter_ref": _FILTER_REF,
    }
    node.update(overrides)
    return node


def _compile(node: dict, *, source_geom: str = "geometry", mpu: float = 1.0) -> str:
    """Compile *node*'s spatial predicate for a metres-per-unit factor of *mpu*."""
    return compile_spatial_predicate(
        node, source_geom=source_geom, local_srid=_LOCAL_SRID, mpu=mpu
    )


@pytest.fixture
def geometry_probe_tables(db) -> Iterator[None]:
    """A schema with one geometry-bearing table and one attribute-only table.

    Created explicitly rather than borrowed from a Django-managed table: only a
    table PostGIS's ``geometry_columns`` lists is offered as a spatial filter
    source, and this pins both sides of that check.
    """
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute("DROP SCHEMA IF EXISTS spatial_filter_probe CASCADE")
        cursor.execute("CREATE SCHEMA spatial_filter_probe")
        cursor.execute(
            "CREATE TABLE spatial_filter_probe.places "
            "(id integer, geom geometry(Point, 4326))"
        )
        cursor.execute(
            "CREATE TABLE spatial_filter_probe.attributes (id integer, name text)"
        )
    yield
    with connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS spatial_filter_probe CASCADE")


class TestHasSpatialNode:
    """Detection drives both the blueprint profiles and the tile-source routing."""

    def test_spatial_node_detected(self) -> None:
        assert has_spatial_node(_node()) is True

    def test_nested_spatial_node_detected(self) -> None:
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {"type": "column", "field": "du"},
                {"type": "group", "operator": "OR", "children": [_node()]},
            ],
        }
        assert has_spatial_node(tree) is True

    def test_column_only_tree_is_not_spatial(self) -> None:
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [{"type": "column", "field": "du"}],
        }
        assert has_spatial_node(tree) is False

    def test_non_dict_and_empty_group_are_not_spatial(self) -> None:
        assert has_spatial_node(None) is False
        assert has_spatial_node([]) is False
        assert has_spatial_node({"type": "group", "children": []}) is False


class TestCompileSpatialPredicate:
    """The SQL the layer model's WHERE clause is built from."""

    def test_intersects_without_buffer(self) -> None:
        sql = _compile(_node())
        assert sql.startswith("EXISTS (SELECT 1 FROM ")
        assert "ST_Intersects(" in sql
        assert "ST_DWithin(" not in sql
        # Only the filtered layer's side is transformed: the filter side is the
        # projection model, whose geometry is already in the region's CRS behind
        # a GiST index — transforming it inline would make that index unusable
        # and turn the probe into a sequential scan of a view.
        assert sql.count("ST_Transform(") == 1
        assert f'ST_Transform(src."geometry", {_LOCAL_SRID})' in sql
        assert f"FROM {_FILTER_REF} AS f" in sql
        assert 'f."sf_geometry"' in sql

    def test_excludes_negates_the_exists(self) -> None:
        sql = _compile(_node(mode="excludes"))
        assert sql.startswith("NOT EXISTS (SELECT 1 FROM ")

    def test_buffer_is_converted_from_metres(self) -> None:
        sql = _compile(_node(buffer_meters=500))
        assert "ST_DWithin(" in sql
        # mpu 1.0 is a metre-based CRS: 500 metres is 500 units. The number is
        # rendered from the metres-per-unit factor, never assumed.
        assert "500.0)" in sql
        assert "ST_Intersects(" not in sql

    def test_buffer_scales_by_metres_per_unit(self) -> None:
        """A CRS in US survey feet needs the metre buffer divided by ~3.28."""
        sql = _compile(_node(buffer_meters=500), mpu=0.30480060960121924)
        assert "1640.416" in sql

    def test_own_source_geometry_column_is_used(self) -> None:
        sql = _compile(_node(), source_geom="local_geometry")
        assert f'ST_Transform(src."local_geometry", {_LOCAL_SRID})' in sql

    def test_group_keeps_only_the_spatial_child(self) -> None:
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [{"type": "column", "field": "du"}, _node()],
        }
        sql = _compile(tree)
        assert sql.startswith("(EXISTS (SELECT 1 FROM ")
        assert sql.endswith("))")
        assert "du" not in sql

    def test_group_with_two_spatial_children_joins_with_the_operator(self) -> None:
        tree = {
            "type": "group",
            "operator": "OR",
            "children": [
                _node(filter_ref='brewgis."spatial_filter"."src_one"'),
                _node(filter_ref='brewgis."spatial_filter"."src_two"'),
            ],
        }
        sql = _compile(tree)
        assert " OR " in sql
        assert '"src_one"' in sql
        assert '"src_two"' in sql

    def test_column_only_tree_has_no_predicate(self) -> None:
        assert _compile({"type": "column", "field": "du"}) == ""

    def test_empty_and_missing_trees_have_no_predicate(self) -> None:
        assert _compile({}) == ""
        assert (
            compile_spatial_predicate(
                None, source_geom="geometry", local_srid=_LOCAL_SRID, mpu=1.0
            )
            == ""
        )

    def test_zero_buffer_is_a_plain_intersection(self) -> None:
        assert "ST_DWithin(" not in _compile(_node(buffer_meters=0))


class TestClientSideSkip:
    """The map's own filter expression ignores spatial nodes."""

    def test_spatial_node_compiles_to_true(self) -> None:
        assert FilterCompiler().compile_to_maplibre(_node()) == ["literal", True]

    def test_group_drops_the_spatial_child(self) -> None:
        tree = {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "column",
                    "field": "du",
                    "operator": "eq",
                    "value": "5",
                    "value_type": "number",
                },
                _node(),
            ],
        }
        assert FilterCompiler().compile_to_maplibre(tree) == [
            "and",
            ["==", ["get", "du"], 5.0],
        ]

    def test_group_of_only_spatial_children_is_true(self) -> None:
        tree = {"type": "group", "operator": "OR", "children": [_node()]}
        assert FilterCompiler().compile_to_maplibre(tree) == ["literal", True]


class TestModelNaming:
    """Both models' names are derivable from their input alone, by both sides."""

    def test_layer_table_name_is_keyed_on_the_layer(self) -> None:
        assert filter_model_table(42) == "filter_42"

    def test_layer_fqn_quotes_every_part(self) -> None:
        assert filter_model_fqn(42) == f'brewgis."{SPATIAL_FILTER_SCHEMA}"."filter_42"'

    def test_source_table_name_is_keyed_on_the_source_identity(self) -> None:
        table = filter_source_model_table("poi", "points", "geometry")
        assert table.startswith("src_")
        # Same source, same model: every condition over one table shares it.
        assert filter_source_model_table("poi", "points", "geometry") == table
        # A different geometry column is a different projection.
        assert filter_source_model_table("poi", "points", "centroid") != table
        # So is a different table with the same name in another schema.
        assert filter_source_model_table("other", "points", "geometry") != table

    def test_source_fqn_quotes_every_part(self) -> None:
        table = filter_source_model_table("poi", "points", "geometry")
        assert (
            filter_source_model_fqn("poi", "points", "geometry")
            == f'brewgis."{SPATIAL_FILTER_SCHEMA}"."{table}"'
        )

    def test_macro_schema_matches_the_service(self) -> None:
        """The macro cannot import the service (it loads before Django), so pin it."""
        assert MODEL_SCHEMA == SPATIAL_FILTER_SCHEMA


class TestNodeSource:
    """How a condition's table is read."""

    def test_table_schema_and_geometry_are_read(self) -> None:
        assert filter_source_of_node(_node()) == ("poi", "points", "geometry")

    def test_missing_geometry_column_falls_back_to_the_conventional_name(self) -> None:
        assert filter_source_of_node(_node(source_geom=None)) == (
            "poi",
            "points",
            "geometry",
        )

    def test_unqualified_table_is_read_from_the_public_schema(self) -> None:
        assert filter_source_of_node(_node(source="points")) == (
            "public",
            "points",
            "geometry",
        )

    def test_unfinished_condition_resolves_to_nothing(self) -> None:
        assert filter_source_of_node(_node(source="")) is None


class TestSourceResolution:
    """Which tables each model may read from, and how they are named."""

    def test_external_model_uses_a_bare_two_part_reference(self, db) -> None:
        # Declared in sqlmesh/external_models.yaml as brewgis.public.base_canvas;
        # SQLMesh qualifies the bare form against the project.
        assert source_ref_for_layer("public", "base_canvas") == "public.base_canvas"

    def test_model_backed_table_uses_the_project_fqn(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "brewgis.workspace.services.sqlmesh_tables._model_backed_tables",
            lambda: frozenset({("sacog", "parcels")}),
        )
        assert model_backed_table_ref("sacog", "parcels") == "brewgis.sacog.parcels"
        assert source_ref_for_layer("sacog", "parcels") == "brewgis.sacog.parcels"

    def test_unknown_table_resolves_to_nothing_for_a_filtered_layer(self, db) -> None:
        assert source_ref_for_layer("public", "no_such_table_xyz") is None

    def test_unknown_table_still_resolves_for_a_filter_source(self, db) -> None:
        # A filter source only has to be readable — the projection copies it and
        # adds no dependency — so it never needs a model-backed reference.
        assert filter_source_ref("public", "no_such_table_xyz") == (
            "public.no_such_table_xyz"
        )


class TestActiveSpatialFilter:
    """Layer-level predicates the views and the tile routing both use."""

    @pytest.fixture
    def layer(self, db) -> Layer:
        return LayerFactory()

    def test_column_only_filters_do_not_count(self, layer) -> None:
        LayerFilter.objects.create(
            layer=layer,
            name="DU",
            filter_json={
                "type": "group",
                "operator": "AND",
                "children": [{"type": "column", "field": "du"}],
            },
            is_active=True,
        )
        assert layer_has_active_spatial_filter(layer) is False

    def test_inactive_spatial_filter_does_not_count(self, layer) -> None:
        LayerFilter.objects.create(
            layer=layer, name="Near POIs", filter_json=_node(), is_active=False
        )
        assert layer_has_active_spatial_filter(layer) is False

    def test_active_spatial_filter_counts(self, layer) -> None:
        LayerFilter.objects.create(
            layer=layer, name="Near POIs", filter_json=_node(), is_active=True
        )
        assert layer_has_active_spatial_filter(layer) is True


class TestFilterSourceTraversal:
    """Which sources a plan has to build projections for."""

    def test_node_sources_are_deduped_and_ordered(self, db) -> None:
        layer = LayerFactory()
        LayerFilter.objects.create(
            layer=layer,
            name="Near POIs",
            filter_json={
                "type": "group",
                "operator": "AND",
                "children": [
                    _node(source="poi.points"),
                    _node(source="poi.points", mode="excludes"),
                    _node(source="other.stops", source_geom="geom"),
                ],
            },
            is_active=True,
        )

        assert layer_filter_sources(layer) == [
            ("poi", "points", "geometry"),
            ("other", "stops", "geom"),
        ]
        assert all_filter_sources() == [
            ("poi", "points", "geometry"),
            ("other", "stops", "geom"),
        ]

    def test_column_filters_contribute_no_sources(self, db) -> None:
        layer = LayerFactory()
        LayerFilter.objects.create(
            layer=layer,
            name="DU",
            filter_json={"type": "column", "field": "du"},
            is_active=True,
        )
        assert layer_filter_sources(layer) == []
        assert all_filter_sources() == []
        assert spatial_nodes() == {}


class TestGeometryColumn:
    """The picker only offers layers with a geometry ``geometry_columns`` knows."""

    def test_registered_geometry_column_is_returned(
        self, geometry_probe_tables
    ) -> None:
        assert registered_geometry_column("spatial_filter_probe", "places") == "geom"

    def test_table_without_geometry_returns_none(self, geometry_probe_tables) -> None:
        assert registered_geometry_column("spatial_filter_probe", "attributes") is None

    def test_fallback_is_the_conventional_column(self, geometry_probe_tables) -> None:
        assert geometry_column("spatial_filter_probe", "attributes") == "geometry"


class TestSpatialFilterProfiles:
    """The per-model facts SQLMesh instantiates one model from."""

    def test_no_layers_with_spatial_filters_yields_no_profiles(self, db) -> None:
        LayerFactory()
        assert spatial_filter_profiles() == []
        assert spatial_filter_source_profiles() == []
        assert spatial_filter_model_fqns() == []

    def test_column_only_filter_yields_no_profile(self, db) -> None:
        layer = LayerFactory()
        LayerFilter.objects.create(
            layer=layer,
            name="DU",
            filter_json={"type": "column", "field": "du"},
            is_active=True,
        )
        assert spatial_filter_profiles() == []

    def test_source_profile_carries_the_projection_facts(
        self, db, geometry_probe_tables
    ) -> None:
        layer = LayerFactory()
        LayerFilter.objects.create(
            layer=layer,
            name="Near places",
            filter_json=_node(source="spatial_filter_probe.places", source_geom="geom"),
            is_active=True,
        )

        profiles = spatial_filter_source_profiles()

        assert len(profiles) == 1
        profile = profiles[0]
        assert profile["source_model_table"] == filter_source_model_table(
            "spatial_filter_probe", "places", "geom"
        )
        assert profile["source_ref"] == "spatial_filter_probe.places"
        assert profile["source_geom"] == "geom"
        assert profile["all_columns"] == ["id", "geom"]

    def test_profile_carries_the_model_facts_and_resolved_filter_ref(
        self, db, geometry_probe_tables
    ) -> None:
        layer = LayerFactory(
            key="parcels", name="Parcels", db_schema="public", db_table="base_canvas"
        )
        node = _node(
            source="spatial_filter_probe.places",
            source_geom="geom",
            buffer_meters=250,
        )
        stored = {key: value for key, value in node.items() if key != "filter_ref"}
        LayerFilter.objects.create(
            layer=layer, name="Near places", filter_json=stored, is_active=True
        )

        profiles = spatial_filter_profiles()

        assert len(profiles) == 1
        profile = profiles[0]
        assert profile["model_table"] == f"filter_{layer.pk}"
        assert profile["source_ref"] == "public.base_canvas"
        assert profile["source_geom"] == "geometry"
        columns = profile["all_columns"]
        assert isinstance(columns, list)
        assert "geometry" in columns
        assert "parcel_id" in columns
        resolved = profile["spatial_filters"]
        assert isinstance(resolved, list)
        # The profile's copy is the stored condition plus the projection it
        # reads — the stored tree itself never carries that key, because the
        # client-side compiler reads the same tree.
        assert resolved[0] == {
            **stored,
            "filter_ref": filter_source_model_fqn(
                "spatial_filter_probe", "places", "geom"
            ),
        }

    def test_layer_with_an_unresolvable_source_is_skipped(
        self, db, geometry_probe_tables
    ) -> None:
        """One bad layer is left out; its resolvable sibling still gets a model."""
        good = LayerFactory(key="good", db_schema="public", db_table="base_canvas")
        LayerFilter.objects.create(
            layer=good,
            name="Near places",
            filter_json=_node(source="spatial_filter_probe.places", source_geom="geom"),
            is_active=True,
        )
        bad = LayerFactory(key="bad", db_schema="public", db_table="not_a_known_table")
        LayerFilter.objects.create(
            layer=bad, name="Near POIs", filter_json=_node(), is_active=True
        )

        profiles = spatial_filter_profiles()

        assert [profile["model_table"] for profile in profiles] == [f"filter_{good.pk}"]

    def test_layer_whose_filter_source_has_no_projection_is_skipped(
        self, db, geometry_probe_tables
    ) -> None:
        layer = LayerFactory(db_schema="public", db_table="base_canvas")
        LayerFilter.objects.create(
            layer=layer,
            name="Near attributes",
            filter_json=_node(
                source="spatial_filter_probe.attributes", source_geom="name"
            ),
            is_active=True,
        )

        assert spatial_filter_source_profiles() == []
        assert spatial_filter_profiles() == []

    def test_model_fqns_cover_both_model_kinds(self, db, geometry_probe_tables) -> None:
        layer = LayerFactory(db_schema="public", db_table="base_canvas")
        LayerFilter.objects.create(
            layer=layer,
            name="Near places",
            filter_json=_node(source="spatial_filter_probe.places", source_geom="geom"),
            is_active=True,
        )

        assert sorted(spatial_filter_model_fqns()) == sorted(
            [
                filter_model_fqn(layer.pk),
                filter_source_model_fqn("spatial_filter_probe", "places", "geom"),
            ]
        )


def _attr_json(response: HttpResponse) -> str:
    """The response body with Django's attribute autoescaping undone.

    ``json_attr`` output lands in a single-quoted HTML attribute, so Django
    escapes every ``"`` to ``&quot;``; the browser reads the attribute value back
    as the original JSON.
    """
    return unescape(response.content.decode())


class TestEditorLayerOptions:
    """The editor offers the workspace's other layers as spatial sources."""

    @pytest.fixture
    def logged_in_client(self, client, user) -> Client:
        client.force_login(user)
        return client

    def test_registered_geometry_is_offered_with_its_column(
        self, logged_in_client, geometry_probe_tables
    ) -> None:
        layer = LayerFactory(
            key="attrs", db_schema="public", db_table="workspace_layer"
        )
        LayerFactory(
            workspace=layer.workspace,
            key="places",
            name="Places",
            db_schema="spatial_filter_probe",
            db_table="places",
        )

        response = logged_in_client.get(
            reverse("workspace:layer_filter_create", kwargs={"layer_pk": layer.pk})
        )

        assert response.status_code == 200
        body = _attr_json(response)
        assert '"value": "spatial_filter_probe.places"' in body
        # The geometry column comes from geometry_columns, not from a guess at
        # the conventional name — this table's is "geom".
        assert '"geometry": "geom"' in body

    def test_the_filtered_layer_is_not_offered(
        self, logged_in_client, geometry_probe_tables
    ) -> None:
        layer = LayerFactory(
            key="places",
            db_schema="spatial_filter_probe",
            db_table="places",
        )

        response = logged_in_client.get(
            reverse("workspace:layer_filter_create", kwargs={"layer_pk": layer.pk})
        )

        assert '"spatial_filter_probe.places"' not in _attr_json(response)

    def test_layer_without_a_registered_geometry_is_not_offered(
        self, logged_in_client, geometry_probe_tables
    ) -> None:
        layer = LayerFactory(
            key="places",
            db_schema="spatial_filter_probe",
            db_table="places",
        )
        # A table with columns but no geometry: a spatial condition against it
        # could never be compiled, so it is not offered as a source.
        LayerFactory(
            workspace=layer.workspace,
            key="attributes",
            name="Attributes",
            db_schema="spatial_filter_probe",
            db_table="attributes",
        )

        response = logged_in_client.get(
            reverse("workspace:layer_filter_create", kwargs={"layer_pk": layer.pk})
        )

        assert '"spatial_filter_probe.attributes"' not in _attr_json(response)


class TestSpatialFilterViewTriggers:
    """A spatial filter changes the layer's tile source, so the page reloads.

    The map resolves a layer's tile source from the database when it renders, so
    neither a MapLibre filter nor a partial swap can show the new rows: the layer
    keeps requesting the table the page was loaded with. The base-canvas fill
    toggle answers the same problem with a page load.
    """

    @pytest.fixture
    def logged_in_client(self, client, user) -> Client:
        client.force_login(user)
        return client

    def test_toggling_a_spatial_filter_reloads_the_page(
        self, logged_in_client, db
    ) -> None:
        layer = LayerFactory()
        flt = LayerFilter.objects.create(
            layer=layer, name="Near POIs", filter_json=_node(), is_active=False
        )

        response = logged_in_client.post(
            reverse("workspace:layer_filter_toggle", kwargs={"pk": flt.pk})
        )

        assert response.status_code == 200
        assert response["HX-Refresh"] == "true"
        assert "HX-Trigger" not in response

    def test_toggling_a_column_filter_keeps_the_live_preview(
        self, logged_in_client, db
    ) -> None:
        layer = LayerFactory()
        flt = LayerFilter.objects.create(
            layer=layer,
            name="DU",
            filter_json={
                "type": "column",
                "field": "du",
                "operator": "eq",
                "value": "5",
                "value_type": "number",
            },
            is_active=False,
        )

        response = logged_in_client.post(
            reverse("workspace:layer_filter_toggle", kwargs={"pk": flt.pk})
        )

        assert response.status_code == 200
        assert response["HX-Trigger"]
        assert "HX-Refresh" not in response

    def test_deleting_an_active_spatial_filter_reloads_the_page(
        self, logged_in_client, db
    ) -> None:
        layer = LayerFactory()
        flt = LayerFilter.objects.create(
            layer=layer, name="Near POIs", filter_json=_node(), is_active=True
        )

        response = logged_in_client.post(
            reverse("workspace:layer_filter_delete", kwargs={"pk": flt.pk})
        )

        assert response.status_code == 200
        assert response["HX-Refresh"] == "true"

    def test_editing_into_a_spatial_filter_reloads_the_page(
        self, logged_in_client, db
    ) -> None:
        layer = LayerFactory()
        flt = LayerFilter.objects.create(
            layer=layer,
            name="DU",
            filter_json={"type": "column", "field": "du"},
            is_active=True,
        )

        response = logged_in_client.post(
            reverse("workspace:layer_filter_edit", kwargs={"pk": flt.pk}),
            {"name": "Near POIs", "filter_json": json.dumps(_node())},
        )

        assert response.status_code == 200
        assert response["HX-Refresh"] == "true"
