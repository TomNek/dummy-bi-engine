# DAX to SQL — Open-core feedback build

This is a deliberately focused, local-first workbench for testing the project's core idea:

1. Connect data with any of the project's existing connectors.
2. Inspect tables, columns, measures, and relationships in the semantic model.
3. Compile supported DAX expressions to DuckDB SQL and evaluate the result.
4. Preview the data and explore it with the complete existing Plotly chart set.

The feedback build does **not** contain custom SVG/IBCS visuals, Tableau visuals or import, static report objects, matrix/table report renderers, report auto-generation, ML features, licensing, subscriptions, or the multi-user report server. The small HTML data grid is included only to validate connections and chart inputs.

## Run locally

Requirements: Python 3.11+, Node.js 20+, and npm.

```powershell
python -m pip install -r requirements-ui.txt
cd dax_ui/frontend
npm ci
```

Start the backend from the repository root:

```powershell
$env:DAX_PROJECT_PATH = "sample_project"
python -m uvicorn dax_ui.open_core_app:app --host 127.0.0.1 --port 8000
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

All 31 currently registered Plotly Express and Plotly graph-object visuals are included: standard bar/line/area/scatter/pie and combo charts, statistical charts, funnels, density charts, hierarchical charts, polar charts, bubbles, 3D charts, financial charts, waterfall, gauge, and Sankey.

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

## Windows desktop releases

The private development repository includes a guarded GitHub Actions path that
publishes this exact validated source snapshot to a separate public repository,
builds the same snapshot as a Tauri/NSIS desktop installer, smoke-tests it, and
attaches checksummed artifacts to the public GitHub Release. Setup and release
instructions are in [`OPEN_CORE_RELEASE.md`](OPEN_CORE_RELEASE.md).
