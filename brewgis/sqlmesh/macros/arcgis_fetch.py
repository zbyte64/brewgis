"""Generalized ArcGIS FeatureServer page enumeration for staging models.

ArcGIS FeatureServer/MapServer services cap responses at 2000 records per
request regardless of ``resultRecordCount``. The page URL list is derived at
render time from the service's live ``returnCountOnly`` count for the same
``where``/envelope query, so fetches scale automatically if a source dataset
grows or shrinks. If the count cannot be probed (no network, API change), a
documented fallback page count is used — extra pages are harmless because
out-of-range ``resultOffset`` values return an empty FeatureCollection
(HTTP 200), and a shortfall would silently truncate the fetch.

DuckDB forbids subqueries and lateral column references inside table
functions, so the page URL list fed to ``read_json_auto`` must be a constant
literal expression — this macro emits it as compile-time SQL text.

SQLMesh binds macro arguments positionally from the SQL call (``name = value``
keywords arrive as ``exp.EQ`` nodes in call order), so call sites MUST pass
arguments in signature order.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from sqlglot import exp
from sqlmesh import macro

_PAGE_SIZE = 2000
# Hard cap on the derived page count — guards against a misbehaving probe.
_MAX_PAGE_COUNT = 64
# Extra pages beyond ceil(count / page_size) absorb source growth between the
# count probe and the page fetches.
_HEADROOM_PAGES = 1


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


def _probe_once(count_url: str) -> int:
    """Issue one count query; raise on transport/parse failure."""
    req = urllib.request.Request(  # noqa: S310
        count_url,
        headers={"User-Agent": "BrewGIS/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    count = payload.get("count")
    if not isinstance(count, (int, float)) or count <= 0:
        error_message = "invalid count payload"
        raise ValueError(error_message)
    return int(count)


@lru_cache(maxsize=32)
def _fetch_feature_count(count_url: str) -> int | None:
    """Return the feature count for *count_url*, or None if unprobeable."""
    for _ in range(2):
        try:
            return _probe_once(count_url)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
        ):
            pass
    return None


@macro()
def arcgis_page_urls(  # noqa: PLR0913
    evaluator,
    endpoint: str,
    where: str,
    out_fields: str,
    geometry: str | None = None,
    fallback_pages: int = 8,
) -> str:
    """Return a DuckDB ``list_value(...)`` literal of paginated query URLs.

    Feature URLs request GeoJSON (f=geojson, outSR=4326); when *geometry* is
    given, both the feature URLs and the count probe filter to that envelope
    (``esriGeometryEnvelope``). The count probe adds ``inSR=4326`` so the
    server interprets the envelope as lon/lat — without it the count endpoint
    returns 0.

    The page count is derived from the live service count (plus headroom) so
    the fetch scales if the source dataset changes; it falls back to
    *fallback_pages* when the count cannot be probed.
    """
    endpoint = _literal_value(endpoint)
    quoted_where = quote(_literal_value(where), safe="")
    quoted_out_fields = quote(_literal_value(out_fields), safe="")
    fallback_pages = int(_literal_value(fallback_pages))
    geometry = None if geometry is None else _literal_value(geometry)
    if geometry is not None:
        quoted_geometry = quote(_literal_value(geometry), safe="")
        base_url = (
            f"{endpoint}?where={quoted_where}"
            f"&outFields={quoted_out_fields}"
            "&returnGeometry=true"
            "&f=geojson"
            "&outSR=4326"
            f"&resultRecordCount={_PAGE_SIZE}"
            f"&geometry={quoted_geometry}"
            "&geometryType=esriGeometryEnvelope"
        )
        count_url = (
            f"{endpoint}?where={quoted_where}"
            "&f=json"
            "&returnCountOnly=true"
            "&inSR=4326"
            f"&geometry={quoted_geometry}"
            "&geometryType=esriGeometryEnvelope"
        )
    else:
        base_url = (
            f"{endpoint}?where={quoted_where}"
            f"&outFields={quoted_out_fields}"
            "&returnGeometry=true"
            "&f=geojson"
            "&outSR=4326"
            f"&resultRecordCount={_PAGE_SIZE}"
        )
        count_url = f"{endpoint}?where={quoted_where}&f=json&returnCountOnly=true"

    count = _fetch_feature_count(count_url)
    if count is None:
        page_count = fallback_pages
    else:
        page_count = min(
            math.ceil(count / _PAGE_SIZE) + _HEADROOM_PAGES, _MAX_PAGE_COUNT
        )
    urls = [f"{base_url}&resultOffset={i * _PAGE_SIZE}" for i in range(page_count)]
    return "list_value(" + ", ".join(repr(u) for u in urls) + ")"
