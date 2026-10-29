"""Shared loaders for the eval runners."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from schema.models import Brief, Recipe

ROOT = Path(__file__).resolve().parents[1]


def briefs() -> list[Brief]:
    return [Brief(**b) for b in yaml.safe_load((ROOT / "data" / "briefs.yaml").read_text())]


def load_library(path: str | None = None) -> list[Recipe]:
    """Fixtures by default; pass a JSONL of generated recipes once round 1 has run."""
    if path is None:
        rows = yaml.safe_load((ROOT / "data" / "fixture_recipes.yaml").read_text())
        return [Recipe(**r, fixture=True) for r in rows]
    return [Recipe(**json.loads(line)) for line in Path(path).read_text().splitlines() if line.strip()]
