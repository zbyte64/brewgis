"""Trip Distribution (T2) — parcel-to-parcel gravity model, blueprinted Python model.

One instance of this model per analyzed scenario, materialized in
``brewgis.ascn<scenario_pk>`` by the same blueprint mechanism the SQL analysis
models use (see ``sqlmesh/macros/analysis_blueprints.py``): ``_PROFILES`` is
resolved while SQLMesh imports this module, so the model's name, its
dependencies and its published result view come from the scenario rows that
exist at load time.

Distribution is a gravity model over parcel centroids::

    T_ij = O_i * (A_j * f(d_ij)) / sum_k(A_k * f(d_ik))

The math itself lives in :mod:`brewgis.sqlmesh.models.python._gravity_model`,
which is importable without a database — this module only wires it to the
scenario's tables. The N x N matrix is what makes this a Python model rather
than SQL: the distance matrix, the row/column sums and the per-origin averages
are one O(N^2) computation per scenario, distributed in origin batches so a
213k-parcel scenario stays inside a few hundred MB (see ``_BATCH_ELEMENTS``).

Distance source is, by default, the Euclidian centroid distance, taken in the
region's projected CRS (``local_srid``) and scaled by that CRS's own
metres-per-unit (:func:`brewgis.sqlmesh.macros.geometry.metres_per_unit`), so
``avg_trip_length_km`` is kilometres whatever the projection's linear unit and
the models that scale by it (vmt, physical_activity) are in the units they
claim. When the scenario sets ``transport_use_network_distance``, pairs of
parcels in different 2 km grid zones travel the road-network zone distance
instead (never less than the straight line), read from the scenario's
``network_zone_distance`` model (see
:mod:`brewgis.sqlmesh.models.python._network_zones`).

Gravity-model coefficients (b, emp_weight, du_weight) are the untuned
literature defaults documented in ``docs/sqlmesh-parameters.md`` §3.1 and are
kept as keyword defaults on the pure function rather than scenario parameters,
matching the hardcoded coefficients of the mode-choice model it feeds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.macros.analysis_blueprints import analysis_blueprint_profiles
from brewgis.sqlmesh.macros.geometry import metres_per_unit
from brewgis.sqlmesh.macros.geometry import require_local_srid
from brewgis.sqlmesh.models.python._gravity_model import _gravity_model
from brewgis.sqlmesh.models.python._network_zones import zone_distance_matrix
from brewgis.sqlmesh.models.python._network_zones import zone_indices

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per analyzed scenario in the database at that moment.
_PROFILES = analysis_blueprint_profiles("trip_distribution")

# Publish this model's result view where the Layers, Martin and UI paths read it
# (see the SQL analysis models' ON_VIRTUAL_UPDATE block). The view selects from
# the scenario schema's own table, never from this model's ``@this_model``: a
# non-prod environment's promotion must not repoint it.
_ON_VIRTUAL_UPDATE = [
    'CREATE SCHEMA IF NOT EXISTS "@{result_schema}"',
    (
        'CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS '
        'SELECT * FROM @{scenario_schema}."@{model_table}"'
    ),
]


@model(
    name="brewgis.@{scenario_schema}.@{model_table}",
    kind=ModelKindName.FULL,
    description=(
        "Daily parcel trip distribution: outbound, inbound and internal trips"
        " plus average trip length, from a gravity model over parcel centroids."
    ),
    column_descriptions={
        "parcel_id": "Parcel identifier from the scenario end state (core_end_state).",
        "trips_outbound": "Trips per day from the parcel to other parcels.",
        "trips_inbound": "Trips per day from other parcels to the parcel.",
        "trips_internal": "Trips per day that start and end inside the parcel.",
        "avg_trip_length_km": (
            "Trip-weighted mean distance of the parcel's outbound trips (km)."
        ),
    },
    columns={
        # The parcel key's type follows the scenario's parcel source — an APN
        # string for the demo regions, a numeric id for a legacy base canvas —
        # so it comes from the blueprint. SQLMesh renders an `@`-bearing column
        # type per blueprint and parses the result, and a key declared with the
        # wrong type cannot join the rest of the scenario's models.
        "parcel_id": "@{parcel_key_type}",
        "trips_outbound": "float",
        "trips_inbound": "float",
        "trips_internal": "float",
        "avg_trip_length_km": "float",
    },
    blueprints=[dict(profile) for profile in _PROFILES],
    on_virtual_update=_ON_VIRTUAL_UPDATE,
    audits=[
        # ``assert_column_non_negative`` splices its ``@column_name`` into SQL as
        # text, so the argument has to be an *expression*: a Python model's audit
        # arguments go through ``exp.convert``, which turns a plain string into a
        # string literal ("WHERE COALESCE('trips_outbound', 0) < 0" — a cast error
        # on a text column, and vacuously true on any other).
        ("assert_column_non_negative", {"column_name": exp.column("trips_outbound")}),
        ("assert_column_non_negative", {"column_name": exp.column("trips_inbound")}),
        ("assert_column_non_negative", {"column_name": exp.column("trips_internal")}),
        # Conserves the scenario's trip generation: outbound vs inbound within
        # 1%, and outbound + internal against trip_generation's total. Its SQL
        # splices ``@{scenario_schema}.trip_generation``, which a Python model's
        # blueprint does render as a bare identifier (checked through the model's
        # own ``render_audit_query``, and executed the way the evaluator runs it:
        # 0 failing rows on scenario 7's 214,675 rows).
        ("assert_total_trips_conserved", {}),
    ],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> pd.DataFrame:
    """Distribute each parcel's trips over the scenario's parcels.

    Both ``resolve_table`` calls are resolvable at parse time by construction:
    SQLMesh derives this model's upstream dependencies by walking this
    function's AST and evaluating the argument of every ``context.resolve_table``
    with ``blueprint_var`` bound to the scenario's blueprint (there is no
    explicit ``depends_on``), so each one has to name its model with the
    blueprint variable inlined rather than an already-computed local — an
    unresolvable argument raises at load time instead of recording the edge.
    """
    trip_generation = context.resolve_table(
        f"brewgis.{context.blueprint_var('scenario_schema')}.trip_generation"
    )
    core_end_state = context.resolve_table(
        f"brewgis.{context.blueprint_var('scenario_schema')}.core_end_state"
    )
    # Resolved whether or not the option is on, so the dependency always exists.
    zone_pairs = context.resolve_table(
        f"brewgis.{context.blueprint_var('scenario_schema')}.network_zone_distance"
    )
    # A scenario's geometry is EPSG:4326, so its coordinates are *degrees*:
    # distances are taken in the region's projected ``local_srid`` instead, whose
    # linear unit is whatever that CRS defines (metres, US survey feet, ...).
    # Scaling by the CRS's own metres-per-unit gives the kilometres
    # ``avg_trip_length_km`` promises its consumers (vmt and physical_activity
    # both scale by it).
    projected_srid = require_local_srid(context)
    km_per_unit = metres_per_unit(projected_srid) / 1000.0

    parcels = context.fetchdf(
        f"""
        SELECT
            tg.parcel_id,
            tg.trips_total,
            ST_X(ST_Transform(ST_Centroid(es.geometry), {projected_srid})) AS x,
            ST_Y(ST_Transform(ST_Centroid(es.geometry), {projected_srid})) AS y,
            COALESCE(es.emp, 0) AS emp,
            COALESCE(es.du, 0) AS du
        FROM {trip_generation} AS tg
        LEFT JOIN {core_end_state} AS es
            ON tg.parcel_id = es.parcel_id
        ORDER BY tg.parcel_id
        """  # noqa: S608 — table names are SQLMesh-resolved identifiers
    )

    if parcels.empty:
        return pd.DataFrame(
            {
                "parcel_id": np.array([], dtype=object),
                "trips_outbound": np.array([], dtype=float),
                "trips_inbound": np.array([], dtype=float),
                "trips_internal": np.array([], dtype=float),
                "avg_trip_length_km": np.array([], dtype=float),
            }
        )

    network: dict[str, np.ndarray] = {}
    if context.blueprint_var("transport_use_network_distance"):
        pairs = context.fetchdf(
            f"""
            SELECT origin_ix, origin_iy, dest_ix, dest_iy, network_distance_km
            FROM {zone_pairs}
            """  # noqa: S608 — table name is a SQLMesh-resolved identifier
        )
        if pairs.empty:
            msg = (
                "transport_use_network_distance is enabled but network_zone_distance"
                " has no rows for this scenario"
            )
            raise RuntimeError(msg)
        parcel_ix, parcel_iy = zone_indices(
            parcels["x"].to_numpy(dtype=float),
            parcels["y"].to_numpy(dtype=float),
            metres_per_unit(projected_srid),
        )
        zones, matrix = zone_distance_matrix(
            parcel_ix=parcel_ix,
            parcel_iy=parcel_iy,
            origin_ix=pairs["origin_ix"].to_numpy(),
            origin_iy=pairs["origin_iy"].to_numpy(),
            dest_ix=pairs["dest_ix"].to_numpy(),
            dest_iy=pairs["dest_iy"].to_numpy(),
            distance_km=pairs["network_distance_km"].to_numpy(dtype=float),
        )
        network = {"zones": zones, "zone_distance_km": matrix}

    outbound, inbound, internal, avg_length = _gravity_model(
        trips=parcels["trips_total"].to_numpy(dtype=float),
        xs=parcels["x"].to_numpy(dtype=float) * km_per_unit,
        ys=parcels["y"].to_numpy(dtype=float) * km_per_unit,
        emp=parcels["emp"].to_numpy(dtype=float),
        du=parcels["du"].to_numpy(dtype=float),
        **network,
    )

    return pd.DataFrame(
        {
            "parcel_id": parcels["parcel_id"].to_numpy(),
            "trips_outbound": outbound,
            "trips_inbound": inbound,
            "trips_internal": internal,
            "avg_trip_length_km": avg_length,
        }
    )
