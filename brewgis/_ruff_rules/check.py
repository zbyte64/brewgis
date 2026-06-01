#!/usr/bin/env python3
"""ruffian plugin: checks BrewGIS anti-patterns in Python source files.

Usage (direct)::

    python -m brewgis._ruff_rules.check file1.py file2.py ...

Usage (ruffian plugin — reads config from stdin)::

    cat config.json | python -m brewgis._ruff_rules.check file1.py ...

Config JSON (optional, read from stdin)::

    {"ruffian_version": "0.1.0", "config": {}}

Output: JSON array of violations to stdout (empty array = clean).

Exit code: 0 always (violations communicated via JSON).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_RUFF_RULES_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _RUFF_RULES_DIR.parent.parent  # brewgis/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from brewgis._ruff_rules.rules import check_file  # noqa: E402


def main() -> None:
    """Entry point for ruffian plugin.

    Reads optional JSON config from stdin, processes file paths from
    argv[1:], and writes JSON violations to stdout.
    """
    # Consume stdin config if provided (ruffian sends it)
    stdin_config_raw: str | None = None
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                json.loads(raw)  # validate JSON, ignore contents for now
    except (json.JSONDecodeError, OSError):
        pass  # no valid config — fine

    files = sys.argv[1:]
    if not files:
        sys.stdout.write("[]\n")
        return

    all_violations: list[dict] = []

    for filepath in files:
        p = Path(filepath)
        if not p.exists():
            continue
        if p.is_dir():
            for py_file in p.rglob("*.py"):
                # Skip migrations and dbt models
                if "/migrations/" in py_file.as_posix() or "/dbt_project/" in py_file.as_posix():
                    continue
                _check_one(py_file, all_violations)
        elif p.suffix == ".py":
            _check_one(p, all_violations)

    sys.stdout.write(json.dumps(all_violations, indent=2))
    sys.stdout.write("\n")


def _check_one(p: Path, violations: list[dict]) -> None:
    """Check a single file and append any violations."""
    try:
        v = check_file(str(p))
        violations.extend(v)
    except SyntaxError:
        pass
    except Exception as exc:
        msg = f"[brewgis-antipatterns] Error checking {p}: {exc}"
        print(msg, file=sys.stderr)

        try:
            violations = check_file(str(p))
            all_violations.extend(violations)
        except SyntaxError:
            # Skip files with syntax errors — ruff handles those
            pass
        except Exception as exc:
            # Plugin failure — report to stderr, don't crash ruffian
            msg = f"[brewgis-antipatterns] Error checking {filepath}: {exc}"
            print(msg, file=sys.stderr)



if __name__ == "__main__":
    main()
