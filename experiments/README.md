# Experiments

Use this directory for reproducible experiment notes and scripts.

Generated outputs belong in `runs/` or `reports/generated/`, which are ignored by git.

Each `zkfDO run` execution creates a directory under `runs/<run-id>/` containing:

- `result.json`: timing, status, exit code, seed, and last observed generation
- `stdout.log`: raw zkFuzz standard output
- `stderr.log`: raw zkFuzz standard error
