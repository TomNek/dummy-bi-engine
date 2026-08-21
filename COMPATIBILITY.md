# Alpha compatibility contract

This contract applies to **Semantic Migration Workbench 0.1.0-alpha.1** on
Windows. “Certified” means the behavior is exercised by `tools/run_alpha_gate.py`;
it does not mean full Power BI compatibility.

| Area | Certified | Experimental / preserve-only | Not in alpha |
|---|---|---|---|
| Projects | Local folder projects; open, parse, save, and reopen | PBIP/TMDL metadata import | Shared/cloud projects |
| Data | Local CSV, Parquet, JSON, Excel, and DuckDB workflows represented by release fixtures | SQL-family and OData connectors | SaaS/cube/Fabric live connections |
| Power Query M | Text preservation, parser, step/dependency inspection, diagnostics, preview/profile, and the release-fixture transformations | Functions/connectors reported by compatibility diagnostics | Claim of complete M parity |
| DAX | 320/320 expressions in the DuckDB conformance corpus; basic relationship filters and matrix totals | Advanced relationship activation, time intelligence, and uncommon window semantics outside that corpus | Claim of complete DAX parity |
| Reports | Local preview with the basic visual/matrix subset used by the sample project gate | Advanced matrix formatting and uncommon visual types | Pixel-perfect Power BI rendering |
| Runtime | Single-user Windows desktop with an NSIS installer and local Python sidecar | Developer-only local HTTP server | MSI for prerelease versions, Docker, Report Server, public URLs, collaboration |

## Representative projects

- `sample_project` is the certified end-to-end local fixture. The gate requires
  its semantic model, pages, and visual definitions to load together.
- `adventureworks_project` is an internal import-compatibility fixture. Loading
  its model/report metadata is checked, but feature-by-feature rendering is not
  certified for this alpha.

For any imported Power Query, the compatibility diagnostics shown by the app are
authoritative. Unsupported operations should be preserved and reported, never
silently described as equivalent.
