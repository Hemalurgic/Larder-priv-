"""Data contracts for the recipe POC.

Closed enums everywhere: anything outside these lists is rejected, never guessed.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Region(str, Enum):
    GB = "GB"


class LifeStage(str, Enum):
    general = "general"
    pregnant = "pregnant"


class CyclePhase(str, Enum):
    menstrual = "menstrual"
    follicular = "follicular"
    ovulatory = "ovulatory"
    luteal = "luteal"


class Diet(str, Enum):
    omnivore = "omnivore"
    vegetarian = "vegetarian"
    vegan = "vegan"


# How restrictive each diet is. Used to spot a parser loosening a diet (a safety miss).
DIET_STRICTNESS = {Diet.omnivore: 0, Diet.vegetarian: 1, Diet.vegan: 2}


class Focus(str, Enum):
    iron = "iron"
    magnesium = "magnesium"
    protein = "protein"
    folate = "folate"


class Meal(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


class Allergen(str, Enum):
    """The 14 UK major allergens."""
    celery = "celery"
    cereals_gluten = "cereals_gluten"
    crustaceans = "crustaceans"
    eggs = "eggs"
    fish = "fish"
    lupin = "lupin"
    milk = "milk"
    molluscs = "molluscs"
    mustard = "mustard"
    tree_nuts = "tree_nuts"
    peanuts = "peanuts"
    sesame = "sesame"
    soya = "soya"
    sulphites = "sulphites"


class CookState(str, Enum):
    """Required on eggs, meat, fish, shellfish and soft cheese. Drives conditional safety rules."""
    raw = "raw"
    lightly_cooked = "lightly_cooked"          # e.g. runny yolk, seared
    cooked_through = "cooked_through"
    heated_until_steaming = "heated_until_steaming"
    as_is = "as_is"                            # used straight from the pack, e.g. cold salami


# ---------- Profile: what a client sends (or what the parser must produce) ----------

class Profile(BaseModel):
    region: Region = Region.GB
    life_stage: LifeStage = LifeStage.general
    cycle_phase: Optional[CyclePhase] = None
    diet: Diet = Diet.omnivore
    focus: list[Focus] = Field(default_factory=list)
    meal: Optional[Meal] = None
    exclude_allergens: list[Allergen] = Field(default_factory=list)
    max_minutes: Optional[int] = Field(default=None, ge=5, le=240)


class ParsedProfile(Profile):
    """Parser output: a Profile plus what it couldn't map and any conflicts it noticed."""
    unmapped: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


# ---------- Briefs and recipes ----------

class Brief(BaseModel):
    id: int
    half: str = "A"                # A = rounds 1-2, B = round 3 holdout
    title: str
    meal: Meal
    diet: Diet                     # the diet the dish is intended for
    focus: list[Focus] = Field(default_factory=list)
    max_minutes: int = 45
    servings: int = 2
    expected_pregnancy: str        # safe | exclude | conditional | limit  (from the matrix)
    tests: str                     # what the brief is designed to test


class RecipeIngredient(BaseModel):
    food: str                      # key in data/ingredient_catalogue.yaml
    grams: float = Field(gt=0)
    note: Optional[str] = None     # e.g. "finely chopped"
    state: Optional[CookState] = None

    @field_validator("food")
    @classmethod
    def snake(cls, v: str) -> str:
        if v != v.strip().lower() or " " in v:
            raise ValueError("food must be a snake_case catalogue key")
        return v


class Recipe(BaseModel):
    id: str                        # e.g. "b09-r1-modelx-B" ; fixtures use "fx09"
    brief_id: int
    title: str
    meal: Meal
    servings: int = Field(ge=1, le=12)
    total_minutes: int = Field(ge=1, le=600)
    ingredients: list[RecipeIngredient] = Field(min_length=1)
    steps: list[str] = Field(default_factory=list)
    image: Optional[str] = None    # URL of the main image, once the image track has made one
    fixture: bool = False          # True = hand-made test skeleton, not a real recipe
