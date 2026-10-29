"""Search: filter the library by profile, then rank. What the API's /recipes/search will call."""
from __future__ import annotations

from engine.catalogue import recipe_tags
from engine.nutrition import claim_rules, compute
from engine.rules import evaluate
from schema.models import Diet, Profile, Recipe

PROTEIN_REF_G = 50  # reference intake used only for ranking, not claims


def _score(recipe: Recipe, profile: Profile, nut: dict) -> float:
    if not profile.focus:
        return 0.0
    ri = claim_rules()["reference_intakes"]
    per = nut["per_serving"]
    score = 0.0
    for f in profile.focus:
        if f.value == "protein":
            score += per["protein_g"] / PROTEIN_REF_G
        else:
            key = {"iron": "iron_mg", "magnesium": "magnesium_mg", "folate": "folate_ug"}[f.value]
            score += per[key] / ri[key]
    tags = recipe_tags(recipe)
    if any(f.value == "iron" for f in profile.focus):
        if profile.diet in (Diet.vegetarian, Diet.vegan) and "vit_c_source" in tags:
            score *= 1.15   # vitamin C helps non-haem iron absorption
        if "tea_coffee" in tags:
            score *= 0.85   # tannins reduce it
    return round(score, 4)


def search(library: list[Recipe], profile: Profile, limit: int = 10, with_nutrition: bool = True) -> dict:
    results, excluded = [], []
    for r in library:
        if profile.meal and r.meal != profile.meal:
            continue
        if profile.max_minutes and r.total_minutes > profile.max_minutes:
            continue
        v = evaluate(r, profile)
        if not v.allowed:
            excluded.append({"id": r.id, "brief_id": r.brief_id, "excluded_by": v.excluded_by})
            continue
        nut = compute(r) if with_nutrition else None
        results.append({
            "id": r.id, "brief_id": r.brief_id, "title": r.title,
            "score": _score(r, profile, nut) if nut else 0.0,
            "allergens": v.allergens, "notes": v.notes, "rules_applied": v.applied,
            "caffeine_mg": v.caffeine_mg, "claims": nut["claims"] if nut else [],
            "nutrition_basis": nut["basis"] if nut else None,
        })
    results.sort(key=lambda x: -x["score"])
    return {"rule_pack": evaluate(library[0], profile).rule_pack if library else None,
            "results": results[:limit], "excluded": excluded}
