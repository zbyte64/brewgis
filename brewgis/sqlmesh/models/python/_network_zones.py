"""Network distance zones — pure math, importable without a database.

The road-network distance option routes between 2 km grid zones rather than
between parcels: a parcel-to-parcel matrix is ~4.5e10 pairs for a 213k-parcel
region, while a region's zones number in the low thousands. network_zone_distance
writes one row per connected zone pair, keyed by the zones' grid cell indices,
and trip_distribution maps every parcel onto the same grid with zone_indices
and looks its pairs up in the dense matrix zone_distance_matrix builds.

The cell of a point is floor(coordinate * metres_per_unit / ZONE_CELL_METRES)
on each axis, taken in the region's projected local_srid; the SQL in
network_zone_distance computes exactly the same expression, so both sides agree
on every parcel's zone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Zone grid cell edge (metres). Fine enough that a zone is a neighbourhood, coarse
# enough that the zone matrix stays small.
ZONE_CELL_METRES = 2000.0
# Upper bound on the zones one scenario may route between: pgRouting's cost is
# one Dijkstra per origin vertex, and the matrix is ZONES x ZONES.
MAX_ZONES = 4000

# Cell index for a parcel with no coordinates (no geometry).
_NAN_CELL = np.iinfo(np.int64).min


def zone_indices(
    x_local: np.ndarray, y_local: np.ndarray, metres_per_unit: float
) -> tuple[np.ndarray, np.ndarray]:
    """Grid cell indices (ix, iy) of projected coordinates.

    Args:
        x_local: x coordinates in local_srid units.
        y_local: y coordinates in local_srid units.
        metres_per_unit: metres per local_srid linear unit.

    Returns:
        Two int64 arrays; a NaN coordinate maps to the sentinel cell
        ``np.iinfo(np.int64).min``.
    """
    return (
        _cell(np.asarray(x_local, dtype=float), metres_per_unit),
        _cell(np.asarray(y_local, dtype=float), metres_per_unit),
    )


def _cell(coordinates: np.ndarray, metres_per_unit: float) -> np.ndarray:
    cells = np.full(coordinates.shape, _NAN_CELL, dtype=np.int64)
    finite = ~np.isnan(coordinates)
    cells[finite] = np.floor(
        coordinates[finite] * metres_per_unit / ZONE_CELL_METRES
    ).astype(np.int64)
    return cells


def zone_distance_matrix(  # noqa: PLR0913
    parcel_ix: np.ndarray,
    parcel_iy: np.ndarray,
    origin_ix: np.ndarray,
    origin_iy: np.ndarray,
    dest_ix: np.ndarray,
    dest_iy: np.ndarray,
    distance_km: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Dense zone codes for the parcels and the zone-to-zone distance matrix.

    Args:
        parcel_ix, parcel_iy: each parcel's grid cell (see zone_indices).
        origin_ix, origin_iy, dest_ix, dest_iy: the cells of each zone pair row.
        distance_km: network distance of each zone pair row (km).

    Returns:
        (zones, matrix): ``zones`` is an int64 dense code per parcel, one code
        per distinct (ix, iy) among the parcels; ``matrix`` is a Z x Z float64
        matrix, NaN where no pair row names both zones. Pair rows naming a zone
        no parcel falls in are ignored. The sentinel (no-coordinates) cell gets
        its own code, and its row and column stay NaN.
    """
    parcel_cells = np.column_stack(
        (np.asarray(parcel_ix, dtype=np.int64), np.asarray(parcel_iy, dtype=np.int64))
    )
    cells, zones = np.unique(parcel_cells, axis=0, return_inverse=True)
    zones = zones.reshape(-1).astype(np.int64)
    n_zones = len(cells)
    matrix = np.full((n_zones, n_zones), np.nan, dtype=np.float64)

    # A region's pair rows run to millions, so the cell -> code lookup is a
    # vectorized index lookup (-1 = a cell no parcel falls in).
    zone_index = pd.MultiIndex.from_arrays((cells[:, 0], cells[:, 1]))
    origin = zone_index.get_indexer(
        pd.MultiIndex.from_arrays(
            (
                np.asarray(origin_ix, dtype=np.int64),
                np.asarray(origin_iy, dtype=np.int64),
            )
        )
    )
    dest = zone_index.get_indexer(
        pd.MultiIndex.from_arrays(
            (np.asarray(dest_ix, dtype=np.int64), np.asarray(dest_iy, dtype=np.int64))
        )
    )
    keep = (origin >= 0) & (dest >= 0)
    # The sentinel cell is not a place: nothing is routed to or from it.
    sentinel = np.nonzero((cells[:, 0] == _NAN_CELL) & (cells[:, 1] == _NAN_CELL))[0]
    if len(sentinel) > 0:
        keep &= (origin != sentinel[0]) & (dest != sentinel[0])
    matrix[origin[keep], dest[keep]] = np.asarray(distance_km, dtype=np.float64)[keep]
    return zones, matrix
