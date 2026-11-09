from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0079_merge_20261108"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="layer",
            options={
                "ordering": (
                    "group__display_order",
                    "group__name",
                    "display_order",
                    "pk",
                )
            },
        ),
    ]
