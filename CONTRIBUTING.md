# Contributing

Thanks for helping improve Dummy BI Engine.

## Before opening a change

- Keep changes within the public desktop edition described in `README.md`.
- Do not add excluded commercial features or compatibility code copied from proprietary products.
- Add or update regression tests for behavior changes.
- Never commit credentials, private data, generated build output, or local project files.

## Development checks

Run the focused Python tests for the area you changed. For frontend changes, also run:

```powershell
cd dax_ui/frontend
npm ci
npm run build
```

The public CI workflow runs the release validator, core tests, dependency audit, frontend build, and browser smoke tests.

## License of contributions

By submitting a contribution, you agree to license it under the repository's [PolyForm Noncommercial License 1.0.0](LICENSE). Only submit work you have the right to contribute. AI-assisted changes are welcome, but the contributor remains responsible for provenance, correctness, security, and third-party license compliance.
