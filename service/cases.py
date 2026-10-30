"""Judged cases from the test bench.

A case is a GraphQL query plus a reviewer's verdict on each recipe it returned or excluded, and any
recipe they expected but didn't get. Cases are JSON files in review/cases/ (LARDER_CASES overrides),
so they can be committed, or in Postgres when DATABASE_URL is set (hosted, where the disk doesn't
persist). `python -m service.cases export` copies hosted cases into review/cases/ to commit.
`python -m evals.judged_cases` re-runs every case and reports regressions.
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

from service import library as lib
from service.schema import schema

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


def database_url() -> str | None:
    """Postgres when one is connected (Vercel's Neon integration sets DATABASE_URL); files otherwise."""
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or None


class FileStore:
    """One JSON file per case, for local use: the files are what gets committed."""

    def __init__(self, root: Path):
        self.root = root

    def get(self, case_id: str) -> dict | None:
        p = self.root / f"{case_id}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def all(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.root.glob("*.json"))] if self.root.exists() else []

    def put(self, case_id: str, body: dict) -> None:
        p = self.root / f"{case_id}.json"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
            tmp.replace(p)
        except OSError:
            raise HTTPException(503, "This server can't save cases to disk. Connect a Postgres database "
                                     "and set DATABASE_URL.") from None

    def delete(self, case_id: str) -> bool:
        p = self.root / f"{case_id}.json"
        if not p.exists():
            return False
        p.unlink()
        return True


class PgStore:
    """A single table of case documents, for hosted use where the disk doesn't persist."""

    def __init__(self, url: str):
        self.url = url

    def _conn(self):
        import psycopg

        conn = psycopg.connect(self.url, autocommit=True)
        conn.execute("create table if not exists larder_cases (id text primary key, body jsonb not null)")
        return conn

    def get(self, case_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("select body from larder_cases where id = %s", (case_id,)).fetchone()
        return row[0] if row else None

    def all(self) -> list[dict]:
        with self._conn() as c:
            return [r[0] for r in c.execute("select body from larder_cases order by id")]

    def put(self, case_id: str, body: dict) -> None:
        from psycopg.types.json import Jsonb

        with self._conn() as c:
            c.execute("insert into larder_cases (id, body) values (%s, %s) "
                      "on conflict (id) do update set body = excluded.body", (case_id, Jsonb(body)))

    def delete(self, case_id: str) -> bool:
        with self._conn() as c:
            return c.execute("delete from larder_cases where id = %s", (case_id,)).rowcount > 0


def store() -> FileStore | PgStore:
    url = database_url()
    return PgStore(url) if url else FileStore(cases_dir())


def _check_id(case_id: str) -> str:
    if not CASE_ID.match(case_id):
        raise HTTPException(400, "Case IDs use lower-case letters, digits and hyphens (up to 64).")
    return case_id


def load_case(case_id: str) -> Case:
    body = store().get(_check_id(case_id))
    if body is None:
        raise HTTPException(404, f"No case '{case_id}'.")
    return Case(**body)


def all_cases() -> list[Case]:
    return [Case(**b) for b in store().all()]


def save_case(case_id: str, case: Case) -> Case:
    s = store()
    old = s.get(_check_id(case_id))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    case = case.model_copy(update={"id": case_id, "rule_pack": lib.rule_pack(), "updated": now,
                                   "created": old["created"] if old else now})
    s.put(case_id, case.model_dump())
    return case


def export_cases(to: Path) -> list[str]:
    """Copy every case from the current store (e.g. the hosted database) into JSON files to commit."""
    files = FileStore(to)
    out = []
    for case in all_cases():
        files.put(case.id, case.model_dump())
        out.append(case.id)
    return out


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
    if not store().delete(_check_id(case_id)):
        raise HTTPException(404, f"No case '{case_id}'.")
    return {"deleted": case_id}


@router.post("/{case_id}/check")
def check_case(case_id: str) -> dict:
    return check(load_case(case_id))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Export judged cases from the database to JSON files.")
    ap.add_argument("command", choices=["export"])
    ap.add_argument("--to", default=str(ROOT / "review" / "cases"))
    a = ap.parse_args()
    if not database_url():
        raise SystemExit("Set DATABASE_URL to the hosted database first (Vercel: Storage > your database > .env).")
    ids = export_cases(Path(a.to))
    print(f"Exported {len(ids)} cases to {a.to}")
