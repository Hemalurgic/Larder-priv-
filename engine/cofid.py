"""Loader for McCance and Widdowson's CoFID 2021 integrated dataset.

Layout (checked against the 2021 xlsx): sheets '1.3 Proximates', '1.4 Inorganics',
'1.5 Vitamins'. Row 1 = display names, row 2 = nutrient codes, row 3 = long names,
data from row 4. Values are per 100 g edible portion (per 100 ml for alcoholic drinks).
'N' = not determined (stored as None, i.e. missing). 'Tr' = trace (stored as 0.0).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "cofid" / "cofid_2021.xlsx"
CACHE = ROOT / "data" / "cofid" / "cofid_2021_subset.json"

# Nutrient code -> our field name
NUTRIENTS = {
    "1.3 Proximates": {"KCALS": "energy_kcal", "PROT": "protein_g", "FAT": "fat_g",
                       "CHO": "carbohydrate_g", "TOTSUG": "sugars_g", "AOACFIB": "fibre_g",
                       "ALCO": "alcohol_g"},
    "1.4 Inorganics": {"FE": "iron_mg", "MG": "magnesium_mg", "NA": "sodium_mg", "CA": "calcium_mg"},
    "1.5 Vitamins": {"FOLT": "folate_ug", "VITC": "vitamin_c_mg", "RETEQU": "vitamin_a_ug"},
}


def _val(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if v == "Tr":
        return 0.0
    if v in ("N", ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def build_cache() -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(XLSX, read_only=True)
    foods: dict[str, dict] = {}
    for sheet, wanted in NUTRIENTS.items():
        rows = wb[sheet].iter_rows(values_only=True)
        next(rows)
        codes = next(rows)
        next(rows)
        idx = {codes.index(c): name for c, name in wanted.items()}
        for r in rows:
            code = r[0]
            if not code:
                continue
            f = foods.setdefault(str(code).strip(), {"name": r[1], "description": r[2], "group": r[3]})
            for i, name in idx.items():
                f[name] = _val(r[i])
    CACHE.write_text(json.dumps(foods, indent=0, ensure_ascii=False))
    return foods


def load() -> dict:
    if CACHE.exists() and CACHE.stat().st_mtime >= XLSX.stat().st_mtime:
        return json.loads(CACHE.read_text())
    return build_cache()


def search(term: str, limit: int = 15) -> list[tuple[str, str]]:
    """Case-insensitive search on food name: every word in term must appear."""
    words = term.lower().split()
    out = []
    for code, f in load().items():
        name = (f["name"] or "").lower()
        if all(w in name for w in words):
            out.append((code, f["name"]))
    return out[:limit]


if __name__ == "__main__":
    import sys

    for code, name in search(" ".join(sys.argv[1:])):
        print(code, "|", name)
