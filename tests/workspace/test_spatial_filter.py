"""Tests for layer filters, materialized as a new layer.

Applying a filter never touches the layer it filters: the matching rows are
materialized by a blueprinted SQLMesh model (``spatial_filter``, one per applied
filter, probing a projection per spatial filter source,
``spatial_filter_source``) and registered as a new Layer. These tests pin the
predicate that model selects with, the preview compiler's decision to ignore
spatial nodes, the profiles SQLMesh instantiates each model from, the new
layer's lifecycle, and that the filtered layer stays exactly as it was.
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
from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerFilter
from brewgis.workspace.models import LayerGroup
from brewgis.workspace.services.filter_compiler import FilterCompiler
from brewgis.workspace.services.spatial_filter import SPATIAL_FILTER_SCHEMA
from brewgis.workspace.services.spatial_filter import all_filter_sources
from brewgis.workspace.services.spatial_filter import apply_filter
from brewgis.workspace.services.spatial_filter import filter_model_fqn
from brewgis.workspace.services.spatial_filter import filter_model_table
from brewgis.workspace.services.spatial_filter import filter_source_model_fqn
from brewgis.workspace.services.spatial_filter import filter_source_model_table
from brewgis.workspace.services.spatial_filter import filter_source_of_node
from brewgis.workspace.services.spatial_filter import filter_sources
from brewgis.workspace.services.spatial_filter import geometry_column
from brewgis.workspace.services.spatial_filter import layer_owns_filter_models
from brewgis.workspace.services.spatial_filter import model_backed_table_ref
from brewgis.workspace.services.spatial_filter import registered_geometry_column
from brewgis.workspace.services.spatial_filter import spatial_predicate
from brewgis.workspace.services.spatial_filter import table_ref
from brewgis.workspace.services.spatial_filter import unapply_filter
from brewgis.workspace.services.sqlmesh_tables import _model_backed_tables
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory
from tests.factories import StyleClassFactory
from tests.factories import SymbologyConfigFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.http import HttpResponse
    from django.test import Client

# A projected CRS (CA Albers, metres) — the region's local CRS in these tests.
_LOCAL_SRID = 3310

# A resolved projection FQN, as the blueprint macro injects it into a profile's
# copy of a condition.
_FILTER_REF = 'brewgis."spatial_filter"."src_deadbeef"'

_DU_EQ_5 = {
    "type": "column",
    "field": "du",
    "operator": "eq",
    "value": "5",
    "value_type": "number",
}


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


def _stored(node: dict) -> dict:
    """*node* as the editor stores it — without the macro-injected ``filter_ref``."""
    return {key: value for key, value in node.items() if key != "filter_ref"}


def _predicate(node: dict, *, source_geom: str = "geometry", mpu: float = 1.0) -> str:
    """Compile one spatial *node* for a metres-per-unit factor of *mpu*."""
    return spatial_predicate(
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


class TestSpatialPredicate:
    """The SQL one spatial condition contributes to the filter model's WHERE."""

    def test_intersects_without_buffer(self) -> None:
        sql = _predicate(_node())
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
        assert _predicate(_node(mode="excludes")).startswith(
            "NOT EXISTS (SELECT 1 FROM "
        )

    def test_buffer_is_converted_from_metres(self) -> None:
        sql = _predicate(_node(buffer_meters=500))
        assert "ST_DWithin(" in sql
        # mpu 1.0 is a metre-based CRS: 500 metres is 500 units. The number is
        # rendered from the metres-per-unit factor, never assumed.
        assert "500.0)" in sql
        assert "ST_Intersects(" not in sql

    def test_buffer_scales_by_metres_per_unit(self) -> None:
        """A CRS in US survey feet needs the metre buffer divided by ~3.28."""
        assert "1640.416" in _predicate(
            _node(buffer_meters=500), mpu=0.30480060960121924
        )

    def test_own_source_geometry_column_is_used(self) -> None:
        sql = _predicate(_node(), source_geom="local_geometry")
        assert f'ST_Transform(src."local_geometry", {_LOCAL_SRID})' in sql

    def test_zero_buffer_is_a_plain_intersection(self) -> None:
        assert "ST_DWithin(" not in _predicate(_node(buffer_meters=0))


class TestFilteredRows:
    """The rows a filter model selects, run against PostGIS.

    The whole tree — column and spatial conditions under any group operator —
    is one predicate, so an ``OR`` across a spatial and a column condition keeps
    the rows either one matches.
    """

    @pytest.fixture
    def rows(self, db) -> Iterator[None]:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cursor.execute("DROP SCHEMA IF EXISTS filter_rows_probe CASCADE")
            cursor.execute("CREATE SCHEMA filter_rows_probe")
            # The filtered layer: three parcels along a line, 4326.
            cursor.execute(
                "CREATE TABLE filter_rows_probe.parcels AS "
                "SELECT * FROM (VALUES "
                "(1, 'residential', ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 3310), 4326)),"
                "(2, 'commercial', ST_Transform(ST_SetSRID(ST_MakePoint(100, 0), 3310), 4326)),"
                "(3, 'residential', ST_Transform(ST_SetSRID(ST_MakePoint(10000, 0), 3310), 4326))"
                ") AS t(id, land_use, geometry)"
            )
            # A projected filter source, as spatial_filter_source materializes it.
            cursor.execute(
                "CREATE TABLE filter_rows_probe.proj AS "
                "SELECT ST_SetSRID(ST_MakePoint(0, 0), 3310) AS sf_geometry"
            )
        yield
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS filter_rows_probe CASCADE")

    @staticmethod
    def _ids(tree: dict) -> list[int]:
        where = FilterCompiler().compile(
            tree, source_geom="geometry", local_srid=_LOCAL_SRID, mpu=1.0
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT src.id FROM filter_rows_probe.parcels AS src WHERE {where} "  # noqa: S608 (compiled predicate)
                "ORDER BY src.id"
            )
            return [row[0] for row in cursor.fetchall()]

    def _near(self, **overrides: object) -> dict:
        return _node(filter_ref="filter_rows_probe.proj", **overrides)

    def test_buffer_selects_rows_within_the_distance(self, rows) -> None:
        assert self._ids(self._near(buffer_meters=150)) == [1, 2]

    def test_excludes_keeps_the_rows_outside(self, rows) -> None:
        assert self._ids(self._near(mode="excludes", buffer_meters=150)) == [3]

    def test_column_and_spatial_conditions_combine(self, rows) -> None:
        residential = {
            "type": "column",
            "field": "land_use",
            "operator": "eq",
            "value": "residential",
        }
        near = self._near(buffer_meters=150)
        both = {"type": "group", "operator": "AND", "children": [residential, near]}
        either = {"type": "group", "operator": "OR", "children": [residential, near]}
        assert self._ids(both) == [1]
        assert self._ids(either) == [1, 2, 3]


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

    def test_filter_table_name_is_keyed_on_the_filter(self) -> None:
        assert filter_model_table(42) == "filter_42"

    def test_filter_fqn_quotes_every_part(self) -> None:
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
    """How a filter model names the tables it reads."""

    def test_external_model_uses_a_bare_two_part_reference(self, db) -> None:
        # Declared in sqlmesh/external_models.yaml as brewgis.public.base_canvas;
        # SQLMesh qualifies the bare form against the project.
        assert table_ref("public", "base_canvas") == "public.base_canvas"

    def test_model_backed_table_uses_the_project_fqn(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "brewgis.workspace.services.sqlmesh_tables._model_backed_tables",
            lambda: frozenset({("sacog", "parcels")}),
        )
        assert model_backed_table_ref("sacog", "parcels") == "brewgis.sacog.parcels"
        assert table_ref("sacog", "parcels") == "brewgis.sacog.parcels"

    def test_any_other_table_is_read_by_its_bare_name(self, db) -> None:
        # An imported shapefile is filtered like any other layer: the model only
        # has to read it.
        assert table_ref("public", "my_import") == "public.my_import"

    def test_an_applied_filters_table_is_model_backed(self, db) -> None:
        """A filtered layer can itself be filtered, through its model's FQN."""
        flt = LayerFilter.objects.create(
            layer=LayerFactory(), name="DU", filter_json=_DU_EQ_5
        )
        table = (SPATIAL_FILTER_SCHEMA, filter_model_table(flt.pk))
        assert table not in _model_backed_tables()

        apply_filter(flt)

        assert table in _model_backed_tables()


class TestApplyFilter:
    """Applying a filter creates a new layer and leaves the filtered one alone."""

    @pytest.fixture
    def source(self, db) -> Layer:
        workspace_layer = LayerFactory(
            name="Parcels",
            db_schema="sacog",
            db_table="parcels",
            geometry_type="fill",
            display_order=3,
        )
        workspace_layer.group = LayerGroup.objects.create(
            workspace=workspace_layer.workspace, name="Land"
        )
        workspace_layer.scenario = ScenarioFactory(workspace=workspace_layer.workspace)
        workspace_layer.save()
        return workspace_layer

    def test_a_new_layer_draws_the_filters_table(self, source) -> None:
        flt = LayerFilter.objects.create(
            layer=source, name="Five DU", filter_json=_DU_EQ_5
        )

        filtered = apply_filter(flt)

        assert filtered.pk != source.pk
        assert filtered.source_table() == (SPATIAL_FILTER_SCHEMA, f"filter_{flt.pk}")
        assert filtered.name == "Parcels — Five DU"
        assert flt.filtered_layer == filtered
        assert filtered.workspace == source.workspace
        assert filtered.group == source.group
        assert filtered.scenario == source.scenario
        assert filtered.geometry_type == source.geometry_type

    def test_the_filtered_layer_is_unchanged(self, source) -> None:
        before = (
            source.source_table(),
            source.to_maplibre_source(),
            source.resolve_tiles_url(),
        )
        flt = LayerFilter.objects.create(
            layer=source, name="Near POIs", filter_json=_stored(_node())
        )

        apply_filter(flt)

        source = Layer.objects.get(pk=source.pk)
        after = (
            source.source_table(),
            source.to_maplibre_source(),
            source.resolve_tiles_url(),
        )
        assert after == before

    def test_symbology_is_copied_not_shared(self, source) -> None:
        config = SymbologyConfigFactory(layer=source, symbology_type="categorical")
        StyleClassFactory(symbology=config, label="A")
        StyleClassFactory(symbology=config, label="B")
        flt = LayerFilter.objects.create(layer=source, name="DU", filter_json=_DU_EQ_5)

        filtered = apply_filter(flt)

        copy = filtered.symbology
        assert copy.pk != config.pk
        assert copy.symbology_type == "categorical"
        assert sorted(c.label for c in copy.classes.all()) == ["A", "B"]
        assert config.classes.count() == 2

    def test_unapplying_deletes_only_the_new_layer(self, source) -> None:
        flt = LayerFilter.objects.create(layer=source, name="DU", filter_json=_DU_EQ_5)
        filtered = apply_filter(flt)

        unapply_filter(flt)

        assert not Layer.objects.filter(pk=filtered.pk).exists()
        assert Layer.objects.filter(pk=source.pk).exists()
        assert LayerFilter.objects.get(pk=flt.pk).filtered_layer is None

    def test_deleting_the_filter_deletes_its_layer(self, source) -> None:
        flt = LayerFilter.objects.create(layer=source, name="DU", filter_json=_DU_EQ_5)
        filtered = apply_filter(flt)

        flt.delete()

        assert not Layer.objects.filter(pk=filtered.pk).exists()

    def test_deleting_the_new_layer_unapplies_the_filter(self, source) -> None:
        flt = LayerFilter.objects.create(layer=source, name="DU", filter_json=_DU_EQ_5)
        filtered = apply_filter(flt)
        assert layer_owns_filter_models(filtered)

        filtered.delete()

        assert LayerFilter.objects.get(pk=flt.pk).filtered_layer is None

    def test_deleting_the_filtered_layer_deletes_the_new_layer(self, source) -> None:
        flt = LayerFilter.objects.create(layer=source, name="DU", filter_json=_DU_EQ_5)
        filtered = apply_filter(flt)
        assert layer_owns_filter_models(source)

        source.delete()

        assert not Layer.objects.filter(pk=filtered.pk).exists()

    def test_a_layer_with_only_unapplied_filters_owns_no_models(self, source) -> None:
        LayerFilter.objects.create(layer=source, name="DU", filter_json=_DU_EQ_5)
        assert not layer_owns_filter_models(source)


class TestFilterSourceTraversal:
    """Which sources a plan has to build projections for."""

    _TREE = {
        "type": "group",
        "operator": "AND",
        "children": [
            _stored(_node(source="poi.points")),
            _stored(_node(source="poi.points", mode="excludes")),
            _DU_EQ_5,
            _stored(_node(source="other.stops", source_geom="geom")),
        ],
    }

    def test_node_sources_are_deduped_and_ordered(self) -> None:
        assert filter_sources(self._TREE) == [
            ("poi", "points", "geometry"),
            ("other", "stops", "geom"),
        ]

    def test_only_applied_filters_need_projections(self, db) -> None:
        layer = LayerFactory()
        flt = LayerFilter.objects.create(
            layer=layer, name="Mixed", filter_json=self._TREE
        )
        assert all_filter_sources() == []

        apply_filter(flt)

        assert all_filter_sources() == [
            ("poi", "points", "geometry"),
            ("other", "stops", "geom"),
        ]

    def test_column_filters_contribute_no_sources(self) -> None:
        assert filter_sources(_DU_EQ_5) == []


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

    def test_unapplied_filters_yield_no_profiles(self, db) -> None:
        LayerFilter.objects.create(
            layer=LayerFactory(), name="Near POIs", filter_json=_stored(_node())
        )
        assert spatial_filter_profiles() == []
        assert spatial_filter_source_profiles() == []
        assert spatial_filter_model_fqns() == []

    def test_column_only_filter_gets_a_model(self, db) -> None:
        layer = LayerFactory(db_schema="public", db_table="base_canvas")
        flt = LayerFilter.objects.create(layer=layer, name="DU", filter_json=_DU_EQ_5)
        apply_filter(flt)

        profiles = spatial_filter_profiles()

        assert [profile["model_table"] for profile in profiles] == [f"filter_{flt.pk}"]
        assert profiles[0]["filter_json"] == _DU_EQ_5
        assert spatial_filter_source_profiles() == []

    def test_source_profile_carries_the_projection_facts(
        self, db, geometry_probe_tables
    ) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(),
            name="Near places",
            filter_json=_stored(
                _node(source="spatial_filter_probe.places", source_geom="geom")
            ),
        )
        apply_filter(flt)

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
        stored = _stored(
            _node(
                source="spatial_filter_probe.places",
                source_geom="geom",
                buffer_meters=250,
            )
        )
        tree = {"type": "group", "operator": "OR", "children": [_DU_EQ_5, stored]}
        flt = LayerFilter.objects.create(
            layer=layer, name="Near places", filter_json=tree
        )
        apply_filter(flt)

        profiles = spatial_filter_profiles()

        assert len(profiles) == 1
        profile = profiles[0]
        assert profile["model_table"] == f"filter_{flt.pk}"
        assert profile["source_ref"] == "public.base_canvas"
        assert profile["source_geom"] == "geometry"
        columns = profile["all_columns"]
        assert isinstance(columns, list)
        assert "geometry" in columns
        assert "parcel_id" in columns
        # The profile's copy is the stored tree with each spatial condition
        # naming the projection it reads — the stored tree itself never carries
        # that key, because the editor and the preview read the same tree.
        assert profile["filter_json"] == {
            **tree,
            "children": [
                _DU_EQ_5,
                {
                    **stored,
                    "filter_ref": filter_source_model_fqn(
                        "spatial_filter_probe", "places", "geom"
                    ),
                },
            ],
        }
        assert "filter_ref" not in json.dumps(
            LayerFilter.objects.get(pk=flt.pk).filter_json
        )

    def test_filter_on_an_unreadable_table_is_skipped(
        self, db, geometry_probe_tables
    ) -> None:
        """One bad filter is left out; its resolvable sibling still gets a model."""
        good = LayerFilter.objects.create(
            layer=LayerFactory(key="good", db_schema="public", db_table="base_canvas"),
            name="Near places",
            filter_json=_stored(
                _node(source="spatial_filter_probe.places", source_geom="geom")
            ),
        )
        bad = LayerFilter.objects.create(
            layer=LayerFactory(
                key="bad", db_schema="public", db_table="not_a_known_table"
            ),
            name="DU",
            filter_json=_DU_EQ_5,
        )
        apply_filter(good)
        apply_filter(bad)

        profiles = spatial_filter_profiles()

        assert [profile["model_table"] for profile in profiles] == [f"filter_{good.pk}"]

    def test_filter_whose_source_has_no_projection_is_skipped(
        self, db, geometry_probe_tables
    ) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(db_schema="public", db_table="base_canvas"),
            name="Near attributes",
            filter_json=_stored(
                _node(source="spatial_filter_probe.attributes", source_geom="name")
            ),
        )
        apply_filter(flt)

        assert spatial_filter_source_profiles() == []
        assert spatial_filter_profiles() == []

    def test_model_fqns_cover_both_model_kinds(self, db, geometry_probe_tables) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(db_schema="public", db_table="base_canvas"),
            name="Near places",
            filter_json=_stored(
                _node(source="spatial_filter_probe.places", source_geom="geom")
            ),
        )
        apply_filter(flt)

        assert sorted(spatial_filter_model_fqns()) == sorted(
            [
                filter_model_fqn(flt.pk),
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


class TestFilterLayerViews:
    """The filter list's toggle applies a filter as a new layer, or removes it.

    Every change to a filtered layer reloads the page: the map resolves its
    layers and their tile sources when it renders.
    """

    @pytest.fixture
    def logged_in_client(self, client, user) -> Client:
        client.force_login(user)
        return client

    @pytest.mark.parametrize(
        "tree", [_DU_EQ_5, _stored(_node())], ids=["column", "spatial"]
    )
    def test_toggling_creates_a_new_layer_and_reloads(
        self, logged_in_client, db, tree
    ) -> None:
        layer = LayerFactory()
        before = layer.source_table()
        flt = LayerFilter.objects.create(layer=layer, name="Picked", filter_json=tree)

        response = logged_in_client.post(
            reverse("workspace:layer_filter_toggle", kwargs={"pk": flt.pk})
        )

        assert response.status_code == 200
        assert response["HX-Refresh"] == "true"
        assert "HX-Trigger" not in response
        filtered = LayerFilter.objects.get(pk=flt.pk).filtered_layer
        assert filtered is not None
        assert filtered.pk != layer.pk
        assert Layer.objects.get(pk=layer.pk).source_table() == before

    def test_toggling_an_applied_filter_removes_its_layer(
        self, logged_in_client, db
    ) -> None:
        layer = LayerFactory()
        flt = LayerFilter.objects.create(layer=layer, name="DU", filter_json=_DU_EQ_5)
        filtered = apply_filter(flt)

        response = logged_in_client.post(
            reverse("workspace:layer_filter_toggle", kwargs={"pk": flt.pk})
        )

        assert response["HX-Refresh"] == "true"
        assert not Layer.objects.filter(pk=filtered.pk).exists()
        assert Layer.objects.filter(pk=layer.pk).exists()

    def test_deleting_an_applied_filter_reloads_the_page(
        self, logged_in_client, db
    ) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(), name="DU", filter_json=_DU_EQ_5
        )
        filtered = apply_filter(flt)

        response = logged_in_client.post(
            reverse("workspace:layer_filter_delete", kwargs={"pk": flt.pk})
        )

        assert response.status_code == 200
        assert response["HX-Refresh"] == "true"
        assert not Layer.objects.filter(pk=filtered.pk).exists()

    def test_deleting_an_unapplied_filter_does_not_reload(
        self, logged_in_client, db
    ) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(), name="DU", filter_json=_DU_EQ_5
        )

        response = logged_in_client.post(
            reverse("workspace:layer_filter_delete", kwargs={"pk": flt.pk})
        )

        assert "HX-Refresh" not in response

    def test_editing_an_applied_filter_reloads_the_page(
        self, logged_in_client, db
    ) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(), name="DU", filter_json=_DU_EQ_5
        )
        apply_filter(flt)

        response = logged_in_client.post(
            reverse("workspace:layer_filter_edit", kwargs={"pk": flt.pk}),
            {"name": "Near POIs", "filter_json": json.dumps(_stored(_node()))},
        )

        assert response.status_code == 200
        assert response["HX-Refresh"] == "true"

    def test_editing_an_unapplied_filter_does_not_reload(
        self, logged_in_client, db
    ) -> None:
        flt = LayerFilter.objects.create(
            layer=LayerFactory(), name="DU", filter_json=_DU_EQ_5
        )

        response = logged_in_client.post(
            reverse("workspace:layer_filter_edit", kwargs={"pk": flt.pk}),
            {"name": "Near POIs", "filter_json": json.dumps(_stored(_node()))},
        )

        assert response.status_code == 200
        assert "HX-Refresh" not in response
