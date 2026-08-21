# Contributing

Thanks for contributing.

This repository’s scope, phase ordering, and invariants are defined by `project_plan.md`.
Do not change architecture or frozen invariants without an explicit plan update.

## License of contributions

By contributing to this repository, you agree that your contributions are licensed under the project’s license (see `LICENSE`).

## Provenance / IP rules

- Do not submit code copied from proprietary or restricted sources.
- Do not paste large blocks of third-party code unless you have the right to do so and it is compatible with the repo license.
- Keep additions minimal, deterministic, and test-covered.

## AI-assisted contributions

AI-assisted development is allowed.
Contributors are responsible for ensuring:
- the contribution is compatible with the repo license
- third-party licenses are respected
- no restricted/copyrighted material is introduced

## Quality bar

- Add/extend regression tests for behavior changes.
- Verify before proposing completion:
  - `python scripts/run_pytests_fast.py`
  - `python scripts/run_ui_tests_parallel.py` (when UI was touched)
