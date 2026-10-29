"""Ingredient catalogue: tags, allergens and the structural checks that run before rules."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from schema.models import Allergen, Recipe

ROOT = Path(__file__).resolve().parents[1]

# Ingredients with these tags must say how they're cooked, because pregnancy rules depend on it.
STATE_REQUIRED_TAGS = {"egg_hen", "egg_non_hen", "meat", "fish", "crustacean_shellfish",
                       "mollusc", "soft_mould_ripened_cheese", "soft_blue_cheese", "cured_meat"}


@lru_cache
def catalogue() -> dict:
    data = yaml.safe_load((ROOT / "data" / "ingredient_catalogue.yaml").read_text())
    for key, entry in data.items():
        entry = entry or {}
        entry.setdefault("allergens", [])
        entry.setdefault("tags", [])
        for a in entry["allergens"]:
            Allergen(a)  # raises if not one of the 14
        data[key] = entry
    return data


def structural_issues(recipe: Recipe) -> list[str]:
    """Gate checks that must pass before a recipe is evaluated at all."""
    cat = catalogue()
    issues = []
    for ing in recipe.ingredients:
        entry = cat.get(ing.food)
        if entry is None:
            issues.append(f"unknown ingredient '{ing.food}' (not in catalogue)")
            continue
        if STATE_REQUIRED_TAGS & set(entry["tags"]) and ing.state is None:
            issues.append(f"'{ing.food}' needs a cook state")
    return issues


def recipe_allergens(recipe: Recipe) -> set[str]:
    cat = catalogue()
    return {a for ing in recipe.ingredients for a in cat.get(ing.food, {}).get("allergens", [])}


def recipe_tags(recipe: Recipe) -> set[str]:
    cat = catalogue()
    return {t for ing in recipe.ingredients for t in cat.get(ing.food, {}).get("tags", [])}


def caffeine_mg_per_serving(recipe: Recipe) -> float:
    cat = catalogue()
    total = sum(cat.get(i.food, {}).get("caffeine_mg_per_100g", 0) * i.grams / 100 for i in recipe.ingredients)
    return round(total / recipe.servings, 1)
