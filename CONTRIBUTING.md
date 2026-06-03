# Contributing

Thanks for contributing to `zkfDO`.

## Workflow

1. Create a focused branch for each task.
2. Keep changes small enough to review comfortably.
3. Run formatting, linting, and tests before opening a pull request.
4. Link the related issue or task in the pull request description.

## Local Checks

```sh
cargo fmt
cargo clippy --all-targets --all-features -- -D warnings
cargo test
```

## Style

- Prefer clear module boundaries over large catch-all files.
- Keep CLI output stable enough for integration tests.
- Do not commit generated run data, compiled circuit artifacts, or local environment files.
