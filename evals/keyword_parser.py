"""No-AI baseline parser: regular expressions only.

It exists to (a) test the scorer end to end and (b) set the floor an LLM has to beat.
If a model can't clearly outperform this on the routing test, the LLM endpoint isn't worth its cost.
"""
from __future__ import annotations

import re

from schema.models import ParsedProfile

PREGNANT = r"pregnan|pregnent|preggo|expecting|bump|midwife|trimester|knocked up|bun in the oven|baby'?s due|due in"
VEGAN = r"\bvegan\b|veegan|\bvgn\b|plant[- ]based|no animal products|anything that comes from an animal"
VEGETARIAN = r"vegetarian|vegitarian|veggie|veggo|don'?t eat meat|no meat"
MEALS = [("breakfast", r"breakfast|brekkie|brekky|brunch"), ("lunch", r"lunch"),
         ("dinner", r"dinner|diner|\btea\b|supper|din dins"), ("snack", r"snack|snak")]
FOCUS = [("iron", r"\biron\b"), ("magnesium", r"magnes"), ("protein", r"prote?i?n|protien"), ("folate", r"folate|folic")]
ALLERGENS = [
    ("cereals_gluten", r"gluten|wheat|coeliac|\bgf\b"), ("milk", r"dairy|lactose|\bdf\b|milk"),
    ("eggs", r"\begg"), ("sesame", r"sesame"), ("soya", r"\bsoy"), ("mustard", r"mustard"),
    ("celery", r"celery"), ("sulphites", r"sulphite"), ("lupin", r"lupin"), ("fish", r"\bno fish|fish allergy|fish and"),
    ("crustaceans", r"shell?fish|prawn"), ("molluscs", r"shell?fish"),
]
CYCLE = [("menstrual", r"on my period|period started|menstrual|aunt flo|the blob|time of the month|day [1-5]\b|heavy period"),
         ("luteal", r"luteal|pms|pre-period|day 2[0-9]\b"),
         ("follicular", r"follicular|week after my period|period'?s just finished"),
         ("ovulatory", r"ovulat")]
OUT_OF_SCOPE = r"carnivore|fodmap|pescatarian|keto|halal|kosher|breastfeed|conceive|menopause|omega|calorie|wine|meal plan|year old|paleo|diabet|coeliac|kidney|pcos|blood pressure|eclampsia|anaemia|deficient|\bus\b|american|irish|irregular|system prompt"


def parse(text: str) -> ParsedProfile:
    t = text.lower()
    d: dict = {}
    if re.search(PREGNANT, t):
        d["life_stage"] = "pregnant"
    if re.search(VEGAN, t):
        d["diet"] = "vegan"
    elif re.search(VEGETARIAN, t):
        d["diet"] = "vegetarian"
    for meal, pat in MEALS:
        if re.search(pat, t):
            d["meal"] = meal
            break
    d["focus"] = [f for f, pat in FOCUS if re.search(pat, t)]
    allergens = [a for a, pat in ALLERGENS if re.search(pat, t)]
    if re.search(r"\bnut", t):
        allergens += ["peanuts", "tree_nuts"]
    elif re.search(r"peanut", t):
        allergens.append("peanuts")
    if re.search(r"tree nut", t):
        allergens = [a for a in allergens if a != "peanuts"] + ["tree_nuts"]
    d["exclude_allergens"] = sorted(set(allergens))
    for phase, pat in CYCLE:
        if re.search(pat, t):
            d["cycle_phase"] = phase
            break
    m = re.search(r"(\d+)\s*(?:min|minute)", t)
    if m and 5 <= int(m.group(1)) <= 240:
        d["max_minutes"] = int(m.group(1))
    unmapped = ["out of scope term"] if re.search(OUT_OF_SCOPE, t) else []
    return ParsedProfile(**d, unmapped=unmapped)
