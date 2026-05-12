from __future__ import annotations

# ruff: noqa: PLR2004, TC002
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np

from brewgis.workspace.built_forms.models import BuildingType


@dataclass
class BuiltFormAssignment:
    """Result of a single built form assignment."""

    built_form_key: int | str
    intersection_density: float


class BuiltFormClassifier:
    """Assign built_form_key and intersection_density to parcels.

    Supports two strategies:
    - **heuristic** — area-based thresholds with pseudorandom diversification.
    - **data_driven** — infer the closest BuildingType by comparing parcel
      density (du_per_acre) against stored BuildingType profiles. Falls back
      to heuristic when insufficient data or building types are available.
    """

    def __init__(
        self,
        *,
        building_types: list[BuildingType] | None = None,
        strategy: str = "heuristic",
    ) -> None:
        """Initialize the classifier.

        Parameters
        ----------
        building_types :
            Explicit list of BuildingType records to use for data-driven
            assignment. If ``None`` (the default), all records are loaded
            from the database.
        strategy :
            ``"heuristic"`` (default) or ``"data_driven"``.
        """
        self._building_types = (
            building_types
            if building_types is not None
            else list(BuildingType.objects.all())
        )
        self._strategy = strategy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Assign ``built_form_key`` and ``intersection_density`` to parcels.

        Parameters
        ----------
        gdf :
            Parcel geometry. Should contain an ``area_gross`` column in
            acres. If absent, it is computed on the fly.

        Returns
        -------
        gpd.GeoDataFrame
            Input frame with added ``built_form_key`` (int) and
            ``intersection_density`` (float) columns.
        """
        if self._strategy == "data_driven":
            return self._assign_data_driven(gdf)
        return self._assign_heuristic(gdf)

    # ------------------------------------------------------------------
    # Heuristic strategy
    # ------------------------------------------------------------------

    def _assign_heuristic(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Area-based heuristic assignment.

        Maps BuildingType PKs based on parcel area thresholds:

        ====== ============================
        Key    Building type
        ====== ============================
        1      SFR Large Lot
        2      SFR Standard
        3      Townhouse
        4      Duplex
        5      Triplex / Fourplex
        6      Courtyard Apartment
        7      Stacked Flats
        8      Mid-Rise Apartment
        9      High-Rise Apartment
        10     Neighborhood Retail
        11     General Commercial
        12     Office Low Rise
        13     Office Mid / High Rise
        14     Light Industrial
        15     Civic / Institutional
        ====== ============================
        """
        if "area_gross" not in gdf.columns:
            gdf_eq = gdf.to_crs("EPSG:6933")
            gdf["area_gross"] = gdf_eq.geometry.area / 4046.86

        area = gdf["area_gross"].fillna(0)
        parcel_ids = gdf.index.values if hasattr(gdf, "index") else np.arange(len(gdf))

        bf_key = np.where(
            area <= 0,
            2,  # default SFR Standard
            np.where(
                area > 3.0,
                np.where(parcel_ids % 5 < 3, 14, 15),  # Industrial or Civic
                np.where(
                    area > 1.5,
                    np.where(
                        parcel_ids % 4 == 0,
                        11,
                        np.where(
                            parcel_ids % 4 == 1,
                            12,
                            np.where(parcel_ids % 4 == 2, 10, 1),
                        ),
                    ),
                    np.where(
                        area > 0.4,
                        np.where(parcel_ids % 5 == 0, 10, 2),
                        np.where(
                            area > 0.15,
                            np.where(
                                parcel_ids % 7 == 0,
                                3,
                                np.where(parcel_ids % 7 == 1, 4, 2),
                            ),
                            np.where(
                                area > 0.08,
                                np.where(
                                    parcel_ids % 3 == 0,
                                    5,
                                    np.where(parcel_ids % 3 == 1, 6, 7),
                                ),
                                np.where(
                                    parcel_ids % 5 == 0,
                                    8,
                                    np.where(parcel_ids % 5 == 1, 9, 7),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        gdf["built_form_key"] = bf_key.astype(int)

        # Intersection density inversely related to parcel area.
        gdf["intersection_density"] = np.where(
            area > 0,
            np.clip(10.0 / np.sqrt(area), 0.5, 25.0),
            0.5,
        ).round(2)

        return gdf

    # ------------------------------------------------------------------
    # Data-driven strategy
    # ------------------------------------------------------------------

    def _assign_data_driven(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Data-driven assignment using BuildingType profiles.

        Uses ``du_per_acre`` and ``emp_per_acre`` from BuildingType records
        to infer the most likely built form for each parcel based on its
        density profile.  Falls back to heuristic when data is insufficient.
        """
        if not self._building_types:
            return self._assign_heuristic(gdf)

        # Build a lightweight lookup from BuildingType records.
        bt_map: dict[int, dict[str, Any]] = {}
        for bt in self._building_types:
            bt_map[bt.id] = {
                "du_per_acre": bt.du_per_acre or 0,
                "emp_per_acre": bt.emp_per_acre or 0,
            }

        if "area_gross" not in gdf.columns:
            gdf_eq = gdf.to_crs("EPSG:6933")
            gdf["area_gross"] = gdf_eq.geometry.area / 4046.86

        area = gdf["area_gross"].fillna(0).clip(lower=0.01)

        # Attempt density matching. For parcels with pop/hh/du data,
        # compute implied density and find the closest BuildingType.
        # Otherwise fall back to heuristic.
        has_density_data = "du" in gdf.columns or "hh" in gdf.columns
        if not has_density_data:
            return self._assign_heuristic(gdf)

        implied_du_per_acre = gdf.get("du", gdf.get("hh", 0)).fillna(0) / area

        # Find the closest BuildingType by du_per_acre.
        bt_ids = list(bt_map.keys())
        bt_densities = np.array(
            [bt_map[i]["du_per_acre"] for i in bt_ids],
            dtype=float,
        )

        parcel_density = implied_du_per_acre.values.reshape(-1, 1)
        if len(bt_densities) > 0:
            diffs = np.abs(parcel_density - bt_densities.reshape(1, -1))
            closest = bt_ids[np.argmin(diffs, axis=1)]
            gdf["built_form_key"] = closest
        else:
            return self._assign_heuristic(gdf)

        return gdf
