"""Built-form key matching in SQL — the SQLMesh half of one shared rule.

``models/analysis/core_end_state.sql`` and its downstream models join a
canvas's ``built_form_key`` to ``built_forms.key``. Both sides are keys of the
same kind but not the same spelling: the base-canvas ETL writes slug-like keys
(``bt__medium_density_detached_residential``) while ``built_forms.key`` holds
the workspace's BuildingType display names, so a raw ``=`` matches only the
keys the paint surfaces wrote.

This macro renders the same normalization
``services.built_form_keys.normalize_built_form_key`` applies in Python — the
rule and its two implementations are pinned together by
``tests/workspace/test_built_form_keys.py``, which runs this SQL and the Python
function over one corpus and compares the results.

The prefix list and separator characters are spelled out here rather than
imported: a macro's sources are serialized into its ``python_env`` and evaluated
standalone (see ``macros/analysis_blueprints.py``), so the SQL half stays free
of project imports.
"""

from __future__ import annotations

from sqlmesh import macro

# Kept textually identical to services/built_form_keys.ETL_KEY_PREFIXES /
# KEY_SEPARATORS — see the parity test named in the module docstring.
_PREFIX_ALTERNATION = "bt__|pt__|bf__"
_SEPARATOR_CLASS = "[-_]"


@macro()
def normalize_built_form_key(evaluator, expression: str) -> str:
    """Normalize a built-form key expression for matching.

    Usage in model SQL::

        ON @normalize_built_form_key(p.built_form_key) = @normalize_built_form_key(bf.key)

    Produces (Postgres)::

        btrim(regexp_replace(
            regexp_replace(lower(btrim(CAST(<expression> AS TEXT))),
                           '^(bt__|pt__|bf__)', ''),
            '[-_]', ' ', 'g'))

    Args:
        expression: SQL expression producing the key (a column reference).

    Returns:
        SQL expression producing the normalized key.
    """
    return (
        "btrim(regexp_replace("
        f"regexp_replace(lower(btrim(CAST({expression} AS TEXT))), "
        f"'^({_PREFIX_ALTERNATION})', ''), "
        f"'{_SEPARATOR_CLASS}', ' ', 'g'))"
    )
