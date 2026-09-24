"""Registration of Python-decorated SQLMesh models blueprinted from the database.

``@model(blueprints=[...])`` instantiates the model once per entry in the list,
and the models that mirror database rows — one instance per workspace with the
built-form fill on (``models/base_canvas/built_form_fill.py``), per ALTERNATIVE
scenario (``models/scenarios/scenario_canvas.py``), per analyzed scenario
(``models/python/trip_distribution.py``, ``models/python/network_zone_distance.py``)
— have no instance at all on a database where that feature has not been used yet.

SQLMesh has no way to say "zero instances" from the decorator: it reads a
declared but empty ``blueprints`` list as *one* instance without any blueprint
variables (``_extract_blueprints`` falls back to ``[None]``), and that phantom
instance renders every ``@{var}`` in the declaration as an empty string and every
``blueprint_var(name, default)`` as its default. For a model whose SELECT is
assembled from its blueprint, that is a query with no projections, and project
load dies with ``Query missing select statements`` — the whole SQLMesh project
(and the UI that loads it) is unloadable because no workspace happened to opt
in.

Registering nothing is the only way to instantiate nothing, so these models
register through :func:`register_blueprint_model`: the ``model(...)`` declaration
is applied only when there is at least one instance. ``models/analysis/**``
reaches the same outcome through ``blueprints @analysis_blueprints(...)``, whose
macro expands an empty profile list to an empty ``exp.Tuple`` (zero models).
The Python-decorated models cannot use that path: the macro route carries
blueprint variables as SQL text, while these read Python values out of
``blueprint_var`` (``all_columns``, a list; ``transport_use_network_distance``,
a bool).
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from typing import Any
from typing import cast


def register_blueprint_model[FuncT: Callable[..., Any]](
    declaration: Callable[[Any], Any],
    func: FuncT,
    blueprints: Sequence[Any],
) -> FuncT:
    """Register *func* under the SQLMesh *declaration*, once per *blueprints* entry.

    *declaration* is the ``model(...)`` object the module would otherwise use as
    a decorator, *blueprints* the profile list built from the database at import.

    With no entries, *declaration* is not applied and *func* stays an ordinary
    function: the module loads and contributes no model, instead of one phantom
    instance. See this module's docstring for what SQLMesh does with an empty
    ``blueprints`` list.
    """
    if not blueprints:
        return func
    # A registry decorator registers *func* and hands the same function back;
    # mypy cannot express that for a declaration whose ``__call__`` is generic.
    return cast("FuncT", declaration(func))
