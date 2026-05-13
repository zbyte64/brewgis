"""Dagster job for the Fresno Demo end-to-end setup pipeline.

Defines a job that materializes the Fresno demo assets in dependency
order. The asset graph (``ins``/``deps``) already encodes the correct
execution order; the job simply selects the relevant assets.
"""

from dagster import job


@job(
    name="fresno_demo_setup",
    description=(
        "End-to-end Fresno demo setup pipeline. Downloads data, runs ETL, "
        "ingests constraints, exports building types, assigns built forms, "
        "creates a scenario, and runs the full dbt analysis pipeline."
    ),
)
def fresno_demo_setup() -> None:
    """Execute the full Fresno demo setup pipeline.

    Asset dependencies are declared via ``ins`` parameters on each
    ``@asset`` definition and are resolved automatically by the
    Dagster asset graph. The job body is intentionally empty because
    all wiring is handled declaratively.
    """
    # Asset dependencies are resolved declaratively via the asset graph.
    # This job body is intentionally empty — execution order is determined
    # by the dependencies declared in each @asset definition's ``ins``.
