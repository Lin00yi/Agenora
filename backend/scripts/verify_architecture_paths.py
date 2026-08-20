"""Fail CI when documented architecture entrypoints are renamed or removed."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "architecture-paths.json"


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(paths, list) or not paths:
        raise SystemExit("architecture-paths.json must contain a non-empty paths list")
    missing = [str(item) for item in paths if not (ROOT / str(item)).exists()]
    if missing:
        raise SystemExit("documented architecture paths are missing:\n" + "\n".join(missing))
    print(f"architecture paths verified: {len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
