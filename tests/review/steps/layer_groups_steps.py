"""Step definitions for Layer Groups feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import scenarios
from pytest_bdd import then

from tests.e2e.steps.common_steps import *  # noqa: F403

scenarios(str(Path(__file__).parent.parent / "features" / "layer_groups.feature"))


@then("the page loads successfully")
def page_loads(page) -> None:
    """Check the page loaded without error."""
    assert page.url, "Page URL should not be empty"
    assert page.title(), "Page title should not be empty"
