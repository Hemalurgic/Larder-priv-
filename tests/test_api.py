"""GraphQL API. Queries 1-4 are the first client's Suggestic queries, verbatim."""
import json
import os
import warnings

import pytest

from service import library as lib
from engine.rules import evaluate
from evals.common import load_library
from evals.run_golden import golden
from schema.models import Diet, Profile

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from service.app import app

KEY = "test-key"

Q1 = """
query RecipeSearch {
recipeSearch(
filter: { should: [{ name: "salmon" }, { ingredients: ["salmon"] }] }
macroNutrientsRange: { calories: { gte: 0, lte: 600 } }
hasImage: true
hasInstructions: true
isPremium: false
first: 10
) {
pageInfo { hasNextPage endCursor }
edges {
node {
id name mainImage totalTimeInSeconds mealTags ingredientLines
parsedIngredientLines { ingredient quantity unit comment }
nutrientsPerServing { calories protein carbs fat fiber sugar sodium }
}
}
}
}
"""

Q2 = """
query {
recipeSearch(tags: ["breakfast", "Breakfast"], hasImage: true,
hasInstructions: true, isPremium: false, first: 50) {
pageInfo { hasNextPage endCursor }
edges { node { id name mealTags } }
}
}
"""

Q3 = """
query Recipe {
recipe(id: "UmVjaXBlOjEyMw==") {
id name mainImage totalTimeInSeconds numberOfServings
instructions ingredientLines
parsedIngredientLines { ingredient quantity unit comment }
nutrientsPerServing { calories protein carbs fat }
}
}
"""

Q4 = """
query Vegan($after: String) {
recipeSearch(dietaryTag: VEGAN, hasImage: true, hasInstructions: true,
isPremium: false, first: 100, after: $after) {
pageInfo { hasNextPage endCursor }
edges { node { id } }
}
}
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fixtures with an image and steps on every recipe except fx30, plus one malformed recipe."""
    rows = []
    for r in load_library():
        d = r.model_dump(mode="json")
        if r.id != "fx30":
            d["image"] = f"https://img.example/{r.id}.jpg"
            d["steps"] = ["Cook it."]
        rows.append(d)
    bad = dict(rows[0], id="bad01", image="https://img.example/bad.jpg",
               ingredients=[{"food": "mystery_meat", "grams": 100}])
    rows.append(bad)
    path = tmp_path / "recipes.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setenv("LARDER_LIBRARY", str(path))
    monkeypatch.setenv("LARDER_API_KEYS", KEY)
    monkeypatch.setenv("LARDER_CASES", str(tmp_path / "cases"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    lib.library.cache_clear()
    yield TestClient(app)
    lib.library.cache_clear()


@pytest.fixture(params=["files", "postgres"])
def case_client(request, client, monkeypatch):
    """The client, with cases stored as files or in Postgres (set LARDER_TEST_DATABASE_URL to run that)."""
    if request.param == "postgres":
        url = os.environ.get("LARDER_TEST_DATABASE_URL")
        if not url:
            pytest.skip("set LARDER_TEST_DATABASE_URL to test the Postgres store")
        import psycopg
        with psycopg.connect(url, autocommit=True) as c:
            c.execute("drop table if exists larder_cases")
        monkeypatch.setenv("DATABASE_URL", url)
    return client


def gql(client, query, variables=None):
    r = client.post("/graphql", json={"query": query, "variables": variables or {}},
                    headers={"Authorization": f"Token {KEY}"})
    assert r.status_code == 200, r.text
    return r.json()


def ids(data):
    return [lib.local_id(e["node"]["id"]) for e in data["edges"]]


def test_q1_salmon_under_600_kcal(client):
    # the only salmon recipe is 609 kcal per serving, so a 600 cap returns nothing
    assert gql(client, Q1)["data"]["recipeSearch"]["edges"] == []
    out = gql(client, Q1.replace("lte: 600", "lte: 700"))["data"]["recipeSearch"]
    assert ids(out) == ["fx25"]
    node = out["edges"][0]["node"]
    assert node["mainImage"] == "https://img.example/fx25.jpg"
    assert node["totalTimeInSeconds"] == lib.library()["fx25"].recipe.total_minutes * 60
    assert node["mealTags"] == ["dinner"]
    assert any("salmon" in line for line in node["ingredientLines"])
    assert node["parsedIngredientLines"][0]["unit"] == "g"
    assert 600 < node["nutrientsPerServing"]["calories"] <= 700


def test_q2_breakfast_any_case_needs_image_and_steps(client):
    out = gql(client, Q2)["data"]["recipeSearch"]
    got = ids(out)
    want = [r.id for r in load_library() if r.meal.value == "breakfast"]
    assert got == want
    assert all(e["node"]["mealTags"] == ["breakfast"] for e in out["edges"])
    snacks = gql(client, Q2.replace('["breakfast", "Breakfast"]', '["SNACK"]'))["data"]["recipeSearch"]
    assert "fx30" not in ids(snacks)    # no image or steps
    assert ids(snacks)


def test_q3_unknown_id_is_null_and_known_id_is_full(client):
    assert gql(client, Q3)["data"]["recipe"] is None
    out = gql(client, Q3.replace("UmVjaXBlOjEyMw==", lib.global_id("fx01")))["data"]["recipe"]
    assert out["name"] == "Spinach and chickpea shakshuka"
    assert out["numberOfServings"] == 2 and out["instructions"] == ["Cook it."]
    assert out["ingredientLines"][0] == "240 g British Lion eggs, 4 eggs, runny yolks"


def test_q4_pages_through_every_vegan_recipe(client):
    want = {e.recipe.id for e in lib.library().values()
            if Diet.vegan in e.diets and e.recipe.image and e.recipe.steps}
    seen, after = [], None
    while True:
        page = gql(client, Q4.replace("first: 100", "first: 2"), {"after": after})["data"]["recipeSearch"]
        seen += ids(page)
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    assert len(seen) == len(set(seen)) and set(seen) == want
    assert gql(client, Q4)["data"]["recipeSearch"]["pageInfo"]["hasNextPage"] is False


def test_malformed_recipe_never_served(client):
    every = gql(client, "{ recipeSearch(first: 100) { edges { node { id } } } }")["data"]["recipeSearch"]
    assert "bad01" not in ids(every)
    assert gql(client, f'{{ recipe(id: "{lib.global_id("bad01")}") {{ id }} }}')["data"]["recipe"] is None


PROFILE_Q = """
query($p: ProfileInput) {
recipeSearch(profile: $p, first: 100) {
rulePack edges { node { id larder { rulePack rulesApplied } } }
}
}
"""


def gql_profile(profile: dict) -> dict:
    return {
        "lifeStage": profile.get("life_stage", "general").upper(),
        "diet": profile.get("diet", "omnivore").upper(),
        "focus": [f.upper() for f in profile.get("focus", [])],
        "meal": profile["meal"].upper() if "meal" in profile else None,
        "excludeAllergens": [a.upper() for a in profile.get("exclude_allergens", [])],
        "maxMinutes": profile.get("max_minutes"),
    }


@pytest.mark.parametrize("g", golden(), ids=lambda g: g["id"])
def test_golden_profiles_through_graphql(client, g):
    out = gql(client, PROFILE_Q, {"p": gql_profile(g["profile"])})["data"]["recipeSearch"]
    briefs = {lib.library()[i].recipe.brief_id for i in ids(out)}
    assert not briefs & set(g["must_not"])
    assert set(g["must"]) <= briefs
    assert out["rulePack"] == "GB@0.1"
    assert all(e["node"]["larder"]["rulePack"] == "GB@0.1" for e in out["edges"])


def test_recipe_by_id_reports_exclusion_for_profile(client):
    pate = next(e.recipe for e in lib.library().values() if any(i.food == "chicken_liver_pate" for i in e.recipe.ingredients))
    q = """query($id: ID!, $p: ProfileInput) { recipe(id: $id, profile: $p) { larder { allowed excludedBy } } }"""
    out = gql(client, q, {"id": lib.global_id(pate.id), "p": {"lifeStage": "PREGNANT"}})["data"]["recipe"]["larder"]
    assert out["allowed"] is False
    assert any(r.startswith("preg-no-pate") for r in out["excludedBy"])
    assert evaluate(pate, Profile()).allowed


def test_dietary_tag_never_loosens_profile_diet(client):
    q = """query($p: ProfileInput) { recipeSearch(dietaryTag: VEGETARIAN, profile: $p, first: 100) { edges { node { id } } } }"""
    got = set(ids(gql(client, q, {"p": {"diet": "VEGAN"}})["data"]["recipeSearch"]))
    assert got and all(Diet.vegan in lib.library()[i].diets for i in got)


def test_upper_bound_excludes_incomplete_nutrient():
    e = next(iter(lib.library().values()))
    fake = lib.Entry(e.recipe, {**e.nutrition, "incomplete": {"energy_kcal": ["x"]}}, e.diets)
    assert lib._in_ranges(fake, {"calories": lib.Range(gte=0)})
    assert not lib._in_ranges(fake, {"calories": lib.Range(lte=10_000)})


def test_premium_page_size_and_cursor(client):
    q = "{ recipeSearch(isPremium: true) { totalCount } }"
    assert gql(client, q)["data"]["recipeSearch"]["totalCount"] == 0
    assert "between 1 and 100" in gql(client, "{ recipeSearch(first: 101) { totalCount } }")["errors"][0]["message"]
    assert "Invalid cursor" in gql(client, '{ recipeSearch(after: "nope") { totalCount } }')["errors"][0]["message"]


def test_auth(client, monkeypatch):
    q = {"query": "{ recipeSearch { totalCount } }"}
    assert client.post("/graphql", json=q).status_code == 401
    assert client.post("/graphql", json=q, headers={"Authorization": "Token wrong"}).status_code == 401
    assert client.post("/graphql", json=q, headers={"X-Api-Key": KEY}).status_code == 200
    assert client.post("/graphql", json=q, headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    monkeypatch.setenv("LARDER_API_KEYS", "")
    assert client.post("/graphql", json=q, headers={"Authorization": f"Token {KEY}"}).status_code == 401
    assert client.get("/health").json()["recipes"] == 30


# ---------- excluded list, judged cases, test bench ----------

PREG_Q = """
query($p: ProfileInput, $f: SearchFilter) {
recipeSearch(profile: $p, filter: $f, first: 100) {
edges { node { id name } }
excluded { id name larder { allowed excludedBy } }
}
}
"""


def pate_recipe():
    return next(e.recipe for e in lib.library().values()
                if any(i.food == "chicken_liver_pate" for i in e.recipe.ingredients))


def test_excluded_lists_rule_removals_that_match_other_filters(client):
    out = gql(client, PREG_Q, {"p": {"lifeStage": "PREGNANT"}})["data"]["recipeSearch"]
    excluded = {lib.local_id(x["id"]): x for x in out["excluded"]}
    pate = pate_recipe()
    assert pate.id in excluded and pate.id not in ids(out)
    assert excluded[pate.id]["larder"]["allowed"] is False
    assert any(r.startswith("preg-no-pate") for r in excluded[pate.id]["larder"]["excludedBy"])
    for rid in excluded:
        assert not evaluate(lib.library()[rid].recipe, Profile(life_stage="pregnant")).allowed
    # a keyword that doesn't match the pate recipe keeps it out of the excluded list too
    out = gql(client, PREG_Q, {"p": {"lifeStage": "PREGNANT"}, "f": {"should": [{"name": "zzz-no-match"}]}})
    assert out["data"]["recipeSearch"]["excluded"] == []


def case_body(judgements):
    return {"name": "Pregnant search", "reviewer": "Test", "query": PREG_Q,
            "variables": {"p": {"lifeStage": "PREGNANT"}}, "judgements": judgements}


def call(client, method, path, body=None):
    return client.request(method, path, json=body, headers={"Authorization": f"Token {KEY}"})


def test_cases_save_list_check_delete(case_client, tmp_path):
    client = case_client
    out = gql(client, PREG_Q, {"p": {"lifeStage": "PREGNANT"}})["data"]["recipeSearch"]
    kept = ids(out)[0]
    pate = pate_recipe().id
    other_excluded = next(lib.local_id(x["id"]) for x in out["excluded"] if lib.local_id(x["id"]) != pate)
    judgements = [
        {"recipe_id": kept, "outcome": "returned", "verdict": "right"},          # holds
        {"recipe_id": pate, "outcome": "excluded", "verdict": "right"},          # holds
        {"recipe_id": ids(out)[1], "outcome": "returned", "verdict": "wrong"},   # open
        {"recipe_id": other_excluded, "outcome": "excluded", "verdict": "unsure"},
        {"recipe_id": pate, "outcome": "missing", "verdict": "wrong", "note": "test"},  # open
    ]
    r = call(client, "PUT", "/cases/preg-1", case_body(judgements))
    assert r.status_code == 200 and r.json()["rule_pack"] == "GB@0.1" and r.json()["created"]
    assert [c["id"] for c in call(client, "GET", "/cases").json()] == ["preg-1"]
    rep = call(client, "POST", "/cases/preg-1/check").json()
    assert rep["counts"] == {"holds": 2, "regression": 0, "open": 2, "fixed": 0, "unsure": 1}

    # a verdict that no longer matches what the engine does is a regression
    judgements[1] = {"recipe_id": pate, "outcome": "returned", "verdict": "right"}
    call(client, "PUT", "/cases/preg-1", case_body(judgements))
    assert call(client, "POST", "/cases/preg-1/check").json()["counts"]["regression"] == 1
    from evals.judged_cases import run as run_cases
    assert run_cases() == 1

    from service.cases import FileStore, export_cases
    exported = tmp_path / "exported"
    assert export_cases(exported) == ["preg-1"]
    assert FileStore(exported).get("preg-1")["judgements"][4]["note"] == "test"

    assert call(client, "PUT", "/cases/Bad Id", case_body([])).status_code == 400
    assert call(client, "GET", "/cases/nope").status_code == 404
    assert call(client, "DELETE", "/cases/preg-1").status_code == 200
    assert call(client, "GET", "/cases").json() == []
    assert client.get("/cases").status_code == 401


def test_status_rules():
    from service.cases import Judgement, status
    J = lambda o, v: Judgement(recipe_id="x", outcome=o, verdict=v)
    assert status(J("returned", "right"), "returned") == "holds"
    assert status(J("returned", "right"), "absent") == "regression"
    assert status(J("excluded", "right"), "excluded") == "holds"
    assert status(J("excluded", "right"), "returned") == "regression"
    assert status(J("returned", "wrong"), "returned") == "open"
    assert status(J("returned", "wrong"), "excluded") == "fixed"
    assert status(J("excluded", "wrong"), "returned") == "fixed"
    assert status(J("missing", "wrong"), "absent") == "open"
    assert status(J("missing", "wrong"), "returned") == "fixed"
    assert status(J("returned", "unsure"), "absent") == "unsure"


def test_testbench_page_and_health(client):
    r = client.get("/testbench")
    assert r.status_code == 200 and "<title>Larder Test Bench</title>" in r.text
    h = client.get("/health").json()
    assert h["fixtures"] == 30 and h["with_images"] == 29


def test_unwritable_case_store_says_what_to_do(client, tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setenv("LARDER_CASES", str(blocker / "cases"))   # can't make a directory under a file
    r = call(client, "PUT", "/cases/x", case_body([]))
    assert r.status_code == 503 and "DATABASE_URL" in r.json()["detail"]


def test_cofid_cache_matches_spreadsheet():
    """The committed cache is what a deploy uses; it must match the spreadsheet it says it came from."""
    from engine import cofid
    assert cofid.SOURCE_HASH.read_text().strip() == cofid.xlsx_sha256()


def test_cofid_uses_cache_without_spreadsheet(monkeypatch, tmp_path):
    """A deploy leaves the xlsx out (.vercelignore); the committed cache must be used, not rebuilt."""
    from engine import cofid
    monkeypatch.setattr(cofid, "XLSX", tmp_path / "missing.xlsx")
    cofid.load.cache_clear()
    try:
        assert len(cofid.load()) > 2000
    finally:
        cofid.load.cache_clear()
