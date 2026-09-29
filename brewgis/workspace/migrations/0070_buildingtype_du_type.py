"""Replace the blended trip rate with UrbanFootprint's per-activity trip model.

Three changes to ``BuildingType``:

- ``du_type`` (new) names the housing class the dwelling units belong to, which
  is what selects the residential trip rate. The vocabulary is SACOG's
  (``public.sacog_building_types_may14`` declares exactly one non-zero dwelling
  unit density column per built form), which UrbanFootprint's three trip classes
  fold together.
- ``trip_rate_override`` (dropped) was a single blended trips-per-unit rate with
  no default: 88 of 97 built forms in a live workspace carried ``0``, which the
  trip model could not tell apart from "unset" and silently turned into zero
  residential trips. Its nine populated rows (3.0-9.5 trips/unit) are what
  ``du_type`` now supplies from UrbanFootprint's rates (3.0-9.57).
- ``pass_by_trip_pct`` (dropped) reduced non-residential trips by a percentage
  of total floor area. UrbanFootprint has no pass-by term, and the reduction was
  being applied to residential floor area as well as commercial.

The data backfill classifies existing rows by name. It is an explicit table
rather than an import of ``built_forms.default_library`` because a migration
must not move when the library does; the values were read off SACOG's catalogue
(``single_family_large_lot_density`` → ``detsf_ll``, and so on), falling back to
the built form's own name and storey count where the catalogue has no row. A
form that houses people but that this table does not name keeps a blank
``du_type``, which the trip generation model audits on rather than guessing a
rate for.
"""

from __future__ import annotations

from django.db import migrations
from django.db import models

DU_TYPES = (
    ("detsf_ll", "Single-family detached, large lot"),
    ("detsf_sl", "Single-family detached, small lot"),
    ("attsf", "Attached single-family"),
    ("mf2to4", "Multifamily, 2-4 units"),
    ("mf5p", "Multifamily, 5+ units"),
)

# Built forms that hold dwelling units, by name, as classified at migration
# time. Sourced from SACOG's `sacog_building_types_may14` where that catalogue
# defines the form, and from the form's own name and storey count otherwise.
DU_TYPE_BY_NAME: dict[str, str] = {
    # ── SACOG catalogue, via its non-zero dwelling unit density column ──
    "Farm Home": "detsf_ll",
    "LARGE LOT NOT FARM HOME": "detsf_ll",
    "Low Density Detached Residential": "detsf_ll",
    "Rural Residential": "detsf_ll",
    "Very Low Density Detached Residential": "detsf_ll",
    "Medium Density Detached Residential": "detsf_sl",
    "Medium-High Density Detached Residential": "detsf_sl",
    "Mobile Home Park": "detsf_sl",
    "Medium-High Density Attached Residential": "attsf",
    "Medium Density Attached Residential": "mf2to4",
    "High Density Attached Residential": "mf5p",
    "Very High Density Attached Residential": "mf5p",
    "Urban Attached Residential": "mf5p",
    "Urban Mid-Rise Residential": "mf5p",
    "High-Rise Mixed Use": "mf5p",
    "Mid-Rise Mixed Use": "mf5p",
    "Residential/Retail Mixed Use High": "mf5p",
    "Residential/Retail Mixed Use Low": "mf5p",
    # ── No catalogue row: classified from the form's own name and massing ──
    "Single-Family Detached - Large Lot": "detsf_ll",
    "Single-Family Detached - Standard": "detsf_sl",
    "Single-Family Attached (Townhouse)": "attsf",
    "Duplex / Two-Flat": "mf2to4",
    "Triplex / Fourplex": "mf2to4",
    "Courtyard Apartment": "mf5p",
    "Stacked Flats": "mf5p",
    "Mid-Rise Apartment (5-9 Stories)": "mf5p",
    "High-Rise Apartment (10+ Stories)": "mf5p",
    # The canvas ETL's mixed-use placeholder, mid-density (8 DU/acre against
    # 12 jobs/acre); SACOG files its equivalent catalogue forms under mf5p.
    "Mixed Use": "mf5p",
    # SACOG's UC DAVIS declares employment only; the workspace's own 1.5
    # DU/acre is campus housing.
    "UC DAVIS": "mf5p",
}


def classify_du_types(apps, schema_editor) -> None:  # noqa: ANN001, ARG001
    """Set ``du_type`` on every existing built form the table above names."""
    BuildingType = apps.get_model("workspace", "BuildingType")
    for name, du_type in DU_TYPE_BY_NAME.items():
        BuildingType.objects.filter(name=name, du_per_acre__gt=0).update(du_type=du_type)


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0069_analysisrun_heartbeat_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="buildingtype",
            name="du_type",
            field=models.CharField(
                blank=True,
                choices=DU_TYPES,
                default="",
                help_text=(
                    "Housing class the dwelling units belong to. Selects the "
                    "residential trip rate (see built_forms.trip_rates); blank "
                    "means the type has no dwelling units."
                ),
                max_length=16,
                verbose_name="Dwelling unit type",
            ),
        ),
        migrations.RunPython(classify_du_types, migrations.RunPython.noop),
        migrations.RemoveField(model_name="buildingtype", name="trip_rate_override"),
        migrations.RemoveField(model_name="buildingtype", name="pass_by_trip_pct"),
    ]
