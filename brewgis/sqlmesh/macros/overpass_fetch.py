"""Overpass API query construction for the DuckDB POI fetch models.

Single source of truth for the OpenStreetMap tag taxonomy behind
``duckdb.osm.poi``: the URL that model fetches, the category/subcategory CASE
expressions it classifies rows with, and — through :data:`POI_CATEGORIES` — the
category list Django's POI import form offers.

It also holds the food-outlet tag set behind ``duckdb.@region.food_pois``, the
fetch the food-access analysis counts healthy and unhealthy outlets from. That
set is deliberately separate from :data:`POI_CATEGORIES`: the import taxonomy
classifies an element into one *category* for the map's POI layers, while food
access needs the healthy/unhealthy split the mRFEI is defined over, and the
import's ``shopping`` category does not carry every tag that split names.

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
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import quote

from sqlglot import exp
from sqlmesh import macro

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# Overpass endpoint. These fetches go through DuckDB's httpfs, which is picky
# about how a mirror answers — it asks for byte ranges, so a mirror that ignores
# them or sends a length httpfs does not expect fails the read with "Server sent
# back more data than expected" or a bare "HTTP GET error". Measured 2026-09-28
# by reading the model's own default-bbox URL through a DuckDB session set up
# like the gateway's:
#   overpass.kumi.systems    160 s, and then every plan read that day failed
#                            (analysis runs 108, 109, 110) with those two errors
#   overpass.private.coffee  211 s, no error
#   overpass-api.de          87 s, then "more data than expected", every time
#   overpass.osm.jp          74 s, then a TLS "peer certificate ... is not OK"
# (The same URL through urllib answers in 24 s — httpfs requests it several times
# over, which is why a mirror's range handling decides this.) Kumi was the host
# before this move, picked 2026-09-22 because the main instance stalled httpfs'
# GET (30 s, then HTTP 504) while urllib fetched the identical URL in about a
# second. Swapping this constant is the whole of a mirror move.
OVERPASS_URL = "https://overpass.private.coffee/api/interpreter"

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


# ── Food access (mRFEI) ───────────────────────────────────────────────────────
#
# The tag set the food-access analysis is defined over, and the class each tag
# lands in. The mRFEI counts outlets a parcel can reach, split into what the
# metric calls healthy (a place to buy groceries) and unhealthy (convenience
# stores and fast food).
#
# Classes are tested in this order, so an element carrying several of these tags
# lands in exactly one class: a place that is also a fast-food outlet is not
# counted as healthy. The order matters for the count, which is why it is stated
# here rather than left to a CASE's fall-through.
FOOD_ACCESS_CLASSES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("unhealthy", (("amenity", "fast_food"), ("shop", "convenience"))),
    (
        "healthy",
        (
            ("shop", "supermarket"),
            ("shop", "grocery"),
            ("shop", "grocer"),
            ("shop", "farmers_market"),
        ),
    ),
)

# Degrees the food fetch expands the region bounding box by before querying
# Overpass. The mRFEI counts outlets within 1 km of a parcel, so the fetch has to
# reach past the region window the other region models are cut to: the Fresno
# demo's parcels run ~1.8 km south of its Overture bbox, whose edge parcels
# would otherwise see no outlets at all.
FOOD_ACCESS_BBOX_MARGIN = 0.02


def _food_access_tags() -> list[tuple[str, str]]:
    """Every ``(key, value)`` pair the food-access fetch asks Overpass for."""
    return [tag for _label, entries in FOOD_ACCESS_CLASSES for tag in entries]


@macro()
def food_access_url(
    evaluator: MacroEvaluator, min_lng: Any, min_lat: Any, max_lng: Any, max_lat: Any
) -> str:
    """Return the Overpass URL for the food-outlet tag set over *bbox* + margin.

    Same shape as :func:`overpass_url`, but the tags are the food set rather than
    the ``poi_categories`` variable's selection: the food fetch is not an import
    the user configures, and its rows are classified by the mRFEI's own split.

    The expanded bounding box is rounded to six decimals — the blueprint bbox is
    a ``Decimal``, and the margin arithmetic on it would otherwise leave a
    binary-float tail (``36.940000000000005``) in the URL text.
    """
    query = _overpass_query(
        min_lng=round(float(_value(min_lng)) - FOOD_ACCESS_BBOX_MARGIN, 6),
        min_lat=round(float(_value(min_lat)) - FOOD_ACCESS_BBOX_MARGIN, 6),
        max_lng=round(float(_value(max_lng)) + FOOD_ACCESS_BBOX_MARGIN, 6),
        max_lat=round(float(_value(max_lat)) + FOOD_ACCESS_BBOX_MARGIN, 6),
        tags=_food_access_tags(),
    )
    return repr(f"{OVERPASS_URL}?data={quote(query, safe='')}")


@macro()
def food_access_class_case(evaluator: MacroEvaluator, tags: Any) -> str:
    """Return the CASE mapping a JSON tags object to its food-access class.

    Emits ``'healthy'``, ``'unhealthy'`` or ``'other'``; the mRFEI reads the
    first two, and ``'other'`` cannot occur for rows this fetch asked for (see
    :data:`FOOD_ACCESS_CLASSES`).
    """
    expression = _sql_text(tags)
    conditions = " ".join(
        f"WHEN json_extract_string({expression}, '$.{key}') = '{value}' THEN '{label}'"
        for label, entries in FOOD_ACCESS_CLASSES
        for key, value in entries
    )
    return f"CASE {conditions} ELSE 'other' END"
