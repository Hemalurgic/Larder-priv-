# Recipe API POC: test harness

Everything for the recipe and routing tests except the model calls themselves. The rules,
nutrition and eval code all runs now on hand-made fixture recipes; add API keys and the same
code runs on generated recipes.

## Run it

```
pip install -e .                      # or: pip install pydantic pyyaml jinja2 openpyxl litellm pytest
python -m pytest -q                   # 11 tests
python -m evals.matrix_check          # pregnancy + diet outcome per recipe vs the matrix (30/30)
python -m evals.run_golden            # 25 golden profiles (25/25)
python -m evals.fault_injection       # 11/11 rules faults caught; 3 critic faults pending a model
python -m evals.score_parser --parser keyword --show-failures   # routing test, no-AI baseline
```

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

## Known limits (to fix before trusting the numbers)

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
