# Dummy BI Engine — Source-Available Desktop Edition

This repository contains the local source-available edition of Dummy BI Engine. It uses the same application shell as the full desktop product.

## Download the Windows desktop app

**[Download the latest Windows x64 installer](https://github.com/TomNek/dummy-bi-engine/releases/latest)**

[Product page](https://www.dummy-bi.com/engine) · [Release notes and checksums](https://github.com/TomNek/dummy-bi-engine/releases/latest) · [All releases](https://github.com/TomNek/dummy-bi-engine/releases)

This is an early feedback build. The installer is not yet Authenticode-signed, so Windows SmartScreen may display a warning.

1. Connect data with any of the project's existing connectors.
2. Inspect tables, columns, measures, and relationships in the semantic model.
3. Compile supported DAX expressions to DuckDB SQL and evaluate the result.
4. Build complete local reports with all Plotly visuals and table.

This edition excludes Transform Studio, Stories, EDU relationships, ML analytics and forecasting, report autogeneration, matrix/static/IBCS visuals, subscriptions and scheduled delivery, server/cloud and marketplace features, and PBIP/TMDL import. Their implementation source is removed from the public snapshot; minimal compatibility stubs keep the shared shell buildable.

## Technical overview

Dummy BI Engine is a local desktop BI authoring application. The public edition contains the same React application shell, local project format, semantic model, DAX compiler, DuckDB execution layer, and report canvas used by the desktop product. It does not require a hosted service.

```text
Tauri desktop shell
  -> starts a bundled Python/FastAPI sidecar on 127.0.0.1 and a random port
  -> generates a random 256-bit authentication token for that launch
  -> opens the React authoring UI in the desktop webview
  -> React calls the authenticated local runtime API
  -> the runtime loads the project and semantic model
  -> DAX is parsed, bound, planned, and lowered to DuckDB SQL
  -> DuckDB queries local or explicitly configured data sources
  -> results are rendered as Plotly figures or tables
```

### Included subsystems

| Area | Included functionality |
| --- | --- |
| Desktop | Windows Tauri application, native folder selection, local sidecar lifecycle, update notification and install/restart flow |
| Projects | Create, open, recent projects, save, Save As, import/export archive, refresh, and local project metadata |
| Views | Report, Data, and Model views using the shared application shell |
| Data | Local and remote connectors listed below, previews, table metadata, and DuckDB-backed query execution |
| Semantic model | Tables, columns, measures, relationships, hierarchies, calculation groups, field parameters, security metadata, and model layouts |
| DAX | Parser, semantic binding, filter/context rewriting, query planning, DuckDB SQL generation, measures, calculated columns/tables, and visual calculations |
| Reports | Pages, canvas layout, filters, slicers, interactions, drill behavior, bookmarks, themes, formatting, visual persistence, import/export, and report metadata |
| Visuals | Every public Plotly visual registered in `open_core_mvp.yml`, plus the table visual |
| Utilities | Formula bar, field/model panes, performance analysis, DAX analysis, selection, undo/redo, canvas settings, and local diagnostics |

### Deliberately excluded

The public snapshot contains no implementation for Transform Studio/Power Query authoring, Stories, EDU relationship explanations, ML analytics or forecasting, report autogeneration, matrix/static/IBCS/custom visuals, subscriptions, scheduled delivery, multi-user server hosting, marketplace/cloud deployment, or PBIP/TMDL import. Edition flags remove these workflows from the UI, backend registration omits their routes, and the publisher removes their implementation files.

### Local project format

A project is an ordinary directory rather than a proprietary database file. Its main structure is:

```text
project/
  model/                 tables, measures, relationships, hierarchies,
                         calculation groups, field parameters, security
  reports/               pages, visuals, filters, slicers, bookmarks,
                         themes, model layouts and selections
  data/                  optional project-local source files
  *.duckdb               optional local DuckDB database
```

YAML and JSON definitions are loaded by `dax_project`, validated into the internal semantic model, and persisted back to the same project directory. Report visuals are individual JSON definitions, which keeps projects inspectable and version-control friendly.

### Runtime and security boundary

The packaged Tauri process owns the backend lifecycle. Each launch uses a random token passed directly to the sidecar; protected API requests must present that token. The backend listens only on loopback. When the source edition is run without Tauri authentication, filesystem operations are constrained to the configured `DAX_PROJECT_PATH` workspace. Project selection is intentional local filesystem access and uses the operating system's native folder dialog in the desktop build.

The application has no product telemetry. Connector secrets are used only by the local process, and excluded Power Query credential-storage code is not present in this repository.

### Updates

The updater reads `latest.json` from this repository. When a newer signed version is available, the application displays an update prompt. Choosing **Update now** downloads the installer artifact, applies it, and restarts the desktop application. Declining leaves the current version running.

### Source and release boundary

`open_core_boundary.yml` is the source allowlist. `tools/publish_open_core_mvp.py` creates a clean public tree, removes excluded implementations and internal documentation, rewrites the public package identities, and installs compatibility stubs only where the shared shell requires an import. `tools/validate_open_core_mvp.py` rejects a release artifact if excluded code, unexpected root documents, private product naming, or invalid build configuration is present.

## Run locally

Requirements: Python 3.11+, Node.js 20+, and npm.

```powershell
python -m pip install -r requirements-ui.txt
cd dax_ui/frontend
npm ci
```

Start the backend from the repository root. The explicit workspace becomes the only project root accepted by the unauthenticated development server:

```powershell
python -m dax_ui.open_core_main --workspace sample_project --host 127.0.0.1 --port 8000
```

Start the public frontend in another terminal:

```powershell
cd dax_ui/frontend
npm run dev:open-core
```

Open `http://127.0.0.1:5174`. The project path is resolved by the backend, so `sample_project` works when the backend is launched from the repository root.

## Included connectors

CSV, Parquet, JSON, folders, Excel, text, binary/blob, DuckDB, SQLite, PostgreSQL, MySQL, HTTP, S3, Azure Blob, Cloudflare R2, Delta Lake, and Iceberg.

Remote credentials and data are used by the locally running process. This feedback build has no product telemetry. Do not post credentials, private connection strings, or sensitive sample data in an issue.

## Included Plotly visuals

All 31 currently registered Plotly Express and Plotly graph-object visuals are included, plus the table visual. Matrix is excluded.

## What feedback is useful?

Please report the shortest reproducible workflow and include:

- connector type and a safe description of the source;
- DAX expression and generated SQL, with sensitive names anonymized;
- expected versus actual result;
- semantic-model shape (tables, important columns, relationships);
- visual type and field assignments;
- Python, Node.js, and operating-system versions.

Use the open-core feedback issue template. The questions we care about most are: does the compiler produce trustworthy SQL, is the semantic model understandable, can you connect realistic data without friction, and which missing core workflow blocks a second session?

## Publish and verify a clean artifact

```powershell
python tools/publish_open_core_mvp.py --output dist/open_core_mvp
python tools/validate_open_core_mvp.py dist/open_core_mvp
```

The publisher is copy-only. It never pushes to GitHub or another remote.

## Support development

If Dummy BI Engine is useful to you, you can support continued development through the funding link shown in the repository sidebar.

## License

Dummy BI Engine is source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, study, modify, and redistribute it for noncommercial purposes. Commercial use is not granted. Contact the maintainer if you need commercial rights.

This is intentionally not described as an OSI-approved open-source license because it restricts commercial use.

## Windows desktop releases

Releases are built from the validated public snapshot as a Tauri/NSIS desktop
installer, smoke-tested, and attached with checksums to the public GitHub Release.

The installed desktop app checks the signed public update feed daily. When a new release is available it offers **Update now**, installs the update, and restarts the application.
