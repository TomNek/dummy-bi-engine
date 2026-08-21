# sample_project (manual UI verification)

This is a minimal, bootable DAX project that matches the repo loader schemas in `dax_project/loader.py`.

## What’s included

- `data/` small CSVs
- `model/tables/*.yaml` table metadata
- `model/measures.yaml` 2 measures
- `model/relationships.yaml` 1 relationship
- `reports/pages.yaml` 1 page
- `reports/visuals/v1.json` 1 bar visual (Sales by Category)

## 1) Build the DuckDB file (required)

The runtime UI executes queries against DuckDB. It does **not** automatically ingest CSVs.

From the repo root:

```powershell
py sample_project\init_duckdb.py
```

This creates `sample_project/sample.duckdb` with tables `Product` and `Sales`.

## 2) Run the UI

Install UI deps (one time):

```powershell
py -m pip install -r requirements-ui.txt
```

Set env vars and start the server:

```powershell
$env:DAX_PROJECT_PATH = "C:\Users\Thomas\Desktop\Python Projects\Dax to SQL Converter\sample_project"
$env:DAX_DUCKDB_PATH = "C:\Users\Thomas\Desktop\Python Projects\Dax to SQL Converter\sample_project\sample.duckdb"
py -m uvicorn dax_ui.server:app --reload
```

Open:

- http://127.0.0.1:8765/runtime/ui-react

## By-eye validation checklist

- UI loads without errors.
- Visual `Sales by Category` renders two bars.
- Expected totals:
  - Bikes Total Sales = 200 + 120 + 360 = 680
  - Accessories Total Sales = 75
  - Bikes Total Qty = 2 + 1 + 3 = 6
  - Accessories Total Qty = 5

## Quick API sanity checks

```powershell
curl -s "http://127.0.0.1:8000/runtime?project=$env:DAX_PROJECT_PATH" | Out-String
curl -s "http://127.0.0.1:8000/runtime/visuals/v1/render?project=$env:DAX_PROJECT_PATH&duckdb_path=$env:DAX_DUCKDB_PATH" | Out-String
```
