"""Check every recipe's pregnancy outcome matches the matrix (success criterion: 30 of 30).

    python -m evals.matrix_check                 # fixtures
    python -m evals.matrix_check --library x.jsonl
"""
from __future__ import annotations

import argparse
import sys

from engine.rules import evaluate
from evals.common import briefs, load_library
from schema.models import Diet, LifeStage, Profile

PREG = Profile(life_stage=LifeStage.pregnant)
LIMIT_IDS = {"preg-tuna-limit", "preg-oily-fish-limit", "preg-caffeine"}


def outcome(recipe) -> str:
    v = evaluate(recipe, PREG)
    if not v.allowed:
        return "exclude"
    if set(v.applied) & LIMIT_IDS:
        return "limit"
    if v.conditional:
        return "conditional"
    return "safe"


def diet_ok(recipe, diet: Diet) -> bool:
    return evaluate(recipe, Profile(diet=diet)).allowed


def run(library_path: str | None = None) -> list[str]:
    by_brief = {b.id: b for b in briefs()}
    failures = []
    for r in load_library(library_path):
        b = by_brief[r.brief_id]
        got = outcome(r)
        if got != b.expected_pregnancy:
            failures.append(f"brief {b.id} {b.title}: pregnancy expected {b.expected_pregnancy}, got {got}")
        # diet: the dish must satisfy the brief's diet and nothing stricter-than-claimed slips through
        if not diet_ok(r, b.diet):
            failures.append(f"brief {b.id} {b.title}: fails its own diet ({b.diet.value})")
        stricter = {Diet.omnivore: [Diet.vegetarian, Diet.vegan], Diet.vegetarian: [Diet.vegan], Diet.vegan: []}[b.diet]
        for d in stricter:
            if diet_ok(r, d):
                failures.append(f"brief {b.id} {b.title}: passes {d.value} but brief says {b.diet.value} (check tags)")
    return failures


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--library")
    args = ap.parse_args()
    fails = run(args.library)
    n = len(load_library(args.library))
    print(f"Matrix check: {n - len({f.split(':')[0] for f in fails})}/{n} recipes clean")
    for f in fails:
        print("  FAIL", f)
    sys.exit(1 if fails else 0)
