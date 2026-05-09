"""Step definitions for Symbology Editor feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then
from pytest_bdd import when

from brewgis.workspace.models import Layer
from tests.review.pages.symbology_page import SymbologyPage
from tests.e2e.steps.common_steps import *  # noqa: F403

scenarios(str(Path(__file__).parent.parent / "features" / "symbology.feature"))


@when(parsers.parse('I navigate to the symbology editor for the "{layer_name}" layer'))
def navigate_symbology(page, live_server_url, layer_name: str) -> None:
    """Navigate to the symbology editor for the named layer."""
    layer = Layer.objects.filter(name=layer_name).last()
    assert layer is not None, f"Layer '{layer_name}' not found"
    SymbologyPage(page).navigate_to_symbology(layer.pk, live_server_url)


@then("I should see the symbology editor form")
def see_symbology_form(page) -> None:
    """Check the symbology editor form is present."""
    assert SymbologyPage(page).has_editor_form(), (
        "Expected symbology editor form to be visible"
    )


@then(parsers.parse("the symbology type selector should include {options}"))
def symbology_type_options(page, options: str) -> None:
    """Check the symbology type select includes the expected options."""
    expected = [o.strip('"') for o in options.split(",")]
    actual = SymbologyPage(page).symbology_type_options()
    for opt in expected:
        assert opt in actual, (
            f"Expected symbology type '{opt}' in options, got {actual}"
        )


@then("I should see color controls")
def see_color_controls(page) -> None:
    """Check color input controls are present."""
    assert SymbologyPage(page).has_color_controls(), (
        "Expected color controls to be visible"
    )


@then(parsers.parse('I should see a "{button_text}" button'))
def see_button(page, button_text: str) -> None:
    """Check a button with the exact text is present."""
    btn = page.get_by_role("button", name=button_text)
    assert btn.is_visible(), (
        f"Expected button '{button_text}' to be visible"
    )


@then("I should see an auto-generate button")
def see_auto_generate(page) -> None:
    """Check the auto-generate button is present."""
    assert SymbologyPage(page).has_auto_generate_button(), (
        "Expected auto-generate button to be visible"
    )
