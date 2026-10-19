"""Drop the per-scenario analysis table and column overrides.

Constraint layers and trip-length reference zones are region data now, chosen
by SQLMesh models (``brewgis.<region>.constraint_layers``,
``region_blueprints.analysis_region_profiles``), and analysis models read the SQLMesh
base canvas's own column names, so ``Scenario.constraints``,
``Scenario.column_mapping``, ``AnalysisRun.column_mapping`` and the
``transport_trip_length_table`` analysis parameter have nothing left to set.
"""

from django.db import migrations

_REMOVED_PARAMETER = "transport_trip_length_table"


def drop_trip_length_table_parameter(apps, schema_editor):  # noqa: ANN001, ANN201, ARG001
    Scenario = apps.get_model("workspace", "Scenario")  # noqa: N806
    for scenario in Scenario.objects.filter(
        analysis_params__has_key=_REMOVED_PARAMETER
    ):
        scenario.analysis_params.pop(_REMOVED_PARAMETER)
        scenario.save(update_fields=["analysis_params"])


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0074_layer_filter_output_layer"),
    ]

    operations = [
        migrations.RemoveField(model_name="scenario", name="constraints"),
        migrations.RemoveField(model_name="scenario", name="column_mapping"),
        migrations.RemoveField(model_name="analysisrun", name="column_mapping"),
        migrations.RunPython(
            drop_trip_length_table_parameter, migrations.RunPython.noop
        ),
    ]
