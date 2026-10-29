"""GraphQL schema, shaped to match the Suggestic queries the first client already sends.

Compatible: recipeSearch (filter.should/must, macroNutrientsRange, tags, dietaryTag, hasImage,
hasInstructions, isPremium, first/after) and recipe(id), with Relay-style edges/pageInfo and
base64 "Recipe:<id>" IDs.

Larder additions, all optional: a `profile` argument, `rulePack` on the connection, and a `larder`
block on each recipe with the rule IDs, notes, allergens and claims behind it.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Optional

import strawberry

from api import library as lib
from engine.rules import evaluate
from schema.models import (Allergen, CyclePhase, Diet, Focus, LifeStage, Meal, Profile,
                           Region)


def _gql_enum(py: type[Enum], name: str, description: str):
    """Expose one of the schema enums with GraphQL-style upper-case names."""
    return strawberry.enum(Enum(name, {m.name.upper(): m.value for m in py}), description=description)


LifeStageEnum = _gql_enum(LifeStage, "LifeStage", "Life stage. Only adults 18+ are in scope.")
CyclePhaseEnum = _gql_enum(CyclePhase, "CyclePhase", "Menstrual cycle phase.")
DietEnum = _gql_enum(Diet, "Diet", "Diet the recipe must suit.")
FocusEnum = _gql_enum(Focus, "NutrientFocus", "Nutrient to favour when ranking.")
MealEnum = _gql_enum(Meal, "Meal", "Meal.")
AllergenEnum = _gql_enum(Allergen, "Allergen", "The 14 UK major allergens.")
RegionEnum = _gql_enum(Region, "Region", "Rule pack region.")


@strawberry.enum(description="Dietary tag, decided by the rules engine from the ingredient catalogue.")
class DietaryTag(Enum):
    VEGAN = "vegan"
    VEGETARIAN = "vegetarian"


# ---------- Inputs ----------

@strawberry.input(description="Text match. Every field given must match.")
class SearchClause:
    name: Optional[str] = strawberry.field(default=None, description="Substring of the recipe name, any case.")
    ingredients: Optional[list[str]] = strawberry.field(
        default=None, description="Every term must match one of the recipe's ingredients.")


@strawberry.input
class SearchFilter:
    should: Optional[list[SearchClause]] = strawberry.field(default=None, description="At least one must match.")
    must: Optional[list[SearchClause]] = strawberry.field(default=None, description="All must match.")


@strawberry.input
class FloatRange:
    gte: Optional[float] = None
    lte: Optional[float] = None


@strawberry.input(description="Per serving. Sodium in mg, the rest in kcal or g. "
                              "An upper bound excludes recipes whose value is incomplete.")
class MacroNutrientsRange:
    calories: Optional[FloatRange] = None
    protein: Optional[FloatRange] = None
    carbs: Optional[FloatRange] = None
    fat: Optional[FloatRange] = None
    fiber: Optional[FloatRange] = None
    sugar: Optional[FloatRange] = None
    sodium: Optional[FloatRange] = None


@strawberry.input(description="Larder addition: who the recipes are for. Safety and allergen rules "
                              "come from the rule pack; omit for a general adult.")
class ProfileInput:
    region: RegionEnum = RegionEnum.GB
    life_stage: LifeStageEnum = LifeStageEnum.GENERAL
    cycle_phase: Optional[CyclePhaseEnum] = None
    diet: DietEnum = DietEnum.OMNIVORE
    focus: Optional[list[FocusEnum]] = None
    meal: Optional[MealEnum] = None
    exclude_allergens: Optional[list[AllergenEnum]] = None
    max_minutes: Optional[int] = None


def to_profile(p: ProfileInput | None) -> Profile:
    if p is None:
        return Profile()
    return Profile(
        region=Region(p.region.value), life_stage=LifeStage(p.life_stage.value),
        cycle_phase=CyclePhase(p.cycle_phase.value) if p.cycle_phase else None,
        diet=Diet(p.diet.value), focus=[Focus(f.value) for f in p.focus or []],
        meal=Meal(p.meal.value) if p.meal else None,
        exclude_allergens=[Allergen(a.value) for a in p.exclude_allergens or []],
        max_minutes=p.max_minutes,
    )


# ---------- Output types ----------

@strawberry.type
class ParsedIngredientLine:
    ingredient: str
    quantity: float
    unit: str
    comment: Optional[str]


@strawberry.type(description="Per serving. Sodium in mg, energy in kcal, the rest in g. "
                             "Raw-weight basis, from CoFID 2021.")
class Nutrients:
    calories: float
    protein: float
    carbs: float
    fat: float
    fiber: float
    sugar: float
    sodium: float


@strawberry.type(description="Larder addition: why this recipe is here.")
class LarderInfo:
    rule_pack: str
    allowed: bool = strawberry.field(description="False only on recipe(id) when the profile excludes it.")
    excluded_by: list[str]
    rules_applied: list[str]
    notes: list[str]
    allergens: list[str]
    dietary_tags: list[DietaryTag]
    claims: list[str]
    nutrition_basis: str
    incomplete_nutrients: list[str] = strawberry.field(
        description="Nutrients with missing data. Their values are lower bounds and earn no claims.")
    fixture: bool = strawberry.field(description="True for test skeletons that are not real recipes.")


@strawberry.type
class Recipe:
    id: strawberry.ID
    name: str
    main_image: Optional[str]
    total_time_in_seconds: int
    number_of_servings: int
    meal_tags: list[str]
    ingredient_lines: list[str]
    parsed_ingredient_lines: list[ParsedIngredientLine]
    instructions: list[str]
    nutrients_per_serving: Nutrients
    is_premium: bool
    larder: LarderInfo


@strawberry.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str]
    end_cursor: Optional[str]


@strawberry.type
class RecipeEdge:
    cursor: str
    node: Recipe


@strawberry.type
class RecipeConnection:
    page_info: PageInfo
    edges: list[RecipeEdge]
    total_count: int
    rule_pack: str
    _excluded: strawberry.Private[list]
    _profile: strawberry.Private[Profile]

    @strawberry.field(description="Larder addition: recipes the rule pack removed for this profile that match "
                                  "every other filter, each with `larder.excludedBy`. Not paged.")
    def excluded(self) -> list[Recipe]:
        return [to_node(e, self._profile) for e in self._excluded]


def to_node(e: lib.Entry, profile: Profile) -> Recipe:
    r = e.recipe
    v = evaluate(r, profile)
    return Recipe(
        id=strawberry.ID(lib.global_id(r.id)), name=r.title, main_image=r.image,
        total_time_in_seconds=r.total_minutes * 60, number_of_servings=r.servings,
        meal_tags=[r.meal.value],
        ingredient_lines=[lib.ingredient_line(i) for i in r.ingredients],
        parsed_ingredient_lines=[ParsedIngredientLine(ingredient=lib.ingredient_name(i.food), quantity=i.grams,
                                                      unit="g", comment=i.note) for i in r.ingredients],
        instructions=r.steps, nutrients_per_serving=Nutrients(**lib.nutrients_per_serving(e)),
        is_premium=False,
        larder=LarderInfo(
            rule_pack=v.rule_pack, allowed=v.allowed, excluded_by=v.excluded_by, rules_applied=v.applied,
            notes=v.notes, allergens=v.allergens,
            dietary_tags=[DietaryTag(d.value) for d in (Diet.vegetarian, Diet.vegan) if d in e.diets],
            claims=e.nutrition["claims"], nutrition_basis=e.nutrition["basis"],
            incomplete_nutrients=lib.incomplete_nutrients(e), fixture=r.fixture,
        ),
    )


MAX_PAGE = 100


@strawberry.type
class Query:
    @strawberry.field(description="Search recipes. Results always pass the rule pack for the profile "
                                  "(a general adult if none is given).")
    def recipe_search(
        self,
        filter: Optional[SearchFilter] = None,
        macro_nutrients_range: Optional[MacroNutrientsRange] = None,
        tags: Annotated[Optional[list[str]], strawberry.argument(description="Meal tags, any case; any may match.")] = None,
        dietary_tag: Optional[DietaryTag] = None,
        has_image: Optional[bool] = None,
        has_instructions: Optional[bool] = None,
        is_premium: Optional[bool] = None,
        profile: Optional[ProfileInput] = None,
        first: int = 20,
        after: Optional[str] = None,
    ) -> RecipeConnection:
        if not 1 <= first <= MAX_PAGE:
            raise ValueError(f"`first` must be between 1 and {MAX_PAGE}.")
        start = lib.offset_after(after)
        prof = to_profile(profile)
        if dietary_tag is not None:
            prof = prof.model_copy(update={"diet": lib.stricter(prof.diet, Diet(dietary_tag.value))})

        def clauses(cs):
            return [lib.TextClause(c.name, c.ingredients or []) for c in cs or []]

        ranges = {}
        if macro_nutrients_range is not None:
            for name in lib.NUTRIENTS:
                rg = getattr(macro_nutrients_range, name)
                if rg is not None:
                    ranges[name] = lib.Range(rg.gte, rg.lte)

        res = lib.search(
            prof, should=clauses(filter and filter.should), must=clauses(filter and filter.must),
            ranges=ranges, tags=tags, has_image=has_image, has_instructions=has_instructions,
            is_premium=is_premium)
        hits = res.hits
        page = hits[start:start + first]
        edges = [RecipeEdge(cursor=lib.cursor(start + i), node=to_node(e, prof)) for i, e in enumerate(page)]
        return RecipeConnection(
            page_info=PageInfo(has_next_page=start + first < len(hits), has_previous_page=start > 0,
                               start_cursor=edges[0].cursor if edges else None,
                               end_cursor=edges[-1].cursor if edges else None),
            edges=edges, total_count=len(hits), rule_pack=res.rule_pack, _excluded=res.excluded, _profile=prof,
        )

    @strawberry.field(description="One recipe by ID. With a profile, `larder.allowed` says whether it suits it.")
    def recipe(self, id: strawberry.ID, profile: Optional[ProfileInput] = None) -> Optional[Recipe]:
        rid = lib.local_id(id)
        e = lib.library().get(rid) if rid else None
        return to_node(e, to_profile(profile)) if e else None


schema = strawberry.Schema(query=Query)
