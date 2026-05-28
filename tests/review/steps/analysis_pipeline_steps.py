"""Step definitions for Analysis Pipeline feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.analysis_pipeline_page import AnalysisPipelinePage

scenarios(str(Path(__file__).parent.parent / "features" / "analysis_pipeline.feature"))


@when("I navigate to the analysis launch page")
def navigate_launch(page, live_server_url) -> None:
    """Navigate to the analysis launch form."""
    AnalysisPipelinePage(page).navigate_to_launch(live_server_url)


@when("I navigate to the analysis list page")
def navigate_list(page, live_server_url) -> None:
    """Navigate to the analysis runs list."""
    AnalysisPipelinePage(page).navigate_to_list(live_server_url)


@then("I should see form fields on the launch page")
def see_form_fields(page) -> None:
    """Check the launch page has form fields."""
    fields = AnalysisPipelinePage(page).launch_form_fields()
    assert len(fields) > 0, f"Expected form fields on launch page, got: {fields}"


@then(parsers.parse('I should see a "{button_text}" button'))
def see_button(page, button_text: str) -> None:
    """Check a named button is visible."""
    button = page.get_by_role("button", name=button_text)
    link = page.get_by_role("link", name=button_text)
    assert button.is_visible() or link.is_visible(), (
        f"Expected button/link '{button_text}' to be visible"
    )


@then("the page should show runs or empty state")
def shows_runs_or_empty(page) -> None:
    """Check the list page either shows runs or an empty state message."""
    pipeline = AnalysisPipelinePage(page)
    has_empty = pipeline.has_empty_message()
    has_runs = pipeline.run_count() > 0
    assert has_empty or has_runs, "Expected either runs or empty state message"


@then("status badges should be visible for listed runs")
def status_badges_visible(page) -> None:
    """Check that status badges are present for any listed runs."""
    badges = AnalysisPipelinePage(page).status_badges()
    if AnalysisPipelinePage(page).run_count() > 0:
        assert len(badges) > 0, "Expected status badges for listed runs"
