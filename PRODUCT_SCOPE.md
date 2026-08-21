# Semantic Migration Workbench 0.1.0-alpha.1

Semantic Migration Workbench is a local Windows technical preview for inspecting,
adapting, and validating DAX-style semantic models and Power Query M workflows on
DuckDB. It is not a Power BI replacement and does not claim complete DAX, M, or
Power BI compatibility.

## Intended users

- BI engineers evaluating a migration away from a closed semantic engine.
- Developers validating DAX-style measures against DuckDB.
- Data engineers inspecting and adapting Power Query M pipelines.

## Certified alpha workflow

1. Open or create a local project.
2. Import local CSV, Parquet, JSON, Excel, or DuckDB-backed data.
3. Preserve and inspect Power Query M in Transform Studio.
4. Parse queries, inspect dependencies and steps, preview supported operations,
   profile results, and review explicit compatibility diagnostics.
5. Define relationships and DAX-style measures.
6. Compile supported measures to DuckDB SQL and preview results locally.
7. Build a local validation report with the stable visual subset.
8. Save, close, reopen, and verify the project without hidden persistence.

## Support levels

- **Certified:** covered by a release-gate test and a representative local fixture.
- **Experimental:** implemented and testable, but not part of the compatibility promise.
- **Preserve only:** imported without data loss; execution requires later adaptation.
- **Excluded:** intentionally absent from the alpha.

The generated compatibility report is authoritative for an imported query. A
function appearing in a catalog is not, by itself, a claim of live connector or
semantic parity.

## Certified in this alpha

- Local authoring mode on Windows.
- Local project open/create/save/reopen.
- Lossless M text storage, parsing, query graph, step inspection, diagnostics,
  preview, profiling, and explicit-save editing.
- Local file and DuckDB source workflows covered by the release fixtures.
- Common scalar, aggregate, iterator, filter-context, and table-expression DAX
  shapes covered by the release conformance suite.
- Basic local report preview and export for the release visual subset.

## Experimental

- SQL-family and OData connectors.
- Power BI PBIP/TMDL/report metadata import.
- Advanced matrix/tablix formatting and uncommon visual types.
- Complex relationship activation, time-intelligence, and window DAX shapes not
  yet included in the certified conformance set.
- Live cloud, SaaS, cube, and Fabric connector adapters.

## Excluded from 0.1.0-alpha.1

- Report Server, public viewer URLs, and multi-user collaboration.
- Docker/server deployment.
- Subscriptions and scheduled delivery.
- ML analytics, forecasting, decision intelligence, and report auto-generation.
- Marketplace, Lakehouse, OneLake, workspace environments, and promotion flows.
- A claim of pixel-perfect Power BI rendering or universal DAX/M compatibility.

## Release gates

The alpha may be packaged only when:

- community/core Python tests pass;
- the certified DAX conformance set passes;
- Power Query release fixtures pass;
- the React type-check and production build pass;
- open-core classification and community artifact validation pass;
- a clean Windows sidecar and installer build pass self-tests; and
- install/open/import/preview/save/reopen/uninstall smoke evidence is recorded.

See `COMPATIBILITY.md` for the exact certified/experimental/excluded contract.
See `docs/first_version_deployment.md` for the current deployment decision and
the shortest path from private alpha to public beta.
