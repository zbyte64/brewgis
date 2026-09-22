"""Attach the pre-existing analysis result layers to the scenario that made them.

Separate from the ``AddField`` that introduced ``Layer.scenario`` because
PostgreSQL refuses to build the field's index in the same transaction as the
row changes below ("cannot CREATE INDEX ... because it has pending trigger
events") — the deferred FK constraint Django adds for the field is left with
unfired trigger events for the rest of that transaction.
"""

from django.db import migrations

RESULT_SCHEMA_PREFIX = "analysis__scenario_"


def attach_analysis_layers_to_scenarios(apps, schema_editor):
    """Point each analysis result layer at the scenario that produced it.

    A scenario's result views are published into ``analysis__scenario_<pk>``
    (see ``analysis/pipeline.py``), which is where the layer sits — so the
    scenario is recoverable from ``db_schema`` for every layer registered
    before this field existed.

    Layers naming a scenario that no longer exists (deleted, or one from
    another workspace) have no scenario to attach to: they are leftovers whose
    result view went with the scenario, and keeping them as workspace-level
    layers would list them against every scenario — the one thing this field
    exists to prevent. They are removed.
    """
    layer_model = apps.get_model("workspace", "Layer")
    scenario_model = apps.get_model("workspace", "Scenario")

    for layer in layer_model.objects.filter(
        db_schema__startswith=RESULT_SCHEMA_PREFIX
    ).only("pk", "db_schema", "workspace_id"):
        scenario_pk = layer.db_schema[len(RESULT_SCHEMA_PREFIX) :]
        if not scenario_pk.isdigit():
            continue

        scenario = scenario_model.objects.filter(
            pk=int(scenario_pk), workspace_id=layer.workspace_id
        ).first()
        if scenario is None:
            layer_model.objects.filter(pk=layer.pk).delete()
            continue

        layer_model.objects.filter(pk=layer.pk).update(scenario_id=scenario.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0055_layer_scenario"),
    ]

    operations = [
        migrations.RunPython(
            attach_analysis_layers_to_scenarios,
            migrations.RunPython.noop,
        ),
    ]
