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
    """Protocol for employment data sources (LEHD WAC)."""

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
    """Default land-use source — all parcels classified as ``"urban"``."""

    @property
    def available(self) -> bool:
        return False

    def classify_parcels(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
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
        from brewgis.workspace.services.census_fetcher import fetch_acs_block_group_polygons  # noqa: PLC0415

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
    """Real employment source — fetches LEHD WAC block data with polygon geometry.

    Downloads TIGER/Line tabblock shapefiles for polygon geometry and joins
    LEHD WAC attribute data from the Census API.
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
        from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_polygons  # noqa: PLC0415

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
        """Classify parcels using NLCD zonal statistics."""
        from brewgis.workspace.services.nlcd_fetcher import compute_nlcd_zonal_stats  # noqa: PLC0415

        if self._parcels_cached is not None:
            return self._parcels_cached

        result = compute_nlcd_zonal_stats(parcels, self._bbox, self._year)
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

    Extracts the road network for the bounding box using osmnx, counts
    intersections per parcel, and normalizes by parcel area.
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
        return True

    def compute_density(self, parcels: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Compute intersection density from OSM road network.

        Falls back to default density if osmnx is not available.
        """
        try:
            import osmnx as ox  # noqa: PLC0415
        except ImportError:
            logger.warning(
                "osmnx not available; using default intersection density %.1f",
                self.DEFAULT_DENSITY,
            )
            if "intersection_density" in parcels.columns:
                parcels["intersection_density"] = parcels[
                    "intersection_density"
                ].fillna(self.DEFAULT_DENSITY)
            return parcels

        try:
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
            from shapely import wkt  # noqa: PLC0415
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
