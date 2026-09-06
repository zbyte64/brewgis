"""Fresno parcel ArcGIS FeatureServer page enumeration for staging models.

The Fresno County parcel service caps responses at 2000 records per request
regardless of ``resultRecordCount``. The page URL list is derived at render
time from the service's live ``returnCountOnly`` count for the same envelope
query (~47,031 features ⇒ 25 pages with headroom), so the fetch scales
automatically if the parcel set grows or shrinks. If the count cannot be
probed (no network, API change), a documented fallback ceiling (28 pages ≈
56,000 parcels) is used — extra pages are harmless because out-of-range
``resultOffset`` values return an empty FeatureCollection (HTTP 200), and a
shortfall would silently truncate the fetch.

DuckDB forbids subqueries and lateral column references inside table
functions, so the page URL list fed to ``read_json_auto`` must be a constant
literal expression — this macro emits it as compile-time SQL text.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from functools import lru_cache

from sqlmesh import macro

_PAGE_SIZE = 2000
# Fallback ceiling when the live count probe fails (network/API change).
_FALLBACK_PAGE_COUNT = 28
# Hard cap on the derived page count — guards against a misbehaving probe.
_MAX_PAGE_COUNT = 64
# Extra pages beyond ceil(count / page_size) absorb source growth between the
# count probe and the page fetches.
_HEADROOM_PAGES = 1

_ENDPOINT = (
    "https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services"
    "/Fresno_County_Parcels/FeatureServer/0/query"
)

# URL-encoded Fresno-Clovis urban envelope (mirrors the archived
# fresno_downloader parcels definition).
_ENVELOPE = (
    "%7B%22xmin%22%3A-119.82%2C%22ymin%22%3A36.72%2C"
    "%22xmax%22%3A-119.72%2C%22ymax%22%3A36.80%7D"
)

# Feature query stem: GeoJSON output (f=geojson), outSR 4326, envelope filter.
_BASE_URL = (
    _ENDPOINT
    + "?where=1%3D1"
    + "&outFields=APN%2CAGENCY_COD%2CROLL_YEAR%2CSHAPE_AREA"
    + "&returnGeometry=true"
    + "&f=geojson"
    + "&outSR=4326"
    + "&resultRecordCount=2000"
    + "&geometry="
    + _ENVELOPE
    + "&geometryType=esriGeometryEnvelope"
)

# Count probe: inSR=4326 is required for the server to interpret the envelope
# as lon/lat (without it the count endpoint returns 0).
_COUNT_URL = (
    _ENDPOINT
    + "?where=1%3D1"
    + "&f=json"
    + "&returnCountOnly=true"
    + "&inSR=4326"
    + "&geometry="
    + _ENVELOPE
    + "&geometryType=esriGeometryEnvelope"
)


def _probe_once() -> int:
    """Issue one count query; raise on transport/parse failure."""
    req = urllib.request.Request(  # noqa: S310
        _COUNT_URL,
        headers={"User-Agent": "BrewGIS/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    count = payload.get("count")
    if not isinstance(count, (int, float)) or count <= 0:
        error_message = "invalid count payload"
        raise ValueError(error_message)
    return int(count)


@lru_cache(maxsize=1)
def _fetch_feature_count() -> int | None:
    """Return the envelope-filtered feature count, or None if unprobeable."""
    for _ in range(2):
        try:
            return _probe_once()
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
        ):
            pass
    return None


@macro()
def fresno_parcel_page_urls(evaluator) -> str:
    """Return a DuckDB ``list_value(...)`` literal of paginated query URLs.

    The page count is derived from the live service count (plus headroom) so
    the fetch scales if the parcel set changes; it falls back to a fixed
    ceiling when the count cannot be probed.
    """
    count = _fetch_feature_count()
    if count is None:
        page_count = _FALLBACK_PAGE_COUNT
    else:
        page_count = min(
            math.ceil(count / _PAGE_SIZE) + _HEADROOM_PAGES, _MAX_PAGE_COUNT
        )
    urls = [f"{_BASE_URL}&resultOffset={i * _PAGE_SIZE}" for i in range(page_count)]
    return "list_value(" + ", ".join(repr(u) for u in urls) + ")"
