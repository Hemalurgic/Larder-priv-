"""Score a parser against evals/parser_cases.yaml.

    python -m evals.score_parser --parser keyword
    python -m evals.score_parser --parser oracle            # sanity check: must score 100%
    python -m evals.score_parser --parser llm:openrouter/<model-id> --repeats 3 [--out results.jsonl]

A case passes only if: core fields match exactly, no safety miss, no invented value,
and unmapped / conflict are flagged where expected.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import ValidationError

from schema.models import DIET_STRICTNESS, Diet, LifeStage, ParsedProfile, Profile

ROOT = Path(__file__).resolve().parents[1]
CORE = ["life_stage", "cycle_phase", "diet", "focus", "meal", "exclude_allergens", "max_minutes"]
LISTS = {"focus", "exclude_allergens"}


def cases() -> list[dict]:
    return yaml.safe_load((ROOT / "evals" / "parser_cases.yaml").read_text())


def _norm(p: Profile) -> dict:
    d = p.model_dump(mode="json")
    return {k: (sorted(d[k]) if k in LISTS else d[k]) for k in CORE}


def score_case(case: dict, predicted: ParsedProfile | None) -> dict:
    exp_profile = Profile(**case.get("expect", {}))
    exp = _norm(exp_profile)
    out = {"id": case["id"], "cat": case["cat"], "text": case["text"]}
    if predicted is None:
        return {**out, "pass": False, "valid": False, "safety_miss": True, "invented": False,
                "exact": False, "unmapped_ok": False, "conflict_ok": False, "errors": ["invalid output"]}
    got = _norm(predicted)
    default = _norm(Profile())
    errors, safety, invented = [], [], []

    for k in CORE:
        if got[k] != exp[k]:
            errors.append(f"{k}: expected {exp[k]}, got {got[k]}")
            if k in LISTS:
                if set(got[k]) - set(exp[k]):
                    invented.append(f"{k}+{sorted(set(got[k]) - set(exp[k]))}")
            elif exp[k] == default[k]:
                invented.append(k)

    if exp_profile.life_stage == LifeStage.pregnant and predicted.life_stage != LifeStage.pregnant:
        safety.append("dropped pregnant")
    if DIET_STRICTNESS[predicted.diet] < DIET_STRICTNESS[exp_profile.diet]:
        safety.append(f"loosened diet {exp_profile.diet.value}->{predicted.diet.value}")
    missing_allergens = set(exp["exclude_allergens"]) - set(got["exclude_allergens"])
    if missing_allergens:
        safety.append(f"dropped allergens {sorted(missing_allergens)}")

    unmapped_ok = bool(predicted.unmapped) if case.get("unmapped") else True
    conflict_ok = bool(predicted.conflicts) if case.get("conflict") else True
    if not unmapped_ok:
        errors.append("should have reported unmapped")
    if not conflict_ok:
        errors.append("should have flagged a conflict")
    exact = all(got[k] == exp[k] for k in CORE)
    return {**out, "valid": True, "exact": exact, "safety_miss": bool(safety), "safety": safety,
            "invented": bool(invented), "invented_fields": invented, "unmapped_ok": unmapped_ok,
            "conflict_ok": conflict_ok, "spurious_unmapped": bool(predicted.unmapped) and not case.get("unmapped"),
            "pass": exact and not safety and not invented and unmapped_ok and conflict_ok, "errors": errors}


def get_parser(name: str):
    if name == "oracle":
        by_text = {c["text"]: c for c in cases()}

        def oracle(text):
            c = by_text[text]
            return ParsedProfile(**c.get("expect", {}), unmapped=["x"] if c.get("unmapped") else [],
                                 conflicts=["x"] if c.get("conflict") else []), {}
        return oracle
    if name == "keyword":
        from evals.keyword_parser import parse
        return lambda text: (parse(text), {})
    if name.startswith("llm:"):
        from generation.llm import parse_profile
        model = name.split(":", 1)[1]
        return lambda text: parse_profile(text, model)
    raise SystemExit(f"unknown parser {name}")


def run(parser_name: str, out_path: str | None = None, repeats: int = 1) -> dict:
    """repeats > 1: each case runs N times; it passes only if every run passes (catches inconsistency)."""
    parser = get_parser(parser_name)
    results = []
    for c in cases():
        runs = []
        for _ in range(repeats):
            t0 = time.time()
            try:
                pred, meta = parser(c["text"])
            except Exception as e:  # bad JSON, schema violation, provider error: scored as invalid
                pred, meta = None, {"error": str(e)[:200]}
            r = score_case(c, pred)
            r.update({"latency_s": round(time.time() - t0, 3), **(meta or {})})
            runs.append(r)
        worst = next((r for r in runs if not r["pass"]), runs[0])
        worst = dict(worst)
        worst["flaky"] = len({r["pass"] for r in runs}) > 1
        worst["cost_usd"] = sum((r.get("cost_usd") or 0) for r in runs)
        worst["latency_s"] = round(sum(r["latency_s"] for r in runs) / len(runs), 3)
        results.append(worst)
    if out_path:
        Path(out_path).write_text("\n".join(json.dumps(r) for r in results) + "\n")
    return summarise(parser_name, results)


def summarise(name: str, results: list[dict]) -> dict:
    n = len(results)
    s = {"parser": name, "cases": n,
         "pass": sum(r["pass"] for r in results),
         "exact_fields": sum(r["exact"] for r in results),
         "safety_misses": sum(r["safety_miss"] for r in results),
         "invented": sum(r["invented"] for r in results),
         "unmapped_missed": sum(not r["unmapped_ok"] for r in results),
         "conflicts_missed": sum(not r["conflict_ok"] for r in results),
         "invalid": sum(not r["valid"] for r in results),
         "flaky": sum(r.get("flaky", False) for r in results),
         "avg_latency_s": round(sum(r["latency_s"] for r in results) / n, 3),
         "cost_usd": round(sum(r.get("cost_usd", 0) or 0 for r in results), 4),
         "by_cat": {}, "failures": [r for r in results if not r["pass"]]}
    cat = defaultdict(lambda: [0, 0])
    for r in results:
        cat[r["cat"]][0] += r["pass"]
        cat[r["cat"]][1] += 1
    s["by_cat"] = {k: f"{v[0]}/{v[1]}" for k, v in cat.items()}
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--parser", default="keyword")
    ap.add_argument("--out")
    ap.add_argument("--show-failures", action="store_true")
    ap.add_argument("--repeats", type=int, default=1)
    a = ap.parse_args()
    s = run(a.parser, a.out, a.repeats)
    print(f"Parser {s['parser']}: {s['pass']}/{s['cases']} pass | safety misses {s['safety_misses']} (must be 0) | "
          f"invented {s['invented']} (must be 0) | unmapped missed {s['unmapped_missed']} | "
          f"conflicts missed {s['conflicts_missed']} | invalid {s['invalid']} | flaky {s['flaky']} | "
          f"avg latency {s['avg_latency_s']}s | cost ${s['cost_usd']}")
    print("  by category:", s["by_cat"])
    if a.show_failures:
        for r in s["failures"]:
            print(f"  {r['id']} [{r['cat']}] {r['text']!r}: {'; '.join(r.get('safety', []) + r['errors'])}")
    sys.exit(0 if s["safety_misses"] == 0 and s["invented"] == 0 else 1)
