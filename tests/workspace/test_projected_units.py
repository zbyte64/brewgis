# ruff: noqa: ANN201, ANN202, ANN204, ANN003, S608
"""Projected measurements follow the local CRS's own linear unit.

``local_srid`` differs per region — CA Albers is in metres, most US State Plane
zones are in US survey feet, some in international feet — so an area or distance
measured in it must be scaled by that CRS's metres-per-unit, never by a constant
that assumes metres. A State Plane (ftUS) region used to report parcels ~10.8x
too large in acres and trips ~3.3x too long in km.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.geometry import local_length_metres
from brewgis.sqlmesh.macros.geometry import metres_in_local_units
from brewgis.sqlmesh.macros.geometry import metres_per_unit
from brewgis.sqlmesh.macros.geometry import st_area_projected

# ~1 km x 1 km block in Sacramento, inside both CA Albers and CA State Plane zone 2.
_PARCEL = "SRID=4326;POLYGON((-121.50 38.50,-121.49 38.50,-121.49 38.51,-121.50 38.51,-121.50 38.50))"

_CRS_UNITS = pytest.mark.parametrize(
    "srid",
    [
        pytest.param(3310, id="ca-albers-metres"),
        pytest.param(2226, id="ca-state-plane-2-us-survey-feet"),
    ],
)


class _Vars:
    def __init__(self, **variables):
        self._variables = variables

    def var(self, name, default=None):
        return self._variables.get(name, default)


def test_international_foot_crs_scales_by_its_foot():
    """Michigan North (ft) is in international feet, not metres or US survey feet."""
    assert metres_per_unit(2251) == pytest.approx(0.3048, rel=1e-12)


def test_geographic_crs_is_refused():
    """Degrees have no planar length: a geographic local_srid must fail loudly."""
    with pytest.raises(ValueError, match="not a projected CRS"):
        metres_per_unit(4326)


def test_unset_local_srid_is_refused():
    """No CRS is guessed when local_srid is missing."""
    with pytest.raises(ValueError, match="local_srid"):
        st_area_projected(_Vars(), "geometry")


@pytest.mark.integration
@pytest.mark.django_db
@_CRS_UNITS
def test_parcel_acres_match_geodesic_area_in_any_unit(srid):
    """The same parcel measures the same acreage whatever the CRS's linear unit."""
    area_sql = st_area_projected(_Vars(local_srid=srid), "g")
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT {area_sql}, ST_Area(g::geography) / 4046.86 FROM (SELECT %s::geometry AS g) AS p",
            [_PARCEL],
        )
        projected_acres, geodesic_acres = cur.fetchone()
    assert projected_acres == pytest.approx(geodesic_acres, rel=5e-3)


@pytest.mark.integration
@pytest.mark.django_db
@_CRS_UNITS
def test_local_length_matches_geodesic_length_in_any_unit(srid):
    """A road length measured in local_srid comes out in metres whatever the CRS's unit."""
    length_sql = local_length_metres(
        _Vars(local_srid=srid), f"ST_Length(ST_Transform(g, {srid}))"
    )
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT {length_sql}, ST_Length(g::geography)"
            " FROM (SELECT ST_Boundary(%s::geometry) AS g) AS p",
            [_PARCEL],
        )
        projected_m, geodesic_m = cur.fetchone()
    assert projected_m == pytest.approx(geodesic_m, rel=5e-3)


@pytest.mark.integration
@pytest.mark.django_db
@_CRS_UNITS
def test_metre_radius_selects_by_metres_in_any_unit(srid):
    """A 402 m search radius keeps a point ~390 m away and drops one ~415 m away."""
    radius_sql = metres_in_local_units(_Vars(local_srid=srid), "402.0")
    with connection.cursor() as cur:
        cur.execute(
            f"""
            WITH o AS (SELECT 'SRID=4326;POINT(-121.5 38.5)'::geography AS g),
            pts AS (
                SELECT ST_Transform(g::geometry, {srid}) AS origin,
                       ST_Transform(ST_Project(g, 390, 0)::geometry, {srid}) AS near,
                       ST_Transform(ST_Project(g, 415, 0)::geometry, {srid}) AS far
                FROM o
            )
            SELECT ST_DWithin(origin, near, {radius_sql}), ST_DWithin(origin, far, {radius_sql}) FROM pts
            """
        )
        assert cur.fetchone() == (True, False)
