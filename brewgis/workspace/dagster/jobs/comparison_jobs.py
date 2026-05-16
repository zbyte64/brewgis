"""Dagster job definitions for the SACOG comparison pipeline."""

from dagster import job


@job(
    name="sacog_comparison",
    description=(
        "End-to-end SACOG base canvas comparison pipeline. Loads reference "
        "parcels, fetches Census ACS and LEHD LODES data, runs dbt base_canvas "
        "models, verifies geometry, creates the base_canvas view, materializes "
        "dbt comparison models, and generates the comparison report."
    ),
)
def sacog_comparison() -> None:
    """Execute the full SACOG comparison pipeline.

    Asset dependencies are declared via ``ins`` parameters on each
    ``@asset`` definition and are resolved automatically by the
    Dagster asset graph. This job body is intentionally empty because
    all wiring is handled declaratively.
    """
