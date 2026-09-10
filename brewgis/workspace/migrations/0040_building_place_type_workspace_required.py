import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0039_copy_building_place_types_per_workspace'),
    ]

    operations = [
        migrations.AlterField(
            model_name='buildingtype',
            name='workspace',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='building_types',
                to='workspace.workspace',
            ),
        ),
        migrations.AlterField(
            model_name='placetype',
            name='workspace',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='place_types',
                to='workspace.workspace',
            ),
        ),
        migrations.AddConstraint(
            model_name='buildingtype',
            constraint=models.UniqueConstraint(
                fields=('workspace', 'name'),
                name='uq_building_type_workspace_name',
            ),
        ),
        migrations.AddConstraint(
            model_name='placetype',
            constraint=models.UniqueConstraint(
                fields=('workspace', 'name'),
                name='uq_place_type_workspace_name',
            ),
        ),
    ]
