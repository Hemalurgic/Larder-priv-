# Larder: recipe and nutrition API (POC)

B2B API for health apps (first client: a women's health app). A client sends a structured profile
(region, life stage, cycle phase, diet, nutrient focus, meal, allergens) and gets back recipes that
are safe and suitable for it, with images, nutrition and the reasons each rule applied. Positioned as
a cheaper, transparent alternative to Suggestic's custom recipe API.

There are no end users of our own. Anything about "what users see" means the client's users in the client's app.

## Principles (don't break these)

1. **The LLM parses; the database decides.** Models write recipes offline and can turn free text into a
   profile. They never choose which recipe a user gets and never set safety data.
2. **Tags and allergens come only from `data/ingredient_catalogue.yaml`.** Recipes reference catalogue
   keys. A model-written tag is never trusted.
3. **Fail closed.** Unknown ingredient, missing cook state, invalid JSON: the recipe is excluded, not guessed.
4. **Rules are data.** `rules/gb_v0.yaml` is a draft, UNREVIEWED rule pack. Don't change rule meaning
   without flagging it for dietitian review. Precedence: safety > allergen > diet > target > preference.
5. **No claim from incomplete data.** A nutrient with missing contributors never earns "source of" / "high in".
6. **Every response carries the rule pack version** and the rule IDs that applied.

## Commands

```
pip install -e .
python -m pytest -q                         # must stay green
python -m evals.matrix_check                # 30/30
python -m evals.run_golden                  # 25/25, blocks publishing on any failure
python -m evals.fault_injection             # 11/11 rules faults caught
python -m evals.score_parser --parser keyword --show-failures
python -m generation.run_round --round 0 --half all --models fixture   # dry run, no keys
```

Model runs go through OpenRouter (`OPENROUTER_API_KEY`, LiteLLM prefix `openrouter/`).
Proposed models and costs: `config/test_models.yaml`. Confirm IDs on openrouter.ai/models and pin versions.

## Layout

See README.md. Key files: `schema/models.py` (contracts), `engine/rules.py` (rules engine),
`engine/nutrition.py` (CoFID 2021 maths), `evals/` (all tests), `prompts/` (templates; version = file hash).

## Current state (29 Oct 2026)

- Built and passing on 30 hand-made fixture recipes (ingredient skeletons, not real recipes).
- Not yet run: any model call. Recipe round 1, critic, LLM routing test all need an OpenRouter key.
- Known limits: README "Known limits" section (raw-weight nutrition, 5 CoFID gaps, 33 proxies,
  placeholder caffeine values, unreviewed rule pack, keyword baseline seen the test cases).

## Next steps, in order

1. `git init`, push to a private GitHub repo, add `.env` (gitignored) with `OPENROUTER_API_KEY`.
2. Confirm model IDs and prices; pin them in `config/test_models.yaml`.
3. Routing test: each parser model with `--repeats 3`. Pass bar: 0 safety misses, 0 invented values.
   Get 30 to 50 real user phrases from the client as an unseen extra set before trusting the scores.
4. Recipe round 1: half A, 3 models x templates A and B, with the critic. Then matrix + golden on
   `runs/round1/recipes.jsonl`, then blind human review via `runs/round1/review.csv`.
5. Wrap the engine in a FastAPI service: `GET /v0/recipes/search`, `GET /v0/recipes/{id}`, API-key
   auth stub, served from the fixture or round library, so the client can call something real.
6. Small review web app (keyboard shortcuts, timer) to replace the CSV once volumes grow.
7. Image test (separate track) after recipe round 2. Plan is in the POC scope doc.

## Writing conventions

UK English. Metric. Plain, direct copy in docs and API messages; no health claims beyond the legal
claim flags.
