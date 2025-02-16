import yaml
from django.db import models

from .procedures import write_model, write_schema, run_model


class StatusChoices(models.TextChoices):
    pass


class DBTModel(models.Model):
    name = models.CharField(max_length=64, unique=True, help_text='The SQL view name')

    status = models.CharField(max_length=64, blank=True)
    schema_spec = models.JSONField(help_text='The portion you would find in a schema.yml file')
    sql_definition = models.TextField(help_text='DBT SQL')

    def apply_to_db(self):
        write_model(self.name, self.sql_definition)
        sync_schema()
        # TODO mark status as ERROR on failure
        run_model(self.name)


def sync_schema():
    write_schema(yaml.dump(generate_schema()))


def generate_schema():
    dbt_models = DBTModel.objects.exclude(status='ERROR')
    return {
        'version': 2,
        'models': [
            {
                name=dbt_model.name,
                **dbt_model.schema_spec
            } for dbt_model in dbt_models
        ]
    }
