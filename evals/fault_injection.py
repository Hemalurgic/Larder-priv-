"""Fault injection: plant known faults in good recipes and check the gates catch them.

Rules/structural faults must be caught 100%. Critic faults need the critic model and are
reported as PENDING until a model is configured (see generation/critic.py).

    python -m evals.fault_injection
"""
from __future__ import annotations

import sys

from engine.rules import evaluate
from evals.common import load_library
from schema.models import CookState, Profile, RecipeIngredient

PREG = {"life_stage": "pregnant"}


def _lib():
    return {r.brief_id: r for r in load_library()}


def swap(recipe, old, new):
    r = recipe.model_copy(deep=True)
    for i in r.ingredients:
        if i.food == old:
            i.food = new
    return r


def add(recipe, food, grams, state=None):
    r = recipe.model_copy(deep=True)
    r.ingredients.append(RecipeIngredient(food=food, grams=grams, state=state))
    return r


def set_state(recipe, food, state):
    r = recipe.model_copy(deep=True)
    for i in r.ingredients:
        if i.food == food:
            i.state = state
    return r


def faults():
    L = _lib()
    return [
        # (id, description, gate, mutated recipe, profiles that must now exclude it)
        ("F01", "Pasteurised feta swapped for unpasteurised", "rules", swap(L[28], "feta_pasteurised", "feta_unpasteurised"), [PREG]),
        ("F02", "Parmesan added to vegan chilli", "rules", add(L[21], "parmesan", 30), [{"diet": "vegetarian"}, {"diet": "vegan"}]),
        ("F03", "Honey added to vegan oats", "rules", add(L[2], "honey", 15), [{"diet": "vegan"}]),
        ("F04", "Sesame oil added to chicken traybake", "rules", add(L[27], "sesame_oil", 10), [{"exclude_allergens": ["sesame"]}]),
        ("F05", "Chicken left raw (cook-through dropped)", "rules", set_state(L[27], "chicken_thigh", CookState.raw), [PREG]),
        ("F06", "Cook state missing on chicken", "structural", set_state(L[27], "chicken_thigh", None), [PREG, {}]),
        ("F07", "Vegan curry paste swapped for standard (shrimp)", "rules", swap(L[23], "thai_green_curry_paste_vegan", "thai_green_curry_paste"), [{"diet": "vegan"}, {"exclude_allergens": ["crustaceans"]}]),
        ("F08", "British Lion eggs swapped for unmarked eggs, still runny", "rules", swap(L[1], "eggs_hen_lion", "eggs_hen"), [PREG]),
        ("F09", "Brie no longer heated", "rules", set_state(L[11], "brie", CookState.as_is), [PREG]),
        ("F10", "Salami served cold", "rules", set_state(L[16], "salami", CookState.as_is), [PREG]),
        ("F11", "Ingredient not in catalogue", "structural", add(L[10], "chorizo", 50, CookState.cooked_through), [{}]),
        ("F12", "Spinach multiplied by 10", "critic", None, []),
        ("F13", "Servings changed 2 -> 6 without changing quantities", "critic", None, []),
        ("F14", "Ingredient used in method but not listed", "critic", None, []),
    ]


def run():
    caught, missed, pending = [], [], []
    for fid, desc, gate, recipe, profiles in faults():
        if recipe is None:
            pending.append((fid, desc, gate))
            continue
        misses = [p for p in profiles if evaluate(recipe, Profile(**p)).allowed]
        (missed if misses else caught).append((fid, desc, gate, misses))
    return caught, missed, pending


if __name__ == "__main__":
    caught, missed, pending = run()
    tested = len(caught) + len(missed)
    print(f"Fault injection: {len(caught)}/{tested} rules/structural faults caught; {len(pending)} critic faults pending a model")
    for fid, desc, gate, misses in missed:
        print(f"  MISSED {fid} [{gate}] {desc} -> still allowed for {misses}")
    for fid, desc, gate in pending:
        print(f"  PENDING {fid} [{gate}] {desc}")
    sys.exit(1 if missed else 0)
