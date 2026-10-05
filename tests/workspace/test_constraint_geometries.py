# ruff: noqa: ANN003, ANN201, ANN202, ANN204
"""``constraint_geometries`` expands a scenario's constraint configuration.

The macro is what turns ``Scenario.constraints`` (per-scenario data) into the
constraint-polygon relation ``env_constraint`` reads, so its two jobs are worth
pinning: the SQL it renders (both CRSes per polygon, the discount, the geometry
column default) and the names it refuses. A name it lets through is spliced
into a FROM clause, so a bad one is a SQL-injection vector rather than a bug.
"""

from __future__ import annotations

import json

import pytest
from sqlglot import parse_one

from brewgis.sqlmesh.macros.spatial_ops import constraint_geometries


class _Vars:
    """Stand-in for the macro evaluator: ``local_srid`` and ``parse_one``."""

    def __init__(self, **variables):
        self._variables = variables

    def var(self, name, default=None):
        return self._variables.get(name, default)

    def parse_one(self, sql):
        return parse_one(sql)


def _render(constraints, *, srid=3310):
    """The macro's SQL, lowercased and whitespace-collapsed.

    sqlglot normalizes what it renders (``ST_Transform`` becomes
    ``ST_TRANSFORM``, ``x::double precision`` becomes ``CAST(x AS DOUBLE)``), so
    the assertions below read the rendered text rather than the hand-written
    form.
    """
    rendered = constraint_geometries(_Vars(local_srid=srid), json.dumps(constraints))
    return " ".join(rendered.sql().lower().split())


def test_empty_configuration_renders_an_empty_relation():
    """No constraints means no polygons, not a missing relation: the consuming
    model's LATERAL and its column references have to stay valid."""
    rendered = _render([])
    assert "where false" in rendered
    assert "probe_geom" in rendered
    assert "local_geom" in rendered
    assert " from " not in rendered.split("where false")[0]


def test_entry_renders_both_crses_the_discount_and_the_geometry_column():
    rendered = _render(
        [
            {
                "table": "public.sac_cnty_wetlands",
                "discount_pct": 100,
                "geom_col": "wkb_geometry",
            }
        ]
    )
    # Tested in EPSG:4326 (the canvas's own CRS, so the predicate can drive its
    # GiST index) and measured in the region's local_srid.
    assert 'st_transform("wkb_geometry", 4326)' in rendered
    assert 'st_transform("wkb_geometry", 3310)' in rendered
    assert '"public"."sac_cnty_wetlands"' in rendered
    assert "discount_pct" in rendered
    assert "100.0" in rendered


def test_geometry_column_defaults_to_geom():
    rendered = _render([{"table": "wetlands", "discount_pct": 50}])
    assert 'st_transform("geom", 4326)' in rendered
    assert '"wetlands"' in rendered
    assert "50.0" in rendered


def test_several_entries_union_in_configured_order():
    rendered = _render(
        [
            {
                "table": "public.streams",
                "discount_pct": 100,
                "geom_col": "wkb_geometry",
            },
            {
                "table": "public.wetlands",
                "discount_pct": 75,
                "geom_col": "wkb_geometry",
            },
        ]
    )
    assert rendered.count("union all") == 1
    assert rendered.index('"public"."streams"') < rendered.index('"public"."wetlands"')
    assert "75.0" in rendered


@pytest.mark.parametrize(
    "table",
    [
        "public.bad-name",
        "public.wetlands; DROP TABLE parcels",
        'public."wetlands"',
        "a.b.c.d",
    ],
)
def test_a_name_that_is_not_a_plain_identifier_is_refused(table):
    """Anything that is not one to three plain identifiers is spliced SQL."""
    with pytest.raises(ValueError, match="not a plain SQL identifier"):
        _render([{"table": table, "discount_pct": 100, "geom_col": "geom"}])


def test_a_geometry_column_that_is_not_a_plain_identifier_is_refused():
    with pytest.raises(ValueError, match="not a plain SQL identifier"):
        _render(
            [
                {
                    "table": "public.wetlands",
                    "discount_pct": 100,
                    "geom_col": "wkb_geometry) FROM x --",
                }
            ]
        )


def test_an_entry_without_a_table_is_refused():
    with pytest.raises(ValueError, match="names no table"):
        _render([{"discount_pct": 100, "geom_col": "geom"}])


@pytest.mark.parametrize("discount", [-1, 101, 100.5])
def test_a_discount_outside_zero_to_one_hundred_is_refused(discount):
    with pytest.raises(ValueError, match="between 0 and 100"):
        _render([{"table": "wetlands", "discount_pct": discount}])


def test_malformed_json_is_refused():
    with pytest.raises(ValueError, match="valid JSON"):
        constraint_geometries(_Vars(local_srid=3310), "{not json")


def test_a_json_object_instead_of_a_list_is_refused():
    with pytest.raises(TypeError, match="must be a JSON list"):
        constraint_geometries(_Vars(local_srid=3310), '{"table": "wetlands"}')


def test_a_non_object_entry_is_refused():
    with pytest.raises(TypeError, match="is not an object"):
        constraint_geometries(_Vars(local_srid=3310), '["wetlands"]')


def test_an_unset_local_srid_is_refused():
    """No CRS is guessed: the measurement CRS must be configuration."""
    with pytest.raises(ValueError, match="local_srid"):
        constraint_geometries(_Vars(), '[{"table": "wetlands", "discount_pct": 100}]')


def test_the_local_crs_comes_from_the_region_configuration():
    """The measurement CRS is the scenario's, not a hardcoded one."""
    rendered = _render([{"table": "wetlands", "discount_pct": 100}], srid=2226)
    assert 'st_transform("geom", 2226)' in rendered
