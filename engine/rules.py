"""Rules engine: profile + recipe -> allowed or not, with the rules that applied and why."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from engine.catalogue import (caffeine_mg_per_serving, catalogue, recipe_allergens,
                              structural_issues)
from schema.models import Profile, Recipe

ROOT = Path(__file__).resolve().parents[1]


@lru_cache
def pack(name: str = "gb_v0") -> dict:
    return yaml.safe_load((ROOT / "rules" / f"{name}.yaml").read_text())


@dataclass
class Verdict:
    allowed: bool
    excluded_by: list[str] = field(default_factory=list)      # rule ids / reasons, in precedence order
    notes: list[str] = field(default_factory=list)            # conditional passes and limits to show
    conditional: list[str] = field(default_factory=list)      # conditional rules that passed on their exception
    applied: list[str] = field(default_factory=list)          # every rule id that matched or passed
    allergens: list[str] = field(default_factory=list)
    caffeine_mg: float = 0.0
    rule_pack: str = ""


def _applies(when: dict, profile: Profile) -> bool:
    if "life_stage" in when and profile.life_stage.value != when["life_stage"]:
        return False
    if "diet" in when and profile.diet.value not in when["diet"]:
        return False
    return True


def _ingredient_matches(match: dict, tags: set[str], state) -> bool:
    if "any_tag" in match and not (tags & set(match["any_tag"])):
        return False
    if "lacks_tag" in match and match["lacks_tag"] in tags:
        return False
    if "state_not_in" in match and state is not None and state.value in match["state_not_in"]:
        return False
    return True


def _risk(risk: dict, tags: set[str], state) -> bool:
    if not (tags & set(risk.get("any_tag", []))):
        return False
    if "state_in" in risk and (state is None or state.value not in risk["state_in"]):
        return state is None  # unknown state counts as risky (fail closed)
    return True


def _exception_holds(unless: dict, tags: set[str], state) -> bool:
    if "has_tag" in unless and unless["has_tag"] not in tags:
        return False
    if "state_in" in unless and (state is None or state.value not in unless["state_in"]):
        return False
    return True


def evaluate(recipe: Recipe, profile: Profile, pack_name: str = "gb_v0") -> Verdict:
    p = pack(pack_name)
    cat = catalogue()
    v = Verdict(allowed=True, rule_pack=f"{p['pack']}@{p['version']}")
    v.allergens = sorted(recipe_allergens(recipe))
    v.caffeine_mg = caffeine_mg_per_serving(recipe)

    issues = structural_issues(recipe)
    if issues:  # never evaluate a malformed recipe; fail closed
        v.allowed = False
        v.excluded_by = [f"structural: {i}" for i in issues]
        return v

    for rule in sorted(p["rules"], key=lambda r: r["priority"]):
        if not _applies(rule["when"], profile):
            continue
        if rule["type"] == "conditional":
            risky = [i for i in recipe.ingredients if _risk(rule["risk"], set(cat[i.food]["tags"]), i.state)]
            if not risky:
                continue
            v.applied.append(rule["id"])
            if all(_exception_holds(rule["unless"], set(cat[i.food]["tags"]), i.state) for i in risky):
                v.conditional.append(rule["id"])
                v.notes.append(rule["pass_note"])
            else:
                v.allowed = False
                v.excluded_by.append(f"{rule['id']}: {rule['reason']}")
            continue
        m = rule["match"]
        if m.get("caffeine"):
            if v.caffeine_mg > 0:
                v.applied.append(rule["id"])
                v.notes.append(f"{rule['reason']} ({v.caffeine_mg} mg per serving)")
            continue
        hit = any(_ingredient_matches(m, set(cat[i.food]["tags"]), i.state) for i in recipe.ingredients)
        if rule["type"] == "exclude" and hit:
            v.allowed = False
            v.excluded_by.append(f"{rule['id']}: {rule['reason']}")
            v.applied.append(rule["id"])
        elif rule["type"] == "limit" and hit:
            v.applied.append(rule["id"])
            v.notes.append(rule["reason"])

    # Priority 2: allergens. Kept after the loop so the reasons list stays complete.
    clash = set(v.allergens) & {a.value for a in profile.exclude_allergens}
    if clash:
        v.allowed = False
        v.excluded_by.append(f"allergen: contains {', '.join(sorted(clash))}")
    return v
