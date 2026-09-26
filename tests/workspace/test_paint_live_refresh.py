"""Live-stack integration test: does a paint operation's result actually
show up on the map without a page reload?

This is deliberately a live-stack test in the same style as
``test_map_render_parity.py`` — real Martin, a real running Django dev
server, and a real Playwright browser — because the bug it guards against
lives entirely *outside* what a Django view-level unit test can see:

1. Real (non-eager) Celery dispatch inside ``ATOMIC_REQUESTS`` raced the
   transaction that creates the ``PaintRun`` row: the worker could grab
   the task and query for that row before the view's transaction had
   committed it, crashing with ``PaintRun.DoesNotExist`` and silently
   never painting anything. Fixed with ``transaction.on_commit`` in
   ``brewgis.workspace.views.paint._enqueue``.
2. Martin caches rendered tile bytes keyed only by ``(source, z, x, y)`` —
   it never looks at the request's query string — so a scenario's canvas
   view (a plain, always-live SQL view; see ``canvas_view_manager``) could
   change underneath it and Martin would keep serving the pre-paint tile
   forever. Verified directly: painting a fixture feature and re-requesting
   its exact tile from Martin returned byte-identical, unchanged content
   (same ETag) even though the view's own SQL returned the new value.
   Fixed by purging the view's Martin cache entry (``DELETE
   /cache/{source_id}``, maplibre/martin#3194) from
   ``purge_scenario_canvas_tiles()`` every time a paint operation writes —
   see ``brewgis.workspace.services.tile_server.purge_martin_cache``.
3. ``BrewGisMap.refreshCanvasTiles()`` only busted the *highlight overlay*
   layer's MapLibre source (``canvasLayerId``), never the *base* layer's
   (``baseLayerId``) — the one actually rendered with the workspace's real
   symbology, i.e. what a user is looking at. Fixed in
   ``js/src/components/brew-gis-map.ts``.

None of the three is visible from a Django test client + eager-mode Celery
(unit-test) perspective: eager mode makes the race impossible to hit, and
the Django test client never touches Martin or a real browser at all. Only
a live run of the actual stack — the real docker Celery worker, the real
Martin container, a real MapLibre instance in a real browser — exercises
the code paths where all three bugs actually lived.

Like the parity test, the basemap is replaced with a blank offline style
(``_OFFLINE_BASEMAP_JS``) — the seeded CARTO default has no tiles at the
fixture's coordinates, and MapLibre only installs the app's data layers (the
painted-features overlay and the scenario canvas view the paint result has to
reach) once its ``load`` event fires, which failed basemap tiles prevent.

Requires the full local docker stack running (``docker compose up``) with
Martin's docker socket mounted (so ``restart_martin()`` works) and
``CELERY_TASK_ALWAYS_EAGER=False`` in the running django/celeryworker
containers (already brewgis's dev default — see ``.envs/.local/.django``).
Run it with ``make test-live-stack``, or directly::

    pytest tests/workspace/test_paint_live_refresh.py -m live_stack -v
"""

from __future__ import annotations

import os
import time
from typing import Any

import psycopg
import pytest
import requests
from django.conf import settings
from playwright.sync_api import Page
from playwright.sync_api import sync_playwright

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from tests.workspace.live_stack import delete_user_rows
from tests.workspace.live_stack import delete_workspace_rows

pytestmark = [pytest.mark.integration, pytest.mark.live_stack]

BASE_URL = os.environ.get("BREWGIS_TEST_BASE_URL", "http://localhost:8000")

TEST_USERNAME = "paint_live_refresh_test"
TEST_PASSWORD = "paint-live-refresh-test-pw"  # noqa: S105

FIXTURE_SCHEMA = "public"
FIXTURE_TABLE = "paint_live_refresh_fixture"

# A quiet spot with no basemap layers drawn on top (see the identical
# comment/reasoning in test_map_render_parity.py) so the fixture polygon
# a) is visible without panning and b) has a deterministic pixel location
# via map.project(), no screen-space feature hunting required.
CENTER_LNG = 30.0
CENTER_LAT = 23.0
ZOOM = 16.0
POLY_HALF_WIDTH = 0.001

FEATURE_ID = "fixture-1"
INITIAL_DU = 10.0
PAINTED_DU = 999.0


def _pg_dsn() -> str:
    """Build a libpq DSN pointed at the same DB Martin/tipg read from.

    Duplicated (not imported) from test_map_render_parity.py — small
    enough to keep this file independently runnable, and both are
    intentionally decoupled from Django's ORM/test-database machinery.
    """
    host = os.environ.get("POSTGRES_HOST")
    if host:
        return (
            f"host={host} port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={os.environ.get('POSTGRES_DB')} "
            f"user={os.environ.get('POSTGRES_USER')} "
            f"password={os.environ.get('POSTGRES_PASSWORD')}"
        )
    db = settings.DATABASES["default"]
    return (
        f"host={db['HOST']} port={db['PORT'] or 5432} dbname={db['NAME']} "
        f"user={db['USER']} password={db['PASSWORD']}"
    )


def _square_wkt(lng: float, lat: float, half: float) -> str:
    x0, x1, y0, y1 = lng - half, lng + half, lat - half, lat + half
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


def _setup_fixture(conn: psycopg.Connection) -> dict[str, Any]:
    """Create a tiny base table, workspace, scenario, and canvas view.

    A dedicated tiny fixture table (one feature) rather than reusing any
    real workspace's full parcel dataset — a real base_canvas table here
    is 200k+ rows, and at low zoom Martin has to render every one of them
    into a single tile (tens of MB). The test deliberately re-requests that
    exact tile right after painting (to catch a stale cache), which purges
    and re-renders it every run regardless of caching being on elsewhere —
    doing that against the real table would make an already-real-network
    integration test unnecessarily slow and flaky.
    """
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {FIXTURE_SCHEMA}.{FIXTURE_TABLE} CASCADE")
        cur.execute(
            f"""
            CREATE TABLE {FIXTURE_SCHEMA}.{FIXTURE_TABLE} (
                parcel_id text PRIMARY KEY,
                geometry geometry(Polygon, 4326) NOT NULL,
                du double precision NOT NULL,
                built_form_key text
            )
            """
        )
        cur.execute(
            f"""
            INSERT INTO {FIXTURE_SCHEMA}.{FIXTURE_TABLE} (
                parcel_id, geometry, du, built_form_key
            )
            VALUES (%s, ST_GeomFromText(%s, 4326), %s, %s)
            """,  # noqa: S608 -- FIXTURE_SCHEMA/FIXTURE_TABLE are fixed module constants
            (
                FEATURE_ID,
                _square_wkt(CENTER_LNG, CENTER_LAT, POLY_HALF_WIDTH),
                INITIAL_DU,
                "mixed_use",
            ),
        )

        cur.execute(
            """
            INSERT INTO workspace_workspace
                (name, db_connection, db_schema, county_fips_list,
                 center_lat, center_lng, zoom, base_table, tile_server_backend,
                 fill_built_form)
            VALUES (%s, 'default', %s, '[]', %s, %s, %s, %s, 'martin', false)
            RETURNING id
            """,
            (
                "Paint Live Refresh Test",
                FIXTURE_SCHEMA,
                CENTER_LAT,
                CENTER_LNG,
                ZOOM,
                f"{FIXTURE_SCHEMA}.{FIXTURE_TABLE}",
            ),
        )
        workspace_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO workspace_layer
                (key, name, description, geometry_type, display_order,
                 layer_source, db_table, workspace_id, db_schema, is_visible)
            VALUES (%s, %s, '', 'fill', 0, 'postgis', %s, %s, %s, true)
            RETURNING id
            """,
            (
                BASE_CANVAS_LAYER_KEY,
                "Fixture Layer",
                FIXTURE_TABLE,
                workspace_id,
                FIXTURE_SCHEMA,
            ),
        )
        layer_id = cur.fetchone()[0]

        slug = "test"
        schema_name = f"scenario_{slug}"
        cur.execute(
            """
            INSERT INTO workspace_scenario
                (name, slug, description, workspace_id, scenario_type,
                 base_year, horizon_year, schema_name, published,
                 public_token, created_at, updated_at,
                 column_mapping, constraints, analysis_params)
            VALUES (%s, %s, '', %s, 'alternative', 2023, 2050, %s, false,
                    gen_random_uuid(), now(), now(),
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
            RETURNING id
            """,
            ("Test Scenario", slug, workspace_id, schema_name),
        )
        scenario_id = cur.fetchone()[0]

        # The map page's scenario switcher (and with it the Paint Mode toggle
        # the test clicks) only renders for a workspace with more than one
        # scenario, and every real workspace has the BASE scenario the app
        # creates alongside its alternatives — so the fixture needs one too.
        cur.execute(
            """
            INSERT INTO workspace_scenario
                (name, slug, description, workspace_id, scenario_type,
                 base_year, horizon_year, schema_name, published,
                 public_token, created_at, updated_at,
                 column_mapping, constraints, analysis_params)
            VALUES ('Fixture Baseline', 'test-base', '', %s, 'base', 2023, 2050,
                    'scenario_test-base', false, gen_random_uuid(), now(), now(),
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
            """,
            (workspace_id,),
        )

        from django.contrib.auth.hashers import make_password

        cur.execute(
            """
            INSERT INTO auth_user
                (password, is_superuser, username, first_name, last_name,
                 email, is_staff, is_active, date_joined)
            VALUES (%s, true, %s, '', '', '', true, true, now())
            ON CONFLICT (username) DO NOTHING
            RETURNING id
            """,
            (make_password(TEST_PASSWORD), TEST_USERNAME),
        )
    conn.commit()

    return {
        "workspace_id": workspace_id,
        "layer_id": layer_id,
        "scenario_id": scenario_id,
        "schema_name": schema_name,
        "slug": slug,
    }


def _create_canvas_view(ids: dict[str, Any]) -> None:
    """Create the scenario's canvas view the way its SQLMesh model does.

    The model itself can't be planned from here: its blueprint profiles read
    the Django ORM (in a test process that is the *test* database) while this
    fixture's scenario and base table live in the stack's real database —
    a *separate* process's dev server is what serves the assertions below
    (see ``_pg_dsn``). So build the same view from the same generator the
    model renders its SELECT from.
    """
    from django.db import connection

    from brewgis.workspace.models import Scenario
    from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
    from brewgis.workspace.services.canvas_view_manager import _qi
    from brewgis.workspace.services.canvas_view_manager import build_canvas_view_select

    # Fetch the real row (rather than a bare in-memory Scenario(pk=...))
    # so `.workspace` resolves — the generator derives the base table from
    # `scenario.workspace.base_table` now, which the fixture's raw INSERT
    # already points at f"{FIXTURE_SCHEMA}.{FIXTURE_TABLE}".
    scenario = Scenario.objects.get(pk=ids["scenario_id"])
    _, _, all_columns = _fetch_base_columns(scenario.workspace.base_table)
    select = build_canvas_view_select(
        base_ref=scenario.workspace.base_table,
        all_columns=all_columns,
        scenario_id=scenario.pk,
    )
    view = _qi(f"{scenario.target_schema}.scenario_{scenario.slug}_canvas")
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_qi(scenario.target_schema)}")
        cursor.execute(f"CREATE OR REPLACE VIEW {view} AS {select}")


def _teardown_fixture(conn: psycopg.Connection, ids: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f'DROP VIEW IF EXISTS "{ids["schema_name"]}"."scenario_{ids["slug"]}_canvas"'
        )
        cur.execute(f'DROP SCHEMA IF EXISTS "{ids["schema_name"]}" CASCADE')
        cur.execute(f"DROP TABLE IF EXISTS {FIXTURE_SCHEMA}.{FIXTURE_TABLE} CASCADE")
    conn.commit()
    delete_workspace_rows(conn, ids["workspace_id"])
    # Last, and defensively: rows in the workspace above (and in any workspace
    # a previous failed run leaked) reference this user.
    delete_user_rows(conn, TEST_USERNAME)


def _wait_until_ready(fqtn: str, timeout: float = 90.0) -> None:
    """Poll Martin until it reports *fqtn* in its catalog.

    Martin only enumerates tables/views at process startup (see
    test_map_render_parity.py's identical helper) — a restarted container
    is *running* long before it's actually finished its startup scan.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/martin/catalog", timeout=5)
            if resp.ok and fqtn in resp.json().get("tiles", {}):
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    msg = f"martin never reported {fqtn} as ready within {timeout}s"
    raise TimeoutError(msg)


@pytest.fixture(scope="module")
def pg_conn() -> Any:
    conn = psycopg.connect(_pg_dsn())
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def fixture_ids(pg_conn: Any, django_db_blocker: Any) -> Any:
    ids = _setup_fixture(pg_conn)
    with django_db_blocker.unblock():
        _create_canvas_view(ids)

    from brewgis.workspace.services.tile_server import restart_martin

    restart_martin()
    _wait_until_ready(f"{ids['schema_name']}.scenario_{ids['slug']}_canvas")

    try:
        yield ids
    finally:
        _teardown_fixture(pg_conn, ids)


# See test_map_render_parity.py for the full story: the seeded default CARTO
# basemap serves no vector tiles at our fixture coordinates (404s), MapLibre's
# errored-tile path never re-schedules a render, and so `load` — which is what
# installs our data layers and the paint overlay — never fires. Rendering
# against a blank offline style removes the third-party basemap from the test.
_OFFLINE_BASEMAP_JS = """
(() => {
    const blankStyle = JSON.stringify({
        version: 8,
        sources: {},
        layers: [
            { id: 'test-background', type: 'background', paint: { 'background-color': '#000000' } },
        ],
    });
    const getElementById = Document.prototype.getElementById;
    Document.prototype.getElementById = function (id) {
        if (id === 'basemap-style-data') {
            return { textContent: blankStyle };
        }
        return getElementById.call(this, id);
    };
})();
"""


def _use_offline_basemap(page: Page) -> None:
    """Make ``brew-gis-map`` render a blank basemap instead of CARTO's."""
    page.add_init_script(script=_OFFLINE_BASEMAP_JS)


def _login(page: Page) -> None:
    """Log in and verify it actually worked.

    A bad password (this test previously copy-pasted a pre-hashed password
    literal for a *different* plaintext from test_map_render_parity.py)
    just re-renders the login form — no exception, no non-2xx response —
    so every downstream step silently ran unauthenticated instead of
    failing here where the real problem is.
    """
    _use_offline_basemap(page)
    page.goto(f"{BASE_URL}/accounts/login/")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="login"]', TEST_USERNAME)
    page.fill('input[name="password"]', TEST_PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "/accounts/login/" not in page.url, (
        f"Login failed for {TEST_USERNAME!r} — still on the login page ({page.url}) "
        "after submitting credentials"
    )


# The feature's properties as the *visible* layer has them. For an
# alternative scenario that layer is the workspace's base layer
# (``baseLayerId``), whose source map.py swaps to the scenario canvas view —
# the layer a user is actually looking at, and the one the paint result has to
# reach. Reading the id off the component keeps this honest if the key ever
# changes (it is ``BASE_CANVAS_LAYER_KEY``), instead of pinning a string that
# silently stops matching a layer name.
_QUERY_FEATURE_JS = """
() => {{
    const el = document.querySelector('brew-gis-map');
    const map = el.getMap();
    const feats = map.queryRenderedFeatures(
        [{x}, {y}], {{ layers: [el.baseLayerId] }}
    );
    return feats.length ? feats[0].properties : null;
}}
"""

# Paint mode's click-to-select handler queries the *highlight overlay*
# layer (canvasLayerId), not the base layer — both come from the same canvas
# view and normally render together, but waiting on this one too (not just the
# base layer) avoids a race where a click is fired a moment before the overlay
# layer specifically has tiles loaded. Both ids come from the component:
# the overlay is ``PAINTED_FEATURES_LAYER_KEY`` ("painted_features"), while
# "scenario_test_canvas" — the *view* this fixture creates — is what the
# overlay's source points at and was never a layer name.
_BOTH_LAYERS_READY_JS = """
() => {{
    const el = document.querySelector('brew-gis-map');
    const map = el.getMap();
    const base = el.baseLayerId;
    const overlay = el.canvasLayerId;
    const feats = map.queryRenderedFeatures(
        [{x}, {y}], {{ layers: [base, overlay] }}
    );
    const layers = new Set(feats.map(f => f.layer.id));
    return layers.has(base) && layers.has(overlay);
}}
"""


def _feature_at(page: Page, point: dict[str, float]) -> dict[str, Any] | None:
    return page.evaluate(_QUERY_FEATURE_JS.format(x=point["x"], y=point["y"]))


def _wait_until_both_layers_ready(
    page: Page, point: dict[str, float], timeout: float = 10
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(_BOTH_LAYERS_READY_JS.format(x=point["x"], y=point["y"])):
            return True
        page.wait_for_timeout(200)
    return False


def _wait_for_paint_result(page: Page, paint_result: Any) -> bool:
    """Poll #paint-result until it shows success/failure.

    Returns whether a spinner/progress indicator was observed at any point
    — the core regression this test guards against.
    """
    saw_spinner = False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        html = paint_result.inner_html()
        if "spinner-border" in html or "Working on it" in html:
            saw_spinner = True
        if "alert-success" in html:
            return saw_spinner
        if "alert-danger" in html:
            pytest.fail(f"Paint request failed: {html}")
        page.wait_for_timeout(50)
    pytest.fail("Paint operation never completed within 30s")
    return saw_spinner  # unreachable, keeps type checkers happy


def _wait_for_repainted_value(
    page: Page, point: dict[str, float]
) -> dict[str, Any] | None:
    """Poll the live map (no reload) until it reflects the painted value."""
    after = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        after = _feature_at(page, point)
        if after is not None and after.get("du") == PAINTED_DU:
            return after
        page.wait_for_timeout(200)
    return after


def test_paint_result_renders_on_the_live_map_without_reload(fixture_ids: Any) -> None:
    """Reproduces the exact user-reported bug: paint a feature through the
    real UI, watch a progress indicator while the (real, non-eager) Celery
    task runs, and confirm the map shows the new value immediately —
    without needing a page reload — once it completes."""
    workspace_id = fixture_ids["workspace_id"]
    scenario_id = fixture_ids["scenario_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        try:
            _login(page)
            page.goto(f"{BASE_URL}/{workspace_id}/map/?scenario={scenario_id}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            page.click("#toggle-paint-btn")
            page.wait_for_timeout(300)

            # Deterministic feature location — no screen-space hunting.
            point = page.evaluate(
                f"""
                () => {{
                    const map = document.querySelector('brew-gis-map').getMap();
                    return map.project([{CENTER_LNG}, {CENTER_LAT}]);
                }}
                """
            )
            # Entering paint mode adds a selection-highlight layer and
            # re-syncs the canvas layer, which briefly leaves nothing
            # rendered at all queryable points — poll rather than assume a
            # fixed settle time.
            assert _wait_until_both_layers_ready(page, point), (
                "Fixture feature was never rendered on both the visible layer and "
                "the paint-mode overlay layer"
            )
            before = _feature_at(page, point)
            assert before is not None, (
                "Fixture feature was not rendered on the map at all"
            )
            assert before["du"] == INITIAL_DU

            # map.project() is canvas-relative; page.mouse.click() needs
            # viewport-relative coordinates, so offset by the canvas's own
            # page position (it sits below a topbar, not at (0, 0)).
            canvas_box = page.query_selector("canvas").bounding_box()
            page.mouse.click(canvas_box["x"] + point["x"], canvas_box["y"] + point["y"])
            page.wait_for_timeout(300)
            feature_count = page.eval_on_selector(
                "#paint-feature-count", "el => el.textContent"
            )
            assert feature_count == "1 feature(s) selected"

            page.select_option("#paint-column", "du")
            page.fill("#paint-value", str(PAINTED_DU))

            paint_result = page.locator("#paint-result")
            page.click("#paint-apply-btn")

            # The core regression: a progress indicator must appear while
            # the real (non-eager) Celery task is in flight and being
            # polled — not just a silent wait with nothing on screen.
            saw_spinner = _wait_for_paint_result(page, paint_result)
            assert saw_spinner, (
                "No progress indicator was ever shown while the paint task was "
                "in flight/polling — a user has no feedback that anything is "
                "happening during a slow paint operation"
            )

            # The regression: without reloading, does the *visible* layer
            # (not just some background data store) reflect the new value?
            after = _wait_for_repainted_value(page, point)
            assert after is not None, (
                "Fixture feature disappeared from the map after painting"
            )
            assert after["du"] == PAINTED_DU, (
                f"Map still shows the pre-paint value ({after['du']}) after the paint "
                f"operation completed and without a page reload — expected {PAINTED_DU}. "
                "This is the bug where Martin's tile cache (or refreshCanvasTiles() "
                "only refreshing one of the two canvas-view-backed layers) hides a "
                "successful paint from the user."
            )
        finally:
            browser.close()
