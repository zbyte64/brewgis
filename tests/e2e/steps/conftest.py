"""Conftest for step definitions — imports all step modules to register them.

pytest-bdd discovers step definitions by module import.  This conftest
ensures common_steps (and any other shared steps) are registered for all
e2e test modules.
"""
from __future__ import annotations

# Import shared steps so they are registered with pytest-bdd
from tests.e2e.steps import common_steps  # noqa: F401
