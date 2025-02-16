import os, os.path
from django.conf import settings
from dbt.cli.main import dbtRunner, dbtRunnerResult

# DBT_PROJECT_DIR  --project-dir
# DBT_PROFILES_DIR --profiles-dir
DBT_PROJECT_FOLDER = settings.DBT_PROJECT_FOLDER
MODEL_FOLDER = settings.DBT_MODEL_FOLDER

# we host our own profile
PROFILE_DIR = os.path.join(DBT_PROJECT_FOLDER, 'profiles')


def dbt_params():
    return ['--profile-dir', PROFILE_DIR]


def run_model(model_name: str):
    dbt = dbtRunner()
    cli_args = ["run", "--select", model_name, *dbt_params()]
    res: dbtRunnerResult = dbt.invoke(cli_args)

    # inspect the results
    for r in res.result:
        print(f"{r.node.name}: {r.status}")


def write_schema(schema_payload: str):
    dest = os.path.join(MODEL_FOLDER, 'schema.yml')
    open(dest, 'w').write(schema_payload)


def write_model(model_name: str, model_payload: str):
    dest = os.path.join(MODEL_FOLDER, model_name + '.sql')
    open(dest, 'w').write(model_payload)