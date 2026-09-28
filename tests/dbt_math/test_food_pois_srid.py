# ruff: noqa: S608 — the identifiers interpolated into the fixture and the
# model's own query are quote-escaped names, never values.
"""Contract: a region's published food-outlet source carries its CRS.

``brewgis.<region>.food_pois_raw`` is a DuckDB-gateway bridge, and that transfer
writes SRID-less WKB: every point lands as SRID 0 however the fetch tagged it
(see the bridge's header). Martin publishes a tile source from the geometry
column and transforms it per tile request, so a Layer registered over the bridge
drew nothing on the map while its rows still showed in the attribute table
(``ST_Transform: Input geometry has unknown (0) SRID``).

The source a Layer reads is therefore the PostGIS VIEW
``brewgis.<region>.food_pois``, which re-tags the bridge's points with
``ST_SetSRID`` — the same repair ``census/tiger_blocks.sql`` makes for its
bridge.

The test executes that published VIEW's own query (rendered by SQLMesh, so the
model file stays the single source of truth) over a bridge table holding SRID-0
points, exactly what the DuckDB push stores, and asserts the CRS survives the
projection the tile server runs. Before the fix the published source *was* the
bridge: SRID 0, and ``ST_Transform`` failed the way Martin's tile requests did.
"""

from __future__ import annotations

# ruff: noqa: S608 — the identifiers interpolated into the fixture and the
# model's own query are quote-escaped names, never values.
import re
import shutil
import tempfile

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.region_blueprints import REGIONS
from brewgis.workspace.analysis.sqlmesh_runner import get_context

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    # transaction=True so the parity fixture's committed blueprint rows are
    # visible to SQLMesh's forked model-loading workers.
    pytest.mark.django_db(transaction=True),
]

_TILE_SRID = 3857
"""The SRID Martin projects every source into before tiling it."""


def test_published_food_pois_source_retags_the_bridge(parity_scenario: str) -> None:
    """Every region's published food-outlet source can be projected to tiles."""
    cache_dir = tempfile.mkdtemp(prefix="brewgis-food-pois-srid-")
    context = get_context(cache_dir=cache_dir)
    try:
        for region in sorted(REGIONS):
            name = f"brewgis.{region}.food_pois"
            model = context.get_model(name)
            assert model is not None, name
            assert model.gateway in (None, "postgis"), (
                f"{name} is on the DuckDB gateway: the tile server reads its "
                "geometry column, which a DuckDB bridge leaves at SRID 0"
            )

            query = model.render_query()
            assert query is not None, name
            rendered = query.sql(dialect="postgres")
            # Executed against the test database, whose name stands in for the
            # project's logical `brewgis` catalog.
            rendered = re.sub(r'"brewgis"\.', "", rendered)

            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{region}"')
                cursor.execute(f'DROP TABLE IF EXISTS "{region}".food_pois_raw')
                cursor.execute(
                    f'CREATE TABLE "{region}".food_pois_raw ('
                    "osm_id BIGINT, name TEXT, shop TEXT, amenity TEXT, "
                    "food_class TEXT, geometry geometry)"
                )
                # SRID 0, as the DuckDB-to-PostGIS bridge stores every point.
                cursor.execute(
                    f'INSERT INTO "{region}".food_pois_raw VALUES ('
                    "1, 'Market', 'supermarket', '', 'healthy', "
                    "ST_GeomFromText('POINT(-119.8 36.7)'))"
                )
                cursor.execute(
                    f"SELECT ST_SRID(geometry), "
                    f"ST_AsText(ST_Transform(geometry, {_TILE_SRID})) "
                    f"FROM ({rendered}) AS published"
                )
                srid, projected = cursor.fetchone()
                cursor.execute(f'DROP TABLE "{region}".food_pois_raw')

            assert srid == 4326, f"{name} publishes SRID {srid}"
            assert projected is not None
    finally:
        for adapter in (context.engine_adapters or {}).values():
            adapter.close()
        context.close()
        shutil.rmtree(cache_dir, ignore_errors=True)
