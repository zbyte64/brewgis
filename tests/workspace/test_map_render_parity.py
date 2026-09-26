"""Render-parity test: does Martin produce the same map pixels as tipg?

This is a *live-stack* integration test, deliberately outside Django's
normal test-database machinery: tipg and Martin are both configured (see
``docker-compose.yml``) to read the real dev database directly, so seeding
data through pytest-django's ephemeral ``test_brewgis`` database would be
invisible to them. Everything here — the fixture geometry table, the
``Workspace``/``Layer``/``SymbologyConfig``/``StyleClass`` rows, and cleanup —
goes through a dedicated psycopg connection straight to the real database,
mirroring the pattern already used by
``brewgis.workspace.analysis.data_export.ensure_export_exists_isolated`` for
the same reason.

It renders through the *real* browser map — Playwright drives an actual
page load of the workspace map view and clicks the "Export Map" button
(brewgis/templates/workspace_map.html), so the exported PNG reflects the
exact MapLibre GL styling code (brewgis.workspace.symbology.generator) and
tile sources a user actually sees, not a reimplementation of them.

Requires the full local docker stack running (``docker compose up``) and a
reachable server at ``BREWGIS_TEST_BASE_URL`` (default
``http://localhost:8000``). Run explicitly, e.g.::

    pytest tests/workspace/test_map_render_parity.py -m integration -v

To regenerate the checked-in tipg baseline (only do this deliberately, and
inspect the new image before committing it)::

    python tests/workspace/test_map_render_parity.py --update-baseline
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import django
import psycopg
import pytest
import requests
from django.conf import settings
from PIL import Image
from PIL import ImageChops
from playwright.sync_api import sync_playwright

pytestmark = [pytest.mark.integration, pytest.mark.live_stack]

BASE_URL = os.environ.get("BREWGIS_TEST_BASE_URL", "http://localhost:8000")
BASELINE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "map_render" / "baseline_tipg.png"
)

TEST_USERNAME = "map_render_parity_test"
TEST_PASSWORD = "map-render-parity-test-pw"  # noqa: S105

FIXTURE_SCHEMA = "public"
FIXTURE_TABLE = "map_render_parity_fixture"
TIPG_CONTAINER_NAME = os.environ.get("TIPG_CONTAINER_NAME", "brewgis_local_tipg")

# Five well-separated squares, each a different graduated-symbology class,
# over a quiet, empty stretch of the Sahara — chosen over open ocean (the
# obvious choice for "no basemap clutter") because the CARTO basemap style
# draws its "water"/"water_shadow" fill layers *above* the point where our
# own layers are inserted ("before: waterway", well below those in the
# layer stack — see BrewGisMap._findBeforeId in js/src/components/
# brew-gis-map.ts), so a fixture placed over ocean is invisible: it's
# rendered, just painted over. Land has no such layer sitting on top.
CENTER_LNG = 10.0
CENTER_LAT = 23.0
ZOOM = 12.0
SQUARE_HALF_WIDTH = 0.01
SQUARE_SPACING = 0.04
CLASSES = [
    # (value, color) — value 0 relies on the base/"below first threshold"
    # class color; StyleClass.min_value thereafter is the step boundary.
    (0, "#e6194b"),  # red
    (1, "#f58231"),  # orange
    (2, "#3cb44b"),  # green
    (3, "#4363d9"),  # blue
    (4, "#911eb4"),  # purple
]


def _pg_dsn() -> str:
    """Build a libpq DSN, preferring discrete POSTGRES_* env vars.

    Those are set correctly in every container regardless of how the
    process was started. Django's own DATABASE_URL, by contrast, is only
    rewritten to the right host by compose/production/django/entrypoint —
    a plain `docker exec`/`docker compose exec` shell (as this test is
    typically invoked from) does not run that entrypoint and would
    otherwise pick up the host-oriented value in `.env`.
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
    """Create the fixture geometry table, workspace, layer, and symbology.

    Returns the ids needed for cleanup and for building the map URL.
    """
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {FIXTURE_SCHEMA}.{FIXTURE_TABLE}")
        cur.execute(
            f"""
            CREATE TABLE {FIXTURE_SCHEMA}.{FIXTURE_TABLE} (
                id serial PRIMARY KEY,
                geom geometry(Polygon, 4326) NOT NULL,
                val_numeric numeric NOT NULL,
                val_float double precision NOT NULL
            )
            """
        )
        n = len(CLASSES)
        for i, (value, _color) in enumerate(CLASSES):
            lng = CENTER_LNG + (i - (n - 1) / 2) * SQUARE_SPACING
            wkt = _square_wkt(lng, CENTER_LAT, SQUARE_HALF_WIDTH)
            cur.execute(
                f"""
                INSERT INTO {FIXTURE_SCHEMA}.{FIXTURE_TABLE}
                    (geom, val_numeric, val_float)
                VALUES (ST_GeomFromText(%s, 4326), %s, %s)
                """,  # noqa: S608 -- FIXTURE_SCHEMA/FIXTURE_TABLE are fixed module constants
                (wkt, value, float(value)),
            )

        cur.execute(
            """
            INSERT INTO workspace_workspace
                (name, db_connection, db_schema, county_fips_list,
                 center_lat, center_lng, zoom, base_table, tile_server_backend,
                 fill_built_form)
            VALUES (%s, 'default', %s, '[]', %s, %s, %s, %s, 'tipg', false)
            RETURNING id
            """,
            (
                "Map Render Parity Test",
                FIXTURE_SCHEMA,
                CENTER_LAT,
                CENTER_LNG,
                ZOOM,
                f"{FIXTURE_SCHEMA}.{FIXTURE_TABLE}",
            ),
        )
        workspace_id = cur.fetchone()[0]

        # The map view resolves the workspace's BASE scenario for every
        # render (``?scenario=`` only overrides it) and 500s without one, so
        # the fixture needs the scenario the app guarantees every workspace
        # has. A BASE scenario's tile source is the base table itself — no
        # canvas view to build.
        cur.execute(
            """
            INSERT INTO workspace_scenario
                (name, slug, description, workspace_id, scenario_type,
                 base_year, horizon_year, schema_name, published,
                 public_token, created_at, updated_at,
                 column_mapping, constraints, analysis_params)
            VALUES ('Baseline', 'parity-base', '', %s, 'base', 2023, 2050,
                    'scenario_parity-base', false, gen_random_uuid(),
                    now(), now(),
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
            """,
            (workspace_id,),
        )

        cur.execute(
            """
            INSERT INTO workspace_layer
                (key, name, description, geometry_type, display_order,
                 layer_source, db_table, workspace_id, db_schema, is_visible)
            VALUES (%s, %s, '', 'fill', 0, 'postgis', %s, %s, %s, true)
            RETURNING id
            """,
            (
                "fixture_layer",
                "Fixture Layer",
                FIXTURE_TABLE,
                workspace_id,
                FIXTURE_SCHEMA,
            ),
        )
        layer_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO workspace_symbologyconfig
                (symbology_type, attribute_column, default_color,
                 default_opacity, stroke_color, stroke_width, line_width,
                 circle_radius, palette_name, reverse_palette, num_classes,
                 classification_method, null_handling, null_color,
                 zero_transparent, auto_generated, layer_id, min_zoom, max_zoom)
            VALUES
                ('graduated', 'val_numeric', %s, 1.0, '#000000', 1.0, 1.0,
                 4.0, '', false, %s, 'manual', 'gray', '#000000',
                 false, false, %s, 0.0, 22.0)
            RETURNING id
            """,
            (CLASSES[0][1], len(CLASSES), layer_id),
        )
        symbology_id = cur.fetchone()[0]

        for sort_order, (value, color) in enumerate(CLASSES):
            cur.execute(
                """
                INSERT INTO workspace_styleclass
                    (label, min_value, color, stroke_color, sort_order, symbology_id)
                VALUES (%s, %s, %s, '', %s, %s)
                """,
                (f"Class {value}", float(value), color, sort_order, symbology_id),
            )

        cur.execute(
            """
            INSERT INTO auth_user
                (password, is_superuser, username, first_name, last_name,
                 email, is_staff, is_active, date_joined)
            VALUES (%s, true, %s, '', '', '', true, true, now())
            ON CONFLICT (username) DO NOTHING
            RETURNING id
            """,
            (
                # A fixed, pre-hashed password (argon2) for TEST_PASSWORD —
                # avoids importing Django's hasher into this psycopg-only path.
                "argon2$argon2id$v=19$m=102400,t=2,p=8$"
                "UTY3ZVVrd2ZiMDJMQW9JZVVRdlJSQw$bC3tK4SWoi+1gz2O0nuaXMat5mSlnTs7o9C7KoUwa7M",
                TEST_USERNAME,
            ),
        )
    conn.commit()
    return {"workspace_id": workspace_id, "layer_id": layer_id}


def _teardown_fixture(conn: psycopg.Connection, ids: dict[str, Any]) -> None:
    """Drop everything the fixture created, children first.

    Scoped to the fixture workspace rather than the ids ``_setup_fixture``
    returned: rendering the map page registers layers of its own (the
    painted-features overlay), and a leftover child row blocks the workspace
    delete — these FKs carry no ``ON DELETE CASCADE``.
    """
    with conn.cursor() as cur:
        # ``layers`` is this function's own fixed sub-select, not user input.
        layers = "SELECT id FROM workspace_layer WHERE workspace_id = %s"
        cur.execute(
            "DELETE FROM workspace_styleclass WHERE symbology_id IN "  # noqa: S608
            f"(SELECT id FROM workspace_symbologyconfig WHERE layer_id IN ({layers}))",
            (ids["workspace_id"],),
        )
        cur.execute(
            f"DELETE FROM workspace_symbologyconfig WHERE layer_id IN ({layers})",  # noqa: S608
            (ids["workspace_id"],),
        )
        cur.execute(
            "DELETE FROM workspace_layer WHERE workspace_id = %s",
            (ids["workspace_id"],),
        )
        cur.execute(
            "DELETE FROM workspace_scenario WHERE workspace_id = %s",
            (ids["workspace_id"],),
        )
        cur.execute(
            "DELETE FROM workspace_workspace WHERE id = %s", (ids["workspace_id"],)
        )
        cur.execute(f"DROP TABLE IF EXISTS {FIXTURE_SCHEMA}.{FIXTURE_TABLE}")
        cur.execute("DELETE FROM auth_user WHERE username = %s", (TEST_USERNAME,))
    conn.commit()


def _set_backend(conn: psycopg.Connection, workspace_id: int, backend: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workspace_workspace SET tile_server_backend = %s WHERE id = %s",
            (backend, workspace_id),
        )
    conn.commit()
    if backend == "martin":
        # Local import: brewgis.workspace.services transitively imports Django
        # models (BaseCanvasSchema -> BaseCanvas), which requires the app
        # registry to already be loaded. The pytest path has that by the
        # time this runs; the `--update-baseline` script path only calls
        # django.setup() inside _update_baseline(), after this module's
        # top-level imports have already executed — so this must stay lazy.
        from brewgis.workspace.services.tile_server import restart_martin

        restart_martin()
        _wait_until_ready("martin")
    elif backend == "tipg":
        _restart_tipg()
        _wait_until_ready("tipg")


def _restart_tipg() -> None:
    """Restart the tipg container so it re-discovers the fixture table.

    tipg (like Martin) only enumerates schemas/tables at process startup —
    there's no production helper for this (tipg's schema list is normally
    static, per TIPG_DB_SCHEMAS), so this is test-only plumbing.
    """
    import docker

    docker.from_env().containers.get(TIPG_CONTAINER_NAME).restart(timeout=10)


def _wait_until_ready(backend: str, timeout: float = 90.0) -> None:
    """Poll the tile backend until it actually reports the fixture table.

    A restarted container is *running* long before it's actually ready:
    Martin in particular does an expensive startup pass computing bounds
    for every table in the whole database (many of which time out and get
    logged, one by one) before it will serve anything — a fixed sleep here
    previously produced a false "Martin renders nothing" result that was
    really just "Martin hadn't finished starting yet".
    """
    deadline = time.monotonic() + timeout
    fqtn = f"{FIXTURE_SCHEMA}.{FIXTURE_TABLE}"
    while time.monotonic() < deadline:
        try:
            if backend == "martin":
                resp = requests.get(f"{BASE_URL}/martin/catalog", timeout=5)
                ready = resp.ok and fqtn in resp.json().get("tiles", {})
            else:
                resp = requests.get(f"{BASE_URL}/tipg/collections", timeout=5)
                ready = resp.ok and any(
                    c.get("id") == fqtn for c in resp.json().get("collections", [])
                )
            if ready:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    msg = f"{backend} never reported {fqtn} as ready within {timeout}s"
    raise TimeoutError(msg)


_LAYER_RENDERED_JS = """
() => {
    const map = document.querySelector('brew-gis-map').getMap();
    return map.queryRenderedFeatures({ layers: ['fixture_layer'] }).length > 0;
}
"""


def _wait_until_layer_rendered(page: Any, timeout: float = 60.0) -> None:
    """Wait until the fixture layer has actually painted features.

    ``_wait_until_ready`` only proves the tile backend *lists* the fixture
    table; right after its container restart it takes a moment more before the
    tiles render. Exporting before that captures an empty map, which reads as a
    render difference against the baseline — and did: the failure was exactly
    7% of the image, the combined area of the fixture's five squares.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(_LAYER_RENDERED_JS):
            return
        page.wait_for_timeout(200)
    msg = f"fixture_layer rendered no features within {timeout}s"
    raise TimeoutError(msg)


def _export_map_png(page: Any, workspace_id: int, out_path: Path) -> None:
    """Log in, open the fixture workspace's map, and capture it via the
    real "Export Map" button — the same code path a user would click."""
    page.goto(f"{BASE_URL}/accounts/login/")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="login"]', TEST_USERNAME)
    page.fill('input[name="password"]', TEST_PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    # A bad credential just re-renders the login form (no exception, no
    # non-2xx status) — assert here, not several steps downstream where a
    # silently-unauthenticated session would fail for an unrelated reason.
    assert "/accounts/login/" not in page.url, (
        f"Login failed for {TEST_USERNAME!r} — still on the login page ({page.url})"
    )

    page.goto(f"{BASE_URL}/{workspace_id}/map/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    _wait_until_layer_rendered(page)

    page.click("#export-map-btn")
    page.wait_for_timeout(300)
    with page.expect_download() as dl_info:
        page.click("#export-png-btn")
    dl_info.value.save_as(str(out_path))


def _image_diff_ratio(path_a: Path, path_b: Path) -> float:
    """Fraction of pixels that differ beyond a small per-channel tolerance."""
    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB").resize(img_a.size)
    diff = ImageChops.difference(img_a, img_b)
    pixels = list(diff.getdata())
    changed = sum(1 for px in pixels if max(px) > 24)
    return changed / len(pixels)


@pytest.fixture(scope="module")
def fixture_ids() -> Any:
    conn = psycopg.connect(_pg_dsn())
    ids = _setup_fixture(conn)
    try:
        yield ids
    finally:
        _teardown_fixture(conn, ids)
        conn.close()


@pytest.fixture(scope="module")
def pg_conn() -> Any:
    conn = psycopg.connect(_pg_dsn())
    try:
        yield conn
    finally:
        conn.close()


def test_tipg_matches_baseline(fixture_ids: Any, pg_conn: Any, tmp_path: Path) -> None:
    """Sanity check: tipg rendering today should still match the checked-in
    baseline — if this fails, the baseline is stale, not (necessarily) a bug."""
    assert BASELINE_PATH.exists(), (
        f"No baseline at {BASELINE_PATH} — generate one with "
        "`python tests/workspace/test_map_render_parity.py --update-baseline`"
    )
    _set_backend(pg_conn, fixture_ids["workspace_id"], "tipg")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        out = tmp_path / "tipg.png"
        _export_map_png(page, fixture_ids["workspace_id"], out)
        browser.close()

    diff = _image_diff_ratio(out, BASELINE_PATH)
    assert diff < 0.02, (
        f"tipg render drifted {diff:.1%} from baseline — investigate before blaming Martin"
    )


def test_martin_matches_tipg_baseline(
    fixture_ids: Any, pg_conn: Any, tmp_path: Path
) -> None:
    """The actual regression guard: Martin should render the identical
    graduated symbology tipg does, not a flat fallback color."""
    assert BASELINE_PATH.exists(), (
        f"No baseline at {BASELINE_PATH} — generate one with "
        "`python tests/workspace/test_map_render_parity.py --update-baseline`"
    )
    _set_backend(pg_conn, fixture_ids["workspace_id"], "martin")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        out = tmp_path / "martin.png"
        _export_map_png(page, fixture_ids["workspace_id"], out)
        browser.close()

    diff = _image_diff_ratio(out, BASELINE_PATH)
    assert diff < 0.05, (
        f"martin render differs {diff:.1%} from the tipg baseline (tolerance 5%) — "
        f"see {out} vs {BASELINE_PATH}"
    )


def _update_baseline() -> None:
    """Regenerate the checked-in tipg baseline. Run explicitly; inspect the
    new image before committing it."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "brewgis.config.settings")
    django.setup()

    conn = psycopg.connect(_pg_dsn())
    ids = _setup_fixture(conn)
    try:
        _set_backend(conn, ids["workspace_id"], "tipg")
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1000, "height": 900})
            _export_map_png(page, ids["workspace_id"], BASELINE_PATH)
            browser.close()
        print(f"Wrote baseline to {BASELINE_PATH}")  # noqa: T201
    finally:
        _teardown_fixture(conn, ids)
        conn.close()


if __name__ == "__main__":
    if "--update-baseline" in sys.argv:
        _update_baseline()
    else:
        print(__doc__)  # noqa: T201
