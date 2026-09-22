"""Built-form key matching — the rule that pairs a canvas key with a BuildingType.

A canvas row names its built form in ``built_form_key``, but the two producers
of that value speak different dialects:

- the base-canvas ETL writes the key it was given by the source data — an
  ETL-style slug (``bt__medium_density_detached_residential``) or, where the
  source carries no built form at all, the ``mixed_use`` placeholder from
  ``services.base_canvas_pipeline``;
- the paint surfaces write the *display name* of the ``BuildingType`` that
  produced the values (``Courtyard Apartment``).

``built_forms.key`` (the table SQLMesh reads, exported by
``analysis.data_export``) holds those same display names. So matching a canvas
key to a built form means normalizing both sides: lowercase, drop an ETL
prefix, and treat ``_``/``-`` as spaces.

The UI (``views.paint``) and the analysis models (``sqlmesh/macros/
built_form_keys.py``) both apply this rule and must agree — a key that resolves
to a Building Type in the paint panel but not in the analysis is a silent
zero in every downstream result. This module is the Python half and deliberately
imports nothing (no Django, no SQLMesh) so both a request path and a test can
use it; the SQL half carries the same rule, and
``tests/workspace/test_built_form_keys.py`` executes both against one corpus.

Spaces are the only whitespace stripped: matching ``str.strip`` exactly would
mean listing every character Python considers whitespace, and every producer
writes plain spaces.
"""

from __future__ import annotations

# ETL key prefixes that carry no identity — stripped before matching so a
# slug-like key ("bt__courtyard_apartment") meets a display name
# ("Courtyard Apartment").
ETL_KEY_PREFIXES: tuple[str, ...] = ("bt__", "pt__", "bf__")

# Characters an ETL key uses where a display name uses a space.
KEY_SEPARATORS: str = "_-"


def normalize_built_form_key(value: str) -> str:
    """Return *value* in the normalized form used to match built form keys."""
    normalized = value.strip().lower()
    for prefix in ETL_KEY_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    for separator in KEY_SEPARATORS:
        normalized = normalized.replace(separator, " ")
    return normalized.strip()
