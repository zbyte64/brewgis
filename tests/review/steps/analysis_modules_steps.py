"""Step definitions for Analysis Modules feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers
from pytest_bdd import scenarios
from pytest_bdd import then

from tests.e2e.steps.common_steps import *  # noqa: F403
from tests.review.pages.analysis_modules_page import AnalysisModulesPage

scenarios(str(Path(__file__).parent.parent / "features" / "analysis_modules.feature"))


@then(parsers.parse("the Analysis Modules panel should have {count} modules"))
def modules_panel_has_count(page, count: str) -> None:
    """Check the number of module entries."""
    count = int(count)
    modules = AnalysisModulesPage(page)
    assert modules.module_count() == count, (
        f"Expected {count} modules, got {modules.module_count()}"
    )


@then(parsers.parse('the modules should include "{name}"'))
def modules_include(page, name: str) -> None:
    """Check a specific module is listed."""
    names = AnalysisModulesPage(page).get_module_names()
    assert name in names, f"Expected module '{name}' in list, got {names}"


@then(
    parsers.parse('the "{module_name}" module should have description "{description}"')
)
def module_has_description(page, module_name: str, description: str) -> None:
    """Check a module's description text."""
    data = AnalysisModulesPage(page).get_module_data(module_name)
    assert data is not None, f"Module '{module_name}' not found"
    actual = data.get("description", "")
    assert actual == description, (
        f"Expected description '{description}' for module "
        f"'{module_name}', got '{actual}'"
    )


@then(parsers.parse('the "{module_name}" module should list inputs {inputs}'))
def module_has_inputs(page, module_name: str, inputs: str) -> None:
    """Check a module lists the expected inputs."""
    data = AnalysisModulesPage(page).get_module_data(module_name)
    assert data is not None, f"Module '{module_name}' not found"
    expected = [i.strip().strip('"') for i in inputs.split(",")]
    actual = data.get("inputs", [])
    for inp in expected:
        assert inp in actual, (
            f"Expected input '{inp}' in module '{module_name}', got {actual}"
        )


@then(parsers.parse('the "{module_name}" module should list outputs {outputs}'))
def module_has_outputs(page, module_name: str, outputs: str) -> None:
    """Check a module lists the expected outputs."""
    data = AnalysisModulesPage(page).get_module_data(module_name)
    assert data is not None, f"Module '{module_name}' not found"
    expected = [o.strip().strip('"') for o in outputs.split(",")]
    actual = data.get("outputs", [])
    for out in expected:
        assert out in actual, (
            f"Expected output '{out}' in module '{module_name}', got {actual}"
        )


@then(parsers.parse('the "{module_name}" module should show input "{input_text}"'))
def module_shows_input(page, module_name: str, input_text: str) -> None:
    """Check a module shows a specific input."""
    data = AnalysisModulesPage(page).get_module_data(module_name)
    assert data is not None, f"Module '{module_name}' not found"
    actual = data.get("inputs", [])
    assert input_text in actual, (
        f"Expected input '{input_text}' in module '{module_name}', got {actual}"
    )
