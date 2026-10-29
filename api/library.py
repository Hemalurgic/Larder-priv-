"""The served library and the search the GraphQL layer calls.

Every keep-or-drop decision about a profile goes through engine.search (and so the rules engine).
This module only adds the Suggestic-style filters on top: keyword, nutrient ranges, meal tags,
image and instructions. Nutrition and per-diet verdicts are worked out once at start-up.

Library source: data/fixture_recipes.yaml by default, or a round's recipes.jsonl via LARDER_LIBRARY.
"""
from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass, field
from functools import lru_cache

from engine.catalogue import catalogue, structural_issues
from engine.nutrition import compute
from engine.rules import evaluate, pack
from engine.search import _score
from engine.search import search as engine_search
from evals.common import load_library
from schema.models import DIET_STRICTNESS, Diet, Profile, Recipe

# Suggestic field name -> our nutrition field
NUTRIENTS = {
    "calories": "energy_kcal", "protein": "protein_g", "carbs": "carbohydrate_g", "fat": "fat_g",
    "fiber": "fibre_g", "sugar": "sugars_g", "sodium": "sodium_mg",
}


@dataclass(frozen=True)
class Entry:
    recipe: Recipe
    nutrition: dict
    diets: frozenset[Diet]      # diets the rules engine allows this recipe for


@lru_cache
def library() -> dict[str, Entry]:
    """Recipes that pass the structural checks. Anything else is never served (fail closed)."""
    out = {}
    for r in load_library(os.environ.get("LARDER_LIBRARY") or None):
        if structural_issues(r):
            continue
        diets = frozenset(d for d in Diet if evaluate(r, Profile(diet=d)).allowed)
        out[r.id] = Entry(r, compute(r), diets)
    return out


# ---------- IDs and cursors ----------

def global_id(recipe_id: str) -> str:
    return base64.b64encode(f"Recipe:{recipe_id}".encode()).decode()


def local_id(gid: str) -> str | None:
    try:
        kind, _, rid = base64.b64decode(gid, validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return rid if kind == "Recipe" and rid else None


def cursor(offset: int) -> str:
    return base64.b64encode(f"offset:{offset}".encode()).decode()


def offset_after(after: str | None) -> int:
    if after is None:
        return 0
    try:
        kind, _, n = base64.b64decode(after, validate=True).decode().partition(":")
        if kind == "offset" and n.isdigit():
            return int(n) + 1
    except (binascii.Error, UnicodeDecodeError):
        pass
    raise ValueError("Invalid cursor. Pass the endCursor from the previous page as `after`.")


# ---------- Display helpers ----------

def ingredient_name(key: str) -> str:
    return catalogue()[key].get("name") or key.replace("_", " ")


def ingredient_line(ing) -> str:
    line = f"{ing.grams:g} g {ingredient_name(ing.food)}"
    return f"{line}, {ing.note}" if ing.note else line


def nutrients_per_serving(entry: Entry) -> dict:
    per = entry.nutrition["per_serving"]
    return {k: per[v] for k, v in NUTRIENTS.items()}


def incomplete_nutrients(entry: Entry) -> list[str]:
    inc = entry.nutrition["incomplete"]
    return [k for k, v in NUTRIENTS.items() if v in inc]


# ---------- Search ----------

@dataclass
class TextClause:
    name: str | None = None
    ingredients: list[str] = field(default_factory=list)

    def matches(self, r: Recipe) -> bool:
        if self.name and self.name.lower() not in r.title.lower():
            return False
        # every listed ingredient must appear, matched on catalogue key or display name
        haystack = [f"{i.food} {ingredient_name(i.food)}".lower() for i in r.ingredients]
        return all(any(term.lower() in h for h in haystack) for term in self.ingredients)


@dataclass
class Range:
    gte: float | None = None
    lte: float | None = None


def stricter(a: Diet, b: Diet | None) -> Diet:
    return b if b is not None and DIET_STRICTNESS[b] > DIET_STRICTNESS[a] else a


def search(profile: Profile, *, should: list[TextClause] = (), must: list[TextClause] = (),
           ranges: dict[str, Range] | None = None, tags: list[str] | None = None,
           has_image: bool | None = None, has_instructions: bool | None = None,
           is_premium: bool | None = None) -> tuple[list[tuple[Entry, dict]], str]:
    """Returns (entry, engine result) pairs in rank order, and the rule pack version."""
    lib = library()
    if is_premium:              # Larder has no premium tier
        return [], rule_pack()
    res = engine_search(list(e.recipe for e in lib.values()), profile, limit=len(lib), with_nutrition=False)
    meal_tags = {t.lower() for t in tags} if tags else None
    out = []
    for hit in res["results"]:
        e = lib[hit["id"]]
        r = e.recipe
        if should and not any(c.matches(r) for c in should):
            continue
        if not all(c.matches(r) for c in must):
            continue
        if meal_tags is not None and r.meal.value not in meal_tags:
            continue
        if has_image is not None and bool(r.image) != has_image:
            continue
        if has_instructions is not None and bool(r.steps) != has_instructions:
            continue
        if ranges and not _in_ranges(e, ranges):
            continue
        out.append((e, hit))
    if profile.focus:  # engine_search ran without nutrition, so rank here from the cached values
        out.sort(key=lambda p: -_focus_score(p[0], profile))
    return out, rule_pack()


def _in_ranges(e: Entry, ranges: dict[str, Range]) -> bool:
    per = nutrients_per_serving(e)
    incomplete = set(incomplete_nutrients(e))
    for name, rg in ranges.items():
        v = per[name]
        if rg.gte is not None and v < rg.gte:
            return False
        if rg.lte is not None:
            # missing data can only make the true value higher, so an upper bound can't be confirmed
            if name in incomplete or v > rg.lte:
                return False
    return True


def _focus_score(e: Entry, profile: Profile) -> float:
    return _score(e.recipe, profile, e.nutrition)


def rule_pack() -> str:
    p = pack()
    return f"{p['pack']}@{p['version']}"
