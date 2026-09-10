import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0037_workspace_base_table'),
    ]

    operations = [
        migrations.AlterField(
            model_name='buildingtype',
            name='name',
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name='placetype',
            name='name',
            field=models.CharField(max_length=128),
        ),
        migrations.AddField(
            model_name='buildingtype',
            name='workspace',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='building_types',
                to='workspace.workspace',
            ),
        ),
        migrations.AddField(
            model_name='placetype',
            name='workspace',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='place_types',
                to='workspace.workspace',
            ),
        ),
    ]
