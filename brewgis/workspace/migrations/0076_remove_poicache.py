"""Drop the never-written POI cache table and the never-called clamp function."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0075_remove_analysis_overrides"),
    ]

    operations = [
        migrations.DeleteModel(
            name="POICache",
        ),
        migrations.RunSQL(
            sql="DROP FUNCTION IF EXISTS public.clamp_non_negative(val double precision);",
            reverse_sql="""
                CREATE OR REPLACE FUNCTION public.clamp_non_negative(val double precision)
                  RETURNS double precision
                  LANGUAGE sql IMMUTABLE PARALLEL SAFE
                  AS $$ SELECT GREATEST(0.0, $1) $$;
            """,
        ),
    ]
