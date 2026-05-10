"""Base Canvas Data Source Adapters — pluggable sources for ETL pipeline steps.

Each adapter implements a ``Source`` protocol for a specific domain
(demographics, employment, land use, etc.).  The ``BaseCanvasETL`` service
consults adapters in priority order, falling back to fillna defaults when
no real data is available.

Adapters defined here:
    * ``NullDemographicSource`` — returns empty; triggers fillna(0.0)
    * ``NullEmploymentSource``  — returns empty; triggers fillna(0.0)
    * ``NullLandUseSource``     — returns default "urban"
    * ``NullIntersectionDensitySource`` — returns default 12.5
    * ``NullIrrigationSource``  — uses hardcoded fractions
"""

from __future__ import annotations

import logging
from typing import Protocol

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)


# ── Protocols ──────────────────────────────────────────────────────────


class DemographicSource(Protocol):
    """Protocol for demographic data sources (Census ACS)."""

    @property
    def available(self) -> bool:
        """Whether this source has data to contribute."""
        ...

    def fetch_block_group_data(
        self,
        state_fips: str,
        county_fips: str,
    ) -> gpd.GeoDataFrame:
        """Return block-group-level demographic attributes.

        Returns a GeoDataFrame with:
            * ``geometry`` — polygon geometry (EPSG:4326)
            * ``geoid`` — unique block-group identifier
            * Canvas demographic columns (pop, hh, du, du_detsf, ...)
        """
        ...


class EmploymentSource(Protocol):
    """Protocol for employment data sources (LEHD/LODES)."""

    @property
    def available(self) -> bool:
        ...

    def fetch_block_data(
        self,
        state_fips: str,
        county_fips: str,
    ) -> gpd.GeoDataFrame:
        """Return block-level employment attributes.

        Returns a GeoDataFrame with:
            * ``geometry`` — polygon geometry (EPSG:4326)
            * ``geoid`` — unique block identifier
            * Canvas employment columns (emp, emp_ret, emp_off, ...)
        """
        ...


class LandUseSource(Protocol):
    """Protocol for land-use / land-cover sources."""

    @property
    def available(self) -> bool:
        ...

    def classify_parcels(
        self,
        parcels: gpd.GeoDataFrame,
    ) -> gpd.GeoDataFrame:
        """Return parcels with ``land_development_category`` populated."""
        ...


class IntersectionDensitySource(Protocol):
    """Protocol for intersection-density computation sources."""

    @property
    def available(self) -> bool:
        ...

    def compute_density(
        self,
        parcels: gpd.GeoDataFrame,
    ) -> gpd.GeoDataFrame:
        """Return parcels with ``intersection_density`` populated."""
        ...


class IrrigationSource(Protocol):
    """Protocol for irrigation estimation sources."""

    @property
    def available(self) -> bool:
        ...

    def estimate_irrigation(
        self,
        parcels: gpd.GeoDataFrame,
    ) -> gpd.GeoDataFrame:
        """Return parcels with irrigation columns populated."""
        ...


# ── Assessor Use Code Classification ──────────────────────────────────
# Maps common CA Standard Land Use Coding Manual codes to development_categories

_ASSESSOR_USE_CODE_MAP: dict[str, str] = {
    # Residential
    "10": "urban",      # Single-family residential
    "11": "urban",      # Single-family residential
    "12": "urban",      # Two-family residential
    "13": "urban",      # Three-family residential
    "14": "urban",      # Four-family residential
    "15": "urban",      # Five+ family residential
    "16": "urban",      # Mixed residential/commercial
    "17": "urban",      # Mobile home parks
    "18": "urban",      # Residential hotels
    # Commercial
    "20": "urban",      # General commercial
    "21": "urban",      # Retail
    "22": "urban",      # Office
    "23": "urban",      # Financial services
    "24": "urban",      # Medical
    # Industrial
    "30": "urban",      # General industrial
    "31": "urban",      # Light industrial
    "32": "urban",      # Heavy industrial
    # Agricultural
    "40": "agricultural",  # General agriculture
    "41": "agricultural",  # Crops
    "42": "agricultural",  # Orchards
    "43": "agricultural",  # Vineyards
    "44": "agricultural",  # Livestock
    "45": "agricultural",  # Dairy
    "46": "agricultural",  # Poultry
    # Vacant / Undeveloped
    "50": "undeveloped",  # Vacant residential
    "51": "undeveloped",  # Vacant commercial
    "52": "undeveloped",  # Vacant industrial
    "53": "undeveloped",  # Vacant agricultural
    # Open Space / Recreation
    "60": "undeveloped",  # Parks / Recreation
    "61": "undeveloped",  # Golf courses
    "62": "undeveloped",  # Cemeteries
    "63": "undeveloped",  # Open space
    # Water / Wetlands
    "70": "undeveloped",  # Water
    "71": "undeveloped",  # Wetlands
    # Public / Institutional
    "80": "urban",      # Public services
    "81": "urban",      # Education
    "82": "urban",      # Religious
    "83": "urban",      # Government
    # Other
    "90": "urban",      # Other
}


def classify_by_assessor_code(assessor_use_code: str | None) -> str | None:
    """Classify a parcel's land development category using assessor use code.

    Looks up the first two digits of the assessor code in the mapping.
    Returns None if no match is found.
    """
    if not assessor_use_code or pd.isna(assessor_use_code):
        return None
    code = str(assessor_use_code).strip()
    prefix = code[:2] if len(code) >= 2 else code  # noqa: PLR2004
    return _ASSESSOR_USE_CODE_MAP.get(prefix)


# ── Null / Default Adapters ────────────────────────────────────────────
# These preserve the current fillna(default) behaviour when real data
# sources are not configured or unavailable.


class NullDemographicSource:
    """Default demographic source — returns nothing; ETL fills with 0.0."""

    @property
    def available(self) -> bool:
        return False

    def fetch_block_group_data(
        self,
        _state_fips: str = "",
        _county_fips: str = "",
    ) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame()


class NullEmploymentSource:
    """Default employment source — returns nothing; ETL fills with 0.0."""

    @property
    def available(self) -> bool:
        return False

    def fetch_block_data(
        self,
        _state_fips: str = "",
        _county_fips: str = "",
    ) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame()


class NullLandUseSource:
    """Default land-use source — tries assessor codes, then defaults to ``"urban"``."""

    @property
    def available(self) -> bool:
        return False  # Still marks as "default" source

    def classify_parcels(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Classify using assessor use codes from parcel attributes if available."""
        # Check for assessor code columns
        code_col = None
        for col in ("assessor_use_code", "land_use", "use_code", "lu_code"):
            if col in parcels.columns:
                code_col = col
                break

        if code_col is not None and "land_development_category" in parcels.columns:
            # Apply assessor code classification where not already set
            mask = parcels["land_development_category"].isna()
            parcels.loc[mask, "land_development_category"] = parcels.loc[mask, code_col].apply(
                classify_by_assessor_code
            )

        return parcels

class NullIntersectionDensitySource:
    """Default intersection-density source — returns default 12.5."""

    @property
    def available(self) -> bool:
        return False

    def compute_density(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        return parcels


class NullIrrigationSource:
    """Default irrigation source — uses hardcoded fractions."""

    @property
    def available(self) -> bool:
        return False

    def estimate_irrigation(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        return parcels

# ── Real Data Adapters ────────────────────────────────────────────────


class CensusDemographicSource:
    """Real demographic source -- fetches ACS block-group data with polygon geometry.

    Downloads TIGER/Line shapefiles for polygon geometry and joins ACS
    attribute data from the Census API.
    """

    def __init__(
        self,
        state_fips: str,
        county_fips: str,
        year: int = 2022,
        use_cache: bool = True,
    ) -> None:
        self._state_fips = state_fips
        self._county_fips = county_fips
        self._year = year
        self._use_cache = use_cache
        self._data: gpd.GeoDataFrame | None = None

    @property
    def available(self) -> bool:
        return bool(self._state_fips and self._county_fips)

    def fetch_block_group_data(
        self,
        state_fips: str = "",
        county_fips: str = "",
    ) -> gpd.GeoDataFrame:
        """Return block-group-level demographics with polygon geometry."""
        from brewgis.workspace.services.census_fetcher import (
            fetch_acs_block_group_polygons,
        )

        if self._data is not None:
            return self._data

        sf = state_fips or self._state_fips
        cf = county_fips or self._county_fips

        try:
            gdf = fetch_acs_block_group_polygons(sf, cf, self._year, self._use_cache)
        except Exception as exc:
            logger.warning("Census fetch failed: %s", exc)
            gdf = gpd.GeoDataFrame()

        self._data = gdf
        return gdf


class LEHDEmploymentSource:
    """Real employment source — fetches LODES WAC block data with polygon geometry.

    Downloads LODES WAC CSV from CES FTP server for employment attributes,
    TIGER/Line tabblock shapefiles for polygon geometry, and CBP data
    from the Census API for sub-sector proportional splitting.
    """

    def __init__(
        self,
        state_fips: str,
        county_fips: str,
        use_cache: bool = True,
    ) -> None:
        self._state_fips = state_fips
        self._county_fips = county_fips
        self._use_cache = use_cache
        self._data: gpd.GeoDataFrame | None = None

    @property
    def available(self) -> bool:
        return bool(self._state_fips and self._county_fips)

    def fetch_block_data(
        self,
        state_fips: str = "",
        county_fips: str = "",
    ) -> gpd.GeoDataFrame:
        """Return block-level employment data with polygon geometry."""
        from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_polygons

        if self._data is not None:
            return self._data

        sf = state_fips or self._state_fips
        cf = county_fips or self._county_fips

        try:
            gdf = fetch_lehd_block_polygons(sf, cf, self._use_cache)
        except Exception as exc:
            logger.warning("LEHD fetch failed: %s", exc)
            gdf = gpd.GeoDataFrame()

        self._data = gdf
        return gdf


class NLCDFetcher:
    """Land-use source that uses NLCD land cover data for classification.

    Computes zonal statistics per parcel from NLCD rasters to determine
    land development category, impervious surface fraction, and irrigation
    estimates.
    """

    def __init__(
        self,
        bbox: tuple[float, float, float, float],
        year: int = 2021,
    ) -> None:
        self._bbox = bbox
        self._year = year
        self._parcels_cached: gpd.GeoDataFrame | None = None

    @property
    def available(self) -> bool:
        return True

    def classify_parcels(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Classify parcels using NLCD zonal statistics.

        Computes the bounding box from parcel geometries with a 5 %
        buffer to avoid edge effects during raster subset download.
        """
        from brewgis.workspace.services.nlcd_fetcher import compute_nlcd_zonal_stats

        if self._parcels_cached is not None:
            return self._parcels_cached

        # Compute bbox from parcels with 5 % buffer
        bounds = parcels.total_bounds  # [minx, miny, maxx, maxy]
        west, south, east, north = bounds
        x_pad = (east - west) * 0.05
        y_pad = (north - south) * 0.05
        bbox = (west - x_pad, south - y_pad, east + x_pad, north + y_pad)

        # First pass: try assessor use codes
        code_col = None
        for col in ("assessor_use_code", "land_use", "use_code", "lu_code"):
            if col in parcels.columns:
                code_col = col
                break

        if code_col is not None:
            if "land_development_category" not in parcels.columns:
                parcels["land_development_category"] = None
            mask = parcels["land_development_category"].isna()
            parcels.loc[mask, "land_development_category"] = parcels.loc[mask, code_col].apply(
                classify_by_assessor_code
            )

        result = compute_nlcd_zonal_stats(parcels, bbox, self._year)
        self._parcels_cached = result
        return result

    def estimate_irrigation(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Estimate irrigation from NLCD impervious fraction.

        Pervious area = total area * (1 - impervious_fraction).
        Irrigated area = pervious area * irrigated_fraction
        (default irrigated_fraction = 0.3 for residential, 0.15 for commercial).
        """
        if self._parcels_cached is None:
            parcels = self.classify_parcels(parcels)

        imp_frac = parcels.get("impervious_fraction", 0.0)
        pervious = 1.0 - imp_frac

        if "area_parcel_res" in parcels.columns:
            parcels["residential_irrigated_area"] = parcels[
                "residential_irrigated_area"
            ].fillna(parcels["area_parcel_res"] * pervious * 0.3)
        else:
            parcels["residential_irrigated_area"] = parcels.get(
                "residential_irrigated_area", parcels["area_gross"]
            ).fillna(parcels["area_gross"] * 0.1)

        if "area_parcel_emp" in parcels.columns:
            parcels["commercial_irrigated_area"] = parcels[
                "commercial_irrigated_area"
            ].fillna(parcels["area_parcel_emp"] * pervious * 0.15)
        else:
            parcels["commercial_irrigated_area"] = parcels.get(
                "commercial_irrigated_area", parcels["area_gross"]
            ).fillna(parcels["area_gross"] * 0.05)

        return parcels


class OSMIntersectionDensitySource:
    """Intersection density source that uses OSM road network data.

    Computes density at jurisdiction level for efficiency and consistency.
    Falls back to per-parcel computation when no jurisdiction column exists.
    """

    DEFAULT_DENSITY = 12.5  # intersections/km^2

    def __init__(
        self,
        bbox: tuple[float, float, float, float],
    ) -> None:
        self._bbox = bbox
        self._cached_density: gpd.GeoSeries | None = None

    @property
    def available(self) -> bool:
        try:
            import osmnx  # noqa: F401
            return True
        except ImportError:
            return False

    def _compute_jurisdiction_density(
        self, jurisdiction_parcels: gpd.GeoDataFrame
    ) -> float | None:
        """Compute intersection density for a jurisdiction's geometry union."""
        try:
            import osmnx as ox  # noqa: PLC0415

            # Union all parcel geometries in the jurisdiction
            # Buffer slightly to avoid edge disconnects
            boundary = jurisdiction_parcels.union_all().buffer(0.001)

            # Get the road network within the boundary
            graph = ox.graph_from_polygon(
                boundary,
                network_type="drive",
                simplify=True,
                retain_all=True,
            )

            # Count intersections (nodes with street_count >= 3)
            nodes, _ = ox.graph_to_gdfs(graph)
            intersections = nodes[nodes["street_count"] >= 3]

            # Compute area in km²
            area_sq_km = (
                jurisdiction_parcels.to_crs("EPSG:6933").area.sum() / 1e6
            )

            if area_sq_km > 0:
                return len(intersections) / area_sq_km
            return None
        except Exception as exc:
            logger.warning(
                "OSM intersection density computation failed: %s", exc
            )
            return None

    def compute_density(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Compute intersection density at jurisdiction level.

        If parcels have a 'jurisdiction' column, groups by it and computes
        one density per jurisdiction. Otherwise computes per-parcel.
        Falls back to DEFAULT_DENSITY on failure.
        """
        if not self.available:
            logger.warning(
                "osmnx not available; using default intersection density %.1f",
                self.DEFAULT_DENSITY,
            )
            if "intersection_density" in parcels.columns:
                parcels["intersection_density"] = parcels[
                    "intersection_density"
                ].fillna(self.DEFAULT_DENSITY)
            return parcels

        if "jurisdiction" not in parcels.columns:
            return self._compute_per_parcel(parcels)

        jurisdictions = parcels["jurisdiction"].unique()
        jurisdiction_density: dict[str, float] = {}

        for juris in jurisdictions:
            mask = parcels["jurisdiction"] == juris
            juris_parcels = parcels[mask]
            density = self._compute_jurisdiction_density(juris_parcels)
            if density is not None:
                jurisdiction_density[juris] = density

        parcels = parcels.copy()
        parcels["intersection_density"] = parcels["jurisdiction"].map(
            jurisdiction_density
        ).fillna(self.DEFAULT_DENSITY).round(2)

        return parcels

    def _compute_per_parcel(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Fall back to per-parcel intersection density computation."""
        try:
            import osmnx as ox  # noqa: PLC0415

            bbox_north = self._bbox[3]
            bbox_south = self._bbox[1]
            bbox_east = self._bbox[2]
            bbox_west = self._bbox[0]

            logger.info("Downloading OSM road network for bounding box ...")
            graph = ox.graph_from_bbox(
                bbox_north, bbox_south, bbox_east, bbox_west,
                network_type="drive",
                simplify=True,
            )

            # Get intersection nodes
            intersections = ox.graph_to_gdfs(graph, nodes=True, edges=False)
            if intersections.empty:
                logger.warning("No intersections found in OSM data; using defaults")
                if "intersection_density" in parcels.columns:
                    parcels["intersection_density"] = parcels[
                        "intersection_density"
                    ].fillna(self.DEFAULT_DENSITY)
                return parcels

            # Count intersections per parcel
            import pandas as pd  # noqa: PLC0415

            intersection_counts: list[int] = []
            for _, parcel in parcels.iterrows():
                geom = parcel.geometry
                if geom is None:
                    intersection_counts.append(0)
                    continue
                count = intersections.sindex.query(geom, predicate="intersects").size
                intersection_counts.append(count)

            parcels = parcels.copy()
            # Area in km^2 (area_gross is in acres)
            area_km2 = parcels["area_gross"].fillna(0.01) * 0.00404686
            densities = pd.Series(intersection_counts, index=parcels.index) / area_km2
            parcels["intersection_density"] = parcels.get(
                "intersection_density", pd.Series(index=parcels.index)
            ).fillna(densities.round(2))

        except Exception as exc:
            logger.warning(
                "OSM intersection density failed: %s; using default %.1f",
                exc,
                self.DEFAULT_DENSITY,
            )
            if "intersection_density" in parcels.columns:
                parcels["intersection_density"] = parcels[
                    "intersection_density"
                ].fillna(self.DEFAULT_DENSITY)

        return parcels
