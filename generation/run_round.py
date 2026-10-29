"""Run a recipe test round: briefs x models x templates -> logged attempts, a recipe library,
automated gate results and a review sheet.

    python -m generation.run_round --round 1 --half A \
        --models anthropic/<model-a>,openai/<model-b>,gemini/<model-c> --templates A,B \
        --critic <critic-model>

Writes to runs/round<N>/:
    attempts.jsonl   every model call (prompt template version, tokens, cost, latency, raw output)
    recipes.jsonl    recipes that passed schema + structural checks (feed to the evals with --library)
    gates.jsonl      per-recipe gate results: schema, structural, rules outcome, nutrition, critic issues
    review.csv       one row per recipe for BLIND human review (rubric columns + timer), shuffled
    review_key.csv   review code -> recipe, model, template (don't share with reviewers)
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pydantic import ValidationError

from engine.catalogue import catalogue, structural_issues
from engine.nutrition import compute
from evals.common import ROOT, briefs
from evals.matrix_check import outcome
from generation.llm import critique, generate_recipe as _generate


def generate_recipe(brief, model, tpl, keys):
    """model "fixture" replays the fixture skeletons: exercises the whole pipeline without API keys."""
    if model == "fixture":
        from evals.common import load_library
        fx = next(r for r in load_library() if r.brief_id == brief.id)
        data = fx.model_dump(mode="json", exclude={"id", "brief_id", "fixture"})
        data["unlisted_ingredients"] = []
        return data, {"model": "fixture", "template": tpl, "cost_usd": 0, "latency_s": 0}
    return _generate(brief, model, tpl, keys)
from schema.models import Recipe

# Blind review: reviewers see a random code, never the model or template. The key is kept separately.
REVIEW_COLUMNS = ["review_code", "brief_id", "title", "reviewer",
                  "follows_brief (P/F)", "safe_method (P/F)", "cookable (1-5)", "appeal (1-5)",
                  "clarity (1-5)", "edits (none/minor/major/reject)", "minutes_spent",
                  "changed_ingredients (Y/N)", "notes"]


def slug(model: str) -> str:
    return model.split("/")[-1].replace(".", "-")[:24]


def run(round_no: int, half: str, models: list[str], templates: list[str], critic_model: str | None):
    out = ROOT / "runs" / f"round{round_no}"
    out.mkdir(parents=True, exist_ok=True)
    keys = sorted(catalogue())
    chosen = [b for b in briefs() if half == "all" or b.half == half]
    with open(out / "attempts.jsonl", "a") as att, open(out / "recipes.jsonl", "a") as rec, \
            open(out / "gates.jsonl", "a") as gates:
        rows = []
        for b in chosen:
            for model in models:
                for tpl in templates:
                    rid = f"b{b.id:02d}-r{round_no}-{slug(model)}-{tpl}"
                    gate = {"recipe_id": rid, "brief_id": b.id, "model": model, "template": tpl}
                    try:
                        data, meta = generate_recipe(b, model, tpl, keys)
                    except Exception as e:  # network, JSON, provider errors: logged, not fatal
                        att.write(json.dumps({**gate, "error": repr(e)[:300]}) + "\n")
                        gate["schema"] = "fail: call or JSON error"
                        gates.write(json.dumps(gate) + "\n")
                        continue
                    att.write(json.dumps({**gate, **meta}) + "\n")
                    unlisted = data.pop("unlisted_ingredients", [])
                    try:
                        r = Recipe(id=rid, brief_id=b.id, **{k: v for k, v in data.items() if k in Recipe.model_fields})
                    except ValidationError as e:
                        gate["schema"] = f"fail: {e.errors()[0]['msg']}"
                        gates.write(json.dumps(gate) + "\n")
                        continue
                    gate["schema"] = "pass"
                    gate["unlisted_ingredients"] = unlisted
                    gate["structural"] = structural_issues(r) or "pass"
                    if gate["structural"] == "pass":
                        gate["pregnancy_outcome"] = outcome(r)
                        gate["pregnancy_expected"] = b.expected_pregnancy
                        n = compute(r)
                        gate["nutrition"] = {"per_serving": n["per_serving"], "claims": n["claims"],
                                             "gaps": n["gaps"], "proxies": n["proxies"]}
                    if critic_model:
                        try:
                            crit, cmeta = critique(b, data, critic_model)
                            att.write(json.dumps({**gate, "step": "critic", **cmeta}) + "\n")
                            gate["critic_issues"] = crit.get("issues", [])
                        except Exception as e:
                            gate["critic_issues"] = [{"check": "critic_error", "severity": "warn", "detail": repr(e)[:200]}]
                    gates.write(json.dumps(gate) + "\n")
                    rec.write(r.model_dump_json() + "\n")
                    rows.append({"recipe_id": rid, "brief_id": b.id, "title": r.title, "model": model, "template": tpl})
    import random
    import secrets
    random.shuffle(rows)  # no grouping by model in the sheet
    with open(out / "review.csv", "a", newline="") as f, open(out / "review_key.csv", "a", newline="") as k:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        kw = csv.DictWriter(k, fieldnames=["review_code", "recipe_id", "model", "template"])
        if f.tell() == 0:
            w.writeheader()
            kw.writeheader()
        for row in rows:
            code = secrets.token_hex(3)
            w.writerow({"review_code": code, "brief_id": row["brief_id"], "title": row["title"]})
            kw.writerow({"review_code": code, "recipe_id": row["recipe_id"], "model": row["model"], "template": row["template"]})
    print(f"Round {round_no}: {len(rows)} recipes written to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--half", default="A", choices=["A", "B", "all"])
    ap.add_argument("--models", required=True, help="comma-separated LiteLLM model names")
    ap.add_argument("--templates", default="A,B")
    ap.add_argument("--critic")
    a = ap.parse_args()
    run(a.round, a.half, a.models.split(","), a.templates.split(","), a.critic)
