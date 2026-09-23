"""Overpass API query construction for the DuckDB POI fetch model.

Single source of truth for the OpenStreetMap tag taxonomy behind
``duckdb.osm.poi``: the URL that model fetches, the category/subcategory CASE
expressions it classifies rows with, and — through :data:`POI_CATEGORIES` — the
category list Django's POI import form offers.

The taxonomy is emitted as one anchored-regex clause per OSM key
(``node["amenity"~"^(cafe|bar)$"](bbox)``) instead of one exact-match clause per
tag, because Overpass is read over HTTP GET (DuckDB's httpfs has no POST) and
the whole query travels in the request line.  Measured 2026-09-22 against
overpass-api.de with the full taxonomy and a Sacramento bbox: 53 exact-match
clauses -> 9,724-byte URL -> HTTP 414 (URI Too Long); 16 regex clauses ->
2,753-byte URL -> HTTP 200.  The alternations are anchored and the values are
``[a-z_]+`` literals escaped through :func:`re.escape`, so the matched elements
are exactly the ones the tag list names — this is a URL-length change, not a
change of which POIs are fetched.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sqlglot import exp
from sqlmesh import macro

# Overpass endpoint. The main instance (overpass-api.de) stalls DuckDB's httpfs
# GET for this query shape — measured 2026-09-22: httpfs reported "Could not
# connect to server" after 30 s and, from SQLMesh's gateway connection, HTTP 504,
# while urllib fetched the identical URL from the same host in about a second
# (88 elements). The Kumi mirror serves the same query to httpfs in ~19 s, so it
# is what this model fetches from; swapping the host here is the only change a
# future move back to the main instance needs.
OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"

# POI category definitions: category -> list of (tag key, tag value) filters.
# An element belongs to the first category in this order that owns one of its
# tags, which is also the order the generated CASE expressions test.
POI_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "restaurants": [
        ("amenity", "restaurant"),
        ("amenity", "fast_food"),
        ("amenity", "cafe"),
        ("amenity", "bar"),
        ("amenity", "pub"),
    ],
    "schools": [
        ("amenity", "school"),
        ("amenity", "university"),
        ("amenity", "college"),
        ("amenity", "library"),
    ],
    "hospitals": [
        ("amenity", "hospital"),
        ("amenity", "clinic"),
        ("amenity", "pharmacy"),
        ("amenity", "doctors"),
    ],
    "parks": [
        ("leisure", "park"),
        ("leisure", "playground"),
        ("leisure", "garden"),
        ("leisure", "nature_reserve"),
        ("landuse", "recreation_ground"),
    ],
    "transit": [
        ("amenity", "bus_station"),
        ("amenity", "ferry_terminal"),
        ("amenity", "taxi"),
        ("railway", "station"),
        ("railway", "halt"),
        ("highway", "bus_stop"),
    ],
    "shopping": [
        ("shop", "supermarket"),
        ("shop", "convenience"),
        ("shop", "mall"),
        ("shop", "department_store"),
        ("shop", "retail"),
    ],
    "lodging": [
        ("tourism", "hotel"),
        ("tourism", "motel"),
        ("tourism", "hostel"),
        ("tourism", "guest_house"),
        ("tourism", "camp_site"),
    ],
    "entertainment": [
        ("amenity", "cinema"),
        ("amenity", "theatre"),
        ("amenity", "nightclub"),
        ("tourism", "museum"),
        ("tourism", "attraction"),
        ("tourism", "zoo"),
    ],
    "public_services": [
        ("amenity", "police"),
        ("amenity", "fire_station"),
        ("amenity", "post_office"),
        ("amenity", "townhall"),
        ("amenity", "courthouse"),
        ("amenity", "community_centre"),
    ],
    "sports": [
        ("leisure", "sports_centre"),
        ("leisure", "fitness_centre"),
        ("leisure", "stadium"),
        ("leisure", "pitch"),
        ("sport", "swimming"),
    ],
    "places_of_worship": [
        ("amenity", "place_of_worship"),
        ("amenity", "cemetery"),
    ],
}

# Unknown categories fall back to this one; an empty selection means "all".
_DEFAULT_CATEGORY = "restaurants"


def _value(value: Any) -> Any:
    """Unwrap a SQLMesh macro argument to its Python value.

    Arguments arrive as sqlglot expressions: literals as ``exp.Literal``,
    negative numbers as ``exp.Neg``, and ``name = value`` keywords as
    ``exp.EQ``. Anything else is rendered back to SQL text, which surfaces in
    the resulting URL as a clearly-unsubstituted ``@VAR(...)``.
    """
    if isinstance(value, exp.EQ):
        value = value.expression
    if isinstance(value, exp.Neg):
        return -float(_value(value.this))
    if isinstance(value, exp.Null):
        return None
    if isinstance(value, exp.Literal):
        return value.this
    if isinstance(value, exp.Expr):
        return value.sql(dialect="duckdb")
    return value


def _sql_text(value: Any) -> str:
    """Render a macro argument as the SQL text it should appear as."""
    if isinstance(value, exp.Expr):
        return value.sql(dialect="duckdb")
    return str(value)


def _selected_tags(categories: Any) -> list[tuple[str, str]]:
    """Return the tag filters for a comma-separated category selection.

    An empty selection means every category; a selection naming no known
    category falls back to :data:`_DEFAULT_CATEGORY`.
    """
    names = [name.strip() for name in str(categories or "").split(",") if name.strip()]
    if not names:
        return [tag for tags in POI_CATEGORIES.values() for tag in tags]
    selected = [tag for name in names for tag in POI_CATEGORIES.get(name, [])]
    return selected or list(POI_CATEGORIES[_DEFAULT_CATEGORY])


def _overpass_query(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    tags: list[tuple[str, str]],
) -> str:
    """Return the Overpass QL query for a bbox and tag list.

    Overpass reads the bbox as ``(south, west, north, east)``.
    """
    bbox = f"{min_lat},{min_lng},{max_lat},{max_lng}"
    by_key: dict[str, list[str]] = {}
    for key, value in tags:
        by_key.setdefault(key, []).append(value)
    clauses = "\n".join(
        f'  {element}["{key}"~"^({"|".join(re.escape(v) for v in values)})$"]({bbox});'
        for key, values in by_key.items()
        for element in ("node", "way")
    )
    return f"\n[out:json][timeout:60];\n(\n{clauses}\n);\nout center;\n"


@macro()
def overpass_url(
    evaluator,
    min_lng: Any,
    min_lat: Any,
    max_lng: Any,
    max_lat: Any,
) -> str:
    """Return the Overpass API URL for a bounding box and the selected categories.

    The category selection comes from the ``poi_categories`` variable (a
    comma-separated list; empty means every category) rather than from an
    argument: SQLMesh binds ``name = value`` macro arguments positionally, so a
    fifth argument would have to be positional and unreadable anyway.

    The URL is a complete GET request — DuckDB's ``read_json_auto`` can only
    read a literal URL, and httpfs issues GET — so the query is percent-encoded
    into the ``data`` parameter. Returns SQL text for a string literal.
    """
    query = _overpass_query(
        min_lng=float(_value(min_lng)),
        min_lat=float(_value(min_lat)),
        max_lng=float(_value(max_lng)),
        max_lat=float(_value(max_lat)),
        tags=_selected_tags(_value(evaluator.var("poi_categories", ""))),
    )
    return repr(f"{OVERPASS_URL}?data={quote(query, safe='')}")


@macro()
def poi_subcategory_case(evaluator, tags: Any) -> str:
    """Return the CASE mapping a JSON tags object to its ``key=value`` subcategory.

    Tags are tested in taxonomy order, so an element carrying several POI tags
    lands in the first category that claims one of them — the rule the POI
    import has always used.
    """
    expression = _sql_text(tags)
    conditions = " ".join(
        f"WHEN json_extract_string({expression}, '$.{key}') = '{value}'"
        f" THEN '{key}={value}'"
        for entries in POI_CATEGORIES.values()
        for key, value in entries
    )
    return f"CASE {conditions} ELSE 'unknown' END"


@macro()
def poi_category_case(evaluator, subcategory: Any) -> str:
    """Return the CASE mapping a ``key=value`` subcategory to its category."""
    expression = _sql_text(subcategory)
    conditions = " ".join(
        f"WHEN {expression} IN ({', '.join(repr(f'{k}={v}') for k, v in entries)})"
        f" THEN '{category}'"
        for category, entries in POI_CATEGORIES.items()
    )
    return f"CASE {conditions} ELSE 'unknown' END"
