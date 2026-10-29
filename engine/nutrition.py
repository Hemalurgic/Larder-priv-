"""Deterministic nutrition calculation from CoFID. No model is involved.

Known limits (POC):
- Recipe grams are pre-cooking edible weights; values are summed from raw CoFID entries.
- No retention factors yet (folate and vitamin C fall with cooking), so those are upper bounds.
- Per-100 g figures use raw total weight unless the recipe gives `yield_factor`
  (cooked weight / raw weight). Claims on raw basis are marked provisional.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from engine import cofid
from schema.models import Recipe

ROOT = Path(__file__).resolve().parents[1]
NEGLIGIBLE_SHARE = 0.02  # a missing value from an ingredient under 2% of recipe weight doesn't block claims
FIELDS = ["energy_kcal", "protein_g", "fat_g", "carbohydrate_g", "sugars_g", "fibre_g",
          "iron_mg", "magnesium_mg", "folate_ug", "vitamin_c_mg", "sodium_mg"]


@lru_cache
def mapping() -> dict:
    return yaml.safe_load((ROOT / "data" / "cofid_map.yaml").read_text())


@lru_cache
def claim_rules() -> dict:
    return yaml.safe_load((ROOT / "rules" / "gb_v0.yaml").read_text())["claims"]


def compute(recipe: Recipe, yield_factor: float | None = None) -> dict:
    foods = cofid.load()
    totals = {f: 0.0 for f in FIELDS}
    incomplete = {f: [] for f in FIELDS}
    negligible = {f: [] for f in FIELDS}
    proxies, gaps = [], []
    raw_weight = sum(i.grams for i in recipe.ingredients)

    def missing(f, ing, m):
        share = ing.grams * m.get("scale", 1.0) / raw_weight
        (negligible if share < NEGLIGIBLE_SHARE else incomplete)[f].append(ing.food)

    for ing in recipe.ingredients:
        m = mapping().get(ing.food, {"match": "gap"})
        if m["match"] == "gap":
            gaps.append(ing.food)
            for f in FIELDS:
                missing(f, ing, m)
            continue
        if m["match"] == "proxy":
            proxies.append(ing.food)
        row = foods[m["code"]]
        factor = ing.grams / 100 * m.get("scale", 1.0)
        for f in FIELDS:
            v = row.get(f)
            if v is None:
                missing(f, ing, m)
            else:
                totals[f] += v * factor

    weight = raw_weight * (yield_factor or 1.0)
    per_serving = {f: round(v / recipe.servings, 2) for f, v in totals.items()}
    per_100g = {f: round(v / weight * 100, 2) for f, v in totals.items()}
    return {
        "per_serving": per_serving,
        "per_100g": per_100g,
        "basis": "cooked_weight" if yield_factor else "raw_weight_provisional",
        "incomplete": {f: v for f, v in incomplete.items() if v},
        "negligible_missing": {f: v for f, v in negligible.items() if v},
        "proxies": proxies,
        "gaps": gaps,
        "claims": claims(per_100g, incomplete),
    }


def claims(per_100g: dict, incomplete: dict) -> list[str]:
    """Claim flags that pass. A nutrient with missing contributors never earns a claim."""
    c = claim_rules()
    out = []
    for nutrient, ri in c["reference_intakes"].items():
        if incomplete.get(nutrient):
            continue
        pct = per_100g[nutrient] / ri * 100
        name = nutrient.split("_")[0]
        if pct >= c["high_in_pct"]:
            out.append(f"high_in_{name}")
        elif pct >= c["source_of_pct"]:
            out.append(f"source_of_{name}")
    kcal = per_100g["energy_kcal"]
    if kcal and not incomplete.get("protein_g") and not incomplete.get("energy_kcal"):
        pe = per_100g["protein_g"] * 4 / kcal * 100
        if pe >= c["protein_energy_pct"]["high_in"]:
            out.append("high_in_protein")
        elif pe >= c["protein_energy_pct"]["source_of"]:
            out.append("source_of_protein")
    return out
