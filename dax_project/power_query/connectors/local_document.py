from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .common import LiveConnectorResponse, blocked_response, configured_response, infer_schema_from_records, rows_from_records


def _project_path(project_root: str | None, raw_path: Any) -> Path:
    root = Path(project_root or ".").resolve()
    path = Path(str(raw_path or ""))
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("Path escapes the project root.")
    return resolved


def _file_meta(path: Path) -> list[Any]:
    data = path.read_bytes()
    return [data, str(path), len(data), hashlib.sha256(data).hexdigest()]


def _folder_rows(path: Path, *, recursive: bool) -> list[list[Any]]:
    iterator = path.rglob("*") if recursive else path.iterdir()
    rows: list[list[Any]] = []
    for item in sorted(iterator, key=lambda p: str(p).lower()):
        if not item.is_file():
            continue
        rows.append([item.name, item.suffix, str(item.parent), item.stat().st_size, item.read_bytes()])
    return rows


def _csv_rows(path: Path | None, text: str | None) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    content = text if text is not None else (path.read_text(encoding="utf-8-sig") if path else "")
    parsed = list(csv.reader(content.splitlines()))
    if not parsed:
        return [], []
    headers = [str(cell or f"Column{idx + 1}") for idx, cell in enumerate(parsed[0])]
    rows = parsed[1:] if len(parsed) > 1 else []
    schema = [{"name": header, "type": "TEXT"} for header in headers]
    return schema, [list(row) for row in rows]


def _json_rows(path: Path | None, text: str | None) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    payload = json.loads(text if text is not None else (path.read_text(encoding="utf-8") if path else "null"))
    records = payload if isinstance(payload, list) else [payload]
    schema = infer_schema_from_records(records)
    return schema, rows_from_records(records, schema)


def execute_local_document(
    *,
    function_name: str,
    operation: str,
    context: Any,
) -> LiveConnectorResponse:
    options = dict(getattr(context, "options", {}) or {})
    profile_id = getattr(context, "credential_profile_id", None)
    try:
        if function_name == "File.Contents":
            raw_path = options.get("path") or options.get("file")
            if not raw_path:
                return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_LOCAL_DOCUMENT_NOT_CONFIGURED", message="File.Contents live execution requires adapter_options.path or adapter_options.file.", connector_id="file", profile_id=profile_id, privacy_level="private")
            path = _project_path(getattr(context, "project_root", None), raw_path)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(str(path))
            schema = [{"name": "Content", "type": "BINARY"}, {"name": "Path", "type": "TEXT"}, {"name": "Size", "type": "NUMBER"}, {"name": "Hash", "type": "TEXT"}]
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=[_file_meta(path)], connector_id="file", profile_id=profile_id, source={"path": str(path)}, folding_capability="not_foldable", privacy_level="private")

        if function_name in {"Folder.Contents", "Folder.Files"}:
            raw_path = options.get("path") or options.get("folder")
            if not raw_path:
                return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_LOCAL_DOCUMENT_NOT_CONFIGURED", message=f"{function_name} live execution requires adapter_options.path or adapter_options.folder.", connector_id="folder", profile_id=profile_id, privacy_level="private")
            path = _project_path(getattr(context, "project_root", None), raw_path)
            if not path.exists() or not path.is_dir():
                raise FileNotFoundError(str(path))
            schema = [{"name": "Name", "type": "TEXT"}, {"name": "Extension", "type": "TEXT"}, {"name": "Folder Path", "type": "TEXT"}, {"name": "Size", "type": "NUMBER"}, {"name": "Content", "type": "BINARY"}]
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=_folder_rows(path, recursive=function_name == "Folder.Files"), connector_id="folder", profile_id=profile_id, source={"path": str(path)}, folding_capability="not_foldable", privacy_level="private")

        if function_name == "Csv.Document":
            path = _project_path(getattr(context, "project_root", None), options.get("path")) if options.get("path") else None
            schema, rows = _csv_rows(path, options.get("text"))
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows, connector_id="csv", profile_id=profile_id, source={"path": str(path) if path else "inline"}, folding_capability="supported", privacy_level="private")

        if function_name == "Json.Document":
            path = _project_path(getattr(context, "project_root", None), options.get("path")) if options.get("path") else None
            schema, rows = _json_rows(path, options.get("text"))
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows, connector_id="json", profile_id=profile_id, source={"path": str(path) if path else "inline"}, folding_capability="supported", privacy_level="private")

        if function_name == "Excel.CurrentWorkbook":
            objects = options.get("objects")
            if not isinstance(objects, list):
                return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="Excel.CurrentWorkbook live execution requires adapter_options.objects from imported workbook metadata.", connector_id="excel_current_workbook", profile_id=profile_id, privacy_level="private")
            schema = [{"name": "Name", "type": "TEXT"}, {"name": "Content", "type": "TABLE"}, {"name": "Kind", "type": "TEXT"}]
            rows = [[item.get("name"), item.get("content", []), item.get("kind", "Table")] for item in objects if isinstance(item, Mapping)]
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows, connector_id="excel_current_workbook", profile_id=profile_id, folding_capability="not_foldable", privacy_level="private")

        if function_name == "Excel.Workbook":
            try:
                import openpyxl  # type: ignore
            except Exception:
                return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message="Excel.Workbook live execution requires openpyxl.", connector_id="excel", profile_id=profile_id, privacy_level="private")
            raw_path = options.get("path") or options.get("file")
            if not raw_path:
                return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_LOCAL_DOCUMENT_NOT_CONFIGURED", message="Excel.Workbook live execution requires adapter_options.path or adapter_options.file.", connector_id="excel", profile_id=profile_id, privacy_level="private")
            path = _project_path(getattr(context, "project_root", None), raw_path)
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            schema = [{"name": "Name", "type": "TEXT"}, {"name": "Data", "type": "TABLE"}, {"name": "Item", "type": "TEXT"}, {"name": "Kind", "type": "TEXT"}, {"name": "Hidden", "type": "LOGICAL"}]
            rows = []
            for sheet in workbook.worksheets:
                values = [list(row) for row in sheet.iter_rows(values_only=True)]
                rows.append([sheet.title, values, sheet.title, "Sheet", sheet.sheet_state != "visible"])
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows, connector_id="excel", profile_id=profile_id, source={"path": str(path)}, folding_capability="not_foldable", privacy_level="private")

        if function_name == "Parquet.Document":
            try:
                import pandas as pd  # type: ignore
            except Exception:
                return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message="Parquet.Document live execution requires pandas with a parquet engine.", connector_id="parquet", profile_id=profile_id, privacy_level="private")
            raw_path = options.get("path") or options.get("file")
            if not raw_path:
                return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_LOCAL_DOCUMENT_NOT_CONFIGURED", message="Parquet.Document live execution requires adapter_options.path or adapter_options.file.", connector_id="parquet", profile_id=profile_id, privacy_level="private")
            path = _project_path(getattr(context, "project_root", None), raw_path)
            frame = pd.read_parquet(path)
            records = frame.head(int(options.get("limit") or 100)).to_dict(orient="records")
            schema = [{"name": str(col), "type": str(dtype)} for col, dtype in frame.dtypes.items()]
            return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema), connector_id="parquet", profile_id=profile_id, source={"path": str(path)}, folding_capability="supported", privacy_level="private")

        if function_name == "Pdf.Tables":
            return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message="Pdf.Tables live execution requires an optional PDF table extraction dependency.", connector_id="pdf", profile_id=profile_id, privacy_level="private")
        if function_name == "RData.FromBinary":
            return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message="RData.FromBinary live execution requires an optional RData reader dependency.", connector_id="rdata", profile_id=profile_id, privacy_level="private")
    except Exception as exc:  # noqa: BLE001
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_LOCAL_DOCUMENT_ERROR", message=str(exc), connector_id="local_document", profile_id=profile_id, privacy_level="private")
    return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_LOCAL_DOCUMENT_NOT_IMPLEMENTED", message=f"No local document adapter path for {function_name}.", connector_id="local_document", profile_id=profile_id, privacy_level="private")
