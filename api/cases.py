"""Judged cases from the test bench.

A case is a GraphQL query plus a reviewer's verdict on each recipe it returned or excluded, and any
recipe they expected but didn't get. Cases are JSON files in review/cases/ (LARDER_CASES overrides),
so they can be committed. `python -m evals.judged_cases` re-runs every case and reports regressions.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api import library as lib
from api.schema import schema

ROOT = Path(__file__).resolve().parents[1]
CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class Judgement(BaseModel):
    recipe_id: str                                         # Larder id, e.g. "fx09" (not the base64 ID)
    name: str = ""
    outcome: Literal["returned", "excluded", "missing"]   # what the query did when it was judged
    verdict: Literal["right", "wrong", "unsure"]           # "missing" is always "wrong"
    note: str = ""


class Case(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=200)
    reviewer: str = ""
    query: str = Field(min_length=1)
    variables: dict = Field(default_factory=dict)
    judgements: list[Judgement] = Field(default_factory=list)
    note: str = ""
    rule_pack: str = ""                                   # set on save: the pack the verdicts were made against
    created: str = ""
    updated: str = ""


def cases_dir() -> Path:
    return Path(os.environ.get("LARDER_CASES") or ROOT / "review" / "cases")


def _path(case_id: str) -> Path:
    if not CASE_ID.match(case_id):
        raise HTTPException(400, "Case IDs use lower-case letters, digits and hyphens (up to 64).")
    return cases_dir() / f"{case_id}.json"


def load_case(case_id: str) -> Case:
    p = _path(case_id)
    if not p.exists():
        raise HTTPException(404, f"No case '{case_id}'.")
    return Case(**json.loads(p.read_text()))


def all_cases() -> list[Case]:
    d = cases_dir()
    return [Case(**json.loads(p.read_text())) for p in sorted(d.glob("*.json"))] if d.exists() else []


def save_case(case_id: str, case: Case) -> Case:
    p = _path(case_id)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = load_case(case_id) if p.exists() else None
    case = case.model_copy(update={"id": case_id, "rule_pack": lib.rule_pack(), "updated": now,
                                   "created": old.created if old else now})
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(case.model_dump(), indent=2, ensure_ascii=False) + "\n")
    tmp.replace(p)
    return case


# ---------- Checking a case against the current engine ----------

def outcomes(data) -> dict[str, str]:
    """Every recipe in a GraphQL response: "returned", or "excluded" if it sits under `excluded`
    or carries larder.allowed = false."""
    out: dict[str, str] = {}

    def walk(x, under_excluded=False):
        if isinstance(x, list):
            for i in x:
                walk(i, under_excluded)
        elif isinstance(x, dict):
            rid = lib.local_id(x["id"]) if isinstance(x.get("id"), str) else None
            if rid:
                larder = x.get("larder") or {}
                excluded = under_excluded or larder.get("allowed") is False
                if out.get(rid) != "returned":
                    out[rid] = "excluded" if excluded else "returned"
            for k, v in x.items():
                walk(v, under_excluded or k == "excluded")

    walk(data)
    return out


def run_query(query: str, variables: dict) -> tuple[dict | None, list[str]]:
    res = schema.execute_sync(query, variable_values=variables or None)
    return res.data, [str(e.message) for e in res.errors or []]


def status(j: Judgement, now: str) -> str:
    """holds / regression for verdicts the reviewer agreed with; open / fixed for ones they didn't."""
    if j.verdict == "unsure":
        return "unsure"
    wanted_returned = (j.outcome == "returned") == (j.verdict == "right") if j.outcome != "missing" else True
    met = (now == "returned") == wanted_returned
    if j.verdict == "right":
        return "holds" if met else "regression"
    return "fixed" if met else "open"


def check(case: Case) -> dict:
    data, errors = run_query(case.query, case.variables)
    if errors:
        return {"id": case.id, "name": case.name, "errors": errors, "results": [], "counts": {}}
    now = outcomes(data)
    results = []
    for j in case.judgements:
        current = now.get(j.recipe_id, "absent")
        results.append({**j.model_dump(), "now": current, "status": status(j, current)})
    counts = {s: sum(r["status"] == s for r in results) for s in ("holds", "regression", "open", "fixed", "unsure")}
    return {"id": case.id, "name": case.name, "errors": [], "results": results, "counts": counts,
            "rule_pack_then": case.rule_pack, "rule_pack_now": lib.rule_pack()}


# ---------- HTTP ----------

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("")
def list_cases() -> list[dict]:
    return [{"id": c.id, "name": c.name, "reviewer": c.reviewer, "judged": len(c.judgements),
             "rule_pack": c.rule_pack, "updated": c.updated} for c in all_cases()]


@router.get("/{case_id}")
def get_case(case_id: str) -> Case:
    return load_case(case_id)


@router.put("/{case_id}")
def put_case(case_id: str, case: Case) -> Case:
    return save_case(case_id, case)


@router.delete("/{case_id}")
def delete_case(case_id: str) -> dict:
    p = _path(case_id)
    if not p.exists():
        raise HTTPException(404, f"No case '{case_id}'.")
    p.unlink()
    return {"deleted": case_id}


@router.post("/{case_id}/check")
def check_case(case_id: str) -> dict:
    return check(load_case(case_id))
