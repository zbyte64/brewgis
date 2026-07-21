"""Points of Interest fetcher — queries OpenStreetMap Overpass API.

Retrieves POIs (amenities, shops, leisure, tourism, transit) within a
bounding box and writes to GeoParquet for DuckDB-ingestion.
Also returns a categorized GeoDataFrame for direct use by callers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Point

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
        tag_clauses.append(f'  node["{key}"="{value}"]({bbox});')
        tag_clauses.append(f'  way["{key}"="{value}"]({bbox});')

    tag_block = "\n".join(tag_clauses)

    return f"""
[out:json][timeout:60];
(
{tag_block}
);
out center;
"""


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
    """Fetch POIs from Overpass API and return a categorized GeoDataFrame.

    Writes the raw Overpass response to a GeoParquet file at
    ``/app/planning/poi/poi_raw.parquet`` so the DuckDB staging VIEW
    (``duckdb.staging.poi_raw``) can read it.

    Args:
        min_lng: Western bound.
        min_lat: Southern bound.
        max_lng: Eastern bound.
        max_lat: Northern bound.
        categories: List of category names to include. None = all.

    Returns:
        GeoDataFrame with categorized POI points (EPSG:4326).
    """
    query = _build_overpass_query(min_lng, min_lat, max_lng, max_lat, categories)

    logger.info("Fetching POIs from Overpass API...")
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    elements = data.get("elements", [])

    # Write raw elements to GeoParquet for DuckDB staging
    parquet_dir = Path("/app/planning/poi")
    parquet_dir.mkdir(parents=True, exist_ok=True)
    raw_records: list[dict[str, Any]] = []
    for elem in elements:
        raw_records.append(
            {
                "id": elem.get("id"),
                "type": elem.get("type"),
                "lat": elem.get("lat"),
                "lng": elem.get("lon"),
                "tags": json.dumps(elem.get("tags", {}) or {}),
                "center": json.dumps(elem.get("center", {}) or {}),
            }
        )
    if raw_records:
        raw_gdf = gpd.GeoDataFrame(
            raw_records,
            geometry=gpd.points_from_xy(
                [r.get("lng", 0) or 0 for r in raw_records],
                [r.get("lat", 0) or 0 for r in raw_records],
            ),
            crs="EPSG:4326",
        )
        raw_gdf.to_parquet(parquet_dir / "poi_raw.parquet", index=False)
        logger.info(
            "Wrote %d raw POI elements to %s",
            len(raw_gdf),
            parquet_dir / "poi_raw.parquet",
        )

    # Process into categorized records
    records: list[dict[str, Any]] = []
    for elem in elements:
        elem_type = elem.get("type", "") or ""
        osm_id = elem.get("id", 0) or 0
        tags_raw = elem.get("tags", {}) or {}
        tags: dict[str, str] = tags_raw if isinstance(tags_raw, dict) else {}
        name = tags.get("name", "")
        category, subcategory = _categorize_element(tags)
        if categories is not None and category not in categories:
            continue

        if elem_type == "node":
            lng = elem.get("lon", 0) or 0
            lat = elem.get("lat", 0) or 0
        else:
            center_raw = elem.get("center", {}) or {}
            center = center_raw if isinstance(center_raw, dict) else {}
            lng = center.get("lon", 0) or 0
            lat = center.get("lat", 0) or 0

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
            "geometry": Point(lng, lat),
        }
        records.append(record)

    if not records:
        logger.warning("No POI records matched the requested categories.")
        return gpd.GeoDataFrame([], geometry="geometry", crs="EPSG:4326")

    df = gpd.GeoDataFrame(records, geometry="geometry")
    df.crs = "EPSG:4326"
    logger.info("Returning %d categorized POIs", len(df))
    return df
