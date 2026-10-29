# Judged cases

Saved from the test bench (`/testbench`). Each file is one query plus a reviewer's verdict on every
recipe it returned or excluded, and any recipe they expected but didn't get.

Commit them. `python -m evals.judged_cases --show` re-runs every case against the current engine:

- **holds**: the reviewer said right, and it still behaves that way
- **regression**: the reviewer said right, and it has changed (exit code 1)
- **open**: the reviewer said wrong, and it hasn't been fixed yet
- **fixed**: the reviewer said wrong, and it now behaves as they wanted

A rule pack change that turns cases into regressions needs the same dietitian sign-off as the change itself.
