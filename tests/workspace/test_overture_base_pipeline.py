# ruff: noqa: ANN201, ANN206
"""Tests for Overture Base Theme — Land Cover & Land Use pipeline.

Covers:
  1. Classification mapping covers all known Overture subtypes
  2. Overture land use map covers all known subtypes
  3. Overture land cover map covers all ESA WorldCover subtypes
  4. All mapped categories are valid land_development_category values
"""

from __future__ import annotations

import csv
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────

_SEED_DIR = Path("brewgis/sqlmesh/seeds")

_VALID_CATEGORIES = frozenset(
    {
        "urban",
        "industrial",
        "agricultural",
        "undeveloped",
        "conservation",
    }
)

# Known Overture LandUseSubtype enum values (from Overture Maps schema)
_ALL_LAND_USE_SUBTYPES = frozenset(
    {
        "agriculture",
        "aquaculture",
        "horticulture",
        "residential",
        "developed",
        "education",
        "medical",
        "religious",
        "entertainment",
        "recreation",
        "golf",
        "cemetery",
        "industrial",
        "resource_extraction",
        "landfill",
        "military",
        "construction",
        "park",
        "protected",
        "grass",
        "managed",
        "campground",
        "transportation",
        "pedestrian",
        "winter_sports",
    }
)

# Known ESA WorldCover subtype values (from Overture Maps schema)
_ALL_LAND_COVER_SUBTYPES = frozenset(
    {
        "barren",
        "crop",
        "forest",
        "grass",
        "mangrove",
        "moss",
        "shrub",
        "snow",
        "urban",
        "wetland",
    }
)


# ── Helpers ─────────────────────────────────────────────────────────


def _load_seed_csv(filename: str) -> list[dict[str, str]]:
    """Load a seed CSV and return rows as dicts (all values stripped)."""
    path = _SEED_DIR / filename
    if not path.exists():
        msg = f"Seed file not found: {path}"
        raise FileNotFoundError(msg)
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: v.strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _subtypes_in_csv(rows: list[dict[str, str]]) -> set[str]:
    """Return the set of non-empty subtype values from rows."""
    return {r["subtype"] for r in rows if r.get("subtype")}


def _classes_by_subtype(rows: list[dict[str, str]]) -> dict[str, set[str]]:
    """Return a dict mapping subtype → set of class values (including None)."""
    result: dict[str, set[str]] = {}
    for r in rows:
        sub = r.get("subtype", "")
        cls = r.get("class", "").strip() or None
        result.setdefault(sub, set()).add(cls)
    return result


def _category_for(
    rows: list[dict[str, str]], subtype: str, class_: str | None = None
) -> str | None:
    """Look up category for subtype + optional class.

    Class-level override takes precedence; falls back to subtype-level default
    (class is None/empty in CSV).
    """
    for r in rows:
        if r["subtype"] == subtype:
            csv_class = r.get("class", "").strip()
            if class_ is not None and csv_class == class_:
                return r.get("category", "").strip()
            if class_ is None and (not csv_class):
                return r.get("category", "").strip()
    return None


# ════════════════════════════════════════════════════════════════════
#  Land Use Map Tests
# ════════════════════════════════════════════════════════════════════


class TestLandUseMapCompleteness:
    """Every known Overture LandUseSubtype must have a default mapping."""

    LU_ROWS: list[dict[str, str]] = []

    @classmethod
    def setup_class(cls):
        cls.LU_ROWS = _load_seed_csv("overture_land_use_map.csv")

    def test_all_subtypes_have_default_mapping(self):
        """Every known subtype must have at least one row with no class (default)."""
        default_subtypes = {
            r["subtype"] for r in self.LU_ROWS if not r.get("class", "").strip()
        }
        missing = _ALL_LAND_USE_SUBTYPES - default_subtypes
        assert not missing, (
            f"Missing default (class=NULL) mapping for subtypes: {sorted(missing)}"
        )

    def test_all_default_categories_are_valid(self):
        """Subtype-level default categories must be valid."""
        for r in self.LU_ROWS:
            if not r.get("class", "").strip():
                assert r["category"] in _VALID_CATEGORIES, (
                    f"Subtype {r['subtype']!r} has invalid default category "
                    f"{r['category']!r}"
                )

    def test_all_class_overrides_have_valid_categories(self):
        """Class-level overrides must have valid categories."""
        for r in self.LU_ROWS:
            csv_class = r.get("class", "").strip()
            if csv_class:
                assert r["category"] in _VALID_CATEGORIES, (
                    f"Subtype {r['subtype']!r} class {csv_class!r} has "
                    f"invalid category {r['category']!r}"
                )

    def test_no_unknown_subtypes_in_csv(self):
        """Subtypes in the CSV that we don't know about should be flagged."""
        csv_subtypes = _subtypes_in_csv(self.LU_ROWS)
        unknown = csv_subtypes - _ALL_LAND_USE_SUBTYPES
        assert not unknown, f"CSV contains unknown subtypes: {sorted(unknown)}"

    def test_no_duplicate_default_mappings(self):
        """Each subtype should have exactly one default (class=NULL) row."""
        defaults: dict[str, int] = {}
        for r in self.LU_ROWS:
            if not r.get("class", "").strip():
                defaults[r["subtype"]] = defaults.get(r["subtype"], 0) + 1
        dupes = {k: v for k, v in defaults.items() if v > 1}
        assert not dupes, f"Subtypes with multiple default mappings: {dupes}"

    def test_lookup_examples(self):
        """Spot-check a few category lookups."""
        rows = self.LU_ROWS

        # Subtype defaults
        assert _category_for(rows, "residential") == "urban"
        assert _category_for(rows, "industrial") == "industrial"
        assert _category_for(rows, "agriculture") == "agricultural"
        assert _category_for(rows, "park") == "undeveloped"
        assert _category_for(rows, "military") == "industrial"

        # Class-level overrides
        assert _category_for(rows, "developed", "commercial") == "urban"
        assert _category_for(rows, "transportation", "airport") == "industrial"
        assert _category_for(rows, "transportation", "port") == "industrial"
        assert _category_for(rows, "protected", "conservation") == "conservation"


# ════════════════════════════════════════════════════════════════════
#  Land Cover Map Tests
# ════════════════════════════════════════════════════════════════════


class TestLandCoverMapCompleteness:
    """Every known ESA WorldCover subtype must have a mapping."""

    LC_ROWS: list[dict[str, str]] = []

    @classmethod
    def setup_class(cls):
        cls.LC_ROWS = _load_seed_csv("overture_land_cover_map.csv")

    def test_all_subtypes_have_mapping(self):
        """Every known land cover subtype must be mapped."""
        mapped = _subtypes_in_csv(self.LC_ROWS)
        missing = _ALL_LAND_COVER_SUBTYPES - mapped
        assert not missing, (
            f"Missing mappings for land cover subtypes: {sorted(missing)}"
        )

    def test_all_categories_are_valid(self):
        """All land cover categories must be valid."""
        for r in self.LC_ROWS:
            assert r["category"] in _VALID_CATEGORIES, (
                f"Subtype {r['subtype']!r} has invalid category {r['category']!r}"
            )

    def test_no_unknown_subtypes(self):
        """Land cover CSV must not contain unknown subtypes."""
        csv_subtypes = _subtypes_in_csv(self.LC_ROWS)
        unknown = csv_subtypes - _ALL_LAND_COVER_SUBTYPES
        assert not unknown, f"CSV contains unknown subtypes: {sorted(unknown)}"

    def test_lookup_examples(self):
        """Spot-check a few land cover lookups."""
        rows = self.LC_ROWS
        assert _category_for(rows, "forest") == "conservation"
        assert _category_for(rows, "crop") == "agricultural"
        assert _category_for(rows, "urban") == "urban"
        assert _category_for(rows, "grass") == "undeveloped"
        assert _category_for(rows, "barren") == "undeveloped"


# ════════════════════════════════════════════════════════════════════
#  Land Use Map Data Quality
# ════════════════════════════════════════════════════════════════════


class TestLandUseMapDataQuality:
    """Additional quality checks on the land use mapping seed data."""

    LU_ROWS: list[dict[str, str]] = []

    @classmethod
    def setup_class(cls):
        cls.LU_ROWS = _load_seed_csv("overture_land_use_map.csv")

    def test_no_empty_category(self):
        """No row should have an empty category."""
        for r in self.LU_ROWS:
            assert r.get("category", "").strip(), (
                f"Row has empty category: subtype={r['subtype']!r}, "
                f"class={r.get('class', '')!r}"
            )

    def test_no_empty_subtype(self):
        """No row should have an empty subtype."""
        for r in self.LU_ROWS:
            assert r.get("subtype", "").strip(), "Row has empty subtype"

    def test_all_known_classes_match_subtypes(self):
        """Class-level rows should have a matching subtype default."""
        by_subtype = _classes_by_subtype(self.LU_ROWS)
        for subtype, classes in by_subtype.items():
            # Verify NULL (default) exists for this subtype
            assert None in classes, (
                f"Subtype {subtype!r} has class overrides but no default mapping"
            )


# ════════════════════════════════════════════════════════════════════
#  Land Cover Map Data Quality
# ════════════════════════════════════════════════════════════════════


class TestLandCoverMapDataQuality:
    """Additional quality checks on the land cover mapping seed data."""

    LC_ROWS: list[dict[str, str]] = []

    @classmethod
    def setup_class(cls):
        cls.LC_ROWS = _load_seed_csv("overture_land_cover_map.csv")

    def test_no_empty_category(self):
        """No row should have an empty category."""
        for r in self.LC_ROWS:
            assert r.get("category", "").strip(), (
                f"Row has empty category: subtype={r['subtype']!r}"
            )

    def test_no_empty_subtype(self):
        """No row should have an empty subtype."""
        for r in self.LC_ROWS:
            assert r.get("subtype", "").strip(), "Row has empty subtype"


# ════════════════════════════════════════════════════════════════════

#  Integration — Seed Data Consistency
# ════════════════════════════════════════════════════════════════════


class TestSeedDataConsistency:
    """Cross-cutting checks between seed files."""

    def test_categories_are_mutually_exclusive(self):
        """All categories in both maps should be from the valid set."""
        lu_rows = _load_seed_csv("overture_land_use_map.csv")
        lc_rows = _load_seed_csv("overture_land_cover_map.csv")
        all_cats = {r["category"] for r in lu_rows} | {r["category"] for r in lc_rows}
        unknown = all_cats - _VALID_CATEGORIES
        assert not unknown, f"Unknown categories across seed files: {sorted(unknown)}"
