"""Trip lengths (T2b) — each parcel's one-way trip length, blueprinted Python model.

One instance of this model per analyzed scenario, materialized in
``brewgis.ascn<scenario_pk>`` by the same blueprint mechanism the SQL analysis
models use (see ``sqlmesh/macros/analysis_blueprints.py``), so its name, its
dependencies and its published result view come from the scenario rows that
exist at load time. With no analyzed scenario it registers no model at all (see
:mod:`brewgis.sqlmesh.blueprint_models`).

This is a *support* model, not an analysis module: it has no entry in
``MODULE_DEPENDENCIES``/``MODULE_RESULT_TABLES``/``MODULE_SQLMESH_SELECTORS``
(mirroring ``quarter_mile_context``), and the consumers that read its table —
``vmt`` and ``physical_activity`` — make SQLMesh plan it as a dependency.

Why the trip length needs its own model at all: UrbanFootprint never *derives*
it. It reads precomputed regional reference data (SACSIM zone-to-zone lengths,
shipped in the source dump), joins every parcel centroid to its zone, and uses
that zone's mean length. A pure gravity distribution over parcel centroids does
produce a trip length, but its absolute scale is an artifact of parcel size and
density — SACOG's canvas lands on ~1.2 km one-way against SACSIM's ~6.4 km, and
VMT is proportional to it, so every VMT number comes out ~5x low.

So: when the scenario names a reference table (``transport_trip_length_table``,
``schema.table``), that table wins. When it does not — Fresno, any region
without such data — the model falls back to the gravity model's own
``avg_trip_length_km``, which preserves the *spatial gradient* (parcels near
employment attract shorter trips, rural ones longer), rescaled so the regional
mean equals ``transport_target_avg_trip_length_km``. The gradient is what makes
the fallback region-specific; the target only fixes the level.

Reference-table contract, checked by the region's loader rather than here: a
plain lowercase ``schema.table`` identifier with a ``wkb_geometry`` geometry
column plus the six numeric ``productions_hbw``/``productions_hbo``/
``productions_nhb``/``attractions_hbw``/``attractions_hbo``/``attractions_nhb``
columns, each in round-trip miles. A parcel's value is the mean of the six for
the zone its centroid falls in, halved and converted to kilometres — the same
unit ``trip_distribution.avg_trip_length_km`` and therefore
``vmt``/``physical_activity`` already expect — then rescaled so the parcels'
mean equals the *table's* own regional mean: assigning each parcel its zone's
length weights the zones by parcel density, which shrinks the regional mean
(SACOG: 5.76 km against the table's 6.42 km, because parcels concentrate in the
short-trip zones), while the rescale keeps the table's spatial structure — the
same relationship to a published regional mean that the fallback has to its
target. The identifier is interpolated into the fetch SQL directly
(scenario-owned configuration, the same trust the scenario's ``parcel_table``
gets), so it must never be built from user input.

The zone join is a ``LEFT JOIN`` on purpose: a parcel whose centroid falls
outside every zone keeps the scaled gravity value instead of dropping its trips
(verified coverage on the SACOG canvas: 52,187/52,187 parcels).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.analysis_blueprints import analysis_blueprint_profiles
from brewgis.sqlmesh.macros.geometry import require_local_srid

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per analyzed scenario in the database at that moment.
_PROFILES = analysis_blueprint_profiles("trip_lengths")

# Round-trip miles -> one-way kilometres, for the reference table's six lengths.
_MI_PER_KM = 1.609344
# Fallback target when the scenario sets no usable value (the registry default).
_DEFAULT_TARGET_AVG_TRIP_LENGTH_KM = 6.42
# The six length columns of a reference table: three productions, three
# attractions. `{alias}` is the table alias; mean of the six, halved and
# converted -> the zone's mean one-way trip length in km.
_ZONE_LENGTH_SUM = (
    "{alias}.productions_hbw + {alias}.productions_hbo + {alias}.productions_nhb"
    " + {alias}.attractions_hbw + {alias}.attractions_hbo + {alias}.attractions_nhb"
)
_ZONE_LENGTH_KM = f"({_ZONE_LENGTH_SUM}) / 6.0 / 2.0 * {_MI_PER_KM!r}"

# Publish this model's result view where the Layers, Martin and UI paths read it
# (see the SQL analysis models' ON_VIRTUAL_UPDATE block). Unlike this model's own
# table, the view also carries the parcel geometry: this is a DataFrame model and
# a pandas frame cannot hand PostGIS a geometry column, while a table without one
# is not a tileable source — Martin publishes no source for it and the layer the
# run registers draws nothing (its rows still show in the attribute table). The
# column is appended last so ``CREATE OR REPLACE VIEW`` can extend the view.
_ON_VIRTUAL_UPDATE = [
    'CREATE SCHEMA IF NOT EXISTS "@{result_schema}"',
    (
        'CREATE OR REPLACE VIEW "@{result_schema}"."@{model_table}" AS '
        "SELECT tl.*, es.geometry "
        'FROM @{scenario_schema}."@{model_table}" AS tl '
        "LEFT JOIN @{scenario_schema}.core_end_state AS es "
        "ON tl.parcel_id = es.parcel_id"
    ),
]


# One declaration, applied once per analyzed scenario below: with none in the
# database there is nothing to instantiate.
_TRIP_LENGTHS_MODEL = model(
    # The table is spelled out rather than ``@{model_table}``: SQLMesh registers
    # Python models by their unrendered name, which trip_distribution already
    # claims ("Duplicate name" — see network_zone_distance for the same fix).
    name="brewgis.@{scenario_schema}.trip_lengths",
    kind=ModelKindName.FULL,
    description=(
        "One-way trip length per parcel in kilometres: the region's reference"
        " trip-length zone when the scenario names such a table, otherwise the"
        " gravity model's spatial gradient rescaled to the target regional mean."
    ),
    column_descriptions={
        "parcel_id": "Parcel identifier from the scenario end state (core_end_state).",
        "avg_trip_length_km": (
            "One-way trip length of the parcel's trips (km): the region's"
            " reference trip-length zone rescaled to the table's regional mean,"
            " or the gravity estimate scaled to the target regional mean."
        ),
    },
    columns={
        # The parcel key's type follows the scenario's parcel source, exactly as
        # trip_distribution declares it — a key declared with the wrong type
        # cannot join the rest of the scenario's models.
        "parcel_id": "@{parcel_key_type}",
        "avg_trip_length_km": "float",
    },
    blueprints=[dict(profile) for profile in _PROFILES],
    on_virtual_update=_ON_VIRTUAL_UPDATE,
    audits=[
        # Audit arguments run through ``exp.convert`` for a Python model, which
        # turns a plain string into a string *literal* — the columns therefore
        # have to be expressions (see trip_distribution's audits).
        ("not_null", {"columns": exp.Tuple(expressions=[exp.column("parcel_id")])}),
        (
            "unique_values",
            {"columns": exp.Tuple(expressions=[exp.column("parcel_id")])},
        ),
        (
            "assert_column_non_negative",
            {"column_name": exp.column("avg_trip_length_km")},
        ),
    ],
)


def _as_float(value: Any, default: float) -> float:
    """Read a blueprint value as a float, falling back to *default* when unset."""
    return default if value is None else float(value)


def execute(
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> pd.DataFrame:
    """Resolve each parcel's one-way trip length for this scenario.

    Both ``context.resolve_table`` calls are resolvable at parse time by
    construction: SQLMesh derives this model's upstream dependencies by walking
    this function's AST and evaluating the argument of every
    ``context.resolve_table`` with ``blueprint_var`` bound to the scenario's
    blueprint, so each one has to name its model with the blueprint variable
    inlined rather than an already-computed local.
    """
    trip_distribution = context.resolve_table(
        f"brewgis.{context.blueprint_var('scenario_schema')}.trip_distribution"
    )
    core_end_state = context.resolve_table(
        f"brewgis.{context.blueprint_var('scenario_schema')}.core_end_state"
    )
    # A reference table is region configuration: a plain ``schema.table`` name,
    # empty when the region ships none. It is interpolated into the fetch below
    # the way ``parcel_table`` is — scenario-owned, never user-supplied SQL.
    table = context.blueprint_var("transport_trip_length_table")
    target = _as_float(
        context.blueprint_var("transport_target_avg_trip_length_km"),
        _DEFAULT_TARGET_AVG_TRIP_LENGTH_KM,
    )

    gravity = context.fetchdf(
        f"""
        SELECT parcel_id, avg_trip_length_km
        FROM {trip_distribution}
        ORDER BY parcel_id
        """  # noqa: S608 — table name is a SQLMesh-resolved identifier
    )
    if gravity.empty:
        return pd.DataFrame(
            {
                "parcel_id": np.array([], dtype=object),
                "avg_trip_length_km": np.array([], dtype=float),
            }
        )

    # The fallback every region gets: keep the gravity model's spatial gradient,
    # fix its absolute level. Without this a region's mean trip length is an
    # artifact of parcel size — and VMT, which multiplies it by the parcel's auto
    # trips, inherits the error directly.
    gravity_mean = float(gravity["avg_trip_length_km"].mean())
    gravity["avg_trip_length_km"] = gravity["avg_trip_length_km"] * (
        target / gravity_mean if gravity_mean > 0 else 1.0
    )

    if table:
        # Distances are taken in the region's projected local_srid (the parcels'
        # own ``centroid_local`` is in it), so the zone geometry is transformed
        # into that CRS too — never the other way round, and never through a
        # coarser CRS.
        srid = require_local_srid(context)
        zone_km = _ZONE_LENGTH_KM.format(alias="z")
        zones = context.fetchdf(
            f"""
            SELECT
                es.parcel_id,
                {zone_km} AS zone_km,
                (
                    SELECT AVG({_ZONE_LENGTH_KM.format(alias="z2")})
                    FROM {table} AS z2
                ) AS zone_mean_km
            FROM {core_end_state} AS es
            LEFT JOIN {table} AS z
                ON ST_Contains(ST_Transform(z.wkb_geometry, {srid}), es.centroid_local)
            ORDER BY es.parcel_id
            """  # noqa: S608 — the table is scenario-owned configuration
        )
        gravity = gravity.merge(zones, on="parcel_id", how="left")
        # The reference table's own regional mean is the region's trip length;
        # assigning each parcel the length of the zone its centroid falls in
        # weights the zones by parcel density, which shrinks the mean (SACOG:
        # 5.76 km against the table's 6.42 km, because parcels concentrate in the
        # short-trip zones). Rescaling by that ratio keeps the table's spatial
        # *structure* — near-employment zones stay shorter than rural ones — and
        # puts the region on its published mean, the same way the fallback puts a
        # region on its target.
        covered = gravity["zone_km"].notna()
        zone_mean = float(gravity["zone_mean_km"].iloc[0])
        parcel_mean = float(gravity.loc[covered, "zone_km"].mean())
        scale = zone_mean / parcel_mean if parcel_mean > 0 else 1.0
        # A parcel outside every zone keeps the scaled gravity value.
        gravity["avg_trip_length_km"] = (gravity["zone_km"] * scale).fillna(
            gravity["avg_trip_length_km"]
        )

    return gravity[["parcel_id", "avg_trip_length_km"]]


# One model per analyzed scenario: with none analyzed, registering nothing is
# what keeps an empty blueprint list from becoming a phantom model.
execute = register_blueprint_model(_TRIP_LENGTHS_MODEL, execute, _PROFILES)
