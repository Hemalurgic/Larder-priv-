# Recipe API POC: test harness

Everything for the recipe and routing tests except the model calls themselves. The rules,
nutrition and eval code all runs now on hand-made fixture recipes; add API keys and the same
code runs on generated recipes.

## Run it

```
pip install -e ".[generation,dev]"          # the service alone needs just: pip install -e .
python -m pytest -q                   # 50 tests, incl. the client's queries against the API
python -m evals.judged_cases --show   # re-check every verdict saved from the test bench
python -m evals.matrix_check          # pregnancy + diet outcome per recipe vs the matrix (30/30)
python -m evals.run_golden            # 25 golden profiles (25/25)
python -m evals.fault_injection       # 11/11 rules faults caught; 3 critic faults pending a model
python -m evals.score_parser --parser keyword --show-failures   # routing test (parked), no-AI baseline
```

## The API

GraphQL, shaped to match the Suggestic queries the first client already sends, so they can switch
without rewriting their integration.

```
LARDER_API_KEYS=dev uvicorn service.app:app --reload        # POST /graphql, GET /health
LARDER_LIBRARY=runs/round1/recipes.jsonl ...             # serve a round's recipes instead of the fixtures
```

Send the key as `Authorization: Token <key>`. With no keys configured, every request is refused.

- `recipeSearch`: `filter { should / must: [{ name, ingredients }] }`, `macroNutrientsRange`, `tags` (meal,
  any case), `dietaryTag` (`VEGAN`, `VEGETARIAN`), `hasImage`, `hasInstructions`, `isPremium`, `first` (1-100),
  `after`. Returns `edges { node }`, `pageInfo`, `totalCount`, `rulePack`.
- `recipe(id)`: IDs are base64 `Recipe:<id>`, as Suggestic's are. Unknown or malformed recipes return null.
- Larder additions, all optional: a `profile` argument on both (life stage, cycle phase, diet, focus, meal,
  allergens, max minutes), and a `larder { ... }` block on each recipe with the rule IDs, notes, allergens,
  dietary tags, claims and incomplete nutrients.
- Every search result passes the rule pack for the profile, or for a general adult if none is sent. Recipes
  that fail the structural checks are never served. An upper bound in `macroNutrientsRange` excludes recipes
  whose value for that nutrient is incomplete, because missing data can only make it higher.

## Test bench

A page for testing the API by hand and recording verdicts, at `/testbench` on the running server:

```
LARDER_API_KEYS=pick-a-key uvicorn service.app:app      # then open http://localhost:8000/testbench
```

Enter the API key and your name at the top. Then:

- **Profile search**: pick a life stage, diet, allergens, focus, meal and the client's filters, and run it.
  The page builds the GraphQL for you; "Edit as GraphQL" or "Show the query" shows it.
- **GraphQL**: write any query, or start from the client's four real queries and a few Larder examples.
- **Judge** every recipe: returned ones are "Should be here" / "Shouldn't be here" / "Unsure"; excluded ones,
  with the rule that removed them, are "Rightly excluded" / "Should be allowed" / "Unsure". Add a note to any.
  "Expected but missing" records a recipe the query should have returned.
- **Save** the case. It's written to `review/cases/<id>.json`; commit it. "Open" reloads a case, re-runs it
  and marks each verdict: still holds, regression, still wrong, or now fixed. "Check all" does every case.

`python -m evals.judged_cases --show` runs the same check from the command line and fails on any regression,
so a reviewer's verdicts become tests. The excluded list comes from a Larder addition to the API:
`recipeSearch { excluded { ... } }`.

## Deploying (Vercel)

The root `app.py` exposes the FastAPI app, which is where Vercel looks for one. A deploy installs only the
base dependencies (about 67 MB); model runs and the CoFID rebuild need the `generation` extra and stay local.

1. In Vercel: **Add New → Project**, import `Studio-Daedalus/Larder`. Leave the build settings as detected.
2. **Settings → Environment Variables**: `LARDER_API_KEYS` = one or more keys, comma-separated.
3. **Storage**: connect a Postgres database (e.g. Neon). It sets `DATABASE_URL`, and saved cases go there,
   because a serverless disk doesn't keep files. Without a database the test bench works but can't save.
4. Deploy. Every branch gets a preview URL; `main` is production. `/testbench` is the test bench,
   `/graphql` the API, `/health` a quick check.

Preview URLs sit behind Vercel's login by default (Deployment Protection). Anyone testing a preview needs
access to the Vercel team, or protection turned off for previews; the API key still guards the data.

To commit cases reviewers saved on the hosted bench: `DATABASE_URL=<from Vercel> python -m service.cases export`
writes them to `review/cases/`.

Guesses to confirm against the client's integration: `mealTags` come back lower case; sodium is in mg;
`instructions` is a list of strings; several `ingredients` terms in one clause must all match;
`isPremium: true` returns nothing (Larder has no premium tier).

With an OpenRouter key (`export OPENROUTER_API_KEY=...`); model picks and costs are in `config/test_models.yaml`:

```
# Recipe test, round 1: 15 briefs (half A) x 3 models x 2 templates, with a critic
python -m generation.run_round --round 1 --half A --models <m1>,<m2>,<m3> --templates A,B --critic <critic>
python -m evals.matrix_check --library runs/round1/recipes.jsonl
python -m evals.run_golden   --library runs/round1/recipes.jsonl
# then fill in runs/round1/review.csv: blind (codes only, shuffled); review_key.csv maps codes back

# Routing test
python -m evals.score_parser --parser llm:openrouter/<model-id> --repeats 3 --out runs/parser.jsonl --show-failures
```

Dry run of the whole recipe pipeline without keys: `--models fixture`.

## What's where

| Path | What |
| --- | --- |
| `schema/models.py` | Profile, Brief, Recipe; closed enums, 14 UK allergens, cook states |
| `data/briefs.yaml` | The 30 briefs, expected pregnancy outcome, half A / B split |
| `data/ingredient_catalogue.yaml` | The only source of allergens and safety tags (116 ingredients) |
| `data/cofid_map.yaml` | Each ingredient's CoFID 2021 code: exact, proxy or gap |
| `data/cofid/` | CoFID 2021 spreadsheet + cached subset |
| `data/fixture_recipes.yaml` | Ingredient skeletons per brief, for testing only; not recipes |
| `rules/gb_v0.yaml` | GB rule pack v0.1, **draft, unreviewed** |
| `engine/` | Catalogue checks, nutrition, rules engine, search |
| `evals/` | Matrix check, golden profiles, fault injection, routing cases (150) + scorer |
| `prompts/` | Recipe templates A and B, critic, parser |
| `generation/` | LiteLLM model layer and the round runner (logs every call, cost and template version) |
| `service/` | GraphQL service: `schema.py` (types, client-compatible), `library.py` (filters over engine.search), `cases.py` (judged cases), `app.py` (FastAPI, key stub), `static/testbench.html` |
| `review/cases/` | Judged cases saved from the test bench; re-checked by `evals/judged_cases.py` |
| `app.py` | Entry point for Vercel and `uvicorn app:app` |

## Known limits (to fix before trusting the numbers)

- **No recipe has an image yet**, and fixtures have no steps. The client's queries all send `hasImage: true`
  and `hasInstructions: true`, so against the fixtures they return nothing until the image track has run.
- **Rule pack is unreviewed.** Drafted from memory of NHS guidance; the dietitian must check every rule.
- **Nutrition is raw-weight based.** No cooking retention factors (folate, vitamin C overstated) and
  per-100 g claims use raw weight unless a yield factor is given. Wet dishes rarely earn per-100 g claims.
- **CoFID gaps:** oat drink, chia seeds, soba noodles, cranberry sauce, nutritional yeast. 33 other
  ingredients use proxies (listed in `cofid_map.yaml`). A missing value from an ingredient under 2% of
  recipe weight doesn't block claims; that's wrong for nutrient-dense ingredients like nutritional yeast.
- **Caffeine values are approximate placeholders** (not in CoFID).
- **Keyword baseline was written with the test cases in view**, so its 134/150 is optimistic. Before
  the LLM routing test, get 30 to 50 real user phrases from the client's app as an unseen extra set.
- **Brand-dependent ingredients** (stocks, curry paste, chocolate, cheddar rennet) rely on the recipe
  naming a compliant product; review has to check the note field.
