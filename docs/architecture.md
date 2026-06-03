# Architecture

`zkfDO` is organized as a Rust CLI that prepares and schedules zkFuzz work instead of reimplementing zkFuzz.

Planned flow:

1. Scan a Circom project.
2. Extract static target features.
3. Rank targets by risk and expected execution cost.
4. Schedule fuzzing under a fixed budget.
5. Run smoke fuzzing and adapt rankings.
6. Store results and generate reports.
