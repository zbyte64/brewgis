"""Points of Interest fetcher — queries OpenStreetMap Overpass API.

Retrieves POIs (amenities, shops, leisure, tourism, transit) within a
bounding box and returns them as a GeoDataFrame point layer.
"""
from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import shape

logger = logging.getLogger(__name__)

# Overpass API endpoint
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# POI category definitions: category → list of (key, value) tag filters
# Each entry is a tag filter — nodes matching ANY tag in the category are included.
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

# Reverse mapping: tag → category for deduplication
_TAG_TO_CATEGORY: dict[tuple[str, str], str] = {}
for cat, tags in POI_CATEGORIES.items():
    for tag in tags:
        _TAG_TO_CATEGORY[tag] = cat


def _build_overpass_query(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None = None,
) -> str:
    """Build an Overpass QL query for POI nodes and ways in the bounding box.

    Args:
        min_lng: Western bound.
        min_lat: Southern bound.
        max_lng: Eastern bound.
        max_lat: Northern bound.
        categories: List of category names to include. None = all.

    Returns:
        Overpass QL query string.
    """
    bbox = f"{min_lat},{min_lng},{max_lat},{max_lng}"

    # Collect tag filters from selected categories
    tags_to_query: list[tuple[str, str]] = []
    if categories:
        for cat in categories:
            tags_to_query.extend(POI_CATEGORIES.get(cat, []))
    else:
        for cat_tags in POI_CATEGORIES.values():
            tags_to_query.extend(cat_tags)

    if not tags_to_query:
        # Default to restaurants if nothing selected
        tags_to_query = POI_CATEGORIES["restaurants"]

    # Build tag filter clauses
    tag_clauses: list[str] = []
    for key, value in tags_to_query:
        tag_clauses.append(f'  (node["{key}"="{value}"]({bbox}); way["{key}"="{value}"]({bbox}); )')

    tag_block = "\n".join(tag_clauses)

    query = f"""
[out:json][timeout:60];
(
{tag_block}
);
out center;
"""
    return query


def _execute_overpass_query(query: str) -> list[dict[str, Any]]:
    """Execute an Overpass QL query and return parsed elements.

    Args:
        query: Overpass QL query string.

    Returns:
        List of element dicts (each with id, type, tags, center, or lat/lng).

    Raises:
        RuntimeError: On HTTP or parse errors.
    """
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=90,
        headers={"User-Agent": "BrewGIS/1.0"},
    )

    if response.status_code != 200:
        msg = f"Overpass API returned HTTP {response.status_code}: {response.text}"
        raise RuntimeError(msg)

    try:
        result: dict[str, Any] = response.json()
    except ValueError as e:
        msg = f"Overpass API returned non-JSON: {e}"
        raise RuntimeError(msg) from e

    if "elements" not in result:
        msg = "Overpass API response missing 'elements' key."
        raise RuntimeError(msg)

    return result["elements"]


def _categorize_element(tags: dict[str, str]) -> tuple[str, str]:
    """Determine the category and subcategory of a POI element from its tags.

    Args:
        tags: OSM element tags dict.

    Returns:
        Tuple of (category, subcategory). Falls back to ("unknown", "unknown").
    """
    for (key, value), cat in _TAG_TO_CATEGORY.items():
        if tags.get(key) == value:
            subcategory = f"{key}={value}"
            return cat, subcategory
    return "unknown", "unknown"


def fetch_pois(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None = None,
) -> gpd.GeoDataFrame:
    """Fetch POIs from OpenStreetMap Overpass API within a bounding box.

    Args:
        min_lng: Western bound.
        min_lat: Southern bound.
        max_lng: Eastern bound.
        max_lat: Northern bound.
        categories: List of POI category names to include. None = all.

    Returns:
        GeoDataFrame with columns: osm_id, name, category, subcategory,
        amenity, shop, leisure, tourism, geometry (Point).

    Raises:
        RuntimeError: On API errors or empty results.
    """
    query = _build_overpass_query(min_lng, min_lat, max_lng, max_lat, categories)
    elements = _execute_overpass_query(query)

    if not elements:
        msg = "Overpass API returned no elements in the bounding box."
        raise RuntimeError(msg)

    records: list[dict[str, Any]] = []
    for elem in elements:
        elem_type = elem.get("type", "")
        osm_id = elem.get("id", 0)
        tags: dict[str, str] = elem.get("tags", {})

        name = tags.get("name", "")

        category, subcategory = _categorize_element(tags)

        # Get geometry
        if elem_type == "node":
            geom = {
                "type": "Point",
                "coordinates": [elem.get("lng", 0), elem.get("lat", 0)],
            }
        else:
            # Way or relation — use center point
            center = elem.get("center", {})
            geom = {
                "type": "Point",
                "coordinates": [center.get("lng", 0), center.get("lat", 0)],
            }

        record = {
            "osm_id": osm_id,
            "osm_type": elem_type,
            "name": name,
            "category": category,
            "subcategory": subcategory,
            "amenity": tags.get("amenity", ""),
            "shop": tags.get("shop", ""),
            "leisure": tags.get("leisure", ""),
            "tourism": tags.get("tourism", ""),
            "geometry": shape(geom),
        }
        records.append(record)

    if not records:
        msg = "No POI records parsed from Overpass response."
        raise RuntimeError(msg)

    df = gpd.GeoDataFrame(records, geometry="geometry")
    df.crs = "EPSG:4326"
    return df
