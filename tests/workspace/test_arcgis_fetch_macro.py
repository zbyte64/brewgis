# ruff: noqa: ANN201, ANN202, ANN003, ARG005
"""Tests for the ArcGIS page-URL macro — the fresno staging models' page list.

SQLMesh renders every model while it loads the project, in every container, on
every plan, so this macro's contract is to *emit SQL and nothing else*. It used
to ask the service for a live feature count first, which put a third-party HTTP
request on the critical path of every plan: one slow ArcGIS host ate a Celery
task's whole time limit and failed an analysis run (run 67) before the plan
started. The page count is declared by the call site instead.
"""

from __future__ import annotations

import urllib.request

import pytest
from sqlglot import exp

from brewgis.sqlmesh.macros.arcgis_fetch import _MAX_PAGE_COUNT
from brewgis.sqlmesh.macros.arcgis_fetch import arcgis_page_urls

_ENDPOINT = "https://example.invalid/FeatureServer/0/query"
_ENVELOPE = '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}'


def _render(**overrides):
    """Render the macro the way the staging models call it."""
    arguments = {
        "endpoint": _ENDPOINT,
        "where": "1=1",
        "out_fields": "APN",
        "geometry": _ENVELOPE,
        "pages": 3,
    }
    arguments.update(overrides)
    return arcgis_page_urls(None, **arguments)


def _urls(sql: str) -> list[str]:
    return sql.removeprefix("list_value(").removesuffix(")").split(", ")


def _as_sqlmesh_arguments(**overrides):
    """The sqlglot nodes a ``@arcgis_page_urls(...)`` call site actually passes."""
    arguments = {
        "endpoint": exp.Literal.string(_ENDPOINT),
        "where": exp.Literal.string("1=1"),
        "out_fields": exp.Literal.string("APN"),
        "geometry": exp.Literal.string(_ENVELOPE),
        "pages": exp.Literal.number(3),
    }
    arguments.update(overrides)
    return arguments


class TestRenderingIsOffline:
    """Rendering must not depend on the network being up, or fast."""

    def test_rendering_issues_no_http_request(self, monkeypatch):
        requests = []
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda *args, **kwargs: requests.append(args)
        )

        sql = _render()

        assert requests == []
        assert sql.startswith("list_value(")
        # The envelope has to be declared lon/lat, or a projected service (the
        # Fresno County assessor MapServer is SR 2228) returns zero features.
        assert "inSR=4326" in sql
        assert "resultRecordCount=2000" in sql


class TestPageList:
    """The emitted page list is the fetch's contract with DuckDB."""

    def test_emits_one_offset_url_per_declared_page(self):
        urls = _urls(_render(pages=3))

        assert len(urls) == 3
        assert "resultOffset=0" in urls[0]
        assert "resultOffset=2000" in urls[1]
        assert "resultOffset=4000" in urls[2]

    def test_order_by_is_passed_through(self):
        # Without ordering the service gives no stable row order, so adjacent
        # pages can overlap or skip features.
        assert all(
            "orderByFields=OBJECTID" in url
            for url in _urls(_render(pages=1, order_by="OBJECTID"))
        )

    def test_never_emits_an_empty_list_and_respects_the_cap(self):
        # An empty list_value() is not a valid table-function argument, so a
        # declared count below one page still has to yield a URL.
        assert _render(pages=0).count("resultOffset=") == 1
        # A typo in a call site must not emit thousands of URLs.
        assert _render(pages=10_000).count("resultOffset=") == _MAX_PAGE_COUNT


class TestArgumentBinding:
    """SQLMesh binds a call site's keywords *positionally*, and passes sqlglot nodes.

    A parameter skipped in the middle hands its slot to the next argument, so a
    call site that passes ``pages`` without ``geometry`` renders
    ``&geometry=<pages>``. ArcGIS answers that with an error document rather than
    a FeatureCollection, which failed a plan inside DuckDB with a binder error
    naming neither the model nor the argument — hence the type checks below.
    """

    def test_accepts_the_nodes_a_call_site_passes(self):
        """sqlglot hands numeric literals over as text (``Literal.this == "3"``),
        so this is the shape that reaches the macro from SQL rather than from a
        Python test call."""
        sql = arcgis_page_urls(None, **_as_sqlmesh_arguments())

        assert len(_urls(sql)) == 3
        assert "inSR=4326" in sql

    def test_null_geometry_omits_the_envelope_filter(self):
        sql = arcgis_page_urls(
            None,
            **_as_sqlmesh_arguments(geometry=exp.Null(), pages=exp.Literal.number(1)),
        )

        assert "geometry=" not in sql
        assert "geometryType" not in sql
        assert len(_urls(sql)) == 1

    def test_refuses_a_page_count_in_the_geometry_slot(self):
        with pytest.raises(ValueError, match="geometry"):
            arcgis_page_urls(
                None,
                **_as_sqlmesh_arguments(
                    geometry=exp.Literal.number(1), pages=exp.Literal.number(8)
                ),
            )

    def test_refuses_text_in_the_pages_slot(self):
        with pytest.raises(ValueError, match="pages"):
            arcgis_page_urls(
                None,
                **_as_sqlmesh_arguments(pages=exp.Literal.string("OBJECTID")),
            )
