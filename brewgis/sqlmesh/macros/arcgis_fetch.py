"""Generalized ArcGIS FeatureServer page enumeration for staging models.

ArcGIS FeatureServer/MapServer services cap responses at 2000 records per
request regardless of ``resultRecordCount``, so fetching a whole layer means
emitting a list of ``resultOffset`` pages. DuckDB forbids subqueries and
lateral column references inside table functions, so the page URL list fed to
``read_json_auto`` must be a constant literal expression — this macro emits it
as compile-time SQL text, and the call site declares how many pages to emit.

**The page count is declared, never probed.** An earlier version asked the
service for its live ``returnCountOnly`` count from inside the macro, which put
a third-party HTTP request on the critical path of *every* SQLMesh plan in every
container: SQLMesh renders each model while loading the project, before the plan
starts, so one slow or unreachable ArcGIS host could consume a Celery task's
entire time limit and fail an analysis run that had nothing to do with the
fetch.

Sizing the declared count leans on two properties of the services:

- **Over-fetching is free.** An out-of-range ``resultOffset`` returns HTTP 200
  with an empty FeatureCollection — verified against all six endpoints this
  macro drives — so extra pages add no rows and cost one request each. (A
  service that answers with an *error document* instead does break the fetch:
  DuckDB infers no ``features`` column and the model fails to bind. That is a
  service fault, not a paging one.)
- **Under-fetching truncates silently.** A shortfall drops features with no
  error anywhere, so each call site declares its page count with growth
  headroom and documents the live count it was sized from.

To re-check a declared count, issue the same query the macro builds with
``returnCountOnly``::

    <endpoint>?where=<where>&f=json&returnCountOnly=true
      [&inSR=4326&geometry=<envelope>&geometryType=esriGeometryEnvelope]

which returns ``{"count": N}``. Size ``pages`` at roughly 1.25 x
``ceil(N / 2000)`` — it only has to stay above the real page count.

SQLMesh binds macro arguments positionally from the SQL call (``name = value``
keywords arrive as ``exp.EQ`` nodes in call order, not by name), so call sites
MUST pass arguments in signature order. ``geometry`` and ``pages`` are therefore
required parameters rather than optional ones: skipping an optional parameter
in the middle hands its slot to the next argument, and a call site that passed
only ``pages`` once reached the service as ``&geometry=1`` — an error document
instead of a FeatureCollection, which failed the plan inside DuckDB with a
binder error naming neither the model nor the argument.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from sqlglot import exp
from sqlmesh import macro

_PAGE_SIZE = 2000
# Hard ceiling on the declared page count — a typo in a call site's ``pages``
# must not emit thousands of URLs. Sized above the largest region fetch: the
# fresno region bbox (fresno.assessor_parcels_raw, FC_PARCEL_SELECT) is ~340k
# features = 171 pages, and clamping below the real page count silently
# truncates the fetch instead of failing.
_MAX_PAGE_COUNT = 256


def _literal_value(value: Any) -> Any:
    """Unwrap a SQLMesh macro argument to its Python value.

    Arguments passed from SQL arrive as sqlglot expressions: string/number
    literals become ``exp.Literal``, and ``name = value`` keywords arrive as
    ``exp.EQ`` nodes whose ``.expression`` holds the actual value. Python-side
    callers pass plain values.
    """
    if isinstance(value, exp.EQ):
        value = value.expression
    if isinstance(value, exp.Null):
        return None
    if isinstance(value, exp.Literal):
        return value.this
    return value


def _raw_argument(value: Any) -> Any:
    """The sqlglot node behind a macro argument (``name = value`` arrives as ``exp.EQ``)."""
    return value.expression if isinstance(value, exp.EQ) else value


def _order_error(name: str, expected: str, value: Any) -> str:
    return (
        f"arcgis_page_urls: {name} must be {expected}, got {value!r} — check the "
        "call site's argument order (SQLMesh binds keywords by position, not by "
        "name, so an omitted argument shifts every later one)"
    )


def _text(value: Any, *, name: str) -> str | None:
    """*value* as text, or ``None`` for SQL NULL — refusing anything else.

    A *number* in a text slot is refused rather than stringified. SQLMesh binds
    a call site's ``name = value`` keywords to parameters **by position**, not
    by name, so a call that skips the optional-looking *geometry* hands its slot
    to the next argument: a page count once reached the service as
    ``&geometry=1``, which ArcGIS answers with an error document instead of a
    FeatureCollection — the fetch then failed deep inside DuckDB with a binder
    error naming neither the model nor the argument. ``geometry`` and ``pages``
    are required parameters for the same reason; this check names the call site
    if a value still lands in the wrong slot.
    """
    node = _raw_argument(value)
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Literal):
        if not node.is_string:
            raise ValueError(_order_error(name, "a string literal or NULL", node))
        return str(node.this)
    if node is None:
        return None
    if isinstance(node, str):
        # Plain Python callers (unit tests) pass the value itself.
        return node
    raise ValueError(_order_error(name, "a string literal or NULL", node))


def _integer(value: Any, *, name: str) -> int:
    """*value* as an int, refusing anything else (and naming *name* if not)."""
    node = _raw_argument(value)
    if isinstance(node, exp.Literal):
        # sqlglot hands numeric literals over as their *text*, the same place a
        # string literal's contents live, so ``is_int`` is what distinguishes them.
        if not node.is_int:
            raise ValueError(_order_error(name, "an integer literal", node))
        return int(node.this)
    if isinstance(node, int) and not isinstance(node, bool):
        return node
    raise ValueError(_order_error(name, "an integer literal", node))


@macro()
def arcgis_page_urls(  # noqa: PLR0913
    evaluator,
    endpoint: str,
    where: str,
    out_fields: str,
    geometry: str | None,
    pages: int,
    order_by: str | None = None,
) -> str:
    """Return a DuckDB ``list_value(...)`` literal of paginated query URLs.

    *geometry* and *pages* have no defaults on purpose: SQLMesh binds keywords
    positionally, so an omitted parameter in the middle shifts every later
    argument into the wrong slot — a silent corruption this signature makes
    impossible. Pass ``NULL`` when there is no envelope.

    Feature URLs request GeoJSON (f=geojson, outSR=4326); when *geometry* is
    given, they filter to that envelope (``esriGeometryEnvelope``), declared
    ``inSR=4326`` so the server interprets the envelope as lon/lat — without it
    a projected layer (e.g. the Fresno County assessor MapServer, SR 2228) reads
    the envelope in its own SR and returns zero features.

    When *order_by* is given it is appended as ``orderByFields``, which makes
    ``resultOffset`` paging deterministic (a county MapServer gives no stable
    row order otherwise, so adjacent pages can overlap or skip features).

    *pages* is the number of ``resultOffset`` pages to emit, clamped to at least
    one (an empty list is not a valid table function argument) and at most
    ``_MAX_PAGE_COUNT``. It is declared by the call site — see the module
    docstring for how to size and re-check it.
    """
    endpoint_url = _text(endpoint, name="endpoint") or ""
    quoted_where = quote(_text(where, name="where") or "", safe="")
    quoted_out_fields = quote(_text(out_fields, name="out_fields") or "", safe="")
    geometry = _text(geometry, name="geometry")
    page_count = max(1, min(_integer(pages, name="pages"), _MAX_PAGE_COUNT))
    order_by = _text(order_by, name="order_by")
    if geometry is not None:
        quoted_geometry = quote(geometry, safe="")
        base_url = (
            f"{endpoint_url}?where={quoted_where}"
            f"&outFields={quoted_out_fields}"
            "&returnGeometry=true"
            "&f=geojson"
            "&outSR=4326"
            f"&resultRecordCount={_PAGE_SIZE}"
            f"&geometry={quoted_geometry}"
            "&geometryType=esriGeometryEnvelope"
            # inSR declares the envelope is lon/lat. Required for services
            # whose layer SR is projected (e.g. the Fresno County assessor
            # MapServer is SR 2228): without it the server reads the envelope
            # in the layer SR and returns zero features. A no-op for 4326.
            "&inSR=4326"
        )
    else:
        base_url = (
            f"{endpoint_url}?where={quoted_where}"
            f"&outFields={quoted_out_fields}"
            "&returnGeometry=true"
            "&f=geojson"
            "&outSR=4326"
            f"&resultRecordCount={_PAGE_SIZE}"
        )

    if order_by is not None:
        base_url += "&orderByFields=" + quote(order_by, safe="")

    urls = [f"{base_url}&resultOffset={i * _PAGE_SIZE}" for i in range(page_count)]
    return "list_value(" + ", ".join(repr(u) for u in urls) + ")"
