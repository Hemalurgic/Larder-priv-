"""Golden-profile suite. Exit code 1 on any failure (wire into CI; it blocks publishing).

    python -m evals.run_golden                  # fixtures
    python -m evals.run_golden --library x.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from engine.search import search
from evals.common import load_library
from schema.models import Profile

ROOT = Path(__file__).resolve().parents[1]


def golden() -> list[dict]:
    return yaml.safe_load((ROOT / "evals" / "golden_profiles.yaml").read_text())


def run(library_path: str | None = None, cases: list[dict] | None = None) -> list[str]:
    library = load_library(library_path)
    failures = []
    for g in cases or golden():
        res = search(library, Profile(**g["profile"]), limit=1000, with_nutrition=False)
        got = {r["brief_id"] for r in res["results"]}
        for bad in sorted(set(g["must_not"]) & got):
            failures.append(f"{g['id']} {g['name']}: returned brief {bad} (must never return)")
        for missing in sorted(set(g["must"]) - got):
            why = next((e["excluded_by"] for e in res["excluded"] if e["brief_id"] == missing), ["filtered by meal/time"])
            failures.append(f"{g['id']} {g['name']}: missing brief {missing} ({'; '.join(why)})")
    return failures


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--library")
    args = ap.parse_args()
    fails = run(args.library)
    n = len(golden())
    bad = {f.split(" ")[0] for f in fails}
    print(f"Golden profiles: {n - len(bad)}/{n} passed")
    for f in fails:
        print("  FAIL", f)
    sys.exit(1 if fails else 0)
