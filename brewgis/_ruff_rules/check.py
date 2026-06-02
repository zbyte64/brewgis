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
import sys
from pathlib import Path

_RUFF_RULES_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _RUFF_RULES_DIR.parent.parent  # brewgis/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from brewgis._ruff_rules.rules import check_file  # noqa: E402


def _collect_files(args: list[str]) -> list[Path]:
    """Resolve file paths from CLI args, expanding directories recursively."""
    files: list[Path] = []
    for filepath in args:
        p = Path(filepath)
        if not p.exists():
            continue
        if p.is_dir():
            for py_file in p.rglob("*.py"):
                if (
                    "/migrations/" in py_file.as_posix()
                    or "/target/" in py_file.as_posix()
                ):
                    continue
                files.append(py_file)
        elif p.suffix == ".py":
            files.append(p)
    return files


def main() -> None:
    """Entry point: reads JSON config from stdin, checks files, writes violations."""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                json.loads(raw)  # validate JSON, ignore contents
    except (json.JSONDecodeError, OSError):
        pass  # no valid config

    py_files = _collect_files(sys.argv[1:])
    if not py_files:
        sys.stdout.write("[]\n")
        return

    all_violations: list[dict] = []
    for py_file in py_files:
        _check_one(py_file, all_violations)

    sys.stdout.write(json.dumps(all_violations, indent=2))
    sys.stdout.write("\n")


def _check_one(p: Path, violations: list[dict]) -> None:
    """Check a single file and append any violations."""
    try:
        v = check_file(str(p))
        violations.extend(v)
    except SyntaxError:
        pass
    except Exception as exc:  # noqa: BLE001
        msg = f"[brewgis-antipatterns] Error checking {p}: {exc}"
        print(msg, file=sys.stderr)  # noqa: T201


if __name__ == "__main__":
    main()
