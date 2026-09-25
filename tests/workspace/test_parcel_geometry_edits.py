"""Grid (split) and merge parcel edits in paint mode.

The canvas view's UNION, the attribute allocation and the undo path are all
exercised against a real PostGIS database: the feature rests on the edited
branch of that view carrying the base's *exact* column types, which only a real
``jsonb_populate_record`` against a real table can prove.

Requires PostgreSQL + PostGIS.
"""

# ruff: noqa: ARG002 — pytest fixtures are requested by name and often unused.

from __future__ import annotations

import json
from dataclasses import replace
from math import radians
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.db import connection
from django.db.models import Max
from django.db.models.expressions import RawSQL
from django.urls import reverse

from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import PaintRun
from brewgis.workspace.models import ParcelGeometryEdit
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
from brewgis.workspace.services.canvas_view_manager import _qi
from brewgis.workspace.services.canvas_view_manager import build_canvas_view_select
from brewgis.workspace.views.paint import _allocate_grid_cell
from brewgis.workspace.views.paint import _allocate_merge
from brewgis.workspace.views.paint import _grid_cell_estimate
from brewgis.workspace.views.paint import _quote_qualified_table
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

if TYPE_CHECKING:
    from django.test import Client

FT_TO_M = 0.3048
SQUARE_FT = 200.0
SIDE_M = SQUARE_FT * FT_TO_M
CELL_FT = 100.0

INT_TABLE = "public.parcel_edit_int_fixture"
TEXT_TABLE = "public.parcel_edit_text_fixture"
INT_IDS = ("1001", "1002")
TEXT_IDS = ("APN-1", "APN-2")
TEXT_KEY_TYPE = "varchar(32)"

# du 4 / du 8 over a 200 x 400 ft site: at a 100 ft cell size the grid is 2 x 4
# and every cell falls wholly inside one parcel, so the splits are exact.
PARCEL_DU = (4.0, 8.0)
PARCEL_POP = (40.0, 80.0)
PARCEL_AREA_GROSS = (1.0, 2.0)
PARCEL_BUILDINGS = (4, 8)

_FIXTURE_COLUMNS = """
    du double precision NOT NULL DEFAULT 0,
    pop double precision NOT NULL DEFAULT 0,
    area_gross double precision NOT NULL DEFAULT 0,
    built_form_key text,
    land_development_category text,
    geometry_key text,
    building_count bigint NOT NULL DEFAULT 0,
    is_residential boolean NOT NULL DEFAULT false
"""


def _create_fixture_table(table: str, key_type: str, ids: tuple[str, str]) -> None:
    """Create *table* with two adjacent 200 x 200 ft parcels sharing an edge.

    The squares are built as Web Mercator envelopes and transformed, so the site
    is exactly 200 x 400 ft in the same space the grid works in (and, sitting on
    the equator, in true ground metres too) — which is what makes a 100 ft grid
    divide it into eight cells that each fall inside a single parcel.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        cursor.execute(
            f"CREATE TABLE {table} ("
            f"parcel_id {key_type} PRIMARY KEY, geometry geometry NOT NULL,"
            f"{_FIXTURE_COLUMNS})"
        )
        for index, parcel_id in enumerate(ids):
            low_x = index * SIDE_M
            high_x = (index + 1) * SIDE_M
            cursor.execute(
                f"INSERT INTO {table} "  # noqa: S608 — table is a module constant
                "(parcel_id, geometry, du, pop, area_gross, built_form_key, "
                " land_development_category, geometry_key, building_count, "
                " is_residential) "
                "VALUES (%(parcel_id)s, ST_Transform(ST_SetSRID(ST_MakeEnvelope("
                "%(low_x)s, 0, %(high_x)s, %(side)s), 3857), 4326), "
                "%(du)s, %(pop)s, %(area_gross)s, 'sf_detached', 'urban', "
                "%(geometry_key)s, %(buildings)s, %(residential)s)",
                {
                    "parcel_id": parcel_id,
                    "low_x": low_x,
                    "high_x": high_x,
                    "side": SIDE_M,
                    "du": PARCEL_DU[index],
                    "pop": PARCEL_POP[index],
                    "area_gross": PARCEL_AREA_GROSS[index],
                    "geometry_key": str(parcel_id),
                    "buildings": PARCEL_BUILDINGS[index],
                    "residential": index == 0,
                },
            )


@pytest.fixture
def fixture_tables(db: Any) -> Any:
    """One key-style fixture table per parcel-key flavour (integer and text)."""
    _create_fixture_table(INT_TABLE, "bigint", INT_IDS)
    _create_fixture_table(TEXT_TABLE, TEXT_KEY_TYPE, TEXT_IDS)
    try:
        yield None
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {INT_TABLE} CASCADE")
            cursor.execute(f"DROP TABLE IF EXISTS {TEXT_TABLE} CASCADE")


class _Harness:
    """A workspace + ALTERNATIVE scenario over one fixture table, plus its view."""

    def __init__(self, *, client: Client, table: str, ids: tuple[str, str]) -> None:
        self.client = client
        self.table = table
        self.ids = ids
        self.workspace = WorkspaceFactory(base_table=table)
        self.scenario = ScenarioFactory(
            workspace=self.workspace,
            name=f"Edits over {table}",
            scenario_type=ScenarioType.ALTERNATIVE,
        )
        self.recreate_view()

    def recreate_view(self) -> None:
        """Create the canvas view the way the scenario's SQLMesh model does."""
        _, _, all_columns = _fetch_base_columns(self.workspace.base_table)
        select = build_canvas_view_select(
            base_ref=self.workspace.base_table,
            all_columns=all_columns,
            scenario_id=self.scenario.pk,
        )
        schema, table = self.scenario.base_layer_source()
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_qi(schema)}")
            cursor.execute(
                f"CREATE OR REPLACE VIEW {_qi(f'{schema}.{table}')} AS {select}"
            )

    def post(self, view_name: str, body: dict[str, Any]) -> Any:
        return self.client.post(
            reverse(
                f"workspace:{view_name}",
                args=[self.workspace.pk, self.scenario.pk],
            ),
            data=json.dumps(body),
            content_type="application/json",
        )

    def grid(
        self, features: Any, cell_size_ft: float = CELL_FT, *, rotation_deg: float = 0.0
    ) -> Any:
        body: dict[str, Any] = {
            "features": list(features),
            "cell_size_ft": cell_size_ft,
        }
        # Left out entirely at zero so the unrotated request stays byte-identical
        # to the one the toolbar sent before rotation existed.
        if rotation_deg:
            body["rotation_deg"] = rotation_deg
        return self.post("grid_parcels", body)

    def view_rows(self) -> list[tuple[Any, ...]]:
        """Every canvas-view row, as ``(…columns…, geometry area)``."""
        self.recreate_view()
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT parcel_id, du, pop, area_gross, built_form_key, "  # noqa: S608
                f"land_development_category, building_count, is_residential, "
                f"geometry_key, uf_is_painted, ST_Area(geometry::geography) "
                f"FROM {_qi(self.scenario.base_layer_table)} ORDER BY parcel_id"
            )
            return cursor.fetchall()

    def parcel_id_column_type(self) -> str:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT data_type FROM information_schema.columns WHERE "
                "table_schema = %s AND table_name = %s AND column_name = 'parcel_id'",
                [
                    self.scenario.target_schema,
                    f"scenario_{self.scenario.slug}_canvas",
                ],
            )
            return cursor.fetchone()[0]

    def view_by_id(self) -> dict[str, tuple[Any, ...]]:
        """Canvas-view rows keyed by feature id (as strings)."""
        return {str(row[0]): row for row in self.view_rows()}

    def base_geometry_area(self) -> float:
        """Geodesic area of the fixture's parcels — the conservation reference."""
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT sum(ST_Area(geometry::geography)) FROM {self.table}"  # noqa: S608
            )
            return float(cursor.fetchone()[0])

    def edits(self, operation: str | None = None) -> list[ParcelGeometryEdit]:
        queryset = ParcelGeometryEdit.objects.filter(scenario=self.scenario)
        if operation is not None:
            queryset = queryset.filter(operation=operation)
        return list(queryset)


@pytest.fixture
def int_harness(db: Any, fixture_tables: Any, client: Client, monkeypatch: Any) -> Any:
    """Fixture over a ``bigint``-keyed base (the published base canvas' shape)."""
    monkeypatch.setattr(
        "brewgis.workspace.views.paint.purge_scenario_canvas_tiles",
        lambda _scenario: None,
    )
    user = UserFactory()
    client.force_login(user)
    return _Harness(client=client, table=INT_TABLE, ids=INT_IDS)


@pytest.fixture
def text_harness(db: Any, fixture_tables: Any, client: Client, monkeypatch: Any) -> Any:
    """Fixture over a text-keyed base (a SQLMesh base: ``parcel_id`` is an APN)."""
    monkeypatch.setattr(
        "brewgis.workspace.views.paint.purge_scenario_canvas_tiles",
        lambda _scenario: None,
    )
    user = UserFactory()
    client.force_login(user)
    return _Harness(client=client, table=TEXT_TABLE, ids=TEXT_IDS)


def _touching_cell_pair(harness: _Harness) -> list[str]:
    """Two adjacent grid cells of *harness*'s view, as strings."""
    view = _qi(harness.scenario.base_layer_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT a.parcel_id::text, b.parcel_id::text "  # noqa: S608
            f"FROM {view} a JOIN {view} b "
            f"ON b.parcel_id > a.parcel_id AND ST_Touches(a.geometry, b.geometry) "
            f"WHERE a.parcel_id < 0 AND b.parcel_id < 0 LIMIT 1"
        )
        return list(cursor.fetchone())


def _cell_area_m2(size_ft: float) -> float:
    """Geodesic area (m²) of one lattice cell of *size_ft* feet on the fixture.

    The fixture sits on the equator, where Web Mercator's metre is the
    ellipsoid's equatorial metre rather than a ground metre: a "100 ft" cell
    measures ≈922.8 m² on the ellipsoid, not 100² ft² — which is why the
    expected area is measured here rather than computed from ``FT_TO_M``.
    """
    side = size_ft * FT_TO_M
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_Area(ST_Transform("
            "ST_SetSRID(ST_MakeEnvelope(0, 0, %s, %s), 3857), 4326)::geography)",
            [side, side],
        )
        return float(cursor.fetchone()[0])


def _edit_areas(harness: _Harness, operation: str = "grid") -> list[float]:
    """Geodesic area (m²) of every edit row of *operation*, ascending."""
    rows = ParcelGeometryEdit.objects.filter(
        scenario=harness.scenario, operation=operation
    ).annotate(area=RawSQL("ST_Area(geometry::geography)", []))
    return sorted(float(row.area) for row in rows)


def _widest_edit_bbox_m(harness: _Harness) -> float:
    """Widest projected (3857) bounding box among the grid's cells.

    An axis-aligned cell of the fixture's 100 ft lattice is exactly its side
    wide; a rotated one is wider by however much the lattice is turned, which
    is what tells the two grids apart independently of the cell count.
    """
    rows = ParcelGeometryEdit.objects.filter(
        scenario=harness.scenario, operation=ParcelGeometryEdit.Operation.GRID
    ).annotate(
        width=RawSQL(
            "ST_XMax(ST_Transform(geometry, 3857)) "
            "- ST_XMin(ST_Transform(geometry, 3857))",
            [],
        )
    )
    return float(rows.aggregate(widest=Max("width"))["widest"])


def _geojson_areas(features: list[dict[str, Any]]) -> list[float]:
    """Geodesic area (m²) of previewed GeoJSON features, measured in PostGIS.

    A preview and the apply that follows it hand out the same cells, so their
    areas have to match to the last decimal — measuring the preview's GeoJSON
    through the same ``ST_Area(geometry::geography)`` keeps the comparison
    honest rather than re-deriving it in Python.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_Area(ST_GeomFromGeoJSON(g)::geography) "
            "FROM unnest(%s::text[]) AS g",
            [[json.dumps(feature["geometry"]) for feature in features]],
        )
        return sorted(float(row[0]) for row in cursor.fetchall())


@pytest.mark.integration
class TestGridParcels:
    """POST grid — the split itself, its conservation and its key typing."""

    def test_grid_splits_the_site_into_cells_that_conserve_every_column(
        self, int_harness: _Harness
    ) -> None:
        response = int_harness.grid(INT_IDS)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["grid_count"] == 8

        edits = int_harness.edits("grid")
        assert len(edits) == 8
        assert len({edit.batch_id for edit in edits}) == 1
        assert all(edit.parcel_id.startswith("-") for edit in edits)
        assert all(edit.source_parcel_ids == sorted(INT_IDS) for edit in edits)
        # Every base column but the two dedicated ones travels in values — that
        # is what makes the canvas view's union complete.
        expected_columns = set(_fetch_base_columns(INT_TABLE)[2]) - {
            "parcel_id",
            "geometry",
        }
        assert {frozenset(edit.values) for edit in edits} == {
            frozenset(expected_columns)
        }

        rows = int_harness.view_rows()
        assert len(rows) == 8
        by_id = {str(row[0]): row for row in rows}
        assert not set(by_id) & set(INT_IDS)
        # Totals conserved: the cells hold exactly what the parcels held.
        assert sum(row[1] for row in rows) == pytest.approx(sum(PARCEL_DU))
        assert sum(row[2] for row in rows) == pytest.approx(sum(PARCEL_POP))
        assert sum(row[3] for row in rows) == pytest.approx(sum(PARCEL_AREA_GROSS))
        # Exact halves, because each cell lies wholly inside one parcel (the
        # shares come from geodesic areas, so they are exact only to the
        # precision of the area arithmetic).
        assert sorted(round(row[1], 9) for row in rows) == [1.0] * 4 + [2.0] * 4
        assert sorted(round(row[3], 9) for row in rows) == [0.25] * 4 + [0.5] * 4
        # Geometry conserved too: the cells cover exactly the site the parcels
        # covered (their measured geodesic area, not the nominal envelope)...
        assert sum(row[10] for row in rows) == pytest.approx(
            int_harness.base_geometry_area()
        )
        # ...as eight full 100 ft squares: their geodesic areas differ only by
        # the ellipsoid's own latitudinal variation across the site.
        areas = [row[10] for row in rows]
        assert max(areas) == pytest.approx(min(areas), rel=0.001)
        # An integral column stays integral — the view's bigint column would
        # reject a fraction — and the cell owns its own id.
        assert sorted(row[6] for row in rows) == [1, 1, 1, 1, 2, 2, 2, 2]
        assert all(str(row[8]) == str(row[0]) for row in rows)
        # Classification/identity columns come from the parcel covering the cell.
        assert {row[4] for row in rows} == {"sf_detached"}
        assert {row[5] for row in rows} == {"urban"}
        assert sorted({row[7] for row in rows}) == [False, True]
        assert all(row[9] is True for row in rows)

        assert int_harness.parcel_id_column_type() == "bigint"
        # The base canvas itself is untouched.
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*), sum(du) FROM {INT_TABLE}")  # noqa: S608
            assert cursor.fetchone() == (2, sum(PARCEL_DU))

    def test_grid_rotation_cuts_on_the_rotated_lattice_and_conserves_the_site(
        self, int_harness: _Harness
    ) -> None:
        response = int_harness.grid(INT_IDS, rotation_deg=45)

        assert response.status_code == 200
        # A 400 x 200 ft site on a lattice turned 45° is cut into its four
        # interior diamonds plus a triangle along each edge — 18 cells where the
        # axis-aligned grid gave 8.
        assert response.json()["grid_count"] == 18
        areas = _edit_areas(int_harness)
        assert sum(areas) == pytest.approx(int_harness.base_geometry_area())
        # Full cells are still full cells: the diamond keeps the 100 ft cell's
        # area and only its bounding box grows, by √2.
        assert max(areas) == pytest.approx(_cell_area_m2(CELL_FT), rel=1e-4)
        assert _widest_edit_bbox_m(int_harness) == pytest.approx(
            CELL_FT * FT_TO_M * 2**0.5, rel=1e-4
        )

    def test_grid_rotation_of_zero_is_the_axis_aligned_grid(
        self, int_harness: _Harness
    ) -> None:
        response = int_harness.post(
            "grid_parcels",
            {
                "features": list(INT_IDS),
                "cell_size_ft": CELL_FT,
                "rotation_deg": 0,
            },
        )

        assert response.status_code == 200
        assert response.json()["grid_count"] == 8
        areas = _edit_areas(int_harness)
        assert max(areas) == pytest.approx(min(areas), rel=0.001)
        assert _widest_edit_bbox_m(int_harness) == pytest.approx(
            CELL_FT * FT_TO_M, rel=1e-4
        )

    def test_grid_rotation_inflates_the_cell_count_guard(
        self, int_harness: _Harness
    ) -> None:
        # The guard sizes the lattice on the selection's envelope; a rotated
        # lattice covers the envelope's *rotated* bounding box instead, so the
        # estimate has to grow with the angle or a diagonal grid would slip
        # past the 50k-cell limit.
        quoted = _quote_qualified_table(*int_harness.scenario.base_layer_source())
        size_m = CELL_FT * FT_TO_M

        assert _grid_cell_estimate(quoted, list(INT_IDS), size_m) == 8
        assert (
            _grid_cell_estimate(quoted, list(INT_IDS), size_m, angle_rad=radians(45))
            == 25
        )

    def test_grid_of_an_already_gridded_cell_replaces_it(
        self, int_harness: _Harness
    ) -> None:
        int_harness.grid(INT_IDS)
        parent = str(int_harness.edits("grid")[0].parcel_id)

        response = int_harness.grid([parent], cell_size_ft=CELL_FT / 2)

        assert response.status_code == 200
        assert response.json()["grid_count"] == 4
        rows = int_harness.view_rows()
        ids = {str(row[0]) for row in rows}
        assert parent not in ids
        assert len(rows) == 8 - 1 + 4
        assert sum(row[1] for row in rows) == pytest.approx(sum(PARCEL_DU))
        assert not ids & set(INT_IDS)
        # The replaced cell's own edit row stays — undo needs it — it is simply
        # outranked by the newer grid that claimed it.
        assert len(int_harness.edits()) == 8 + 4

    def test_grid_rejects_a_missing_or_non_positive_cell_size(
        self, int_harness: _Harness
    ) -> None:
        assert (
            int_harness.post("grid_parcels", {"features": list(INT_IDS)}).status_code
            == 400
        )
        assert int_harness.grid(INT_IDS, cell_size_ft=0).status_code == 400
        assert not int_harness.edits()

    def test_grid_rejects_a_parcel_outside_the_scenarios_canvas(
        self, int_harness: _Harness
    ) -> None:
        response = int_harness.grid([*INT_IDS, "999999"])

        assert response.status_code == 404
        assert "999999" in response.json()["message"]
        assert not int_harness.edits()

    def test_text_keyed_base_keeps_its_parcel_id_type(
        self, text_harness: _Harness
    ) -> None:
        response = text_harness.grid(TEXT_IDS)

        assert response.status_code == 200
        assert response.json()["grid_count"] == 8
        rows = text_harness.view_rows()
        assert len(rows) == 8
        assert all(str(row[0]).startswith("-") for row in rows)
        assert sum(row[1] for row in rows) == pytest.approx(sum(PARCEL_DU))
        assert text_harness.parcel_id_column_type() == "character varying"


@pytest.mark.integration
class TestMergeParcels:
    """POST merge — the union geometry and the summed attributes."""

    def test_merge_of_two_base_parcels_leaves_one_row_carrying_both(
        self, int_harness: _Harness
    ) -> None:
        response = int_harness.post("merge_parcels", {"features": list(INT_IDS)})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["merged_count"] == 1
        # Deterministic survivor: the lowest id, and it is not necessarily
        # numeric, hence the lexicographic pick.
        assert body["painted_features"] == [min(INT_IDS)]

        edits = int_harness.edits("merge")
        assert len(edits) == 1
        assert edits[0].parcel_id == min(INT_IDS)
        assert edits[0].source_parcel_ids == sorted(INT_IDS)
        # The survivor is one of its own sources: the union hides the base rows
        # for both ids, and the merged row must survive that.
        rows = int_harness.view_rows()
        assert len(rows) == 1
        merged = rows[0]
        assert str(merged[0]) == min(INT_IDS)
        assert merged[1] == pytest.approx(sum(PARCEL_DU))
        assert merged[2] == pytest.approx(sum(PARCEL_POP))
        assert merged[3] == pytest.approx(sum(PARCEL_AREA_GROSS))
        assert merged[6] == sum(PARCEL_BUILDINGS)
        assert str(merged[8]) == str(merged[0])
        assert merged[9] is True
        # Identity/classification come from the surviving parcel.
        assert merged[7] is True
        assert merged[4] == "sf_detached"
        assert merged[10] == pytest.approx(int_harness.base_geometry_area())

        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*), sum(du) FROM {INT_TABLE}")  # noqa: S608
            assert cursor.fetchone() == (2, sum(PARCEL_DU))

    def test_merge_of_two_cells_sums_only_their_own_values(
        self, int_harness: _Harness
    ) -> None:
        int_harness.grid(INT_IDS)
        before = {str(row[0]): row for row in int_harness.view_rows()}
        first, second = _touching_cell_pair(int_harness)
        survivor = min(first, second)

        response = int_harness.post("merge_parcels", {"features": [first, second]})

        assert response.status_code == 200
        assert response.json()["painted_features"] == [survivor]
        rows = int_harness.view_rows()
        assert len(rows) == 7
        by_id = {str(row[0]): row for row in rows}
        merged = by_id[survivor]
        assert merged[1] == pytest.approx(before[first][1] + before[second][1])
        assert merged[3] == pytest.approx(before[first][3] + before[second][3])
        assert merged[10] == pytest.approx(before[first][10] + before[second][10])
        assert sum(row[1] for row in rows) == pytest.approx(sum(PARCEL_DU))
        # The six untouched cells still carry their own ids.
        assert set(by_id) == {str(row[0]) for row in rows}

    def test_merge_rejects_a_single_parcel(self, int_harness: _Harness) -> None:
        response = int_harness.post("merge_parcels", {"features": [INT_IDS[0]]})

        assert response.status_code == 400
        assert not int_harness.edits()

    def test_merge_clears_the_survivors_paint_and_undo_restores_it(
        self, int_harness: _Harness
    ) -> None:
        # The survivor keeps its own id, so paint already on it would otherwise
        # mask the values the merge computes from every source — values that
        # already include that paint, since they are read off the canvas view.
        survivor = min(INT_IDS)
        PaintedCanvas.objects.create(
            scenario=int_harness.scenario,
            feature_id=survivor,
            column_name="du",
            painted_value=99.0,
        )
        assert int_harness.view_by_id()[survivor][1] == pytest.approx(99.0)

        batch_id = int_harness.post(
            "merge_parcels", {"features": list(INT_IDS)}
        ).json()["batch_id"]

        merged = int_harness.view_by_id()[survivor]
        assert merged[1] == pytest.approx(99.0 + PARCEL_DU[1])
        assert merged[3] == pytest.approx(sum(PARCEL_AREA_GROSS))
        assert not PaintedCanvas.objects.filter(
            scenario=int_harness.scenario, feature_id=survivor
        ).exists()

        response = int_harness.post("undo_paint", {"batch_id": batch_id})

        assert response.status_code == 200
        restored = PaintedCanvas.objects.get(
            scenario=int_harness.scenario,
            feature_id=survivor,
            column_name="du",
        )
        assert restored.painted_value == pytest.approx(99.0)
        assert {str(row[0]) for row in int_harness.view_rows()} == set(INT_IDS)
        assert int_harness.view_by_id()[survivor][1] == pytest.approx(99.0)


@pytest.mark.integration
class TestGeometryEditPreviews:
    """POST grid/merge preview — the geometry the apply writes, and nothing else."""

    def test_grid_preview_returns_the_cells_the_grid_then_writes(
        self, int_harness: _Harness
    ) -> None:
        body = {"features": list(INT_IDS), "cell_size_ft": CELL_FT, "rotation_deg": 45}

        preview = int_harness.post("grid_preview", body)

        assert preview.status_code == 200
        geojson = preview.json()["geojson"]
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 18
        # A preview is a read: no edit rows, and not even the PaintRun row the
        # apply endpoints create.
        assert not int_harness.edits()
        assert not PaintRun.objects.filter(scenario=int_harness.scenario).exists()

        applied = int_harness.post("grid_parcels", body)

        assert applied.status_code == 200
        assert applied.json()["grid_count"] == len(geojson["features"])
        assert _geojson_areas(geojson["features"]) == pytest.approx(
            _edit_areas(int_harness)
        )

    def test_grid_preview_without_rotation_previews_the_axis_aligned_cells(
        self, int_harness: _Harness
    ) -> None:
        preview = int_harness.post(
            "grid_preview", {"features": list(INT_IDS), "cell_size_ft": CELL_FT}
        )

        assert preview.status_code == 200
        features = preview.json()["geojson"]["features"]
        assert len(features) == 8
        areas = _geojson_areas(features)
        # Eight equal cells tiling the site exactly, as the applied grid's are.
        assert max(areas) == pytest.approx(_cell_area_m2(CELL_FT), rel=1e-4)
        assert max(areas) == pytest.approx(min(areas), rel=0.001)
        assert sum(areas) == pytest.approx(int_harness.base_geometry_area())

    def test_merge_preview_returns_the_union_the_merge_then_writes(
        self, int_harness: _Harness
    ) -> None:
        preview = int_harness.post("merge_preview", {"features": list(INT_IDS)})

        assert preview.status_code == 200
        features = preview.json()["geojson"]["features"]
        assert len(features) == 1
        assert not int_harness.edits()

        applied = int_harness.post("merge_parcels", {"features": list(INT_IDS)})

        assert applied.status_code == 200
        assert int_harness.edits("merge")[0].geometry.equals(
            GEOSGeometry(json.dumps(features[0]["geometry"]))
        )

    def test_previews_reject_what_the_applies_reject(
        self, int_harness: _Harness
    ) -> None:
        # The same shared validation, so a preview never reports a grid or merge
        # the apply would then refuse.
        assert (
            int_harness.post("grid_preview", {"features": list(INT_IDS)}).status_code
            == 400
        )
        assert (
            int_harness.post(
                "grid_preview",
                {"features": [*INT_IDS, "999999"], "cell_size_ft": CELL_FT},
            ).status_code
            == 404
        )
        assert (
            int_harness.post("merge_preview", {"features": [INT_IDS[0]]}).status_code
            == 400
        )
        assert not int_harness.edits()


@pytest.mark.integration
class TestUndoGeometryEdits:
    """Undo restores the parcels a grid or merge replaced."""

    def test_undo_of_a_grid_restores_the_parcels_and_drops_the_cells_paint(
        self, int_harness: _Harness
    ) -> None:
        batch_id = int_harness.grid(INT_IDS).json()["batch_id"]
        cell_id = int_harness.edits()[0].parcel_id
        PaintedCanvas.objects.create(
            scenario=int_harness.scenario,
            feature_id=cell_id,
            column_name="du",
            painted_value=999.0,
        )

        response = int_harness.post("undo_paint", {"batch_id": batch_id})

        assert response.status_code == 200
        assert response.json()["undone_count"] == 1
        assert int_harness.edits() == []
        assert PaintedCanvas.objects.filter(scenario=int_harness.scenario).count() == 0
        rows = int_harness.view_rows()
        assert {str(row[0]) for row in rows} == set(INT_IDS)
        assert sum(row[1] for row in rows) == pytest.approx(sum(PARCEL_DU))

    def test_undo_of_a_merge_restores_both_parcels(self, int_harness: _Harness) -> None:
        batch_id = int_harness.post(
            "merge_parcels", {"features": list(INT_IDS)}
        ).json()["batch_id"]

        response = int_harness.post("undo_paint", {"batch_id": batch_id})

        assert response.status_code == 200
        assert int_harness.edits() == []
        rows = int_harness.view_rows()
        assert {str(row[0]) for row in rows} == set(INT_IDS)
        assert sum(row[1] for row in rows) == pytest.approx(sum(PARCEL_DU))


@pytest.fixture
def density_column(monkeypatch: Any) -> Any:
    """Give ``pct_minority`` a density metatype for one test.

    ``BaseCanvasSchema`` derives each column's metatype from the base-canvas
    model, which only ever yields identity/geometry/classification/count, so the
    area-averaging branch is reached by patching the metatype here rather than by
    seeding a ``BaseCanvasColumn`` row the schema does not actually read.
    """
    columns = dict(BaseCanvasSchema.columns())
    columns["pct_minority"] = replace(columns["pct_minority"], metatype="density")
    monkeypatch.setattr(BaseCanvasSchema, "_COLUMNS", columns)


_SOURCES: dict[str, dict[str, Any]] = {
    "a": {
        "du": 4.0,
        "area_m2": 400.0,
        "geometry_key": "a",
        "built_form_key": "sf",
        "land_development_category": "urban",
        "id_source": "sacog",
        "building_count": 3,
        "pct_minority": 20.0,
    },
    "b": {
        "du": 8.0,
        "area_m2": 100.0,
        "geometry_key": "b",
        "built_form_key": "mf",
        "land_development_category": "suburban",
        "id_source": "fresno",
        "building_count": 9,
        "pct_minority": 60.0,
    },
}


class TestAllocateGridCell:
    """The split's per-cell allocation, independent of any database."""

    def test_extensive_values_are_taken_in_proportion_to_the_area_covered(self) -> None:
        # One source, four equal cells: the shares add up to the source's whole.
        cells = [
            _allocate_grid_cell(_SOURCES, {"a": 100.0}, str(-index))
            for index in range(1, 5)
        ]

        assert [cell["du"] for cell in cells] == [1.0, 1.0, 1.0, 1.0]
        assert sum(cell["du"] for cell in cells) == pytest.approx(_SOURCES["a"]["du"])

    def test_a_cell_covering_two_parcels_sums_both_shares(self) -> None:
        cell = _allocate_grid_cell(_SOURCES, {"a": 200.0, "b": 25.0}, "-1")

        assert cell["du"] == pytest.approx(4.0 * 0.5 + 8.0 * 0.25)

    def test_density_columns_are_spread_over_the_cells_source_composition(
        self, density_column: Any
    ) -> None:
        cell = _allocate_grid_cell(_SOURCES, {"a": 300.0, "b": 100.0}, "-1")

        assert cell["pct_minority"] == pytest.approx((20.0 * 300 + 60.0 * 100) / 400)

    def test_identity_and_classification_come_from_the_dominant_source(self) -> None:
        cell = _allocate_grid_cell(_SOURCES, {"a": 10.0, "b": 90.0}, "-7")

        assert cell["built_form_key"] == "mf"
        assert cell["land_development_category"] == "suburban"
        assert cell["id_source"] == "fresno"
        assert cell["geometry_key"] == "-7"

    def test_integral_columns_are_rounded_while_fractional_ones_are_not(self) -> None:
        cell = _allocate_grid_cell(_SOURCES, {"a": 100.0}, "-1")

        assert cell["building_count"] == 1  # round(3 * 0.25)
        assert isinstance(cell["building_count"], int)
        assert cell["du"] == pytest.approx(1.0)


class TestAllocateMerge:
    """The merge's allocation, independent of any database."""

    def test_extensive_values_are_summed_and_densities_area_weighted(
        self, density_column: Any
    ) -> None:
        values = _allocate_merge(_SOURCES, "a", "a")

        assert values["du"] == pytest.approx(_SOURCES["a"]["du"] + _SOURCES["b"]["du"])
        assert values["building_count"] == 12
        assert values["pct_minority"] == pytest.approx((20.0 * 400 + 60.0 * 100) / 500)

    def test_identity_and_classification_come_from_the_survivor(self) -> None:
        values = _allocate_merge(_SOURCES, "b", "b")

        assert values["geometry_key"] == "b"
        assert values["id_source"] == "fresno"
        assert values["built_form_key"] == "mf"
        assert values["land_development_category"] == "suburban"

    def test_the_keys_are_exactly_the_base_columns_the_values_must_carry(self) -> None:
        # The canvas view reads every one of these out of the edit row's values,
        # so a column missing here would come back NULL on the merged parcel.
        values = _allocate_merge(_SOURCES, "a", "a")

        assert set(values) == {
            "du",
            "geometry_key",
            "built_form_key",
            "land_development_category",
            "id_source",
            "building_count",
            "pct_minority",
        }
