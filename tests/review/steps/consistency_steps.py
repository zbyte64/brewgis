"""Step definitions for Cross-Surface Consistency feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.pages.home_page import HomePage
from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.analysis_modules_page import AnalysisModulesPage
from tests.review.pages.consistency_page import ConsistencyPage

scenarios(str(Path(__file__).parent.parent / "features" / "consistency.feature"))


@when("I navigate to the home page")
def navigate_home(page, live_server_url) -> None:
    """Navigate to the home page."""
    HomePage(page, live_server_url).navigate_to()


@then("I should see the main navigation bar")
def see_navbar(page) -> None:
    """Check the navbar is visible."""
    assert ConsistencyPage(page, "").has_navbar(), (
        "Expected navigation bar to be visible"
    )


@then("I should see navigation links")
def see_nav_links(page) -> None:
    """Check navbar has navigation links."""
    links = ConsistencyPage(page, "").navbar_links()
    assert len(links) > 0, f"Expected navigation links, got {links}"


@then("the Analysis Modules panel should show empty state or modules")
def modules_shows_empty_or_content(page) -> None:
    """Check the analysis modules panel has content or empty state."""
    modules = AnalysisModulesPage(page)
    has_content = modules.module_count() > 0
    has_empty = modules.has_empty_message()
    assert has_content or has_empty, (
        "Expected analysis modules panel to show modules or empty state"
    )
