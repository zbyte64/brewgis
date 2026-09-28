# ruff: noqa: S608 — the identifiers interpolated into the fixtures and into the
# models' own rendered queries are quote-escaped names, never values.
"""Contract: every published source wrapping a DuckDB bridge carries its CRS.

A DuckDB-gateway bridge writes SRID-less WKB, so however its SELECT tags a
geometry, the column lands as SRID 0 (``osm/food_pois_raw.sql`` records the
probe). The tile server publishes a source from the geometry column and
transforms it per tile request, so a source registered over a bridge answers
every tile request with ``ST_Transform: Input geometry has unknown (0) SRID`` —
a Layer drew nothing on the map while its rows still showed in the attribute
table.

Each published name is therefore a PostGIS VIEW that re-tags its bridge with
``ST_SetSRID``, the repair ``census/tiger_blocks.sql`` makes, and each bridge
keeps the ``_raw`` suffix so the split is visible at every call site.

The test renders each published VIEW's own query — the model file stays the
single source of truth — runs it over a synthetic bridge table holding SRID-0
geometries, exactly what the DuckDB push stores, and asserts every geometry
column survives with its CRS. Before the fix each of these names *was* the
bridge: SRID 0, and ``ST_Transform`` failed the way Martin's tile requests did.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.region_blueprints import REGIONS
from brewgis.workspace.analysis.sqlmesh_runner import get_context

if TYPE_CHECKING:
    from sqlmesh.core.context import Context

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    # transaction=True so the parity fixture's committed blueprint rows are
    # visible to SQLMesh's forked model-loading workers.
    pytest.mark.django_db(transaction=True),
]

_TILE_SRID = 3857
"""The SRID the tile server projects every source into before tiling it."""

_LOCAL = "local_srid"
"""Marker for a column the model tags with the project's own ``local_srid``."""

_POINT = "ST_GeomFromText('POINT(-119.8 36.7)')"
_POLYGON = (
    "ST_GeomFromText('POLYGON((-119.9 36.6, -119.9 36.7, -119.8 36.6, -119.9 36.6))')"
)
_LINE = "ST_GeomFromText('LINESTRING(-119.9 36.6, -119.8 36.7)')"


@dataclass(frozen=True)
class Bridge:
    """A DuckDB bridge and the published VIEW the project exposes over it."""

    published: str
    """Model FQN of the published VIEW; ``{region}`` where the model is regional."""

    raw: str
    """Model FQN of the DuckDB bridge; ``{region}`` likewise."""

    schema: str
    """Schema the bridge table lands in; ``{region}`` for a regional bridge."""

    table: str
    """Bridge table name within *schema*, which the synthetic table stands in for."""

    ddl: str
    """Bridge columns, geometry columns untyped as the DuckDB push creates them."""

    row: str
    """One SRID-0 row for that table."""

    srids: dict[str, int | str]
    """Published column -> SRID it must report (``_LOCAL`` = the project's)."""

    @property
    def regional(self) -> bool:
        return "{region}" in self.published


BRIDGES: tuple[Bridge, ...] = (
    Bridge(
        published="brewgis.{region}.food_pois",
        raw="brewgis.{region}.food_pois_raw",
        schema="{region}",
        table="food_pois_raw",
        ddl="osm_id bigint, name text, shop text, amenity text, food_class text, geometry geometry",
        row=f"1, 'Market', 'supermarket', '', 'healthy', {_POINT}",
        srids={"geometry": 4326},
    ),
    Bridge(
        published="brewgis.{region}.buildings_combined",
        raw="brewgis.{region}.buildings_combined_raw",
        schema="{region}",
        table="buildings_combined_raw",
        ddl=(
            "geometry geometry, wgs84_geometry geometry, local_geometry geometry, "
            "height double precision, levels integer, class text, source text, "
            "bf_source text, confidence double precision"
        ),
        row=f"{_POLYGON}, {_POLYGON}, {_POLYGON}, 10.0, 2, 'residential', 'overture', NULL, NULL",
        srids={"geometry": 3857, "wgs84_geometry": 4326, "local_geometry": _LOCAL},
    ),
    Bridge(
        published="brewgis.{region}.overture_land_use",
        raw="brewgis.{region}.overture_land_use_raw",
        schema="{region}",
        table="overture_land_use_raw",
        ddl="geometry geometry, wgs84_geometry geometry, area double precision, subtype text, class text",
        row=f"{_POLYGON}, {_POLYGON}, 1.0, 'residential', 'residential'",
        srids={"geometry": 3857, "wgs84_geometry": 4326},
    ),
    Bridge(
        published="brewgis.{region}.overture_transport",
        raw="brewgis.{region}.overture_transport_raw",
        schema="{region}",
        table="overture_transport_raw",
        ddl=(
            "geometry geometry, wgs84_geometry geometry, local_geometry geometry, "
            "surface text, class text, subclass text, width double precision"
        ),
        row=f"{_LINE}, {_LINE}, NULL, 'paved', 'primary', NULL, 3.5",
        srids={"geometry": 3857, "wgs84_geometry": 4326},
    ),
    Bridge(
        published="brewgis.{region}.overture_road_subsegments",
        raw="brewgis.{region}.overture_road_subsegments_raw",
        schema="{region}",
        table="overture_road_subsegments_raw",
        ddl=(
            "segment_id text, from_connector_id text, from_at double precision, "
            "to_connector_id text, to_at double precision, wgs84_geometry geometry"
        ),
        row=f"'segment', 'from', 0.0, 'to', 1.0, {_LINE}",
        srids={"wgs84_geometry": 4326},
    ),
    Bridge(
        published="brewgis.osm.poi",
        raw="brewgis.osm.poi_raw",
        schema="osm",
        table="poi_raw",
        ddl=(
            "osm_id bigint, osm_type text, name text, category text, subcategory text, "
            "amenity text, shop text, leisure text, tourism text, geometry geometry"
        ),
        row=f"1, 'node', 'Market', 'Retail', 'shop=supermarket', '', 'supermarket', '', '', {_POINT}",
        srids={"geometry": 4326},
    ),
)


def _cases() -> list[Bridge]:
    """Every bridge, one instance per region for the regional ones."""
    cases: list[Bridge] = []
    for bridge in BRIDGES:
        if not bridge.regional:
            cases.append(bridge)
            continue
        cases.extend(
            replace(
                bridge,
                published=bridge.published.format(region=region),
                raw=bridge.raw.format(region=region),
                schema=bridge.schema.format(region=region),
            )
            for region in sorted(REGIONS)
        )
    return cases


def _rendered(context: Context, name: str) -> str:
    """The published VIEW's own query, aimed at the test database."""
    model = context.get_model(name)
    query = model.render_query()
    assert query is not None, name
    # Executed against the test database, whose name stands in for the project's
    # logical `brewgis` catalog.
    return re.sub(r'"brewgis"\.', "", query.sql(dialect="postgres"))


def test_published_views_retag_their_bridges(parity_scenario: str) -> None:
    """Every published source over a DuckDB bridge can be projected to tiles."""
    cache_dir = tempfile.mkdtemp(prefix="brewgis-bridge-srid-")
    context = get_context(cache_dir=cache_dir)
    local_srid = int(context.config.variables["local_srid"])
    try:
        for bridge in _cases():
            model = context.get_model(bridge.published)
            assert model is not None, bridge.published
            assert model.gateway in (None, "postgis"), (
                f"{bridge.published} is on the DuckDB gateway: consumers read its "
                "geometry column, which a DuckDB bridge leaves at SRID 0"
            )
            raw_model = context.get_model(bridge.raw)
            assert raw_model is not None, bridge.raw
            assert raw_model.gateway == "duckdb", (
                f"{bridge.raw} is not the DuckDB bridge the synthetic SRID-0 table "
                "stands in for; the published VIEW must wrap one"
            )

            rendered = _rendered(context, bridge.published)

            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{bridge.schema}"')
                cursor.execute(
                    f'DROP VIEW IF EXISTS "{bridge.schema}"."{bridge.table}"'
                )
                cursor.execute(
                    f'DROP TABLE IF EXISTS "{bridge.schema}"."{bridge.table}"'
                )
                cursor.execute(
                    f'CREATE TABLE "{bridge.schema}"."{bridge.table}" ({bridge.ddl})'
                )
                # SRID 0, as the DuckDB-to-PostGIS bridge stores every geometry.
                cursor.execute(
                    f'INSERT INTO "{bridge.schema}"."{bridge.table}" VALUES ({bridge.row})'
                )

                for column, expected in bridge.srids.items():
                    resolved = local_srid if expected == _LOCAL else expected
                    cursor.execute(
                        f"SELECT ST_SRID({column}), "
                        f"ST_AsText(ST_Transform({column}, {_TILE_SRID})) "
                        f"FROM ({rendered}) AS published"
                    )
                    srid, projected = cursor.fetchone()
                    assert srid == resolved, (
                        f"{bridge.published}.{column} publishes SRID {srid}, "
                        f"expected {resolved}: the tile server cannot transform it"
                    )
                    assert projected is not None, (
                        f"{bridge.published}.{column} could not be projected to "
                        f"EPSG:{_TILE_SRID}"
                    )

                cursor.execute(f'DROP TABLE "{bridge.schema}"."{bridge.table}"')
    finally:
        for adapter in (context.engine_adapters or {}).values():
            adapter.close()
        context.close()
        shutil.rmtree(cache_dir, ignore_errors=True)
