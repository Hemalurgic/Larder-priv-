"""Run with: python -m pytest -q"""
from engine.catalogue import catalogue, structural_issues
from engine.nutrition import compute
from engine.rules import evaluate
from evals import fault_injection, matrix_check, run_golden, score_parser
from evals.common import briefs, load_library
from generation.llm import ENV
from schema.models import LifeStage, Profile


def lib():
    return {r.brief_id: r for r in load_library()}


def test_every_fixture_uses_catalogue_and_states():
    for r in load_library():
        assert structural_issues(r) == [], r.id


def test_matrix_30_of_30():
    assert matrix_check.run() == []


def test_golden_profiles():
    assert run_golden.run() == []


def test_fault_injection_rules_caught():
    caught, missed, pending = fault_injection.run()
    assert not missed
    assert len(caught) == 11


def test_precedence_pate_never_reaches_pregnant_iron_focus():
    v = evaluate(lib()[9], Profile(life_stage=LifeStage.pregnant, focus=["iron"]))
    assert not v.allowed and any("preg-no-liver" in e for e in v.excluded_by)


def test_cooked_hen_egg_is_safe_not_conditional():
    v = evaluate(lib()[26], Profile(life_stage=LifeStage.pregnant))
    assert v.allowed and not v.conditional


def test_missing_state_fails_closed():
    r = lib()[27].model_copy(deep=True)
    r.ingredients[0].state = None
    assert not evaluate(r, Profile()).allowed


def test_claims_never_from_incomplete_data():
    n = compute(lib()[2])  # oat drink and chia are CoFID gaps
    assert "iron_mg" in n["incomplete"] and not any("iron" in c for c in n["claims"])


def test_parser_scorer_oracle_is_perfect():
    s = score_parser.run("oracle")
    assert s["pass"] == s["cases"] == 150


def test_parser_scorer_detects_safety_miss():
    from schema.models import ParsedProfile
    case = {"id": "x", "cat": "t", "text": "pregnant", "expect": {"life_stage": "pregnant"}}
    assert score_parser.score_case(case, ParsedProfile())["safety_miss"]


def test_templates_render():
    keys = sorted(catalogue())
    b = briefs()[0]
    for name in ["recipe_A.j2", "recipe_B.j2"]:
        assert b.title in ENV.get_template(name).render(brief=b, catalogue_keys=keys)
    assert "hello" in ENV.get_template("parser.j2").render(text="hello")
    assert b.title in ENV.get_template("critic.j2").render(brief=b, recipe_json="{}")
