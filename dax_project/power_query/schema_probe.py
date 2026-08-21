from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import execute_power_query_adapter
from .execution_strategy import build_schema_probe_summary


_ADAPTER_FUNCTION_BY_OPERATION = {
    "source_sql": "Sql.Database",
    "source_odbc": "Odbc.DataSource",
    "source_odata": "OData.Feed",
    "source_web": "Web.Contents",
    "source_sharepoint": "SharePoint.Files",
    "source_excel": "Excel.Workbook",
    "source_json": "Json.Document",
    "source_parquet": "Parquet.Document",
}


def _clean_schema(schema: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in schema or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("column") or "").strip()
        if not name:
            continue
        out.append({"name": name, "type": str(item.get("type") or "ANY")})
    return out


def _columns_from_schema(schema: Sequence[Mapping[str, Any]] | None) -> list[str]:
    return [str(item.get("name") or "") for item in _clean_schema(schema) if str(item.get("name") or "")]


def _safe_project_path(project_root: str | None, raw_path: str | None) -> Path | None:
    if not project_root or not raw_path:
        return None
    try:
        root = Path(project_root).resolve()
        path = Path(str(raw_path))
        candidate = path if path.is_absolute() else root / path
        resolved = candidate.resolve()
        if root == resolved or root in resolved.parents:
            return resolved
    except Exception:
        return None
    return None


def _csv_schema_from_options_or_file(
    *,
    node: Mapping[str, Any],
    source_paths_by_step: Mapping[str, str],
    project_root: str | None,
) -> tuple[list[dict[str, Any]], str]:
    args = node.get("args") if isinstance(node.get("args"), Mapping) else {}
    options = args.get("csv_options") if isinstance(args.get("csv_options"), Mapping) else {}
    column_count = options.get("columns")
    if isinstance(column_count, str) and column_count.isdigit():
        column_count = int(column_count)
    if isinstance(column_count, int) and column_count > 0:
        return ([{"name": f"Column{index}", "type": "TEXT"} for index in range(1, column_count + 1)], "csv_options")

    source_ref = str(args.get("source_ref") or "")
    raw_path = source_paths_by_step.get(source_ref)
    path = _safe_project_path(project_root, raw_path)
    if not path or not path.exists() or not path.is_file():
        return ([], "unresolved_file")

    delimiter = str(options.get("delimiter") or ",")
    if delimiter.lower() == "#(tab)":
        delimiter = "\t"
    try:
        with path.open("r", encoding=str(options.get("encoding") or "utf-8"), newline="") as handle:
            first_row = next(csv.reader(handle, delimiter=delimiter), [])
    except Exception:
        return ([], "file_read_failed")
    if not first_row:
        return ([], "empty_file")
    return ([{"name": f"Column{index}", "type": "TEXT"} for index in range(1, len(first_row) + 1)], "csv_file_sample")


def _adapter_schema(
    function_name: str,
    *,
    project_root: str | None,
    credential_profile_id: str | None,
    fixture_mode: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = execute_power_query_adapter(
        function_name,
        {
            "function_name": function_name,
            "project_root": project_root,
            "credential_profile_id": credential_profile_id,
            "fixture_mode": fixture_mode,
        },
        operation="schema",
    ).to_dict()
    return _clean_schema(result.get("schema") if isinstance(result, Mapping) else []), {
        "execution_state": result.get("execution_state"),
        "credential_profile_id": result.get("credential_profile_id"),
        "folding_capability": result.get("folding_capability"),
        "diagnostics": [
            {
                "code": item.get("code"),
                "severity": item.get("severity"),
                "message": item.get("message"),
            }
            for item in result.get("diagnostics") or []
            if isinstance(item, Mapping)
        ][:3],
    }


def build_power_query_schema_probe(
    *,
    ir_nodes: Sequence[Mapping[str, Any]],
    plan_steps: Sequence[Mapping[str, Any]],
    project_root: str | None = None,
    schema_probe_mode: str = "plan",
    credential_profile_id: str | None = None,
    fixture_mode: bool = True,
) -> dict[str, Any]:
    """Build a real schema probe report plus lowering hints.

    ``schema_probe_mode='plan'`` preserves the older metadata-only behavior.
    ``'execute'`` asks fixture/live adapters or safe local file probes for
    schemas, then exposes ``resolved_columns_by_step`` for relational lowering.
    """

    base = build_schema_probe_summary(plan_steps)
    mode = str(schema_probe_mode or "plan").strip().lower()
    if mode in {"off", "disabled", "none"}:
        return {**base, "mode": "off", "status": "disabled"}
    if mode not in {"execute", "executed", "probe"}:
        return {**base, "mode": "plan"}

    source_paths_by_step: dict[str, str] = {}
    schemas_by_step: dict[str, list[dict[str, Any]]] = {}
    candidates: list[dict[str, Any]] = []

    for node in ir_nodes:
        op = str(node.get("op") or "")
        step_id = str(node.get("m_step_id") or node.get("id") or "")
        args = node.get("args") if isinstance(node.get("args"), Mapping) else {}
        if op == "source_file" and args.get("path"):
            source_paths_by_step[step_id] = str(args.get("path"))

    for node in ir_nodes:
        op = str(node.get("op") or "")
        step_id = str(node.get("m_step_id") or node.get("id") or "")
        if not step_id:
            continue
        schema: list[dict[str, Any]] = []
        schema_source = ""
        diagnostics: list[dict[str, Any]] = []

        if op == "source_csv":
            schema, schema_source = _csv_schema_from_options_or_file(
                node=node,
                source_paths_by_step=source_paths_by_step,
                project_root=project_root,
            )
        elif op in _ADAPTER_FUNCTION_BY_OPERATION:
            function_name = _ADAPTER_FUNCTION_BY_OPERATION[op]
            try:
                schema, adapter_meta = _adapter_schema(
                    function_name,
                    project_root=project_root,
                    credential_profile_id=credential_profile_id,
                    fixture_mode=fixture_mode,
                )
                schema_source = f"adapter:{function_name}"
                diagnostics = [dict(item) for item in adapter_meta.get("diagnostics") or [] if isinstance(item, Mapping)]
            except Exception as exc:  # noqa: BLE001
                schema_source = f"adapter:{function_name}"
                diagnostics = [{"code": "PQ_SCHEMA_PROBE_FAILED", "severity": "warning", "message": str(exc)}]

        if schema:
            schemas_by_step[step_id] = schema
            candidates.append(
                {
                    "step_id": step_id,
                    "operation": op,
                    "status": "resolved",
                    "schema_source": schema_source or "schema_probe",
                    "schema": schema,
                    "columns": _columns_from_schema(schema),
                    "diagnostics": diagnostics,
                }
            )
        elif op in {"source_csv", *tuple(_ADAPTER_FUNCTION_BY_OPERATION)}:
            candidates.append(
                {
                    "step_id": step_id,
                    "operation": op,
                    "status": "unresolved",
                    "schema_source": schema_source or "schema_probe",
                    "diagnostics": diagnostics,
                }
            )

    for node in ir_nodes:
        step_id = str(node.get("m_step_id") or node.get("id") or "")
        args = node.get("args") if isinstance(node.get("args"), Mapping) else {}
        base_ref = str(args.get("source_ref") or "")
        if step_id and base_ref and base_ref in schemas_by_step and step_id not in schemas_by_step:
            schemas_by_step[step_id] = list(schemas_by_step[base_ref])

    base_candidates = [
        dict(item)
        for item in base.get("candidates") or []
        if isinstance(item, Mapping)
    ]
    for item in base_candidates:
        step_id = str(item.get("step_id") or "")
        if step_id in schemas_by_step and not any(str(c.get("step_id") or "") == step_id for c in candidates):
            schema = schemas_by_step[step_id]
            candidates.append(
                {
                    **item,
                    "status": "resolved_from_dependency",
                    "schema_source": "dependency_schema",
                    "schema": schema,
                    "columns": _columns_from_schema(schema),
                }
            )

    resolved_count = len([item for item in candidates if str(item.get("status") or "").startswith("resolved")])
    required = bool(base.get("required")) and resolved_count < len(base_candidates)
    status = "resolved" if resolved_count and not required else "partial" if resolved_count else str(base.get("status") or "not_required")
    return {
        **base,
        "mode": "execute",
        "required": required,
        "status": status,
        "candidate_count": len(candidates),
        "resolved_count": resolved_count,
        "candidates": candidates,
        "resolved_columns_by_step": {
            step_id: _columns_from_schema(schema)
            for step_id, schema in schemas_by_step.items()
            if _columns_from_schema(schema)
        },
    }
