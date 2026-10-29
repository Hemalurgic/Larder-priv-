"""Re-run every judged case from the test bench (review/cases/) against the current engine.

    python -m evals.judged_cases [--show]

holds       the reviewer said right, and it still behaves that way
regression  the reviewer said right, and it has changed           -> exit code 1
open        the reviewer said wrong, and it hasn't been fixed yet
fixed       the reviewer said wrong, and it now behaves as they wanted
"""
from __future__ import annotations

import argparse
import sys

from api.cases import all_cases, check


def run(show: bool = False) -> int:
    regressions = errors = 0
    cases = all_cases()
    for case in cases:
        rep = check(case)
        if rep["errors"]:
            errors += 1
            print(f"ERROR {case.id}: {'; '.join(rep['errors'])}")
            continue
        c = rep["counts"]
        regressions += c["regression"]
        print(f"{case.id}: {c['holds']} hold, {c['regression']} regression, {c['open']} open, "
              f"{c['fixed']} fixed, {c['unsure']} unsure")
        for r in rep["results"]:
            if r["status"] == "regression" or (show and r["status"] in ("open", "fixed")):
                print(f"    {r['status'].upper()} {r['recipe_id']} {r['name']}: judged {r['outcome']}, "
                      f"now {r['now']}" + (f" ({r['note']})" if r["note"] else ""))
    print(f"Judged cases: {len(cases)} run, {regressions} regressions, {errors} errors")
    return 1 if regressions or errors else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="also list open and fixed judgements")
    sys.exit(run(ap.parse_args().show))
