from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    """Restate ``zero_transparent``'s help text.

    The flag now also keeps zero values out of the statistics and the
    classification, not only out of the paint — the admin help text said
    "make zero-values fully transparent" only.
    """

    dependencies = [
        ("workspace", "0056_attach_analysis_layers_to_scenarios"),
    ]

    operations = [
        migrations.AlterField(
            model_name="symbologyconfig",
            name="zero_transparent",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Draw zero-values fully transparent, and leave them out of the "
                    "statistics and classification behind the symbology."
                ),
            ),
        ),
    ]
