from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0054_scenario_analysis_params"),
    ]

    operations = [
        migrations.AddField(
            model_name="layer",
            name="scenario",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Scenario this layer belongs to, for per-scenario results (a "
                    "scenario's analysis views and its canvas view). Null for "
                    "workspace-level layers — the base canvas, the painted-features "
                    "overlay and imported data — which every scenario shows."
                ),
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="layers",
                to="workspace.scenario",
            ),
        ),
    ]
