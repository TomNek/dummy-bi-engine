"""Auto-extracted route module from dax_ui.server._runtime_routes."""

import copy
import datetime
import json
import logging
import os
import re
import time
import uuid
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Optional

from starlette.requests import Request

import dax_compiler
from dax_engine.ir import MeasureRef, ir_to_dict
from dax_engine.planner import VisualQuerySpec, plan_card_query, plan_visual_query
from dax_engine.planner.visual_planner import resolve_facade_column_refs, resolve_params
from dax_project import get_measure, list_measures, load_project
from dax_project.expr_json import parse_expr
from dax_project.introspection import list_columns, list_tables
from dax_project.security import apply_ols, get_role, resolve_role_name
from dax_project.errors import NotFoundError
from dax_project.save import (
    delete_column_yaml,
    delete_measure_yaml,
    delete_table_yaml,
    update_measure_yaml,
    upsert_column_yaml,
    upsert_table_yaml,
    load_report_filters,
    load_calc_group_selections,
    load_calculation_groups_yaml,
    load_field_parameters_yaml,
    load_slicer_defs,
    load_slicer_instances,
    load_slicers,
    save_report_filters,
    save_calc_group_selections,
    save_calculation_groups_yaml,
    save_field_parameters_yaml,
    save_slicer_defs,
    save_slicer_instances,
    save_slicers,
    save_security_yaml,
    flatten_calc_group_selections,
    resolve_effective_calc_group_selections,
    load_field_parameter_selections,
    save_field_parameter_selections,
    flatten_field_parameter_selections,
    resolve_effective_field_parameter_selections,
    load_what_if_selections,
    save_what_if_selections,
    flatten_what_if_selections,
    resolve_effective_what_if_selections,
    save_pages,
    load_bookmarks,
    save_bookmarks,
)
from dax_project.visual_types import load_visual_type_registry

from dax_ui.server._runtime_helpers import *  # noqa: F403
from dax_ui.server._ir_walkers import (
    _collect_expr_refs_from_json,
    _ols_hidden_refs_for_visual,
    _is_booleanish_security_filter,
)
from dax_ui.server._security import (
    _security_roles_to_json,
    _collect_param_refs,
    _collect_column_refs,
    _collect_measure_refs,
    _validate_single_role_payload,
    _role_from_request,
    _resolve_security_for_request,
    _compile_rls_security_predicates,
    _validate_columnref_in_model,
    _validate_measureref_in_model,
    _resolve_role_and_scope_model,
    _RuntimeSecurityState,
    _build_runtime_security_state,
    _case_insensitive_dict_get,
    _validate_ir_objects_against_model_scoped,
)
from dax_ui.server._filters import (
    _resolve_hierarchy_level_to_column_ref_dict,
    _parse_scoped_filters_payload,
    _parse_interaction_filters_payload,
    _resolve_payload_param_values,
    _resolve_payload_calc_groups,
    _resolve_payload_what_if_values,
)
from dax_ui.server._duckdb import (
    _duckdb_table_exists,
    _sql_string_literal,
    _resolve_source_path,
    _is_remote_path,
    _ensure_duckdb_extension,
    _csv_options_from_source,
    _read_by_format_sql,
    _ensure_duckdb_sources_loaded,
    _connect_duckdb_for_project,
    _REL_CARDINALITY_SYNONYMS,
    _normalize_relationship_cardinality,
    _pretty_relationship_cardinality,
    _detect_relationship_cardinality,
    _resolve_and_validate_relationship_cardinality,
    _serialize_stat_value,
)
from dax_ui.server._engine import (
    ValidateResult,
    _ensure_mapping_loaded,
    PreparedEngineState,
    _ENGINE_LOCK,
    _ENGINE_CACHE,
    _ACTIVE_ENGINE,
    _norm_project_key,
    _project_signature,
    get_prepared_engine,
    _get_engine_table_sources,
    _compile_table_sources_for_model,
    _resolve_project_path,
    _resolve_duckdb_path,
    _deep_merge,
)
from dax_ui.server._plotly import (
    _PLOTLY_COLOR_SEQUENCES,
    _FORMAT_SCHEMA,
    _LEGEND_POSITION_MAP,
    _DEFAULT_VISUAL_INTERACTIONS,
    _format_options_to_plotly_patch,
    _apply_format_patch_to_figure,
    _normalize_visual_interactions,
)
from dax_ui.server._visual_io import (
    _load_visual_json,
    _save_visual_json,
    _delete_visual_json,
    _next_visual_id,
    _slot_value_present,
    _expr_output_name,
    _build_spec_from_encodings,
)
from dax_ui.server._validation import (
    _validate_measure,
    _analyze_ir_complexity,
    _generate_dax_suggestions,
)

logger = logging.getLogger(__name__)


# Module-level helpers from __init__
from dax_ui.server import (
    _validate_safe_name,
    _json_safe,
    _json_safe_with_path,
)
from dax_ui.server._routes_core import (
    _build_virtual_tables,
    _get_virtual_table_distinct_values,
    _evaluate_measure_ref_scalar,
    _evaluate_measure_ref_set,
)




def _load_model_layouts(project_path: str) -> list[dict]:
    """Load model_layouts.yaml from the reports directory. Returns [] if missing."""
    import yaml as _yaml
    path = Path(project_path) / "reports" / "model_layouts.yaml"
    if not path.exists():
        return []
    try:
        raw = _yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]
    except Exception:
        return []

def _save_model_layouts(project_path: str, layouts: list[dict]) -> None:
    """Persist model_layouts.yaml to the reports directory."""
    import yaml as _yaml
    reports_dir = Path(project_path) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "model_layouts.yaml"
    path.write_text(
        _yaml.dump(layouts, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )



def register_model_ext_routes(app):
    from fastapi import Body, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    def _power_query_entries_for_model(model: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for table in getattr(model, "tables", []) or []:
            pq = getattr(table, "power_query", None)
            if not isinstance(pq, Mapping):
                continue
            primary = dict(pq)
            primary.setdefault("table_name", getattr(table, "name", ""))
            out.append(primary)
            for extra in primary.get("additional_queries") or []:
                if isinstance(extra, Mapping):
                    item = dict(extra)
                    item.setdefault("table_name", getattr(table, "name", ""))
                    out.append(item)
        return out

    def _find_power_query_entry(model: Any, query_id: str) -> dict[str, Any]:
        qid = str(query_id or "").strip()
        if not qid:
            raise ValueError("query_id is required")
        for query in _power_query_entries_for_model(model):
            candidates = {
                str(query.get("query_id") or ""),
                str(query.get("table_name") or ""),
                str(query.get("partition_name") or ""),
            }
            if qid.upper() in {candidate.strip().upper() for candidate in candidates if candidate.strip()}:
                return query
        raise ValueError(f"Unknown transform query: {qid!r}")

    def _power_query_helper_raw_m(model: Any, current_query: Mapping[str, Any]) -> dict[str, str]:
        current_ids = {
            str(current_query.get("query_id") or "").strip().upper(),
            str(current_query.get("table_name") or "").strip().upper(),
            str(current_query.get("partition_name") or "").strip().upper(),
        }
        current_ids = {item for item in current_ids if item}
        helpers: dict[str, str] = {}
        for query in _power_query_entries_for_model(model):
            qid = str(query.get("query_id") or query.get("table_name") or query.get("partition_name") or "").strip()
            if not qid or qid.upper() in current_ids:
                continue
            raw_m = query.get("raw_m")
            if isinstance(raw_m, str) and raw_m.strip():
                helpers[qid] = raw_m
        return helpers

    def _power_query_table_ref_names(query: Mapping[str, Any]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        query_id_value = str(query.get("query_id") or "").strip()
        candidates = [query_id_value]
        for key in ("table_name", "partition_name"):
            name = str(query.get(key) or "").strip()
            if not query_id_value or name.upper() == query_id_value.upper():
                candidates.append(name)
        for name in candidates:
            if name and name.upper() not in seen:
                seen.add(name.upper())
                names.append(name)
        return names

    def _power_query_reference_tables(
        *,
        project_path: str,
        model: Any,
        current_query: Mapping[str, Any],
        limit: int,
    ) -> dict[str, tuple[list[dict[str, Any]], list[list[Any]]]]:
        from dax_project.power_query import evaluate_preview_table

        current_ids = {name.upper() for name in _power_query_table_ref_names(current_query)}
        refs: dict[str, tuple[list[dict[str, Any]], list[list[Any]]]] = {}
        for query in _power_query_entries_for_model(model):
            names = _power_query_table_ref_names(query)
            if not names or names[0].upper() in current_ids:
                continue
            raw_m = str(query.get("raw_m") or "")
            if not raw_m.strip():
                continue
            source_preview: dict[str, Any] = {"columns": [], "rows": [], "sql": ""}
            try:
                source_block = _power_query_preview_source_block(query)
                src = _normalize_import_source(source_block, project_path=project_path, allow_missing_table=False)
                source_preview = _preview_from_source(project_path=project_path, src=src, limit=limit)
            except Exception:
                source_preview = {"columns": [], "rows": [], "sql": ""}
            try:
                evaluated = evaluate_preview_table(
                    raw_m=raw_m,
                    columns=source_preview.get("columns") or [],
                    rows=source_preview.get("rows") or [],
                    source_sql=str(source_preview.get("sql") or ""),
                    helper_queries=_power_query_helper_raw_m(model, query),
                    table_variables=refs,
                )
            except Exception:
                continue
            if evaluated.blocked_steps or not evaluated.columns:
                continue
            table_value = ([dict(col) for col in evaluated.columns], [list(row) for row in evaluated.rows])
            for name in names:
                refs[name] = table_value
        return refs

    def _power_query_preview_source_block(query: Mapping[str, Any]) -> dict[str, Any]:
        source_mapping = query.get("source_mapping")
        if not isinstance(source_mapping, Mapping):
            raise ValueError("Transform query has no mapped source to preview")
        source_block = source_mapping.get("source_block")
        if not isinstance(source_block, Mapping):
            raise ValueError("Transform query has no mapped source block to preview")
        block = dict(source_block)
        src_type = str(block.get("type") or "").strip().lower()
        if src_type == "web":
            raise ValueError("Web source preview needs a format-aware connector mapping first")
        if src_type in {"sql", "odata", "sharepoint", "odbc"}:
            raise ValueError(f"Transform source type {src_type!r} is preserved/mapped but not preview-executable yet")
        return block

    def _power_query_adapter_function(query: Mapping[str, Any]) -> tuple[str, str] | None:
        from dax_project.power_query import function_catalog_rows

        by_name = {str(row.get("function") or ""): row for row in function_catalog_rows()}
        adapter_tracks = {"relational_connector", "cloud_storage_lake", "web_saas_api", "native_query", "semantic_cube"}
        local_fixture_only = {"Excel.CurrentWorkbook", "Pdf.Tables", "RData.FromBinary"}
        mappings_raw = query.get("source_mappings")
        mappings = mappings_raw if isinstance(mappings_raw, list) else []
        source_mapping = query.get("source_mapping")
        if isinstance(source_mapping, Mapping):
            mappings = [source_mapping, *[item for item in mappings if item is not source_mapping]]
        for mapping in mappings:
            if not isinstance(mapping, Mapping):
                continue
            fn = str(mapping.get("raw_function") or "").strip()
            row = by_name.get(fn)
            if not row:
                continue
            track = str(row.get("support_track") or "")
            if track in adapter_tracks or fn in local_fixture_only:
                return fn, track
        functions = query.get("functions")
        if isinstance(functions, list):
            for item in functions:
                fn = str(item or "").strip()
                row = by_name.get(fn)
                if not row:
                    continue
                track = str(row.get("support_track") or "")
                if track in adapter_tracks or fn in local_fixture_only:
                    return fn, track
        return None

    def _power_query_preview_from_adapter(
        query: Mapping[str, Any],
        *,
        project_path: str,
        limit: int,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        adapter_info = _power_query_adapter_function(query)
        if adapter_info is None:
            return None
        from dax_project.power_query import execute_power_query_adapter

        function_name, support_track = adapter_info
        approval_raw = (payload or {}).get("approval_record") if isinstance(payload, Mapping) else None
        approval_record = approval_raw if isinstance(approval_raw, Mapping) else None
        fixture_mode = True
        credential_profile_id = None
        adapter_options: dict[str, Any] = {}
        if isinstance(payload, Mapping):
            fixture_mode = bool(payload.get("fixture_mode", True))
            raw_profile_id = payload.get("credential_profile_id")
            credential_profile_id = str(raw_profile_id).strip() if raw_profile_id is not None and str(raw_profile_id).strip() else None
            raw_options = payload.get("adapter_options")
            if isinstance(raw_options, Mapping):
                adapter_options = dict(raw_options)
        operation = "native_query" if support_track == "native_query" else "preview"
        result = execute_power_query_adapter(
            function_name,
            {
                "fixture_mode": fixture_mode,
                "project_root": project_path,
                "credential_profile_id": credential_profile_id,
                "options": adapter_options,
                "approval_record": dict(approval_record) if approval_record is not None else None,
                "privacy_level": "organizational",
            },
            operation=operation,
        ).to_dict()
        rows = [list(row) for row in (result.get("preview_rows") or [])][:limit]
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
        execution_scope = "fixture_adapter" if fixture_mode else "live_adapter"
        preview = {
            "sql": "",
            "columns": result.get("schema") or [],
            "rows": _json_safe(rows),
            "row_count": len(rows),
            "applied_steps": [],
            "blocked_steps": [],
            "diagnostics": diagnostics,
            "execution_scope": execution_scope,
            "adapter_result": result,
            "result_step_id": function_name,
        }
        if result.get("execution_state") == "blocked":
            preview["blocked_steps"] = [
                {
                    "step_id": function_name,
                    "reason": "; ".join(str(item.get("message") or "") for item in diagnostics if isinstance(item, Mapping)).strip()
                    or "Transform adapter execution is blocked.",
                }
            ]
            preview["execution_scope"] = f"{execution_scope}_blocked"
        return {
            "function": function_name,
            "support_track": support_track,
            "source": {
                "type": "power_query_adapter",
                "function": function_name,
                "connector_id": result.get("connector_id"),
                "fixture_mode": fixture_mode,
                "credential_profile_id": credential_profile_id,
            },
            "source_preview": {
                "sql": "",
                "columns": result.get("schema") or [],
                "rows": _json_safe(rows),
                "row_count": len(rows),
                "adapter_result": result,
            },
            "preview": preview,
            "adapter_result": result,
        }

    def _power_query_table_yaml_path(project_path: str, table_name: str) -> Path:
        table = str(table_name or "").strip()
        if not table:
            raise ValueError("Transform query is not associated with a table")
        tables_dir = (Path(project_path) / "model" / "tables").resolve()
        path = (tables_dir / f"{table}.yaml").resolve()
        try:
            path.relative_to(tables_dir)
        except ValueError as exc:
            raise ValueError("Invalid transform table path") from exc
        if not path.exists():
            raise FileNotFoundError(f"Table YAML not found for transform table: {table!r}")
        return path

    def _power_query_entry_matches(query: Mapping[str, Any], query_id: str) -> bool:
        qid = str(query_id or "").strip().upper()
        if not qid:
            return False
        candidates = {
            str(query.get("query_id") or ""),
            str(query.get("table_name") or ""),
            str(query.get("partition_name") or ""),
        }
        return qid in {candidate.strip().upper() for candidate in candidates if candidate.strip()}

    def _power_query_query_id(query: Mapping[str, Any]) -> str:
        return str(query.get("query_id") or query.get("table_name") or query.get("partition_name") or "").strip()

    def _power_query_m_identifier(name: str) -> str:
        value = str(name or "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            return value
        return '#"' + value.replace('"', '""') + '"'

    def _power_query_m_string(value: str) -> str:
        return '"' + str(value or "").replace('"', '""') + '"'

    def _power_query_empty_table_raw_m(columns: list[str] | None = None) -> str:
        names = [str(item).strip() for item in (columns or []) if str(item).strip()]
        if not names:
            names = ["Column1"]
        column_expr = "{" + ", ".join(_power_query_m_string(name) for name in names) + "}"
        return f"let\n    Source = #table({column_expr}, {{}})\nin\n    Source"

    def _power_query_file_raw_m(path: str) -> str:
        return (
            "let\n"
            f"    Source = File.Contents({_power_query_m_string(path)}),\n"
            "    Csv = Csv.Document(Source)\n"
            "in\n"
            "    Csv"
        )

    def _power_query_transform_commands() -> list[dict[str, Any]]:
        def command(
            command_id: str,
            label: str,
            category: str,
            scope: str,
            template_kind: str,
            required_inputs: list[dict[str, Any]],
            *,
            supported_state: str = "supported",
            proof_state: str = "fixture_execution_parity",
            folding_state: str = "depends_on_source",
        ) -> dict[str, Any]:
            return {
                "id": command_id,
                "label": label,
                "category": category,
                "scope": scope,
                "required_inputs": required_inputs,
                "template_kind": template_kind,
                "supported_state": supported_state,
                "proof_state": proof_state,
                "folding_state": folding_state,
            }

        column = {"id": "column", "label": "Column", "type": "column"}
        columns = {"id": "columns", "label": "Columns", "type": "columns"}
        text_value = {"id": "value", "label": "Value", "type": "text"}
        return [
            command("preview", "Preview", "Home", "query", "preview", []),
            command("query_duplicate", "Duplicate", "Home", "query", "query_action", [{"id": "new_query_id", "label": "New name", "type": "text"}]),
            command("query_reference", "Reference", "Home", "query", "query_action", [{"id": "new_query_id", "label": "New name", "type": "text"}]),
            command("query_rename", "Rename", "Home", "query", "query_action", [{"id": "new_query_id", "label": "New name", "type": "text"}]),
            command("query_settings", "Settings", "Home", "query", "query_action", []),
            command("rename_column", "Rename Column", "Clean", "column", "step", [column, {"id": "new_name", "label": "New name", "type": "text"}]),
            command("change_type", "Change Type", "Clean", "column", "step", [column, {"id": "data_type", "label": "Type", "type": "select", "options": ["text", "number", "date", "datetime", "logical"]}]),
            command("replace_values", "Replace Values", "Clean", "column", "step", [columns, {"id": "old_value", "label": "Find", "type": "text"}, {"id": "new_value", "label": "Replace", "type": "text"}]),
            command("trim_text", "Trim", "Clean", "column", "step", [columns]),
            command("clean_text", "Clean Text", "Clean", "column", "step", [columns]),
            command("upper_text", "Uppercase", "Clean", "column", "step", [columns]),
            command("lower_text", "Lowercase", "Clean", "column", "step", [columns]),
            command("fill_down", "Fill Down", "Clean", "column", "step", [columns], folding_state="local_or_source_specific"),
            command("fill_up", "Fill Up", "Clean", "column", "step", [columns], folding_state="local_or_source_specific"),
            command("remove_errors", "Remove Errors", "Clean", "column", "step", [columns], folding_state="local_or_source_specific"),
            command("replace_errors", "Replace Errors", "Clean", "column", "step", [columns, text_value], folding_state="local_or_source_specific"),
            command("keep_columns", "Keep Columns", "Shape", "column", "step", [columns]),
            command("remove_columns", "Remove Columns", "Shape", "column", "step", [columns]),
            command("filter_rows", "Filter Rows", "Shape", "column", "step", [column, {"id": "operator", "label": "Operator", "type": "select", "options": ["equals", "not equals", "contains", "starts with", "greater than", "less than"]}, text_value]),
            command("keep_top_rows", "Keep Top Rows", "Shape", "table", "step", [{"id": "count", "label": "Rows", "type": "number"}]),
            command("remove_top_rows", "Remove Top Rows", "Shape", "table", "step", [{"id": "count", "label": "Rows", "type": "number"}]),
            command("sort", "Sort", "Shape", "column", "step", [column, {"id": "direction", "label": "Direction", "type": "select", "options": ["ascending", "descending"]}]),
            command("split_column", "Split Column", "Shape", "column", "step", [column, {"id": "delimiter", "label": "Delimiter", "type": "text"}, {"id": "left_name", "label": "First output", "type": "text"}, {"id": "right_name", "label": "Second output", "type": "text"}], folding_state="local_or_source_specific"),
            command("merge_columns", "Merge Columns", "Shape", "column", "step", [columns, {"id": "delimiter", "label": "Delimiter", "type": "text"}, {"id": "new_name", "label": "New column", "type": "text"}], folding_state="local_or_source_specific"),
            command("pivot", "Pivot", "Shape", "column", "step", [column, {"id": "value_column", "label": "Values column", "type": "column"}], supported_state="script_assist", folding_state="source_specific"),
            command("unpivot", "Unpivot", "Shape", "column", "step", [columns], supported_state="script_assist", folding_state="source_specific"),
            command("group_by", "Group By", "Shape", "table", "step", [columns, {"id": "new_name", "label": "New column", "type": "text"}, {"id": "operation", "label": "Operation", "type": "select", "options": ["count rows", "sum"]}, {"id": "value_column", "label": "Value column", "type": "column", "optional": True}]),
            command("merge_queries", "Merge Queries", "Combine", "query", "step", [{"id": "right_query", "label": "Right query", "type": "query"}, {"id": "left_column", "label": "Left key", "type": "column"}, {"id": "right_column", "label": "Right key", "type": "text"}, {"id": "join_kind", "label": "Join kind", "type": "select", "options": ["left outer", "inner", "right outer", "full outer", "left anti", "right anti"]}], folding_state="proof_required"),
            command("append_queries", "Append Queries", "Combine", "query", "step", [{"id": "other_query", "label": "Other query", "type": "query"}], folding_state="local_or_source_specific"),
            command("custom_column", "Custom Column", "Enrich", "table", "step", [{"id": "new_name", "label": "New column", "type": "text"}, {"id": "expression", "label": "Expression", "type": "expression"}]),
            command("conditional_column", "Conditional Column", "Enrich", "column", "step", [column, {"id": "operator", "label": "Operator", "type": "select", "options": ["equals", "not equals", "contains", "greater than", "less than"]}, {"id": "compare_value", "label": "Compare", "type": "text"}, {"id": "then_value", "label": "Then", "type": "text"}, {"id": "else_value", "label": "Else", "type": "text"}, {"id": "new_name", "label": "New column", "type": "text"}]),
            command("index_column", "Index Column", "Enrich", "table", "step", [{"id": "new_name", "label": "Column name", "type": "text"}, {"id": "start", "label": "Start", "type": "number"}, {"id": "increment", "label": "Increment", "type": "number"}]),
            command("date_column", "Date Part", "Enrich", "column", "step", [column, {"id": "part", "label": "Part", "type": "select", "options": ["year", "month", "day"]}, {"id": "new_name", "label": "New column", "type": "text"}]),
            command("number_column", "Number Formula", "Enrich", "column", "step", [column, {"id": "operation", "label": "Operation", "type": "select", "options": ["absolute", "round", "double"]}, {"id": "new_name", "label": "New column", "type": "text"}]),
        ]

    def _power_query_transform_command(command_id: str) -> dict[str, Any]:
        target = str(command_id or "").strip()
        for command in _power_query_transform_commands():
            if command["id"] == target:
                return command
        raise ValueError(f"Unknown transform command: {target!r}")

    def _power_query_column_expr(columns: list[str]) -> str:
        return "{" + ", ".join(_power_query_m_string(name) for name in columns) + "}"

    def _power_query_field_ref(name: str) -> str:
        return "[" + _power_query_m_identifier(name) + "]"

    def _power_query_scalar_expr(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value)
        if re.fullmatch(r"-?\d+(\.\d+)?", text.strip()):
            return text.strip()
        lowered = text.strip().lower()
        if lowered in {"true", "false", "null"}:
            return lowered
        return _power_query_m_string(text)

    def _power_query_columns_from_payload(payload: Mapping[str, Any], values: Mapping[str, Any]) -> list[str]:
        raw = values.get("columns", payload.get("selected_columns"))
        if raw is None and values.get("column") is not None:
            raw = [values.get("column")]
        if isinstance(raw, str):
            items = [raw]
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        return [str(item).strip() for item in items if str(item).strip()]

    def _power_query_command_base(
        raw_m: str,
        selected_step_id: str | None,
    ) -> tuple[str, str | None, set[str]]:
        from dax_project.power_query import parse_m_query

        steps, result_expression, _functions, _diagnostics = parse_m_query(raw_m)
        if not steps:
            raise ValueError("Transform command needs a parseable query")
        existing_ids = {step.id.strip().upper() for step in steps}
        if selected_step_id and selected_step_id.strip():
            selected = selected_step_id.strip()
            if selected.upper() not in existing_ids:
                raise ValueError(f"Unknown selected step: {selected!r}")
            return _power_query_m_identifier(selected), selected, existing_ids
        result_text = str(result_expression or "").strip()
        for step in reversed(steps):
            if result_text and step.id.strip().upper() == result_text.replace('#"', '').replace('"', '').strip().upper():
                return _power_query_m_identifier(step.id), step.id, existing_ids
        return _power_query_m_identifier(steps[-1].id), steps[-1].id, existing_ids

    def _power_query_next_step_id(base: str, existing_ids: set[str]) -> str:
        candidate = re.sub(r"[^A-Za-z0-9_ ]+", "", base).strip() or "Step"
        if candidate.upper() not in existing_ids:
            return candidate
        index = 2
        while f"{candidate} {index}".upper() in existing_ids:
            index += 1
        return f"{candidate} {index}"

    def _power_query_filter_expression(column: str, operator: str, value: Any) -> str:
        field = _power_query_field_ref(column)
        op = operator.strip().lower().replace("_", " ")
        scalar = _power_query_scalar_expr(value)
        if op == "equals":
            return f"{field} = {scalar}"
        if op == "not equals":
            return f"{field} <> {scalar}"
        if op == "contains":
            return f"Text.Contains(Text.From({field}), Text.From({scalar}))"
        if op == "starts with":
            return f"Text.StartsWith(Text.From({field}), Text.From({scalar}))"
        if op == "greater than":
            return f"{field} > {scalar}"
        if op == "less than":
            return f"{field} < {scalar}"
        if op == "greater or equal":
            return f"{field} >= {scalar}"
        if op == "less or equal":
            return f"{field} <= {scalar}"
        raise ValueError(f"Unsupported filter operator: {operator!r}")

    def _power_query_command_expression(
        command_id: str,
        source_ref: str,
        payload: Mapping[str, Any],
    ) -> tuple[str, str]:
        values_raw = payload.get("values")
        values = values_raw if isinstance(values_raw, Mapping) else {}
        columns = _power_query_columns_from_payload(payload, values)
        column = str(values.get("column") or (columns[0] if columns else "")).strip()
        count = int(values.get("count") or 10)

        if command_id == "keep_columns":
            if not columns:
                raise ValueError("Keep columns needs at least one column")
            return "Kept Columns", f"Table.SelectColumns({source_ref}, {_power_query_column_expr(columns)})"
        if command_id == "remove_columns":
            if not columns:
                raise ValueError("Remove columns needs at least one column")
            return "Removed Columns", f"Table.RemoveColumns({source_ref}, {_power_query_column_expr(columns)})"
        if command_id == "rename_column":
            new_name = str(values.get("new_name") or "").strip()
            if not column or not new_name:
                raise ValueError("Rename column needs a column and new name")
            return "Renamed Columns", f"Table.RenameColumns({source_ref}, {{{{{_power_query_m_string(column)}, {_power_query_m_string(new_name)}}}}})"
        if command_id == "change_type":
            data_type = str(values.get("data_type") or "text").strip().lower()
            type_map = {"text": "type text", "number": "type number", "date": "type date", "datetime": "type datetime", "logical": "type logical"}
            if not column:
                raise ValueError("Change type needs a column")
            return "Changed Type", f"Table.TransformColumnTypes({source_ref}, {{{{{_power_query_m_string(column)}, {type_map.get(data_type, 'type text')}}}}})"
        if command_id == "sort":
            direction = str(values.get("direction") or "ascending").strip().lower()
            order = "Order.Descending" if direction == "descending" else "Order.Ascending"
            if not column:
                raise ValueError("Sort needs a column")
            return "Sorted Rows", f"Table.Sort({source_ref}, {{{{{_power_query_m_string(column)}, {order}}}}})"
        if command_id == "filter_rows":
            if not column:
                raise ValueError("Filter rows needs a column")
            predicate = _power_query_filter_expression(column, str(values.get("operator") or "equals"), values.get("value"))
            return "Filtered Rows", f"Table.SelectRows({source_ref}, each {predicate})"
        if command_id == "keep_top_rows":
            return "Kept Top Rows", f"Table.FirstN({source_ref}, {max(0, count)})"
        if command_id == "remove_top_rows":
            return "Removed Top Rows", f"Table.Skip({source_ref}, {max(0, count)})"
        if command_id == "split_column":
            delimiter = str(values.get("delimiter") or ",")
            left_name = str(values.get("left_name") or f"{column}.1").strip()
            right_name = str(values.get("right_name") or f"{column}.2").strip()
            if not column:
                raise ValueError("Split column needs a column")
            return "Split Column", (
                f"Table.SplitColumn({source_ref}, {_power_query_m_string(column)}, "
                f"Splitter.SplitTextByDelimiter({_power_query_m_string(delimiter)}, QuoteStyle.Csv), "
                f"{_power_query_column_expr([left_name, right_name])})"
            )
        if command_id == "merge_columns":
            delimiter = str(values.get("delimiter") or " ")
            new_name = str(values.get("new_name") or "Merged").strip()
            if len(columns) < 2:
                raise ValueError("Merge columns needs at least two columns")
            return "Merged Columns", (
                f"Table.CombineColumns({source_ref}, {_power_query_column_expr(columns)}, "
                f"Combiner.CombineTextByDelimiter({_power_query_m_string(delimiter)}, QuoteStyle.None), {_power_query_m_string(new_name)})"
            )
        if command_id == "replace_values":
            if not columns:
                raise ValueError("Replace values needs at least one column")
            return "Replaced Values", (
                f"Table.ReplaceValue({source_ref}, {_power_query_scalar_expr(values.get('old_value'))}, "
                f"{_power_query_scalar_expr(values.get('new_value'))}, Replacer.ReplaceText, {_power_query_column_expr(columns)})"
            )
        text_transforms = {
            "trim_text": ("Trimmed Text", "Text.Trim"),
            "clean_text": ("Cleaned Text", "Text.Clean"),
            "upper_text": ("Uppercased Text", "Text.Upper"),
            "lower_text": ("Lowercased Text", "Text.Lower"),
        }
        if command_id in text_transforms:
            if not columns:
                raise ValueError("Text transform needs at least one column")
            step_name, fn = text_transforms[command_id]
            ops = ", ".join("{" + f"{_power_query_m_string(name)}, {fn}, type text" + "}" for name in columns)
            return step_name, f"Table.TransformColumns({source_ref}, {{{ops}}})"
        if command_id == "fill_down":
            if not columns:
                raise ValueError("Fill down needs at least one column")
            return "Filled Down", f"Table.FillDown({source_ref}, {_power_query_column_expr(columns)})"
        if command_id == "fill_up":
            if not columns:
                raise ValueError("Fill up needs at least one column")
            return "Filled Up", f"Table.FillUp({source_ref}, {_power_query_column_expr(columns)})"
        if command_id == "remove_errors":
            if not columns:
                raise ValueError("Remove errors needs at least one column")
            return "Removed Errors", f"Table.RemoveRowsWithErrors({source_ref}, {_power_query_column_expr(columns)})"
        if command_id == "replace_errors":
            if not columns:
                raise ValueError("Replace errors needs at least one column")
            replacements = ", ".join("{" + f"{_power_query_m_string(name)}, {_power_query_scalar_expr(values.get('value'))}" + "}" for name in columns)
            return "Replaced Errors", f"Table.ReplaceErrorValues({source_ref}, {{{replacements}}})"
        if command_id == "group_by":
            if not columns:
                raise ValueError("Group by needs at least one group column")
            new_name = str(values.get("new_name") or "Rows").strip()
            operation = str(values.get("operation") or "count rows").strip().lower()
            value_column = str(values.get("value_column") or "").strip()
            if operation == "sum":
                if not value_column:
                    raise ValueError("Sum group by needs a value column")
                aggregate = f"{{{_power_query_m_string(new_name)}, each List.Sum({_power_query_field_ref(value_column)}), type number}}"
            else:
                aggregate = f"{{{_power_query_m_string(new_name)}, each Table.RowCount(_), Int64.Type}}"
            return "Grouped Rows", f"Table.Group({source_ref}, {_power_query_column_expr(columns)}, {{{aggregate}}})"
        if command_id == "merge_queries":
            right_query = str(values.get("right_query") or "").strip()
            left_column = str(values.get("left_column") or column).strip()
            right_column = str(values.get("right_column") or left_column).strip()
            join_kind = str(values.get("join_kind") or "left outer").strip().lower().replace(" ", "")
            join_map = {"leftouter": "JoinKind.LeftOuter", "inner": "JoinKind.Inner", "rightouter": "JoinKind.RightOuter", "fullouter": "JoinKind.FullOuter", "leftanti": "JoinKind.LeftAnti", "rightanti": "JoinKind.RightAnti"}
            if not right_query or not left_column or not right_column:
                raise ValueError("Merge queries needs right query and key columns")
            return "Merged Queries", (
                f"Table.NestedJoin({source_ref}, {_power_query_column_expr([left_column])}, "
                f"{_power_query_m_identifier(right_query)}, {_power_query_column_expr([right_column])}, "
                f"{_power_query_m_string(right_query)}, {join_map.get(join_kind, 'JoinKind.LeftOuter')})"
            )
        if command_id == "append_queries":
            other_query = str(values.get("other_query") or "").strip()
            if not other_query:
                raise ValueError("Append queries needs another query")
            return "Appended Query", f"Table.Combine({{{source_ref}, {_power_query_m_identifier(other_query)}}})"
        if command_id == "custom_column":
            new_name = str(values.get("new_name") or "Custom").strip()
            expression = str(values.get("expression") or "null").strip()
            return "Added Custom", f"Table.AddColumn({source_ref}, {_power_query_m_string(new_name)}, each {expression})"
        if command_id == "conditional_column":
            new_name = str(values.get("new_name") or "Conditional").strip()
            predicate = _power_query_filter_expression(column, str(values.get("operator") or "equals"), values.get("compare_value"))
            return "Added Conditional", f"Table.AddColumn({source_ref}, {_power_query_m_string(new_name)}, each if {predicate} then {_power_query_scalar_expr(values.get('then_value'))} else {_power_query_scalar_expr(values.get('else_value'))})"
        if command_id == "index_column":
            new_name = str(values.get("new_name") or "Index").strip()
            start = int(values.get("start") or 0)
            increment = int(values.get("increment") or 1)
            return "Added Index", f"Table.AddIndexColumn({source_ref}, {_power_query_m_string(new_name)}, {start}, {increment})"
        if command_id == "date_column":
            part = str(values.get("part") or "year").strip().lower()
            fn = {"year": "Date.Year", "month": "Date.Month", "day": "Date.Day"}.get(part, "Date.Year")
            new_name = str(values.get("new_name") or part.title()).strip()
            if not column:
                raise ValueError("Date part needs a column")
            return "Added Date Part", f"Table.AddColumn({source_ref}, {_power_query_m_string(new_name)}, each {fn}(Date.From({_power_query_field_ref(column)})))"
        if command_id == "number_column":
            operation = str(values.get("operation") or "absolute").strip().lower()
            new_name = str(values.get("new_name") or operation.title()).strip()
            if not column:
                raise ValueError("Number formula needs a column")
            field = _power_query_field_ref(column)
            expr = {"absolute": f"Number.Abs({field})", "round": f"Number.Round({field})", "double": f"{field} * 2"}.get(operation, f"Number.Abs({field})")
            return "Added Number", f"Table.AddColumn({source_ref}, {_power_query_m_string(new_name)}, each {expr})"
        if command_id in {"pivot", "unpivot"}:
            raise ValueError("This command is available through Script Assist until form-safe templates are certified")
        raise ValueError(f"Unsupported transform command: {command_id!r}")

    def _power_query_command_draft(
        *,
        existing: Mapping[str, Any],
        query_id: str,
        payload: Mapping[str, Any],
        project_path: str,
    ) -> dict[str, Any]:
        from dax_project.power_query import add_m_step_expression, build_power_query_applied_step_edit_preview, build_power_query_metadata

        command_id = str(payload.get("command_id") or payload.get("id") or "").strip()
        command = _power_query_transform_command(command_id)
        if command.get("template_kind") == "query_action":
            raise ValueError("Query action commands use the query action endpoint")
        if command_id == "preview":
            raise ValueError("Preview command is handled by the preview endpoint")
        raw_m = payload.get("raw_m")
        if raw_m is not None and not isinstance(raw_m, str):
            raise ValueError("raw_m must be a string if provided")
        source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
        selected_step_raw = payload.get("selected_step_id")
        selected_step_id = str(selected_step_raw).strip() if selected_step_raw is not None and str(selected_step_raw).strip() else None
        source_ref, after_step_id, existing_ids = _power_query_command_base(source_raw_m, selected_step_id)
        step_base, expression = _power_query_command_expression(command_id, source_ref, payload)
        step_id = str(payload.get("step_id") or "").strip() or _power_query_next_step_id(step_base, existing_ids)
        patched_raw_m = add_m_step_expression(
            source_raw_m,
            step_id,
            expression,
            after_step_id=after_step_id,
            make_result=True,
        )
        metadata = build_power_query_metadata(
            query_id=str(existing.get("query_id") or query_id),
            raw_m=patched_raw_m,
            table_name=str(existing.get("table_name") or "") or None,
            partition_name=str(existing.get("partition_name") or "") or None,
            mode=str(existing.get("mode") or "") or None,
        )
        preview = build_power_query_applied_step_edit_preview(
            before_raw_m=source_raw_m,
            after_raw_m=patched_raw_m,
            operation=command_id,
            step_id=step_id,
            project_root=project_path,
        )
        return {
            "command": command,
            "command_id": command_id,
            "step_id": step_id,
            "expression": expression,
            "raw_m": patched_raw_m,
            "query": metadata,
            "applied_step_edit_preview": preview,
        }

    def _replace_power_query_reference(raw_m: str, old_query_id: str, new_query_id: str) -> tuple[str, int]:
        old_id = str(old_query_id or "").strip()
        if not old_id:
            return raw_m, 0
        new_ref = _power_query_m_identifier(new_query_id)
        count = 0

        quoted_pattern = re.compile(r'#"' + re.escape(old_id.replace('"', '""')) + r'"', re.IGNORECASE)
        raw_m, quoted_count = quoted_pattern.subn(new_ref, raw_m)
        count += quoted_count

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", old_id):
            bare_pattern = re.compile(r"(?<![#\"A-Za-z0-9_])" + re.escape(old_id) + r"(?![A-Za-z0-9_])")
            raw_m, bare_count = bare_pattern.subn(new_ref, raw_m)
            count += bare_count
        return raw_m, count

    def _power_query_table_records(project_path: str, model: Any) -> list[dict[str, Any]]:
        import yaml as _yaml

        records: list[dict[str, Any]] = []
        for table in getattr(model, "tables", []) or []:
            table_name = str(getattr(table, "name", "") or "").strip()
            if not table_name:
                continue
            try:
                table_path = _power_query_table_yaml_path(project_path, table_name)
            except Exception:
                continue
            table_yaml = _yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
            if not isinstance(table_yaml, dict):
                continue
            current = table_yaml.get("power_query")
            if not isinstance(current, Mapping):
                continue
            primary = dict(current)
            primary.setdefault("table_name", table_name)
            records.append(
                {
                    "table_name": table_name,
                    "table_path": table_path,
                    "table_yaml": table_yaml,
                    "query": primary,
                    "kind": "primary",
                    "index": None,
                }
            )
            for idx, extra in enumerate(current.get("additional_queries") or []):
                if not isinstance(extra, Mapping):
                    continue
                item = dict(extra)
                item.setdefault("table_name", table_name)
                records.append(
                    {
                        "table_name": table_name,
                        "table_path": table_path,
                        "table_yaml": table_yaml,
                        "query": item,
                        "kind": "additional",
                        "index": idx,
                    }
                )
        return records

    def _power_query_find_record(records: list[dict[str, Any]], query_id: str) -> dict[str, Any]:
        for record in records:
            query = record.get("query")
            if isinstance(query, Mapping) and _power_query_entry_matches(query, query_id):
                return record
        raise ValueError(f"Unknown transform query: {query_id!r}")

    def _power_query_metadata_from_existing(
        existing: Mapping[str, Any],
        *,
        query_id: str,
        raw_m: str,
        table_name: str | None,
        partition_name: str | None,
        mode: str | None,
        preserve_additional: bool = True,
    ) -> dict[str, Any]:
        from dax_project.power_query import build_power_query_metadata

        metadata = build_power_query_metadata(
            query_id=query_id,
            raw_m=raw_m,
            table_name=table_name or None,
            partition_name=partition_name or None,
            mode=mode or None,
        )
        for key in (
            "load_enabled",
            "refresh_enabled",
            "group",
            "query_group",
            "description",
            "credential_profile_id",
            "privacy_level",
            "source_settings",
        ):
            if key in existing:
                metadata[key] = copy.deepcopy(existing[key])
        if preserve_additional and isinstance(existing.get("additional_queries"), list):
            metadata["additional_queries"] = copy.deepcopy(existing.get("additional_queries") or [])
        return metadata

    def _power_query_apply_record_updates(records: list[dict[str, Any]]) -> list[str]:
        import yaml as _yaml

        dirty: dict[Path, dict[str, Any]] = {}
        for record in records:
            if "next_query" not in record:
                continue
            table_yaml = record["table_yaml"]
            current = table_yaml.get("power_query")
            if not isinstance(current, dict):
                continue
            if record.get("kind") == "primary":
                table_yaml["power_query"] = record["next_query"]
            else:
                additional = list(current.get("additional_queries") or [])
                idx = int(record.get("index") or 0)
                if idx < 0 or idx >= len(additional):
                    raise ValueError("Transform additional query index is out of range")
                additional[idx] = record["next_query"]
                current["additional_queries"] = additional
                table_yaml["power_query"] = current
            dirty[Path(record["table_path"])] = table_yaml
        written: list[str] = []
        for path, table_yaml in dirty.items():
            path.write_text(
                _yaml.safe_dump(table_yaml, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            written.append(str(path))
        return written

    def _power_query_append_additional_query(record: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
        current = record["table_yaml"].get("power_query")
        if not isinstance(current, dict):
            raise ValueError("Transform table YAML has no editable primary query")
        additional = list(current.get("additional_queries") or [])
        additional.append(dict(metadata))
        current["additional_queries"] = additional
        record["table_yaml"]["power_query"] = current

    def _power_query_authoring_preview(
        entries: list[Mapping[str, Any]],
        *,
        project_path: str,
        query_id: str,
        raw_m: str,
        credential_profile_id: str | None = None,
    ) -> dict[str, Any]:
        from dax_project.power_query import (
            build_power_query_graph,
            build_power_query_parity_gap_report,
            build_power_query_project_parity_readiness,
        )

        graph = build_power_query_graph(entries)
        gap = build_power_query_parity_gap_report(
            raw_m,
            project_root=project_path,
            schema_probe_mode="execute",
            credential_profile_id=credential_profile_id,
            fixture_mode=True,
            execution_target="duckdb",
            query_id=query_id,
            query_entries=entries,
        )
        readiness = build_power_query_project_parity_readiness(
            entries,
            project_root=project_path,
            schema_probe_mode="execute",
            credential_profile_id=credential_profile_id,
            fixture_mode=True,
            execution_target="duckdb",
            persist_certification=False,
        )
        return {
            "dependency_preview": graph,
            "fold_frontier": gap.get("fold_frontier"),
            "parity_impact": {
                "query_gap_report": gap,
                "project_readiness": {
                    "readiness_score": readiness.get("readiness_score"),
                    "aggregate_summary": readiness.get("aggregate_summary"),
                    "proof_state": readiness.get("proof_state"),
                },
            },
        }

    @app.get("/runtime/power_query/functions")
    def runtime_power_query_functions():
        from dax_project.power_query import list_function_metadata

        return _ok({"functions": [fn.to_dict() for fn in list_function_metadata()]})

    @app.get("/runtime/power_query/transform-commands")
    def runtime_power_query_transform_commands():
        return _ok({"commands": _power_query_transform_commands()})

    @app.get("/runtime/power_query/function-catalog")
    def runtime_power_query_function_catalog():
        from dax_project.power_query import build_function_coverage_catalog

        return _ok({"catalog": build_function_coverage_catalog()})

    @app.get("/runtime/power_query/live-connectors/setup-manifest")
    def runtime_power_query_live_connector_setup_manifest():
        from dax_project.power_query import build_live_connector_setup_manifest

        return _ok({"manifest": build_live_connector_setup_manifest()})

    @app.post("/runtime/power_query/live-connectors/oauth/start")
    def runtime_power_query_live_connector_oauth_start(payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import start_live_connector_oauth

        try:
            return _ok({"oauth": start_live_connector_oauth(payload or {})})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/live-connectors/oauth/complete")
    def runtime_power_query_live_connector_oauth_complete(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import complete_live_connector_oauth

        try:
            project_path = _resolve_project_path_runtime(project)
            completed = complete_live_connector_oauth(project_path, payload or {})
            return _ok({"project": project_path, **completed})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/live-connectors/{profile_id}/certify")
    def runtime_power_query_live_connector_certify(profile_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import certify_live_connector_profile

        try:
            project_path = _resolve_project_path_runtime(project)
            certified = certify_live_connector_profile(project_path, profile_id, payload or {})
            return _ok({"project": project_path, **certified})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/power_query/credential-profiles")
    def runtime_power_query_credential_profiles(project: Optional[str] = None):
        from dax_project.power_query import list_credential_profiles

        try:
            project_path = _resolve_project_path_runtime(project)
            return _ok({"project": project_path, "profiles": list_credential_profiles(project_path)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/credential-profiles")
    def runtime_power_query_create_credential_profile(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import upsert_credential_profile

        try:
            project_path = _resolve_project_path_runtime(project)
            profile = upsert_credential_profile(project_path, payload or {})
            return _ok({"project": project_path, "profile": profile})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.patch("/runtime/power_query/credential-profiles/{profile_id}")
    def runtime_power_query_update_credential_profile(profile_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import upsert_credential_profile

        try:
            project_path = _resolve_project_path_runtime(project)
            body = dict(payload or {})
            body["profile_id"] = profile_id
            profile = upsert_credential_profile(project_path, body)
            return _ok({"project": project_path, "profile": profile})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/power_query/credential-profiles/{profile_id}")
    def runtime_power_query_delete_credential_profile(profile_id: str, project: Optional[str] = None):
        from dax_project.power_query import delete_credential_profile

        try:
            project_path = _resolve_project_path_runtime(project)
            deleted = delete_credential_profile(project_path, profile_id)
            return _ok({"project": project_path, "deleted": bool(deleted), "profile_id": profile_id})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/credential-profiles/{profile_id}/test")
    def runtime_power_query_test_credential_profile(profile_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import execute_power_query_adapter, get_credential_profile
        from dax_project.power_query.connectors.oauth import readiness_from_result

        connector_to_function = {
            "sql": "Sql.Database",
            "sql_database": "Sql.Database",
            "sqlserver": "Sql.Database",
            "sql_server": "Sql.Database",
            "postgres": "PostgreSQL.Database",
            "postgresql": "PostgreSQL.Database",
            "mysql": "MySQL.Database",
            "odbc": "Odbc.DataSource",
            "oledb": "OleDb.DataSource",
            "ado_dotnet": "AdoDotNet.DataSource",
            "oracle": "Oracle.Database",
            "db2": "DB2.Database",
            "informix": "Informix.Database",
            "sap_hana": "SapHana.Database",
            "sybase": "Sybase.Database",
            "teradata": "Teradata.Database",
            "access": "Access.Database",
            "odata": "OData.Feed",
            "odata_feed": "OData.Feed",
            "web": "Web.Contents",
            "web_page": "Web.Page",
            "web_browser": "Web.BrowserContents",
            "web_action": "WebAction.Request",
            "sharepoint": "SharePoint.Contents",
            "microsoft_graph": "SharePoint.Contents",
            "graph": "SharePoint.Contents",
            "exchange": "Exchange.Contents",
            "active_directory": "ActiveDirectory.Domains",
            "azure_storage": "AzureStorage.Blobs",
            "azure_blob": "AzureStorage.Blobs",
            "azure_data_lake": "AzureStorage.DataLake",
            "azure_table_storage": "AzureStorage.Tables",
            "delta_lake": "DeltaLake.Table",
            "hdfs": "Hdfs.Contents",
            "hdinsight": "HdInsight.Contents",
            "cdm": "Cdm.Contents",
            "salesforce": "Salesforce.Data",
            "google_analytics": "GoogleAnalytics.Accounts",
            "adobe_analytics": "AdobeAnalytics.Cubes",
            "soda": "Soda.Feed",
            "analysis_services": "AnalysisServices.Databases",
            "xmla": "AnalysisServices.Databases",
            "semantic_cube": "AnalysisServices.Databases",
            "powerbi_dataflows": "PowerBI.Dataflows",
            "essbase": "Essbase.Cubes",
            "sap_business_warehouse": "SapBusinessWarehouse.Cubes",
            "fabric_ai": "FabricAI.Prompt",
        }
        try:
            project_path = _resolve_project_path_runtime(project)
            profile = get_credential_profile(project_path, profile_id)
            if not profile:
                return _err(404, f"Credential profile {profile_id!r} was not found")
            connector_id = str(profile.get("connector_id") or "").strip().lower()
            function_name = str(payload.get("function_name") or connector_to_function.get(connector_id) or "Sql.Database")
            adapter_options = payload.get("adapter_options") if isinstance(payload.get("adapter_options"), Mapping) else {}
            result = execute_power_query_adapter(
                function_name,
                {
                    "fixture_mode": False,
                    "project_root": project_path,
                    "credential_profile_id": profile_id,
                    "options": dict(adapter_options or {}),
                    "approval_record": payload.get("approval_record") if isinstance(payload.get("approval_record"), Mapping) else None,
                    "privacy_level": str(profile.get("privacy_level") or "organizational"),
                },
                operation=str(payload.get("operation") or "preview"),
            ).to_dict()
            readiness = readiness_from_result(
                connector_id=connector_id,
                profile=profile,
                result=result,
                mock_live=bool((adapter_options or {}).get("mock_live")),
            )
            return _ok({"project": project_path, "profile": profile, "result": result, "readiness": readiness, **readiness})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/power_query/functions/{function_name}")
    def runtime_power_query_function(function_name: str):
        from dax_project.power_query import get_function_metadata

        meta = get_function_metadata(function_name)
        if meta is None:
            return _err(404, f"Unknown transform function: {function_name!r}")
        return _ok({"function": meta.to_dict()})

    @app.get("/runtime/power_query/queries")
    def runtime_power_query_queries(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            return _ok({"project": project_path, "queries": _power_query_entries_for_model(model)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries")
    def runtime_power_query_create(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        import yaml as _yaml

        from dax_project.power_query import build_power_query_metadata

        try:
            query_id = str((payload or {}).get("query_id") or "").strip()
            _validate_safe_name(query_id, label="query_id")
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing_ids = {
                _power_query_query_id(query).upper()
                for query in _power_query_entries_for_model(model)
                if _power_query_query_id(query)
            }
            if query_id.upper() in existing_ids:
                return _err(400, f"Transform query {query_id!r} already exists")

            tables_dir = (Path(project_path) / "model" / "tables").resolve()
            tables_dir.mkdir(parents=True, exist_ok=True)
            source_table = str((payload or {}).get("source_table") or "").strip()
            table_name = source_table or query_id
            _validate_safe_name(table_name, label="table_name")
            table_path = (tables_dir / f"{table_name}.yaml").resolve()
            try:
                table_path.relative_to(tables_dir)
            except ValueError as exc:
                raise ValueError("Invalid transform table path") from exc

            if table_path.exists():
                table_yaml = _yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
                if not isinstance(table_yaml, dict):
                    return _err(400, f"Table YAML for {table_name!r} must be a mapping")
            else:
                table_yaml = {"name": table_name, "columns": [], "is_calculated": False}

            columns = [
                str(item.get("name") or "").strip()
                for item in (table_yaml.get("columns") or [])
                if isinstance(item, Mapping) and str(item.get("name") or "").strip()
            ]
            raw_m = str((payload or {}).get("raw_m") or "").strip()
            source_settings: dict[str, Any] = {}
            starter = str((payload or {}).get("starter") or (payload or {}).get("template") or "blank").strip().lower()
            source_path = str((payload or {}).get("source_path") or "").strip()
            source = table_yaml.get("source") if isinstance(table_yaml.get("source"), Mapping) else {}
            if not raw_m:
                if source_path:
                    raw_m = _power_query_file_raw_m(source_path)
                    source_settings["path"] = source_path
                elif starter == "table" and source_table and str(source.get("type") or "").strip().lower() == "csv" and str(source.get("path") or "").strip():
                    raw_m = _power_query_file_raw_m(str(source.get("path") or "").strip())
                    source_settings["source_table"] = source_table
                    source_settings["path"] = str(source.get("path") or "").strip()
                else:
                    raw_m = _power_query_empty_table_raw_m(columns)
                    if source_table:
                        source_settings["source_table"] = source_table
            if not raw_m.strip():
                return _err(400, "raw_m must be a non-empty string")

            metadata = build_power_query_metadata(
                query_id=query_id,
                raw_m=raw_m,
                table_name=table_name,
                partition_name=str((payload or {}).get("partition_name") or query_id),
                mode=str((payload or {}).get("mode") or table_yaml.get("storage_mode") or "import"),
            )
            metadata["load_enabled"] = bool((payload or {}).get("load_enabled", False))
            metadata["refresh_enabled"] = bool((payload or {}).get("refresh_enabled", True))
            metadata["authoring_origin"] = {"operation": "create", "starter": starter or "blank"}
            for key in ("credential_profile_id", "privacy_level"):
                value = (payload or {}).get(key)
                if isinstance(value, str) and value.strip():
                    metadata[key] = value.strip()
            payload_source_settings = (payload or {}).get("source_settings")
            if isinstance(payload_source_settings, Mapping):
                source_settings.update(dict(payload_source_settings))
            if source_settings:
                metadata["source_settings"] = source_settings

            current = table_yaml.get("power_query")
            if isinstance(current, Mapping):
                additional = list(current.get("additional_queries") or [])
                if any(isinstance(item, Mapping) and _power_query_entry_matches(item, query_id) for item in additional):
                    return _err(400, f"Transform query {query_id!r} already exists")
                next_current = dict(current)
                additional.append(metadata)
                next_current["additional_queries"] = additional
                table_yaml["power_query"] = next_current
            else:
                table_yaml["power_query"] = metadata

            if source_path and not isinstance(table_yaml.get("source"), Mapping):
                table_yaml["source"] = {"type": "csv", "path": source_path}
            table_path.write_text(
                _yaml.safe_dump(table_yaml, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            _invalidate_engine_cache_for_project(project_path)
            model, _pages, _visuals = load_project(project_path)
            return _ok({
                "project": project_path,
                "query": metadata,
                "queries": _power_query_entries_for_model(model),
                "path": str(table_path),
                "created": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/power_query/graph")
    def runtime_power_query_graph(project: Optional[str] = None):
        from dax_project.power_query import build_power_query_graph

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            return _ok({"project": project_path, "graph": build_power_query_graph(_power_query_entries_for_model(model))})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/power_query/parity-readiness")
    def runtime_power_query_parity_readiness(
        project: Optional[str] = None,
        schema_probe_mode: str = "plan",
        credential_profile_id: Optional[str] = None,
        fixture_mode: bool = True,
        execution_target: str = "duckdb",
    ):
        from dax_project.power_query import build_power_query_project_parity_readiness

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            readiness = build_power_query_project_parity_readiness(
                _power_query_entries_for_model(model),
                project_root=project_path,
                schema_probe_mode=schema_probe_mode,
                credential_profile_id=credential_profile_id,
                fixture_mode=fixture_mode,
                execution_target=execution_target,
                persist_certification=True,
                persist_local_parity=True,
            )
            return _ok({"project": project_path, "readiness": readiness})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/power_query/queries/{query_id}")
    def runtime_power_query_query(query_id: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            return _ok({"project": project_path, "query": _find_power_query_entry(model, query_id)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/authoring-action")
    def runtime_power_query_authoring_action(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            operation = str((payload or {}).get("operation") or "").strip().lower()
            if operation not in {"duplicate", "reference", "rename", "settings"}:
                return _err(400, "operation must be duplicate, reference, rename, or settings")
            persist = bool((payload or {}).get("persist", False))
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            records = _power_query_table_records(project_path, model)
            target_record = _power_query_find_record(records, query_id)
            existing = target_record["query"]
            current_id = _power_query_query_id(existing)
            if not current_id:
                return _err(400, "Selected transform query has no query_id")
            raw_m_override = (payload or {}).get("raw_m")
            if raw_m_override is not None and not isinstance(raw_m_override, str):
                return _err(400, "raw_m must be a string if provided")
            source_raw_m = raw_m_override if isinstance(raw_m_override, str) else str(existing.get("raw_m") or "")
            existing_ids = {
                _power_query_query_id(record["query"]).upper()
                for record in records
                if isinstance(record.get("query"), Mapping) and _power_query_query_id(record["query"])
            }

            next_entries: list[dict[str, Any]] = [dict(record["query"]) for record in records]
            affected_query_id = current_id
            affected_raw_m = source_raw_m
            new_query: dict[str, Any] | None = None
            reference_updates: list[dict[str, Any]] = []

            if operation in {"duplicate", "reference", "rename"}:
                new_query_id_raw = (payload or {}).get("new_query_id")
                if not isinstance(new_query_id_raw, str) or not new_query_id_raw.strip():
                    return _err(400, "new_query_id must be a non-empty string")
                new_query_id = new_query_id_raw.strip()
                if operation != "rename" and new_query_id.upper() in existing_ids:
                    return _err(400, f"Transform query {new_query_id!r} already exists")
                if operation == "rename" and new_query_id.upper() != current_id.upper() and new_query_id.upper() in existing_ids:
                    return _err(400, f"Transform query {new_query_id!r} already exists")
            else:
                new_query_id = current_id

            if operation in {"duplicate", "reference"}:
                if operation == "reference":
                    new_raw_m = f"let\n    Source = {_power_query_m_identifier(current_id)}\nin\n    Source"
                else:
                    new_raw_m = source_raw_m
                new_query = _power_query_metadata_from_existing(
                    existing,
                    query_id=new_query_id,
                    raw_m=new_raw_m,
                    table_name=str(existing.get("table_name") or target_record.get("table_name") or "") or None,
                    partition_name=new_query_id,
                    mode=str(existing.get("mode") or "") or None,
                    preserve_additional=False,
                )
                new_query["load_enabled"] = bool((payload or {}).get("load_enabled", False))
                new_query["refresh_enabled"] = bool((payload or {}).get("refresh_enabled", True))
                new_query["authoring_origin"] = {"operation": operation, "source_query_id": current_id}
                for key in ("credential_profile_id", "privacy_level"):
                    value = (payload or {}).get(key)
                    if isinstance(value, str) and value.strip():
                        new_query[key] = value.strip()
                source_settings = (payload or {}).get("source_settings")
                if isinstance(source_settings, Mapping):
                    new_query["source_settings"] = dict(source_settings)
                next_entries.append(new_query)
                affected_query_id = new_query_id
                affected_raw_m = new_raw_m
                if persist:
                    _power_query_append_additional_query(target_record, new_query)

            elif operation == "rename":
                target_query = _power_query_metadata_from_existing(
                    existing,
                    query_id=new_query_id,
                    raw_m=source_raw_m,
                    table_name=str(existing.get("table_name") or target_record.get("table_name") or "") or None,
                    partition_name=new_query_id if str(existing.get("partition_name") or current_id).upper() == current_id.upper() else str(existing.get("partition_name") or "") or None,
                    mode=str(existing.get("mode") or "") or None,
                    preserve_additional=target_record.get("kind") == "primary",
                )
                target_record["next_query"] = target_query
                affected_query_id = new_query_id
                affected_raw_m = source_raw_m
                for idx, item in enumerate(next_entries):
                    if _power_query_entry_matches(item, current_id):
                        next_entries[idx] = target_query
                        break
                if bool((payload or {}).get("update_references", True)):
                    for record in records:
                        record_query = record.get("query")
                        if not isinstance(record_query, Mapping) or _power_query_entry_matches(record_query, current_id):
                            continue
                        original_raw = str(record_query.get("raw_m") or "")
                        updated_raw, replacement_count = _replace_power_query_reference(original_raw, current_id, new_query_id)
                        if replacement_count <= 0 or updated_raw == original_raw:
                            continue
                        updated_query = _power_query_metadata_from_existing(
                            record_query,
                            query_id=_power_query_query_id(record_query),
                            raw_m=updated_raw,
                            table_name=str(record_query.get("table_name") or record.get("table_name") or "") or None,
                            partition_name=str(record_query.get("partition_name") or "") or None,
                            mode=str(record_query.get("mode") or "") or None,
                            preserve_additional=record.get("kind") == "primary",
                        )
                        record["next_query"] = updated_query
                        reference_updates.append(
                            {
                                "query_id": _power_query_query_id(record_query),
                                "replacement_count": replacement_count,
                            }
                        )
                        for idx, item in enumerate(next_entries):
                            if _power_query_entry_matches(item, _power_query_query_id(record_query)):
                                next_entries[idx] = updated_query
                                break

            elif operation == "settings":
                updated_query = _power_query_metadata_from_existing(
                    existing,
                    query_id=current_id,
                    raw_m=source_raw_m,
                    table_name=str(existing.get("table_name") or target_record.get("table_name") or "") or None,
                    partition_name=str(existing.get("partition_name") or "") or None,
                    mode=str(existing.get("mode") or "") or None,
                    preserve_additional=target_record.get("kind") == "primary",
                )
                if "load_enabled" in payload:
                    updated_query["load_enabled"] = bool(payload.get("load_enabled"))
                if "refresh_enabled" in payload:
                    updated_query["refresh_enabled"] = bool(payload.get("refresh_enabled"))
                for key in ("credential_profile_id", "privacy_level"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        updated_query[key] = value.strip()
                    elif key in payload and not value:
                        updated_query.pop(key, None)
                source_settings = payload.get("source_settings")
                if isinstance(source_settings, Mapping):
                    updated_query["source_settings"] = dict(source_settings)
                target_record["next_query"] = updated_query
                affected_raw_m = source_raw_m
                for idx, item in enumerate(next_entries):
                    if _power_query_entry_matches(item, current_id):
                        next_entries[idx] = updated_query
                        break

            credential_profile_id = None
            if isinstance((payload or {}).get("credential_profile_id"), str) and str((payload or {}).get("credential_profile_id")).strip():
                credential_profile_id = str((payload or {}).get("credential_profile_id")).strip()
            preview = _power_query_authoring_preview(
                next_entries,
                project_path=project_path,
                query_id=affected_query_id,
                raw_m=affected_raw_m,
                credential_profile_id=credential_profile_id,
            )
            written_paths: list[str] = []
            if persist:
                written_paths = _power_query_apply_record_updates(records)
                if new_query is not None:
                    import yaml as _yaml

                    table_path = Path(target_record["table_path"])
                    table_path.write_text(
                        _yaml.safe_dump(target_record["table_yaml"], sort_keys=False, allow_unicode=True),
                        encoding="utf-8",
                    )
                    written_paths.append(str(table_path))
                _invalidate_engine_cache_for_project(project_path)
            return _ok({
                "project": project_path,
                "operation": operation,
                "persisted": persist,
                "query_id": current_id,
                "affected_query_id": affected_query_id,
                "query": new_query or next((item for item in next_entries if _power_query_entry_matches(item, affected_query_id)), None),
                "queries": next_entries,
                "reference_updates": reference_updates,
                "paths": sorted(set(written_paths)),
                **preview,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    def _runtime_power_query_command(query_id: str, project: Optional[str], payload: dict, *, persist: bool):
        try:
            command_id = str((payload or {}).get("command_id") or (payload or {}).get("id") or "").strip()
            command = _power_query_transform_command(command_id)
            if command_id == "preview":
                return runtime_power_query_preview(query_id, project=project, payload=payload)
            if command.get("template_kind") == "query_action":
                mapping = {
                    "query_duplicate": "duplicate",
                    "query_reference": "reference",
                    "query_rename": "rename",
                    "query_settings": "settings",
                }
                values = (payload or {}).get("values")
                values_map = values if isinstance(values, Mapping) else {}
                action_payload = {
                    "operation": mapping.get(command_id, "settings"),
                    "persist": persist,
                    "raw_m": (payload or {}).get("raw_m"),
                }
                action_payload.update(dict(values_map))
                return runtime_power_query_authoring_action(query_id, project=project, payload=action_payload)

            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            records = _power_query_table_records(project_path, model)
            target_record = _power_query_find_record(records, query_id)
            existing = target_record["query"]
            draft = _power_query_command_draft(
                existing=existing,
                query_id=query_id,
                payload=payload or {},
                project_path=project_path,
            )
            updated_query = _power_query_metadata_from_existing(
                existing,
                query_id=str(existing.get("query_id") or query_id),
                raw_m=str(draft["raw_m"]),
                table_name=str(existing.get("table_name") or target_record.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
                preserve_additional=target_record.get("kind") == "primary",
            )
            draft["query"] = updated_query
            next_entries: list[dict[str, Any]] = []
            for record in records:
                item = dict(record["query"])
                if record is target_record:
                    item = updated_query
                next_entries.append(item)
            credential_profile_id = None
            if isinstance((payload or {}).get("credential_profile_id"), str) and str((payload or {}).get("credential_profile_id")).strip():
                credential_profile_id = str((payload or {}).get("credential_profile_id")).strip()
            preview = _power_query_authoring_preview(
                next_entries,
                project_path=project_path,
                query_id=str(updated_query.get("query_id") or query_id),
                raw_m=str(draft["raw_m"]),
                credential_profile_id=credential_profile_id,
            )
            written_paths: list[str] = []
            if persist:
                target_record["next_query"] = updated_query
                written_paths = _power_query_apply_record_updates(records)
                _invalidate_engine_cache_for_project(project_path)
            return _ok({
                "project": project_path,
                "command": command,
                "command_id": command_id,
                "persisted": persist,
                "query_id": str(existing.get("query_id") or query_id),
                "step_id": draft.get("step_id"),
                "expression": draft.get("expression"),
                "raw_m": draft.get("raw_m"),
                "query": updated_query,
                "paths": written_paths,
                "draft": not persist,
                "applied_step_edit_preview": draft.get("applied_step_edit_preview"),
                **preview,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/commands/preview")
    def runtime_power_query_command_preview(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        return _runtime_power_query_command(query_id, project, payload or {}, persist=False)

    @app.post("/runtime/power_query/queries/{query_id}/commands/apply")
    def runtime_power_query_command_apply(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        return _runtime_power_query_command(query_id, project, payload or {}, persist=True)

    @app.put("/runtime/power_query/queries/{query_id}")
    def runtime_power_query_update(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        import yaml as _yaml

        from dax_project.power_query import build_power_query_metadata

        try:
            raw_m = payload.get("raw_m")
            if not isinstance(raw_m, str) or not raw_m.strip():
                return _err(400, "raw_m must be a non-empty string")
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            table_name = str(existing.get("table_name") or "").strip()
            table_path = _power_query_table_yaml_path(project_path, table_name)
            table_yaml = _yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
            if not isinstance(table_yaml, dict):
                return _err(400, f"Table YAML for {table_name!r} must be a mapping")

            partition_name = str(payload.get("partition_name") or existing.get("partition_name") or table_name)
            mode = str(payload.get("mode") or existing.get("mode") or table_yaml.get("storage_mode") or "import")
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=raw_m,
                table_name=table_name,
                partition_name=partition_name,
                mode=mode,
            )

            current = table_yaml.get("power_query")
            if isinstance(current, Mapping) and _power_query_entry_matches(current, query_id):
                previous_additional = current.get("additional_queries")
                if isinstance(previous_additional, list) and previous_additional:
                    metadata["additional_queries"] = previous_additional
                table_yaml["power_query"] = metadata
            elif isinstance(current, Mapping):
                additional = list(current.get("additional_queries") or [])
                updated = False
                for idx, item in enumerate(additional):
                    if isinstance(item, Mapping) and _power_query_entry_matches(item, query_id):
                        additional[idx] = metadata
                        updated = True
                        break
                if not updated:
                    return _err(404, f"Transform query {query_id!r} was not found in table YAML")
                next_current = dict(current)
                next_current["additional_queries"] = additional
                table_yaml["power_query"] = next_current
            else:
                table_yaml["power_query"] = metadata

            table_path.write_text(
                _yaml.safe_dump(table_yaml, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"project": project_path, "query": metadata, "path": str(table_path)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/parse")
    def runtime_power_query_parse(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_metadata

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or ""),
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({"project": project_path, "query": metadata})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/intellisense")
    def runtime_power_query_intellisense(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_intellisense

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            cursor_raw = payload.get("cursor_offset")
            cursor_offset = len(raw_m) if isinstance(raw_m, str) else len(str(existing.get("raw_m") or ""))
            if cursor_raw is not None:
                try:
                    cursor_offset = int(cursor_raw)
                except (TypeError, ValueError):
                    return _err(400, "cursor_offset must be an integer if provided")
            step_raw = payload.get("step_id")
            if step_raw is not None and not isinstance(step_raw, str):
                return _err(400, "step_id must be a string if provided")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            assist = build_power_query_intellisense(
                source_raw_m,
                cursor_offset=cursor_offset,
                step_id=step_raw.strip() if isinstance(step_raw, str) and step_raw.strip() else None,
                query_entries=_power_query_entries_for_model(model),
            )
            return _ok({
                "project": project_path,
                "query_id": existing.get("query_id"),
                "intellisense": assist,
                "draft": isinstance(raw_m, str),
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/steps/{step_id}/patch")
    def runtime_power_query_patch_step(query_id: str, step_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_applied_step_edit_preview, build_power_query_metadata, replace_m_step_expression

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            expression = payload.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                return _err(400, "expression must be a non-empty string")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = replace_m_step_expression(source_raw_m, step_id, expression)
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            patched_step = next(
                (
                    step for step in metadata.get("steps", [])
                    if isinstance(step, Mapping) and str(step.get("id") or "").strip().upper() == step_id.strip().upper()
                ),
                None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "step_id": step_id,
                "raw_m": patched_raw_m,
                "query": metadata,
                "step": patched_step,
                "applied_step_edit_preview": build_power_query_applied_step_edit_preview(
                    before_raw_m=source_raw_m,
                    after_raw_m=patched_raw_m,
                    operation="patch",
                    step_id=step_id,
                    project_root=project_path,
                ),
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/steps/add")
    def runtime_power_query_add_step(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import add_m_step_expression, build_power_query_applied_step_edit_preview, build_power_query_metadata

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            step_id = payload.get("step_id")
            expression = payload.get("expression")
            after_step_id = payload.get("after_step_id")
            if not isinstance(step_id, str) or not step_id.strip():
                return _err(400, "step_id must be a non-empty string")
            if not isinstance(expression, str) or not expression.strip():
                return _err(400, "expression must be a non-empty string")
            if after_step_id is not None and not isinstance(after_step_id, str):
                return _err(400, "after_step_id must be a string if provided")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = add_m_step_expression(
                source_raw_m,
                step_id,
                expression,
                after_step_id=after_step_id.strip() if isinstance(after_step_id, str) and after_step_id.strip() else None,
                make_result=bool(payload.get("make_result", True)),
            )
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "step_id": step_id,
                "raw_m": patched_raw_m,
                "query": metadata,
                "applied_step_edit_preview": build_power_query_applied_step_edit_preview(
                    before_raw_m=source_raw_m,
                    after_raw_m=patched_raw_m,
                    operation="add",
                    step_id=step_id,
                    project_root=project_path,
                ),
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/steps/{step_id}/delete")
    def runtime_power_query_delete_step(query_id: str, step_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_applied_step_edit_preview, build_power_query_metadata, delete_m_step_expression

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = delete_m_step_expression(source_raw_m, step_id)
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "step_id": step_id,
                "raw_m": patched_raw_m,
                "query": metadata,
                "applied_step_edit_preview": build_power_query_applied_step_edit_preview(
                    before_raw_m=source_raw_m,
                    after_raw_m=patched_raw_m,
                    operation="delete",
                    step_id=step_id,
                    project_root=project_path,
                ),
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/steps/{step_id}/rename")
    def runtime_power_query_rename_step(query_id: str, step_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_applied_step_edit_preview, build_power_query_metadata, rename_m_step_expression

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            new_step_id = payload.get("new_step_id")
            if not isinstance(new_step_id, str) or not new_step_id.strip():
                return _err(400, "new_step_id must be a non-empty string")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = rename_m_step_expression(source_raw_m, step_id, new_step_id)
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "step_id": step_id,
                "new_step_id": new_step_id,
                "raw_m": patched_raw_m,
                "query": metadata,
                "applied_step_edit_preview": build_power_query_applied_step_edit_preview(
                    before_raw_m=source_raw_m,
                    after_raw_m=patched_raw_m,
                    operation="rename",
                    step_id=step_id,
                    project_root=project_path,
                ),
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/steps/reorder")
    def runtime_power_query_reorder_step(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_applied_step_edit_preview, build_power_query_metadata, reorder_m_step_expression

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            step_id = payload.get("step_id")
            before_step_id = payload.get("before_step_id")
            after_step_id = payload.get("after_step_id")
            if not isinstance(step_id, str) or not step_id.strip():
                return _err(400, "step_id must be a non-empty string")
            if before_step_id is not None and not isinstance(before_step_id, str):
                return _err(400, "before_step_id must be a string if provided")
            if after_step_id is not None and not isinstance(after_step_id, str):
                return _err(400, "after_step_id must be a string if provided")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = reorder_m_step_expression(
                source_raw_m,
                step_id,
                before_step_id=before_step_id.strip() if isinstance(before_step_id, str) and before_step_id.strip() else None,
                after_step_id=after_step_id.strip() if isinstance(after_step_id, str) and after_step_id.strip() else None,
            )
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "step_id": step_id,
                "raw_m": patched_raw_m,
                "query": metadata,
                "applied_step_edit_preview": build_power_query_applied_step_edit_preview(
                    before_raw_m=source_raw_m,
                    after_raw_m=patched_raw_m,
                    operation="reorder",
                    step_id=step_id,
                    project_root=project_path,
                ),
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/settings/patch")
    def runtime_power_query_patch_settings(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_applied_step_edit_preview, build_power_query_metadata, replace_m_step_expression

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            step_id = payload.get("step_id")
            expression = payload.get("expression")
            if step_id is not None and not isinstance(step_id, str):
                return _err(400, "step_id must be a string if provided")
            if expression is not None and not isinstance(expression, str):
                return _err(400, "expression must be a string if provided")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = (
                replace_m_step_expression(source_raw_m, step_id, expression)
                if isinstance(step_id, str) and step_id.strip() and isinstance(expression, str) and expression.strip()
                else source_raw_m
            )
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "step_id": step_id,
                "settings": payload.get("settings") if isinstance(payload.get("settings"), Mapping) else {},
                "raw_m": patched_raw_m,
                "query": metadata,
                "applied_step_edit_preview": build_power_query_applied_step_edit_preview(
                    before_raw_m=source_raw_m,
                    after_raw_m=patched_raw_m,
                    operation="settings_patch",
                    step_id=step_id if isinstance(step_id, str) else None,
                    project_root=project_path,
                ),
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/parameter/patch")
    def runtime_power_query_patch_parameter(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_metadata, replace_m_parameter_value_expression

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            expression = payload.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                return _err(400, "expression must be a non-empty string")
            source_raw_m = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            patched_raw_m = replace_m_parameter_value_expression(source_raw_m, expression)
            metadata = build_power_query_metadata(
                query_id=str(existing.get("query_id") or query_id),
                raw_m=patched_raw_m,
                table_name=str(existing.get("table_name") or "") or None,
                partition_name=str(existing.get("partition_name") or "") or None,
                mode=str(existing.get("mode") or "") or None,
            )
            return _ok({
                "project": project_path,
                "query_id": metadata.get("query_id"),
                "raw_m": patched_raw_m,
                "query": metadata,
                "draft": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/map-source")
    def runtime_power_query_map_source(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import map_source_bindings_from_m, map_sources_from_m

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            source_text = raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or "")
            mappings = map_sources_from_m(source_text)
            bindings = map_source_bindings_from_m(source_text)
            return _ok({
                "project": project_path,
                "query_id": existing.get("query_id"),
                "source_mapping": mappings[0].to_dict() if mappings else None,
                "source_mappings": [mapping.to_dict() for mapping in mappings],
                "source_mapping_count": len(mappings),
                "source_bindings": [binding.to_dict() for binding in bindings],
                "source_binding_count": len(bindings),
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/transpile")
    def runtime_power_query_transpile(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_neutral_transform_plan

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            schema_probe_mode = str(payload.get("schema_probe_mode") or "plan")
            credential_profile_id = payload.get("credential_profile_id")
            if credential_profile_id is not None and not isinstance(credential_profile_id, str):
                return _err(400, "credential_profile_id must be a string if provided")
            fixture_mode = bool(payload.get("fixture_mode", True))
            execution_target = str(payload.get("execution_target") or "duckdb")
            plan = build_neutral_transform_plan(
                raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or ""),
                project_root=project_path,
                schema_probe_mode=schema_probe_mode,
                credential_profile_id=credential_profile_id,
                fixture_mode=fixture_mode,
                execution_target=execution_target,
            )
            return _ok({
                "project": project_path,
                "query_id": existing.get("query_id"),
                "plan": plan,
                "execution_scope": "neutral_transform_plan",
                "message": "This endpoint returns a neutral transform readiness plan; full SQL emission is a later transform slice.",
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/parity-gap-report")
    def runtime_power_query_parity_gap_report(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_parity_gap_report

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            existing = _find_power_query_entry(model, query_id)
            raw_m = payload.get("raw_m")
            if raw_m is not None and not isinstance(raw_m, str):
                return _err(400, "raw_m must be a string if provided")
            schema_probe_mode = str(payload.get("schema_probe_mode") or "plan")
            credential_profile_id = payload.get("credential_profile_id")
            if credential_profile_id is not None and not isinstance(credential_profile_id, str):
                return _err(400, "credential_profile_id must be a string if provided")
            fixture_mode = bool(payload.get("fixture_mode", True))
            execution_target = str(payload.get("execution_target") or "duckdb")
            report = build_power_query_parity_gap_report(
                raw_m if isinstance(raw_m, str) else str(existing.get("raw_m") or ""),
                project_root=project_path,
                schema_probe_mode=schema_probe_mode,
                credential_profile_id=credential_profile_id,
                fixture_mode=fixture_mode,
                execution_target=execution_target,
                query_id=str(existing.get("query_id") or query_id),
                query_entries=_power_query_entries_for_model(model),
            )
            return _ok({
                "project": project_path,
                "query_id": existing.get("query_id"),
                "parity_gap_report": report,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/diagnostics")
    def runtime_power_query_diagnostics(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import (
            build_power_query_diagnostics,
            build_power_query_metadata,
            evaluate_preview_table,
        )

        try:
            started = time.perf_counter()
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            query = _find_power_query_entry(model, query_id)
            raw_m_payload = payload.get("raw_m")
            if raw_m_payload is not None and not isinstance(raw_m_payload, str):
                return _err(400, "raw_m must be a string if provided")
            raw_m = raw_m_payload if isinstance(raw_m_payload, str) else str(query.get("raw_m") or "")
            include_preview = bool(payload.get("include_preview", True))
            target_step_id_raw = payload.get("step_id")
            if target_step_id_raw is not None and not isinstance(target_step_id_raw, str):
                return _err(400, "step_id must be a string if provided")
            target_step_id = target_step_id_raw.strip() if isinstance(target_step_id_raw, str) and target_step_id_raw.strip() else None
            limit = int(payload.get("limit") or 100)
            if limit <= 0:
                limit = 100
            limit = min(limit, 1000)

            metadata = build_power_query_metadata(
                query_id=str(query.get("query_id") or query_id),
                raw_m=raw_m,
                table_name=str(query.get("table_name") or "") or None,
                partition_name=str(query.get("partition_name") or "") or None,
                mode=str(query.get("mode") or "") or None,
            )
            timings_ms: dict[str, float] = {}
            preview: dict[str, Any] | None = None
            source_sql = ""
            source_row_count: int | None = None
            preview_error: str | None = None

            if include_preview:
                try:
                    source_started = time.perf_counter()
                    source_limit = min(max(limit * 10, 100), 5000)
                    adapter_preview = _power_query_preview_from_adapter(metadata, project_path=project_path, limit=source_limit, payload=payload)
                    if adapter_preview is not None:
                        source_preview = dict(adapter_preview.get("source_preview") or {})
                        preview = dict(adapter_preview.get("preview") or {})
                        preview["rows"] = list(preview.get("rows") or [])[:limit]
                        preview["row_count"] = len(preview["rows"])
                        source_sql = str(source_preview.get("sql") or "")
                        source_row_count = int(source_preview.get("row_count") or len(source_preview.get("rows") or []))
                        timings_ms["adapter_preview"] = round((time.perf_counter() - source_started) * 1000, 3)
                    else:
                        try:
                            source_block = _power_query_preview_source_block(metadata)
                            src = _normalize_import_source(source_block, project_path=project_path, allow_missing_table=False)
                            source_preview = _preview_from_source(project_path=project_path, src=src, limit=source_limit)
                            timings_ms["source_preview"] = round((time.perf_counter() - source_started) * 1000, 3)
                        except Exception as exc:  # noqa: BLE001
                            preview_error = str(exc)
                            source_preview = {"columns": [], "rows": [], "sql": ""}
                        source_sql = str(source_preview.get("sql") or "")
                        source_rows = source_preview.get("rows") or []
                        source_row_count = len(source_rows)
                        eval_started = time.perf_counter()
                        evaluated = evaluate_preview_table(
                            raw_m=raw_m,
                            columns=source_preview.get("columns") or [],
                            rows=source_rows,
                            source_sql=source_sql,
                            target_step_id=target_step_id,
                            helper_queries=_power_query_helper_raw_m(model, query),
                            table_variables=_power_query_reference_tables(project_path=project_path, model=model, current_query=query, limit=source_limit),
                        )
                        timings_ms["preview_evaluation"] = round((time.perf_counter() - eval_started) * 1000, 3)
                        preview = evaluated.to_preview_dict(source_sql=source_sql)
                        preview["rows"] = list(preview.get("rows") or [])[:limit]
                        preview["row_count"] = len(preview["rows"])
                        if preview_error and (evaluated.applied_steps or evaluated.columns):
                            preview_error = None
                except Exception as exc:  # noqa: BLE001
                    preview_error = str(exc)

            timings_ms["total"] = round((time.perf_counter() - started) * 1000, 3)
            report = build_power_query_diagnostics(
                query_id=str(metadata.get("query_id") or query_id),
                raw_m=raw_m,
                table_name=str(metadata.get("table_name") or "") or None,
                partition_name=str(metadata.get("partition_name") or "") or None,
                source_sql=source_sql,
                source_row_count=source_row_count,
                preview=preview,
                preview_error=preview_error,
                timings_ms=timings_ms,
                draft=isinstance(raw_m_payload, str),
                target_step_id=target_step_id,
            )
            return _ok({"project": project_path, "query_id": metadata.get("query_id"), "diagnostics": report})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/power_query/compatibility-report")
    def runtime_power_query_compatibility_report(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            reports: list[dict[str, Any]] = []
            for query in _power_query_entries_for_model(model):
                report = query.get("compatibility_report")
                if isinstance(report, Mapping):
                    item = dict(report)
                else:
                    from dax_project.power_query import build_power_query_metadata

                    rebuilt = build_power_query_metadata(
                        query_id=str(query.get("query_id") or query.get("table_name") or "Query"),
                        raw_m=str(query.get("raw_m") or ""),
                        table_name=str(query.get("table_name") or "") or None,
                        partition_name=str(query.get("partition_name") or "") or None,
                        mode=str(query.get("mode") or "") or None,
                    )
                    item = dict(rebuilt.get("compatibility_report") or {})
                item.setdefault("query_id", query.get("query_id"))
                item.setdefault("table_name", query.get("table_name"))
                item.setdefault("partition_name", query.get("partition_name"))
                reports.append(item)
            return _ok({"project": project_path, "reports": reports})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/preview")
    def runtime_power_query_preview(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_power_query_metadata, evaluate_preview_table

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            query = _find_power_query_entry(model, query_id)
            raw_m_payload = payload.get("raw_m")
            if raw_m_payload is not None and not isinstance(raw_m_payload, str):
                return _err(400, "raw_m must be a string if provided")
            raw_m = raw_m_payload if isinstance(raw_m_payload, str) else str(query.get("raw_m") or "")
            target_step_id_raw = payload.get("step_id")
            if target_step_id_raw is not None and not isinstance(target_step_id_raw, str):
                return _err(400, "step_id must be a string if provided")
            target_step_id = target_step_id_raw.strip() if isinstance(target_step_id_raw, str) and target_step_id_raw.strip() else None
            query_for_preview: Mapping[str, Any] = query
            if isinstance(raw_m_payload, str):
                query_for_preview = build_power_query_metadata(
                    query_id=str(query.get("query_id") or query_id),
                    raw_m=raw_m,
                    table_name=str(query.get("table_name") or "") or None,
                    partition_name=str(query.get("partition_name") or "") or None,
                    mode=str(query.get("mode") or "") or None,
                )
            limit = int(payload.get("limit") or 100)
            if limit <= 0:
                limit = 100
            limit = min(limit, 1000)
            src: dict[str, Any] | None = None
            source_preview: dict[str, Any] = {"columns": [], "rows": [], "sql": ""}
            source_error: str | None = None
            source_limit = min(max(limit * 10, 100), 5000)
            adapter_preview = _power_query_preview_from_adapter(query_for_preview, project_path=project_path, limit=limit, payload=payload)
            if adapter_preview is not None:
                preview = dict(adapter_preview.get("preview") or {})
                return _ok({
                    "project": project_path,
                    "query_id": query.get("query_id"),
                    "table_name": query.get("table_name"),
                    "source": adapter_preview.get("source"),
                    "preview": preview,
                    "adapter_result": adapter_preview.get("adapter_result"),
                    "execution_scope": preview.get("execution_scope") or "fixture_adapter",
                    "step_id": target_step_id,
                    "message": "Preview is served by the transform fixture adapter for this connector/native/semantic source.",
                })
            try:
                source_block = _power_query_preview_source_block(query_for_preview)
                src = _normalize_import_source(source_block, project_path=project_path, allow_missing_table=False)
                source_preview = _preview_from_source(project_path=project_path, src=src, limit=source_limit)
            except Exception as exc:  # noqa: BLE001
                source_error = str(exc)
            evaluated = evaluate_preview_table(
                raw_m=raw_m,
                columns=source_preview.get("columns") or [],
                rows=source_preview.get("rows") or [],
                source_sql=str(source_preview.get("sql") or ""),
                target_step_id=target_step_id,
                helper_queries=_power_query_helper_raw_m(model, query),
                table_variables=_power_query_reference_tables(project_path=project_path, model=model, current_query=query, limit=source_limit),
            )
            if source_error and not evaluated.applied_steps and not evaluated.columns:
                raise ValueError(source_error)
            preview = evaluated.to_preview_dict(source_sql=str(source_preview.get("sql") or ""))
            preview["rows"] = list(preview.get("rows") or [])[:limit]
            preview["row_count"] = len(preview["rows"])
            return _ok({
                "project": project_path,
                "query_id": query.get("query_id"),
                "table_name": query.get("table_name"),
                "source": src,
                "preview": preview,
                "execution_scope": preview.get("execution_scope") or "mapped_source",
                "step_id": target_step_id,
                "message": "Preview applies the supported M table-operation subset over mapped-source rows; unsupported steps are returned as blockers.",
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/power_query/queries/{query_id}/profile")
    def runtime_power_query_profile(query_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        from dax_project.power_query import build_data_profile, build_power_query_metadata, evaluate_preview_table

        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            query = _find_power_query_entry(model, query_id)
            raw_m_payload = payload.get("raw_m")
            if raw_m_payload is not None and not isinstance(raw_m_payload, str):
                return _err(400, "raw_m must be a string if provided")
            raw_m = raw_m_payload if isinstance(raw_m_payload, str) else str(query.get("raw_m") or "")
            target_step_id_raw = payload.get("step_id")
            if target_step_id_raw is not None and not isinstance(target_step_id_raw, str):
                return _err(400, "step_id must be a string if provided")
            target_step_id = target_step_id_raw.strip() if isinstance(target_step_id_raw, str) and target_step_id_raw.strip() else None
            query_for_profile: Mapping[str, Any] = query
            if isinstance(raw_m_payload, str):
                query_for_profile = build_power_query_metadata(
                    query_id=str(query.get("query_id") or query_id),
                    raw_m=raw_m,
                    table_name=str(query.get("table_name") or "") or None,
                    partition_name=str(query.get("partition_name") or "") or None,
                    mode=str(query.get("mode") or "") or None,
                )
            limit = int(payload.get("limit") or 1000)
            if limit <= 0:
                limit = 1000
            limit = min(limit, 5000)
            src: dict[str, Any] | None = None
            source_preview: dict[str, Any] = {"columns": [], "rows": [], "sql": ""}
            source_error: str | None = None
            adapter_preview = _power_query_preview_from_adapter(query_for_profile, project_path=project_path, limit=limit, payload=payload)
            if adapter_preview is not None:
                preview = dict(adapter_preview.get("preview") or {})
                profile = build_data_profile(
                    columns=preview.get("columns") or [],
                    rows=preview.get("rows") or [],
                )
                return _ok({
                    "project": project_path,
                    "query_id": query.get("query_id"),
                    "table_name": query.get("table_name"),
                    "source": adapter_preview.get("source"),
                    "profile": profile,
                    "adapter_result": adapter_preview.get("adapter_result"),
                    "execution_scope": preview.get("execution_scope") or "fixture_adapter",
                    "applied_steps": preview.get("applied_steps") or [],
                    "blocked_steps": preview.get("blocked_steps") or [],
                    "step_id": target_step_id,
                    "result_step_id": preview.get("result_step_id"),
                })
            try:
                source_block = _power_query_preview_source_block(query_for_profile)
                src = _normalize_import_source(source_block, project_path=project_path, allow_missing_table=False)
                source_preview = _preview_from_source(project_path=project_path, src=src, limit=limit)
            except Exception as exc:  # noqa: BLE001
                source_error = str(exc)
            evaluated = evaluate_preview_table(
                raw_m=raw_m,
                columns=source_preview.get("columns") or [],
                rows=source_preview.get("rows") or [],
                source_sql=str(source_preview.get("sql") or ""),
                target_step_id=target_step_id,
                helper_queries=_power_query_helper_raw_m(model, query),
                table_variables=_power_query_reference_tables(project_path=project_path, model=model, current_query=query, limit=limit),
            )
            if source_error and not evaluated.applied_steps and not evaluated.columns:
                raise ValueError(source_error)
            profile = build_data_profile(
                columns=evaluated.columns,
                rows=evaluated.rows,
            )
            return _ok({
                "project": project_path,
                "query_id": query.get("query_id"),
                "table_name": query.get("table_name"),
                "source": src,
                "profile": profile,
                "execution_scope": "mapped_source_plus_supported_steps" if evaluated.applied_steps else "mapped_source",
                "applied_steps": evaluated.applied_steps,
                "blocked_steps": evaluated.blocked_steps,
                "step_id": target_step_id,
                "result_step_id": evaluated.result_step_id,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/columns/distinct")
    def get_distinct_column_values(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        table: str = "",
        column: str = "",
        q: Optional[str] = None,
        limit: int = 200,
    ):
        """Return distinct values for a column for the Filters value picker.

        Deterministic ordering, best-effort type handling.
        """

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        tname = str(table or "").strip()
        cname = str(column or "").strip()
        if not tname:
            return _err(400, "table is required")
        if not cname:
            return _err(400, "column is required")

        lim = int(limit or 200)
        if lim <= 0:
            lim = 200
        lim = min(lim, 2000)

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=None)
            model_scoped = sec_state.model_scoped
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        # Check if this is a virtual table (Field Param / Calc Group / What-If)
        virtual_prefixes = ("FieldParams_", "CalcGroup_", "WhatIf_")
        is_virtual = any(tname.startswith(p) or tname.upper().startswith(p.upper()) for p in virtual_prefixes)

        if is_virtual:
            # Handle virtual table distinct values
            try:
                virtual_tables = _build_virtual_tables(model_scoped)
                vt = next((vt for vt in virtual_tables if vt["name"].upper() == tname.upper()), None)
                if vt is None:
                    return _err(400, f"Unknown virtual table: {tname!r}")
                if cname.upper() not in {c.upper() for c in vt["columns"]}:
                    return _err(400, f"Unknown column: {tname}[{cname}]")
                values = _get_virtual_table_distinct_values(model_scoped, vt["name"], cname)
                # Apply search filter if provided
                if q is not None and str(q).strip():
                    qv = str(q).strip().lower()
                    values = [v for v in values if qv in str(v).lower()]
                # Apply limit
                values = values[:lim]
                return _ok({"values": values})
            except Exception as exc:  # noqa: BLE001
                return _err(400, str(exc))

        # Physical table handling below
        # Validate table/column names via model introspection.
        try:
            tables = list_tables(model_scoped)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        if tname.upper() not in {t.upper() for t in tables}:
            return _err(400, f"Unknown table: {tname!r}")

        try:
            cols = list_columns(model_scoped, tname)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        if cname.upper() not in {c.upper() for c in cols}:
            return _err(400, f"Unknown column: {tname}[{cname}]")

        from dax_engine.sql_utils import quote_ident

        rls_sql: Optional[str] = None
        try:
            rls_sql = _case_insensitive_dict_get(sec_state.sec_predicates or {}, f"{tname}.__RLS__")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        con = None
        try:
            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            col_sql = f"{quote_ident(tname)}.{quote_ident(cname)}"

            where_sql = f"WHERE {col_sql} IS NOT NULL"
            params = []
            if q is not None and str(q).strip():
                qv = str(q).strip()
                # Text-like search across string form.
                where_sql += f" AND CAST({col_sql} AS VARCHAR) ILIKE ('%' || ? || '%')"
                params.append(qv)

            if rls_sql is not None and str(rls_sql).strip():
                where_sql += f" AND ({rls_sql})"

            sql = (
                f"SELECT DISTINCT {col_sql} AS v "
                f"FROM {quote_ident(tname)} "
                f"{where_sql} "
                f"ORDER BY v "
                f"LIMIT {lim}"
            )
            rows = con.execute(sql, params).fetchall()
            values = [r[0] for r in rows]
            return _ok({"values": values})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

    def _relationships_path(project_path: str) -> Path:
        return Path(project_path) / "model" / "relationships.yaml"

    def _load_relationships_yaml_runtime(project_path: str) -> list[dict[str, Any]]:
        import yaml as _yaml

        path = _relationships_path(project_path)
        if not path.exists():
            return []
        raw = _yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("relationships", [])
        else:
            items = []

        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            frm = item.get("from") if isinstance(item.get("from"), Mapping) else {}
            to = item.get("to") if isinstance(item.get("to"), Mapping) else {}
            from_table = str(frm.get("table") or "").strip()
            from_column = str(frm.get("column") or "").strip()
            to_table = str(to.get("table") or "").strip()
            to_column = str(to.get("column") or "").strip()
            if not from_table or not from_column or not to_table or not to_column:
                continue
            direction = str(item.get("cross_filter_direction") or "single").strip().lower() or "single"
            if direction not in ("single", "both"):
                direction = "single"
            rel_id = str(item.get("rel_id") or "").strip()
            if not rel_id:
                rel_id = f"{from_table}.{from_column}->{to_table}.{to_column}"
            out.append(
                {
                    "from_table": from_table,
                    "from_column": from_column,
                    "to_table": to_table,
                    "to_column": to_column,
                    "active": bool(item.get("active", True)),
                    "rel_id": rel_id,
                    "cross_filter_direction": direction,
                    "cardinality": (str(item.get("cardinality")).strip() if isinstance(item.get("cardinality"), str) else None),
                }
            )
        return out

    def _save_relationships_yaml_runtime(project_path: str, relationships: list[dict[str, Any]]) -> None:
        import yaml as _yaml

        path = _relationships_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        for rel in relationships:
            direction = str(rel.get("cross_filter_direction") or "single").strip().lower() or "single"
            if direction not in ("single", "both"):
                direction = "single"
            row: dict[str, Any] = {
                "from": {
                    "table": str(rel.get("from_table") or "").strip(),
                    "column": str(rel.get("from_column") or "").strip(),
                },
                "to": {
                    "table": str(rel.get("to_table") or "").strip(),
                    "column": str(rel.get("to_column") or "").strip(),
                },
                "active": bool(rel.get("active", True)),
                "cross_filter_direction": direction,
            }
            rel_id = str(rel.get("rel_id") or "").strip()
            if rel_id:
                row["rel_id"] = rel_id
            cardinality = rel.get("cardinality")
            if isinstance(cardinality, str) and cardinality.strip():
                row["cardinality"] = cardinality.strip()
            rows.append(row)

        payload: dict[str, Any] = {"relationships": rows}
        path.write_text(
            _yaml.dump(payload, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _validate_relationship_payload(project_path: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
        model, _pages, _visuals = load_project(project_path)
        table_cols: dict[str, set[str]] = {}
        for t in getattr(model, "tables", []) or []:
            t_name = str(getattr(t, "name", "")).strip()
            if not t_name:
                continue
            table_cols[t_name.upper()] = {
                str(getattr(c, "name", "")).strip().upper()
                for c in (getattr(t, "columns", []) or [])
                if str(getattr(c, "name", "")).strip()
            }

        from_table = str(payload.get("from_table") or "").strip()
        from_column = str(payload.get("from_column") or "").strip()
        to_table = str(payload.get("to_table") or "").strip()
        to_column = str(payload.get("to_column") or "").strip()

        if not from_table or not from_column or not to_table or not to_column:
            raise ValueError("from_table, from_column, to_table, and to_column are required")

        direction = str(payload.get("cross_filter_direction") or "single").strip().lower() or "single"
        if direction not in ("single", "both"):
            raise ValueError("cross_filter_direction must be 'single' or 'both'")

        if from_table.upper() not in table_cols:
            raise ValueError(f"Unknown from_table: {from_table!r}")
        if to_table.upper() not in table_cols:
            raise ValueError(f"Unknown to_table: {to_table!r}")
        if from_column.upper() not in table_cols[from_table.upper()]:
            raise ValueError(f"Unknown from_column: {from_table}[{from_column}]")
        if to_column.upper() not in table_cols[to_table.upper()]:
            raise ValueError(f"Unknown to_column: {to_table}[{to_column}]")

        cardinality = _resolve_and_validate_relationship_cardinality(
            project_path=project_path,
            model=model,
            requested_cardinality=(str(payload.get("cardinality")).strip() if payload.get("cardinality") is not None else None),
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
        )

        rel_id = str(payload.get("rel_id") or "").strip()
        if not rel_id:
            rel_id = f"{from_table}.{from_column}->{to_table}.{to_column}"

        normalized = {
            "from_table": from_table,
            "from_column": from_column,
            "to_table": to_table,
            "to_column": to_column,
            "active": bool(payload.get("active", True)),
            "rel_id": rel_id,
            "cross_filter_direction": direction,
            "cardinality": cardinality,
        }
        return normalized, model

    @app.get("/runtime/relationships")
    def runtime_list_relationships(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            rels = _load_relationships_yaml_runtime(project_path)
            return _ok({"relationships": rels})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/relationships")
    def runtime_create_relationship(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            rel_new, _model = _validate_relationship_payload(project_path, payload)
            rels = _load_relationships_yaml_runtime(project_path)

            dup = next(
                (
                    r
                    for r in rels
                    if str(r.get("from_table", "")).upper() == rel_new["from_table"].upper()
                    and str(r.get("from_column", "")).upper() == rel_new["from_column"].upper()
                    and str(r.get("to_table", "")).upper() == rel_new["to_table"].upper()
                    and str(r.get("to_column", "")).upper() == rel_new["to_column"].upper()
                ),
                None,
            )
            if dup is not None:
                return _err(409, "Relationship already exists")

            rels.append(rel_new)
            _save_relationships_yaml_runtime(project_path, rels)
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"relationship": rel_new, "relationships": rels})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/relationships/cardinality/detect")
    def runtime_detect_relationship_cardinality(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            normalized, _model = _validate_relationship_payload(
                project_path,
                {
                    "from_table": payload.get("from_table"),
                    "from_column": payload.get("from_column"),
                    "to_table": payload.get("to_table"),
                    "to_column": payload.get("to_column"),
                    "cross_filter_direction": "single",
                    "active": True,
                    "cardinality": None,
                },
            )
            detected = str(normalized.get("cardinality") or "").strip().lower()
            return _ok(
                {
                    "cardinality": detected,
                    "cardinality_display": _pretty_relationship_cardinality(detected) if detected else None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/relationships/{rel_id}")
    def runtime_update_relationship(rel_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            rels = _load_relationships_yaml_runtime(project_path)
            idx = next((i for i, r in enumerate(rels) if str(r.get("rel_id", "")).upper() == rel_id.upper()), None)
            if idx is None:
                return _err(404, f"Relationship not found: {rel_id!r}")

            merged = dict(rels[idx])
            merged.update(payload or {})
            merged["rel_id"] = str(payload.get("rel_id") or rels[idx].get("rel_id") or rel_id)
            rel_new, _model = _validate_relationship_payload(project_path, merged)

            # Avoid duplicates after update.
            for j, r in enumerate(rels):
                if j == idx:
                    continue
                if (
                    str(r.get("from_table", "")).upper() == rel_new["from_table"].upper()
                    and str(r.get("from_column", "")).upper() == rel_new["from_column"].upper()
                    and str(r.get("to_table", "")).upper() == rel_new["to_table"].upper()
                    and str(r.get("to_column", "")).upper() == rel_new["to_column"].upper()
                ):
                    return _err(409, "Relationship already exists")

            rels[idx] = rel_new
            _save_relationships_yaml_runtime(project_path, rels)
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"relationship": rel_new, "relationships": rels})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/relationships/{rel_id}")
    def runtime_delete_relationship(rel_id: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            rels = _load_relationships_yaml_runtime(project_path)
            idx = next((i for i, r in enumerate(rels) if str(r.get("rel_id", "")).upper() == rel_id.upper()), None)
            if idx is None:
                return _err(404, f"Relationship not found: {rel_id!r}")
            deleted = rels.pop(idx)
            _save_relationships_yaml_runtime(project_path, rels)
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"deleted": deleted, "relationships": rels})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/tables/{table}/table_type")
    def runtime_set_table_type(
        table: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Set or clear the table_type (fact/dim/bridge) for a table.

        Persists to the table's YAML file. Used by the Model View to control
        layout (facts left, dimensions top/right).
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        table_type_raw = payload.get("table_type")
        if table_type_raw is None or (isinstance(table_type_raw, str) and not table_type_raw.strip()):
            table_type_val = None
        elif isinstance(table_type_raw, str) and table_type_raw.strip().lower() in ("fact", "dim", "bridge"):
            table_type_val = table_type_raw.strip().lower()
        else:
            return _err(400, f"Invalid table_type: {table_type_raw!r}. Must be 'fact', 'dim', 'bridge', or null.")

        # Read existing YAML, update table_type, write back.
        root = Path(project_path)
        tables_dir = root / "model" / "tables"
        path = tables_dir / f"{table}.yaml"
        if not path.exists():
            return _err(400, f"Table YAML not found: {table}")

        try:
            import yaml as _yaml
            raw = _yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return _err(400, f"Table file is not a valid mapping: {table}")

            if table_type_val is None:
                raw.pop("table_type", None)
            else:
                raw["table_type"] = table_type_val

            path.write_text(_yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return _err(400, f"Failed to update table_type: {exc}")

        return _ok({"table": table, "table_type": table_type_val})

    # ── Column metadata updates ──────────────────────────────────────────

    @app.put("/runtime/tables/{table}/columns/{column}/sort_by")
    def runtime_set_column_sort_by(
        table: str,
        column: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Set or clear the sort_by_column for a column.

        Payload: { "sort_by_column": "OtherColumn" }  — or null/empty to clear.
        Used by the Data View to configure semantic-model-style "Sort by Column".
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        sort_by_raw = payload.get("sort_by_column")
        sort_by_val: str | None = None
        if isinstance(sort_by_raw, str) and sort_by_raw.strip():
            sort_by_val = sort_by_raw.strip()

        root = Path(project_path)
        path = root / "model" / "tables" / f"{table}.yaml"
        if not path.exists():
            return _err(400, f"Table YAML not found: {table}")

        try:
            import yaml as _yaml
            raw = _yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return _err(400, f"Table file is not a valid mapping: {table}")

            cols = raw.get("columns")
            if not isinstance(cols, list):
                return _err(400, f"Table {table} has no columns list")

            found = False
            for c in cols:
                if isinstance(c, dict) and c.get("name") == column:
                    if sort_by_val:
                        # Validate that target column exists in the same table
                        valid_cols = {cc.get("name") for cc in cols if isinstance(cc, dict)}
                        if sort_by_val not in valid_cols:
                            return _err(400, f"Target column {sort_by_val!r} not found in table {table}")
                        if sort_by_val == column:
                            return _err(400, "A column cannot sort by itself")

                        # --- Validation: no circular sort-by chains ---
                        # Build the existing sort_by graph for this table
                        sort_by_graph: dict[str, str] = {}
                        for cc in cols:
                            if isinstance(cc, dict):
                                existing_sb = cc.get("sort_by_column")
                                if existing_sb and cc.get("name") != column:
                                    sort_by_graph[cc["name"]] = existing_sb
                        # Add the proposed edge
                        sort_by_graph[column] = sort_by_val
                        # Walk the chain from sort_by_val to detect cycles
                        visited: set[str] = {column}
                        current = sort_by_val
                        while current in sort_by_graph:
                            if current in visited:
                                return _err(400,
                                    f"Circular sort-by chain detected: setting {column!r} "
                                    f"to sort by {sort_by_val!r} creates a cycle")
                            visited.add(current)
                            current = sort_by_graph[current]

                        # --- Validation: max sort-by chain depth of 1 ---
                        # Only a single level of sort-by indirection is supported.
                        # (a) Target column must not already sort by another column
                        #     (otherwise: column → sort_by_val → X  ⇒  depth 2)
                        for cc in cols:
                            if isinstance(cc, dict) and cc.get("name") == sort_by_val:
                                if cc.get("sort_by_column") and cc["sort_by_column"] != column:
                                    return _err(400,
                                        f"Column {sort_by_val!r} already sorts by {cc['sort_by_column']!r}. "
                                        f"Only one level of sort-by indirection is allowed.")
                                break
                        # (b) Source column must not already be a sort-by target of another column
                        #     (otherwise: Y → column → sort_by_val  ⇒  depth 2)
                        for cc in cols:
                            if isinstance(cc, dict) and cc.get("name") != column:
                                if cc.get("sort_by_column") == column:
                                    return _err(400,
                                        f"Column {column!r} is already the sort-by target of {cc['name']!r}. "
                                        f"Setting a sort-by on it would create a chain depth > 1.")
                                    break

                        # --- Validation: deterministic mapping check ---
                        # Must run BEFORE persisting, so a non-deterministic mapping blocks the save.
                        try:
                            import duckdb as _ddb
                            import os as _os
                            db_path = _os.environ.get("DAX_DUCKDB_PATH")
                            if db_path:
                                _con = _ddb.connect(db_path, read_only=True)
                            else:
                                _con = _ddb.connect()
                                csv_path = root / "data" / f"{table}.csv"
                                parquet_path = root / "data" / f"{table}.parquet"
                                if csv_path.exists():
                                    _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_csv_auto('{csv_path}')")
                                elif parquet_path.exists():
                                    _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{parquet_path}')")
                            # Check: COUNT(DISTINCT sort_col) per source_col value should be 1
                            try:
                                result = _con.execute(
                                    f'SELECT COUNT(*) FROM ('
                                    f'  SELECT \"{column}\", COUNT(DISTINCT \"{sort_by_val}\") AS cnt'
                                    f'  FROM \"{table}\"'
                                    f'  GROUP BY \"{column}\"'
                                    f'  HAVING cnt > 1'
                                    f')'
                                ).fetchone()
                                if result and result[0] > 0:
                                    _con.close()
                                    return _err(400,
                                        f"{result[0]} value(s) of '{column}' map to multiple "
                                        f"values of '{sort_by_val}'. The sort would be non-deterministic.")
                            except Exception:  # noqa: BLE001
                                pass  # Table might not exist in DuckDB yet
                            _con.close()
                        except Exception:  # noqa: BLE001
                            pass  # DuckDB not available

                        c["sort_by_column"] = sort_by_val
                    else:
                        c.pop("sort_by_column", None)
                    found = True
                    break

            if not found:
                return _err(400, f"Column {column!r} not found in table {table}")

            path.write_text(
                _yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, f"Failed to update sort_by_column: {exc}")

        return _ok({"table": table, "column": column, "sort_by_column": sort_by_val})

    @app.put("/runtime/tables/{table}/columns/{column}/data_type")
    def runtime_set_column_data_type(
        table: str,
        column: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Set the data type and optionally decimal places for a column.

        Payload: { "type": "DECIMAL", "decimal_places": 2 }
        Used by the field pane context menu to change column data types.
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        new_type = payload.get("type")
        if not isinstance(new_type, str) or not new_type.strip():
            return _err(400, "type is required (e.g. 'INTEGER', 'DECIMAL', 'VARCHAR', 'DATE', 'BOOLEAN')")
        new_type = new_type.strip().upper()

        decimal_places = payload.get("decimal_places")
        if decimal_places is not None:
            try:
                decimal_places = int(decimal_places)
                if decimal_places < 0 or decimal_places > 10:
                    return _err(400, "decimal_places must be between 0 and 10")
            except (TypeError, ValueError):
                return _err(400, "decimal_places must be an integer")

        root = Path(project_path)
        path = root / "model" / "tables" / f"{table}.yaml"
        if not path.exists():
            return _err(400, f"Table YAML not found: {table}")

        try:
            import yaml as _yaml
            raw = _yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return _err(400, f"Table file is not a valid mapping: {table}")

            cols = raw.get("columns")
            if not isinstance(cols, list):
                return _err(400, f"Table {table} has no columns list")

            found = False
            for c in cols:
                if isinstance(c, dict) and c.get("name") == column:
                    # --- Data compatibility check ---
                    # Try casting existing data to the new type via DuckDB.
                    # If any values fail the cast, reject with a descriptive error.
                    try:
                        import duckdb as _ddb
                        import os as _os
                        db_path = _os.environ.get("DAX_DUCKDB_PATH")
                        _con = None
                        _table_available = False

                        if db_path:
                            _con = _ddb.connect(db_path, read_only=True)
                            # Check if table exists in the DuckDB file
                            try:
                                _con.execute(f'SELECT 1 FROM "{table}" LIMIT 0')
                                _table_available = True
                            except Exception:  # noqa: BLE001
                                # Table not in DuckDB — fall back to CSV/parquet
                                _con.close()
                                _con = _ddb.connect()
                                csv_path = root / "data" / f"{table}.csv"
                                parquet_path = root / "data" / f"{table}.parquet"
                                if csv_path.exists():
                                    _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_csv_auto('{csv_path}')")
                                    _table_available = True
                                elif parquet_path.exists():
                                    _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{parquet_path}')")
                                    _table_available = True
                                else:
                                    # Try case-insensitive CSV lookup
                                    data_dir = root / "data"
                                    if data_dir.exists():
                                        for f in data_dir.iterdir():
                                            if f.stem.lower() == table.lower() and f.suffix.lower() in ('.csv', '.parquet'):
                                                if f.suffix.lower() == '.csv':
                                                    _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_csv_auto('{f}')")
                                                else:
                                                    _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{f}')")
                                                _table_available = True
                                                break
                        else:
                            _con = _ddb.connect()
                            csv_path = root / "data" / f"{table}.csv"
                            parquet_path = root / "data" / f"{table}.parquet"
                            if csv_path.exists():
                                _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_csv_auto('{csv_path}')")
                                _table_available = True
                            elif parquet_path.exists():
                                _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{parquet_path}')")
                                _table_available = True
                            else:
                                data_dir = root / "data"
                                if data_dir.exists():
                                    for f in data_dir.iterdir():
                                        if f.stem.lower() == table.lower() and f.suffix.lower() in ('.csv', '.parquet'):
                                            if f.suffix.lower() == '.csv':
                                                _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_csv_auto('{f}')")
                                            else:
                                                _con.execute(f"CREATE TABLE \"{table}\" AS SELECT * FROM read_parquet('{f}')")
                                            _table_available = True
                                            break

                        # Map type string to DuckDB cast target
                        cast_type = new_type
                        if new_type == "DECIMAL" and decimal_places is not None:
                            cast_type = f"DECIMAL(18,{decimal_places})"

                        # Try the cast and count failures
                        if _con and _table_available:
                            try:
                                fail_result = _con.execute(
                                    f'SELECT COUNT(*) AS fail_count, '
                                    f'MIN(CAST(\"{column}\" AS VARCHAR)) AS sample_val '
                                    f'FROM \"{table}\" '
                                    f'WHERE TRY_CAST(\"{column}\" AS {cast_type}) IS NULL '
                                    f'AND \"{column}\" IS NOT NULL'
                                ).fetchone()
                                if fail_result and fail_result[0] > 0:
                                    sample = fail_result[1] or "?"
                                    _con.close()
                                    return _err(400,
                                        f"{fail_result[0]} value(s) in column '{column}' cannot be converted "
                                        f"to {new_type} (e.g. '{sample}'). Fix the data first or choose "
                                        f"a compatible type.")
                            except Exception:  # noqa: BLE001
                                pass  # Query issue — skip check
                            _con.close()
                    except Exception:  # noqa: BLE001
                        pass  # DuckDB not available — skip check

                    # Set the type, potentially with decimal precision
                    if new_type == "DECIMAL" and decimal_places is not None:
                        c["type"] = f"DECIMAL(18,{decimal_places})"
                    else:
                        c["type"] = new_type
                    # Store decimal_places metadata if provided
                    if decimal_places is not None:
                        c["format"] = f"#,##0.{'0' * decimal_places}"
                    found = True
                    break

            if not found:
                return _err(400, f"Column {column!r} not found in table {table}")

            path.write_text(
                _yaml.dump(raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, f"Failed to update data type: {exc}")

        return _ok({"table": table, "column": column, "type": new_type, "decimal_places": decimal_places})


    @app.get("/runtime/model-layouts")
    def runtime_get_model_layouts(project: Optional[str] = None):
        """Return saved model view layouts (diagram pages)."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        layouts = _load_model_layouts(project_path)
        return _ok({"layouts": layouts})

    @app.put("/runtime/model-layouts")
    def runtime_save_model_layouts(
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Save model view layouts (diagram pages).

        Payload: { "layouts": [ { id, name, visibleTables, nodePositions }, ... ] }
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        layouts_raw = payload.get("layouts")
        if not isinstance(layouts_raw, list):
            return _err(400, "layouts must be a list")

        cleaned: list[dict] = []
        for i, item in enumerate(layouts_raw):
            if not isinstance(item, dict):
                return _err(400, f"layouts[{i}] must be an object")
            lid = str(item.get("id") or "").strip()
            lname = str(item.get("name") or "").strip()
            if not lid:
                return _err(400, f"layouts[{i}].id is required")
            if not lname:
                return _err(400, f"layouts[{i}].name is required")

            visible = item.get("visibleTables")
            if visible is not None and not isinstance(visible, list):
                return _err(400, f"layouts[{i}].visibleTables must be a list or null")
            if isinstance(visible, list):
                visible = [str(v) for v in visible if isinstance(v, str) and v.strip()]

            positions = item.get("nodePositions")
            if positions is not None and not isinstance(positions, dict):
                return _err(400, f"layouts[{i}].nodePositions must be an object or null")
            if not isinstance(positions, dict):
                positions = {}

            cleaned.append({
                "id": lid,
                "name": lname,
                "visibleTables": visible,
                "nodePositions": {
                    str(k): {"x": float(v.get("x", 0)), "y": float(v.get("y", 0))}
                    for k, v in positions.items()
                    if isinstance(v, dict)
                },
            })

        _save_model_layouts(project_path, cleaned)
        return _ok({"saved": len(cleaned)})

    @app.post("/runtime/tables/{table}/columns")
    def runtime_create_table_calculated_column(
        table: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        col_name = str(payload.get("name") or "").strip()
        expr_text = _coalesce_expr_payload(payload)
        col_type = payload.get("type")
        description = payload.get("description")
        folder = payload.get("folder")

        if not col_name:
            return _err(400, "name is required")
        try:
            _validate_safe_name(col_name, label="column name")
        except ValueError as e:
            return _err(400, str(e))
        if not isinstance(expr_text, str) or not expr_text.strip():
            return _err(400, "expression is required")

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table!r}")

            # Check for duplicate column names (including physical columns)
            for c in getattr(t, "columns", []) or []:
                if str(getattr(c, "name", "")).upper() == col_name.upper():
                    if not bool(getattr(c, "is_calculated", False)):
                        return _err(409, f"Column exists and is not calculated: {table!r}[{col_name!r}]")
                    else:
                        return _err(409, f"Calculated column already exists: {table!r}[{col_name!r}] ΓÇö use PUT to update")

            upsert_column_yaml(
                project_path,
                table=str(getattr(t, "name", table)),
                name=col_name,
                col_type=str(col_type).strip() if isinstance(col_type, str) and col_type.strip() else "UNKNOWN",
                source=None,
                expression=expr_text,
                is_calculated=True,
                description=str(description) if isinstance(description, str) and description.strip() else None,
                folder=str(folder) if isinstance(folder, str) and folder.strip() else None,
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"table": table, "column": {"name": col_name, "expression": expr_text}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/tables/{table}/columns/{name}")
    def runtime_update_table_calculated_column(
        table: str,
        name: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        expr_text = _coalesce_expr_payload(payload)
        col_type = payload.get("type")
        description = payload.get("description")
        folder = payload.get("folder")
        if not isinstance(expr_text, str) or not expr_text.strip():
            return _err(400, "expression is required")

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table!r}")

            current = next(
                (
                    c
                    for c in getattr(t, "columns", []) or []
                    if str(getattr(c, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Column not found: {table!r}[{name!r}]")
            if not bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Column is not calculated: {table!r}[{name!r}]")

            upsert_column_yaml(
                project_path,
                table=str(getattr(t, "name", table)),
                name=str(getattr(current, "name", name)),
                col_type=str(col_type).strip() if isinstance(col_type, str) and col_type.strip() else str(getattr(current, "type", "UNKNOWN") or "UNKNOWN"),
                source=None,
                expression=expr_text,
                is_calculated=True,
                description=str(description) if isinstance(description, str) and description.strip() else None,
                folder=str(folder) if isinstance(folder, str) and folder.strip() else None,
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"table": table, "column": {"name": name, "expression": expr_text}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/tables/{table}/columns/{name}")
    def runtime_delete_table_calculated_column(table: str, name: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table!r}")

            current = next(
                (
                    c
                    for c in getattr(t, "columns", []) or []
                    if str(getattr(c, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Column not found: {table!r}[{name!r}]")
            if not bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Column is not calculated: {table!r}[{name!r}]")

            removed = delete_column_yaml(
                project_path,
                table=str(getattr(t, "name", table)),
                name=str(getattr(current, "name", name)),
            )
            if not removed:
                return _err(404, f"Column not found: {table!r}[{name!r}]")
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"deleted": {"table": table, "column": name}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    # ── Column type update (any column, not just calculated) ──────────
    @app.patch("/runtime/tables/{table}/columns/{name}")
    def runtime_patch_column(
        table: str,
        name: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Update a column's type (and optionally description/folder).

        Unlike PUT (calc-only), PATCH works on any column — physical or
        calculated.  This endpoint persists the change to the table's YAML
        file and invalidates the engine cache so the DuckDB loader picks
        up the new type on next query.
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        new_type = payload.get("type")
        new_desc = payload.get("description")
        new_folder = payload.get("folder")

        if not isinstance(new_type, str) or not new_type.strip():
            return _err(400, "type is required (e.g. 'INTEGER', 'DOUBLE', 'VARCHAR')")

        _VALID_TYPES = {
            "INTEGER", "BIGINT", "SMALLINT", "TINYINT",
            "DOUBLE", "FLOAT", "DECIMAL",
            "VARCHAR", "BOOLEAN", "DATE", "TIMESTAMP", "BLOB",
            "UNKNOWN",
        }
        normalised_type = new_type.strip().upper()
        if normalised_type not in _VALID_TYPES:
            return _err(400, f"Unsupported type: {new_type!r}.  Allowed: {', '.join(sorted(_VALID_TYPES))}")

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (t for t in getattr(model, "tables", []) or []
                 if str(getattr(t, "name", "")).upper() == table.upper()),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table!r}")

            current = next(
                (c for c in getattr(t, "columns", []) or []
                 if str(getattr(c, "name", "")).upper() == name.upper()),
                None,
            )
            if current is None:
                return _err(404, f"Column not found: {table!r}[{name!r}]")

            # Preserve existing fields that the caller didn't send.
            upsert_column_yaml(
                project_path,
                table=str(getattr(t, "name", table)),
                name=str(getattr(current, "name", name)),
                col_type=normalised_type,
                source=dict(getattr(current, "source", None) or {}) if getattr(current, "source", None) else None,
                expression=getattr(current, "expression", None),
                is_calculated=bool(getattr(current, "is_calculated", False)) if getattr(current, "is_calculated", False) else None,
                description=(str(new_desc) if isinstance(new_desc, str) and new_desc.strip()
                             else getattr(current, "description", None)),
                folder=(str(new_folder) if isinstance(new_folder, str) and new_folder.strip()
                        else getattr(current, "folder", None)),
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({
                "table": table,
                "column": name,
                "type": normalised_type,
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/tables/{table}/columns/validate")
    def runtime_validate_table_calculated_column(
        table: str,
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        expr_text = _coalesce_expr_payload(payload)
        if not isinstance(expr_text, str) or not expr_text.strip():
            return _err(400, "expression is required")
        limit = _coalesce_limit(payload, default=50)

        sql: Optional[str] = None
        try:
            _ensure_mapping_loaded()
            model, _pages, _visuals = load_project(project_path)

            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=payload)
            model_scoped = sec_state.model_scoped

            # Enforce OLS: validate the table is visible.
            if not any(
                str(getattr(t, "name", "")).upper() == str(table).upper() for t in getattr(model_scoped, "tables", []) or []
            ):
                return _err(400, f"Unknown or hidden table: {table!r}")

            from dax_parser.ir_mapper import ast_to_ir
            from dax_parser.parser import parse_expression
            from dax_engine.sql_utils import as_from_source, quote_alias
            from dax_engine.table_sources import resolve_table_source_raw_sql

            ir = ast_to_ir(parse_expression(expr_text))
            if not isinstance(ir, dax_compiler.ScalarExpr):
                return _err(400, f"Calculated column expression must be scalar; got {type(ir).__name__}")

            # Enforce OLS by validating referenced objects against the role-scoped model.
            _validate_ir_objects_against_model_scoped(ir, model_scoped)

            with _ENGINE_LOCK:
                expr_sql = dax_compiler.compile_expr(ir, sec_state.ctx)
                expr_sql = dax_compiler.rewrite_qualifiers_to_alias(expr_sql, "t")

                table_rls = _case_insensitive_dict_get(sec_state.sec_predicates or {}, f"{table}.__RLS__")
                where_sql = ""
                if isinstance(table_rls, str) and table_rls.strip():
                    where_sql = f" WHERE {dax_compiler.rewrite_qualifiers_to_alias(table_rls, 't')}"

                raw_src = resolve_table_source_raw_sql(table)
                upper = raw_src.lstrip().upper()
                if raw_src.strip().startswith("(") or upper.startswith("SELECT") or upper.startswith("WITH"):
                    from_src = as_from_source(raw_src, "t")
                else:
                    from_src = f"{raw_src} AS t"

                sql = f"SELECT *, ({expr_sql}) AS {quote_alias('__calc')} FROM {from_src}{where_sql} LIMIT {limit}"

            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            cur = con.execute(dax_compiler.normalize_sql(sql))
            rows = cur.fetchall()
            cols = [c[0] for c in (cur.description or [])]
            return _ok({"table": table, "sql": sql, "columns": cols, "rows": [_json_safe(list(r)) for r in rows], "row_count": len(rows)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql, details={"endpoint": "table_column_validate", "project": project_path, "table": table})

    _IMPORT_CONNECTORS: list[dict[str, Any]] = [
        {
            "type": "csv",
            "label": "CSV file",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "File path", "required": True, "kind": "path", "placeholder": "data/sales.csv"},
                {"name": "delimiter", "label": "Delimiter", "required": False, "kind": "text", "placeholder": ","},
                {"name": "header", "label": "Header", "required": False, "kind": "bool"},
                {"name": "encoding", "label": "Encoding", "required": False, "kind": "text"},
                {"name": "nullstr", "label": "Null strings (comma-separated)", "required": False, "kind": "text"},
            ],
        },
        {
            "type": "parquet",
            "label": "Parquet file",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "File path", "required": True, "kind": "path", "placeholder": "data/sales.parquet"},
            ],
        },
        {
            "type": "json",
            "label": "JSON file",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "File path", "required": True, "kind": "path", "placeholder": "data/data.json"},
            ],
        },
        {
            "type": "folder",
            "label": "Folder inventory",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "Folder path", "required": True, "kind": "path", "placeholder": "data"},
                {"name": "mode", "label": "Mode", "required": False, "kind": "select", "options": ["files", "contents"]},
                {"name": "recursive", "label": "Recursive", "required": False, "kind": "bool"},
                {"name": "include_folders", "label": "Include folders", "required": False, "kind": "bool"},
            ],
        },
        {
            "type": "excel",
            "label": "Excel file",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "File path", "required": True, "kind": "path", "placeholder": "data/workbook.xlsx"},
            ],
        },
        {
            "type": "text",
            "label": "Text file",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "File path", "required": True, "kind": "path", "placeholder": "data/data.txt"},
            ],
        },
        {
            "type": "blob",
            "label": "Blob file",
            "category": "File",
            "status": "active",
            "params": [
                {"name": "path", "label": "Blob path", "required": True, "kind": "path", "placeholder": "data/blob.bin"},
            ],
        },
        {
            "type": "duckdb",
            "label": "DuckDB file",
            "category": "Database",
            "status": "active",
            "params": [
                {"name": "path", "label": "DB file path", "required": True, "kind": "path", "placeholder": "data/my.duckdb"},
                {"name": "schema", "label": "Schema", "required": False, "kind": "text", "placeholder": "main"},
                {"name": "table", "label": "Table", "required": True, "kind": "text"},
            ],
        },
        {
            "type": "sqlite",
            "label": "SQLite file",
            "category": "Database",
            "status": "active",
            "params": [
                {"name": "path", "label": "DB file path", "required": True, "kind": "path", "placeholder": "data/my.sqlite"},
                {"name": "table", "label": "Table", "required": True, "kind": "text"},
            ],
        },
        {
            "type": "postgres",
            "label": "PostgreSQL",
            "category": "Database",
            "status": "active",
            "params": [
                {"name": "path", "label": "Connection string", "required": True, "kind": "text", "placeholder": "postgres://user:pass@host:5432/db"},
                {"name": "schema", "label": "Schema", "required": False, "kind": "text", "placeholder": "public"},
                {"name": "table", "label": "Table", "required": True, "kind": "text"},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "mysql",
            "label": "MySQL",
            "category": "Database",
            "status": "active",
            "params": [
                {"name": "path", "label": "Connection string", "required": True, "kind": "text", "placeholder": "mysql://user:pass@host:3306/db"},
                {"name": "schema", "label": "Database", "required": True, "kind": "text"},
                {"name": "table", "label": "Table", "required": True, "kind": "text"},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "http",
            "label": "HTTP/HTTPS",
            "category": "Cloud Storage",
            "status": "active",
            "params": [
                {"name": "path", "label": "URL", "required": True, "kind": "text", "placeholder": "https://example.com/data.parquet"},
                {"name": "format", "label": "Format", "required": True, "kind": "select", "options": ["parquet", "csv", "json", "text"]},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "s3",
            "label": "AWS S3",
            "category": "Cloud Storage",
            "status": "active",
            "params": [
                {"name": "path", "label": "S3 URL", "required": True, "kind": "text", "placeholder": "s3://bucket/path"},
                {"name": "format", "label": "Format", "required": True, "kind": "select", "options": ["parquet", "csv", "json", "text"]},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "azure_blob",
            "label": "Cloud Blob Storage",
            "category": "Cloud Storage",
            "status": "active",
            "params": [
                {"name": "path", "label": "Cloud storage URL", "required": True, "kind": "text", "placeholder": "cloud://container/path"},
                {"name": "format", "label": "Format", "required": True, "kind": "select", "options": ["parquet", "csv", "json", "text"]},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "cloudflare_r2",
            "label": "Cloudflare R2",
            "category": "Cloud Storage",
            "status": "active",
            "params": [
                {"name": "path", "label": "R2 URL", "required": True, "kind": "text", "placeholder": "r2://bucket/path"},
                {"name": "format", "label": "Format", "required": True, "kind": "select", "options": ["parquet", "csv", "json", "text"]},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "delta",
            "label": "Delta Lake",
            "category": "Lakehouse",
            "status": "active",
            "params": [
                {"name": "path", "label": "Table path", "required": True, "kind": "text", "placeholder": "s3://bucket/delta"},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
        {
            "type": "iceberg",
            "label": "Iceberg",
            "category": "Lakehouse",
            "status": "active",
            "params": [
                {"name": "path", "label": "Table path", "required": True, "kind": "text", "placeholder": "s3://bucket/iceberg"},
                {"name": "auth_mode", "label": "Auth mode", "required": False, "kind": "select", "options": ["connection_string", "env_vars"]},
            ],
        },
    ]

    def _normalize_import_source(
        src: Mapping[str, Any],
        *,
        project_path: str,
        allow_missing_table: bool,
    ) -> dict[str, Any]:
        if not isinstance(src, Mapping):
            raise ValueError("source must be an object")
        src_type = str(src.get("type") or "").strip().lower()
        from dax_project.open_core_profile import OPEN_CORE_DATA_CONNECTIONS, is_open_core_mvp

        if is_open_core_mvp() and src_type not in OPEN_CORE_DATA_CONNECTIONS:
            allowed = ", ".join(sorted(OPEN_CORE_DATA_CONNECTIONS))
            raise ValueError(
                f"Connector {src_type!r} is not available in the open-core MVP. "
                f"Supported connectors: {allowed}."
            )
        if src_type not in {
            "csv",
            "parquet",
            "json",
            "folder",
            "excel",
            "text",
            "blob",
            "duckdb",
            "sqlite",
            "postgres",
            "mysql",
            "http",
            "s3",
            "azure_blob",
            "cloudflare_r2",
            "delta",
            "iceberg",
        }:
            raise ValueError(f"Unsupported source type: {src_type!r}")

        path_raw = src.get("path")
        if not isinstance(path_raw, str) or not path_raw.strip():
            raise ValueError("source.path is required")
        path_clean = str(path_raw).strip()
        is_remote = _is_remote_path(path_clean)

        out: dict[str, Any] = {"type": src_type, "path": path_clean}

        auth_mode = src.get("auth_mode")
        if isinstance(auth_mode, str) and auth_mode.strip():
            out["auth_mode"] = auth_mode.strip()

        local_types = {"csv", "parquet", "json", "folder", "excel", "text", "blob", "duckdb", "sqlite"}
        remote_types = {"http", "s3", "azure_blob", "cloudflare_r2"}
        if src_type in local_types or (src_type in {"delta", "iceberg"} and not is_remote):
            full = _resolve_source_path(project_path, path_clean)
            if not full.exists():
                raise ValueError(f"Source path not found: {path_clean!r}")
        if src_type in remote_types and not is_remote:
            raise ValueError("source.path must be a remote URL for this connector")

        if src_type in remote_types:
            fmt = str(src.get("format") or "").strip().lower()
            if fmt not in {"csv", "parquet", "json", "text"}:
                raise ValueError("source.format is required")
            out["format"] = fmt

        if src_type == "csv":
            if "delimiter" in src:
                delim = str(src.get("delimiter") or "").strip()
                if delim:
                    if len(delim) != 1:
                        raise ValueError("csv delimiter must be a single character")
                    out["delimiter"] = delim
            if "header" in src:
                out["header"] = bool(src.get("header"))
            if "encoding" in src and isinstance(src.get("encoding"), str) and str(src.get("encoding") or "").strip():
                out["encoding"] = str(src.get("encoding") or "").strip()
            if "nullstr" in src:
                nullstr = src.get("nullstr")
                if isinstance(nullstr, list):
                    out["nullstr"] = [str(v) for v in nullstr]
                elif isinstance(nullstr, str):
                    out["nullstr"] = str(nullstr)
                else:
                    raise ValueError("csv nullstr must be a string or list")
        elif src_type == "folder":
            mode = str(src.get("mode") or "files").strip().lower()
            if mode not in {"files", "contents"}:
                raise ValueError("folder mode must be 'files' or 'contents'")
            out["mode"] = mode
            out["recursive"] = bool(src.get("recursive", mode == "files"))
            out["include_folders"] = bool(src.get("include_folders", mode == "contents"))
        elif src_type in {"duckdb", "postgres", "mysql"}:
            schema = str(src.get("schema") or "").strip()
            table = str(src.get("table") or "").strip()
            if not table and not allow_missing_table:
                raise ValueError("source.table is required")
            if src_type == "mysql" and not schema:
                raise ValueError("source.schema is required")
            if schema:
                out["schema"] = schema
            if table:
                out["table"] = table
        elif src_type == "sqlite":
            table = str(src.get("table") or "").strip()
            if not table and not allow_missing_table:
                raise ValueError("source.table is required")
            if table:
                out["table"] = table

        return out

    def _columns_from_cursor(cur: Any) -> list[dict[str, Any]]:
        desc = list(cur.description or [])
        out: list[dict[str, Any]] = []
        for c in desc:
            name = c[0] if len(c) > 0 else None
            typ = c[1] if len(c) > 1 else None
            if not name:
                continue
            out.append({"name": str(name), "type": str(typ) if typ is not None else "UNKNOWN"})
        return out

    def _preview_from_source(
        *,
        project_path: str,
        src: Mapping[str, Any],
        limit: int,
    ) -> dict[str, Any]:
        import duckdb

        src_type = str(src.get("type") or "").strip().lower()
        sql = ""
        params: list[Any] = []

        if src_type == "folder":
            full = _resolve_source_path(project_path, str(src.get("path") or ""))
            mode = str(src.get("mode") or "files").strip().lower()
            recursive = bool(src.get("recursive", mode == "files"))
            include_folders = bool(src.get("include_folders", mode == "contents"))
            if not full.exists() or not full.is_dir():
                raise ValueError(f"Folder source path not found: {src.get('path')!r}")
            candidates = full.rglob("*") if recursive else full.iterdir()
            entries = sorted(candidates, key=lambda item: str(item).lower())
            rows: list[list[Any]] = []
            for item in entries:
                is_dir = item.is_dir()
                if is_dir and not include_folders:
                    continue
                if not is_dir and mode == "contents" and item.parent != full:
                    continue
                stat = item.stat()
                extension = "" if is_dir else item.suffix
                folder_path = str(item.parent) + os.sep
                rows.append([
                    None if is_dir else {"kind": "binary_ref", "path": str(item), "size": stat.st_size},
                    item.name,
                    extension,
                    None,
                    datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    {"Kind": "Folder" if is_dir else "File", "IsFolder": is_dir, "Size": stat.st_size},
                    folder_path,
                ])
                if len(rows) >= int(limit):
                    break
            columns = [
                {"name": "Content", "type": "BINARY"},
                {"name": "Name", "type": "VARCHAR"},
                {"name": "Extension", "type": "VARCHAR"},
                {"name": "Date accessed", "type": "TIMESTAMP"},
                {"name": "Date modified", "type": "TIMESTAMP"},
                {"name": "Date created", "type": "TIMESTAMP"},
                {"name": "Attributes", "type": "STRUCT"},
                {"name": "Folder Path", "type": "VARCHAR"},
            ]
            return {
                "sql": f"FOLDER_INVENTORY({src.get('path')!r})",
                "columns": columns,
                "rows": _json_safe(rows),
                "row_count": len(rows),
            }

        if src_type in {"csv", "parquet", "json", "text", "blob", "excel"}:
            full = _resolve_source_path(project_path, str(src.get("path") or ""))
            if src_type == "text":
                # Keep text preview independent from DuckDB's platform-specific
                # filesystem metadata conversion.  This mirrors read_text's
                # one-row-per-file schema and is deterministic on hosted Windows.
                stat = full.stat()
                content = full.read_text(encoding="utf-8")
                rows = [[
                    full.as_posix(),
                    content,
                    stat.st_size,
                    datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc),
                ]]
                return {
                    "sql": "READ_TEXT(?)",
                    "columns": [
                        {"name": "filename", "type": "VARCHAR"},
                        {"name": "content", "type": "VARCHAR"},
                        {"name": "size", "type": "UBIGINT"},
                        {"name": "last_modified", "type": "TIMESTAMP WITH TIME ZONE"},
                    ],
                    "rows": _json_safe(rows),
                    "row_count": 1,
                }
            if src_type == "blob":
                # Raw bytes are not JSON serializable.  Use the same stable
                # binary reference shape exposed by folder inventory previews.
                stat = full.stat()
                rows = [[
                    full.as_posix(),
                    {"kind": "binary_ref", "path": full.as_posix(), "size": stat.st_size},
                    stat.st_size,
                    datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc),
                ]]
                return {
                    "sql": "READ_BLOB(?)",
                    "columns": [
                        {"name": "filename", "type": "VARCHAR"},
                        {"name": "content", "type": "BLOB"},
                        {"name": "size", "type": "UBIGINT"},
                        {"name": "last_modified", "type": "TIMESTAMP WITH TIME ZONE"},
                    ],
                    "rows": _json_safe(rows),
                    "row_count": 1,
                }
            con = duckdb.connect()
            if src_type == "csv":
                read_sql, _ = _csv_options_from_source(src)
                sql = f"SELECT * FROM {read_sql} LIMIT {int(limit)}"
                params = [str(full)]
            elif src_type == "parquet":
                sql = f"SELECT * FROM read_parquet(?) LIMIT {int(limit)}"
                params = [str(full)]
            elif src_type == "json":
                sql = f"SELECT * FROM read_json_auto(?) LIMIT {int(limit)}"
                params = [str(full)]
            elif src_type == "excel":
                _ensure_duckdb_extension(con, "excel")
                sql = f"SELECT * FROM read_excel(?) LIMIT {int(limit)}"
                params = [str(full)]

            cur = con.execute(sql, params)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        if src_type in {"http", "s3", "azure_blob", "cloudflare_r2"}:
            con = duckdb.connect()
            if src_type == "azure_blob":
                _ensure_duckdb_extension(con, "azure")
            else:
                _ensure_duckdb_extension(con, "httpfs")

            fmt = str(src.get("format") or "").strip().lower()
            read_sql, _ = _read_by_format_sql(fmt, src)
            sql = f"SELECT * FROM {read_sql} LIMIT {int(limit)}"
            params = [str(src.get("path") or "").strip()]
            cur = con.execute(sql, params)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        if src_type in {"delta", "iceberg"}:
            con = duckdb.connect()
            _ensure_duckdb_extension(con, "httpfs")
            ext_name = "delta" if src_type == "delta" else "iceberg"
            _ensure_duckdb_extension(con, ext_name)
            read_fn = "read_delta" if src_type == "delta" else "read_iceberg"
            raw_path = str(src.get("path") or "").strip()
            path_value = raw_path
            if raw_path and not _is_remote_path(raw_path):
                path_value = str(_resolve_source_path(project_path, raw_path))
            sql = f"SELECT * FROM {read_fn}(?) LIMIT {int(limit)}"
            params = [path_value]
            cur = con.execute(sql, params)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        if src_type == "duckdb":
            full = _resolve_source_path(project_path, str(src.get("path") or ""))
            con = duckdb.connect(str(full))
            schema = str(src.get("schema") or "main").strip() or "main"
            table = str(src.get("table") or "").strip()
            if not table:
                raise ValueError("source.table is required")
            qual = f"{dax_compiler.quote_ident(schema)}.{dax_compiler.quote_ident(table)}"
            sql = f"SELECT * FROM {qual} LIMIT {int(limit)}"
            cur = con.execute(sql)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        if src_type == "sqlite":
            full = _resolve_source_path(project_path, str(src.get("path") or ""))
            con = duckdb.connect()
            try:
                con.execute("INSTALL sqlite_scanner")
            except Exception:
                pass
            con.execute("LOAD sqlite_scanner")
            table = str(src.get("table") or "").strip()
            if not table:
                raise ValueError("source.table is required")
            sql = f"SELECT * FROM sqlite_scan(?, ?) LIMIT {int(limit)}"
            params = [str(full), table]
            cur = con.execute(sql, params)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        if src_type == "postgres":
            con = duckdb.connect()
            _ensure_duckdb_extension(con, "postgres")
            schema = str(src.get("schema") or "public").strip() or "public"
            table = str(src.get("table") or "").strip()
            if not table:
                raise ValueError("source.table is required")
            sql = f"SELECT * FROM postgres_scan(?, ?, ?) LIMIT {int(limit)}"
            params = [str(src.get("path") or "").strip(), schema, table]
            cur = con.execute(sql, params)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        if src_type == "mysql":
            con = duckdb.connect()
            _ensure_duckdb_extension(con, "mysql")
            schema = str(src.get("schema") or "").strip()
            table = str(src.get("table") or "").strip()
            if not schema:
                raise ValueError("source.schema is required")
            if not table:
                raise ValueError("source.table is required")
            sql = f"SELECT * FROM mysql_scan(?, ?, ?) LIMIT {int(limit)}"
            params = [str(src.get("path") or "").strip(), schema, table]
            cur = con.execute(sql, params)
            rows = cur.fetchall()
            cols = _columns_from_cursor(cur)
            return {"sql": sql, "columns": cols, "rows": _json_safe(rows), "row_count": len(rows)}

        raise ValueError(f"Unsupported source type: {src_type!r}")

    def _infer_columns_from_source(*, project_path: str, src: Mapping[str, Any]) -> list[dict[str, Any]]:
        preview = _preview_from_source(project_path=project_path, src=src, limit=0)
        cols = preview.get("columns")
        if not isinstance(cols, list):
            return []
        return cols

    def _list_tables_for_source(*, project_path: str, src: Mapping[str, Any]) -> list[dict[str, Any]]:
        import duckdb

        src_type = str(src.get("type") or "").strip().lower()

        if src_type == "duckdb":
            full = _resolve_source_path(project_path, str(src.get("path") or ""))
            con = duckdb.connect(str(full))
            rows = con.execute(
                "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' ORDER BY table_schema, table_name"
            ).fetchall()
            return [{"schema": r[0], "name": r[1]} for r in rows]

        if src_type == "sqlite":
            full = _resolve_source_path(project_path, str(src.get("path") or ""))
            con = duckdb.connect()
            try:
                con.execute("INSTALL sqlite_scanner")
            except Exception:
                pass
            con.execute("LOAD sqlite_scanner")
            rows = con.execute(
                "SELECT name FROM sqlite_scan(?, 'sqlite_master') WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
                [str(full)],
            ).fetchall()
            return [{"schema": None, "name": r[0]} for r in rows]

        if src_type == "postgres":
            con = duckdb.connect()
            _ensure_duckdb_extension(con, "postgres")
            sql = (
                "SELECT table_schema, table_name FROM postgres_query(?, "
                "'SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_type=''BASE TABLE'' ORDER BY table_schema, table_name')"
            )
            rows = con.execute(sql, [str(src.get("path") or "").strip()]).fetchall()
            return [{"schema": r[0], "name": r[1]} for r in rows]

        if src_type == "mysql":
            con = duckdb.connect()
            _ensure_duckdb_extension(con, "mysql")
            sql = (
                "SELECT table_schema, table_name FROM mysql_query(?, "
                "'SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_type=''BASE TABLE'' ORDER BY table_schema, table_name')"
            )
            rows = con.execute(sql, [str(src.get("path") or "").strip()]).fetchall()
            return [{"schema": r[0], "name": r[1]} for r in rows]

        return []

    @app.get("/runtime/data_sources/connectors")
    def runtime_get_data_source_connectors():
        from dax_project.open_core_profile import OPEN_CORE_DATA_CONNECTIONS, is_open_core_mvp

        connectors = _IMPORT_CONNECTORS
        if is_open_core_mvp():
            connectors = [row for row in connectors if str(row.get("type") or "") in OPEN_CORE_DATA_CONNECTIONS]
        return _ok({"connectors": connectors})

    @app.post("/runtime/data_sources/inspect")
    def runtime_data_sources_inspect(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            src_raw = safe.get("source") if isinstance(safe.get("source"), Mapping) else safe
            src = _normalize_import_source(src_raw, project_path=project_path, allow_missing_table=True)
            tables = _list_tables_for_source(project_path=project_path, src=src)
            return _ok({"source": src, "tables": tables})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/data_sources/preview")
    def runtime_data_sources_preview(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            src_raw = safe.get("source") if isinstance(safe.get("source"), Mapping) else safe
            src = _normalize_import_source(src_raw, project_path=project_path, allow_missing_table=False)
            limit_raw = safe.get("limit")
            limit = int(limit_raw) if isinstance(limit_raw, (int, float)) else 50
            if limit < 0:
                limit = 0
            if limit > 500:
                limit = 500
            result = _preview_from_source(project_path=project_path, src=src, limit=limit)
            return _ok({"source": src, **result})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/tables/sources")
    def runtime_tables_sources(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            out: list[dict[str, Any]] = []
            for t in getattr(model, "tables", []) or []:
                if bool(getattr(t, "is_calculated", False)):
                    continue
                row = {
                    "name": getattr(t, "name", ""),
                    "columns": [
                        {"name": getattr(c, "name", ""), "type": getattr(c, "type", "UNKNOWN")}
                        for c in (getattr(t, "columns", []) or [])
                    ],
                    "source": getattr(t, "source", None) if isinstance(getattr(t, "source", None), Mapping) else None,
                    "storage_mode": getattr(t, "storage_mode", None) or "import",
                }
                out.append(row)
            out.sort(key=lambda d: str(d.get("name", "")).upper())
            return _ok({"tables": out})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/tables/import")
    def runtime_import_table(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            name = str(safe.get("name") or "").strip()
            if not name:
                raise ValueError("table name is required")

            model, _pages, _visuals = load_project(project_path)
            if any(str(getattr(t, "name", "")).upper() == name.upper() for t in getattr(model, "tables", []) or []):
                raise ValueError(f"Table already exists: {name!r}")

            src_raw = safe.get("source") if isinstance(safe.get("source"), Mapping) else safe
            src = _normalize_import_source(src_raw, project_path=project_path, allow_missing_table=False)

            columns = _infer_columns_from_source(project_path=project_path, src=src)
            if not columns:
                raise ValueError("No columns inferred from source")

            col_rows = [{"name": c.get("name"), "type": c.get("type") or "UNKNOWN"} for c in columns]

            folder = str(safe.get("folder") or "").strip() if safe.get("folder") is not None else None
            description = str(safe.get("description") or "").strip() if safe.get("description") is not None else None
            table_type_raw = str(safe.get("table_type") or "").strip().lower()
            table_type = table_type_raw if table_type_raw in ("fact", "dim", "bridge") else None

            # Phase 9: accept optional storage_mode.
            storage_mode_raw = str(safe.get("storage_mode") or "").strip().lower()
            storage_mode_val: Optional[str] = None
            if storage_mode_raw:
                from dax_engine.storage_modes import parse_storage_mode, storage_mode_to_str, validate_storage_mode_source
                parsed_sm = parse_storage_mode(storage_mode_raw)
                validate_storage_mode_source(parsed_sm, src, table_name=name)
                storage_mode_val = storage_mode_to_str(parsed_sm)

            upsert_table_yaml(
                project_path,
                name=name,
                columns=col_rows,
                source=src,
                expression=None,
                is_calculated=False,
                description=description if description else None,
                folder=folder if folder else None,
                table_type=table_type,
                storage_mode=storage_mode_val,
            )

            _invalidate_engine_cache_for_project(project_path)
            return _ok({"table": {"name": name, "columns": col_rows, "source": src, "storage_mode": storage_mode_val or "import"}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/tables/storage_modes")
    def runtime_tables_storage_modes(project: Optional[str] = None):
        """List all physical tables with their storage mode, source type, and metadata."""
        try:
            from dax_engine.storage_modes import infer_storage_mode, parse_storage_mode, storage_mode_to_str, describe_storage_mode

            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            out: list[dict[str, Any]] = []
            for t in getattr(model, "tables", []) or []:
                if bool(getattr(t, "is_calculated", False)):
                    continue
                src = getattr(t, "source", None)
                src_type = None
                if isinstance(src, Mapping):
                    src_type = str(src.get("type") or "").strip().lower() or None

                raw_mode = getattr(t, "storage_mode", None)
                try:
                    mode = parse_storage_mode(raw_mode)
                except ValueError:
                    mode = infer_storage_mode(src if isinstance(src, Mapping) else None)

                row = {
                    "name": getattr(t, "name", ""),
                    "storage_mode": storage_mode_to_str(mode),
                    "storage_mode_display": describe_storage_mode(mode),
                    "source_type": src_type,
                    "explicit": raw_mode is not None,
                }
                out.append(row)
            out.sort(key=lambda d: str(d.get("name", "")).upper())
            return _ok({"tables": out})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/tables/{table_name}/refresh")
    def runtime_table_refresh(table_name: str, project: Optional[str] = None):
        """Refresh a single table based on its storage mode.

        - Import: drop + recreate from source (full refresh).
        - DirectLake: drop + recreate view (re-frame metadata).
        - DirectQuery: no-op (always live).
        """
        try:
            from dax_engine.storage_modes import StorageMode, infer_storage_mode, parse_storage_mode, storage_mode_to_str

            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)

            tbl = None
            for t in getattr(model, "tables", []) or []:
                if str(getattr(t, "name", "")).strip().upper() == table_name.strip().upper():
                    tbl = t
                    break
            if tbl is None:
                raise ValueError(f"Table not found: {table_name!r}")
            if bool(getattr(tbl, "is_calculated", False)):
                raise ValueError(f"Calculated tables cannot be refreshed: {table_name!r}")

            src = getattr(tbl, "source", None)
            if not isinstance(src, Mapping):
                raise ValueError(f"Table {table_name!r} has no source definition")

            raw_mode = getattr(tbl, "storage_mode", None)
            try:
                mode = parse_storage_mode(raw_mode)
            except ValueError:
                mode = infer_storage_mode(src)

            if mode == StorageMode.DIRECT_QUERY:
                return _ok({"table": table_name, "storage_mode": "direct_query", "action": "noop", "message": "DirectQuery tables do not require refresh"})

            # For Import and DirectLake: drop existing table/view and recreate.
            db_path = _resolve_duckdb_path(None)
            if db_path:
                return _err(409, "Refresh is not supported when DAX_DUCKDB_PATH is set (persistent mode). Manage tables directly in the DuckDB file.")

            # Re-load from source by reconnecting (the existing connection is in-memory).
            # Since this is a single-table refresh, we need to use the shared connection.
            # For now, invalidate the engine cache to force a full reload on next request.
            _invalidate_engine_cache_for_project(project_path)

            action = "refresh" if mode == StorageMode.IMPORT else "frame"
            return _ok({
                "table": table_name,
                "storage_mode": storage_mode_to_str(mode),
                "action": action,
                "message": f"Table {table_name!r} scheduled for {action}. Changes will take effect on next query.",
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/refresh_all")
    def runtime_refresh_all(project: Optional[str] = None):
        """Refresh all import tables + frame all direct_lake tables."""
        try:
            from dax_engine.storage_modes import StorageMode, infer_storage_mode, parse_storage_mode, storage_mode_to_str

            project_path = _resolve_project_path_runtime(project)

            db_path = _resolve_duckdb_path(None)
            if db_path:
                return _err(409, "Refresh is not supported when DAX_DUCKDB_PATH is set (persistent mode).")

            model, _pages, _visuals = load_project(project_path)
            results: list[dict[str, Any]] = []
            for t in getattr(model, "tables", []) or []:
                if bool(getattr(t, "is_calculated", False)):
                    continue
                src = getattr(t, "source", None)
                if not isinstance(src, Mapping):
                    continue
                raw_mode = getattr(t, "storage_mode", None)
                try:
                    m = parse_storage_mode(raw_mode)
                except ValueError:
                    m = infer_storage_mode(src)

                name = str(getattr(t, "name", "")).strip()
                if m == StorageMode.DIRECT_QUERY:
                    results.append({"name": name, "storage_mode": "direct_query", "action": "noop"})
                elif m == StorageMode.IMPORT:
                    results.append({"name": name, "storage_mode": "import", "action": "refresh"})
                elif m == StorageMode.DIRECT_LAKE:
                    results.append({"name": name, "storage_mode": "direct_lake", "action": "frame"})

            _invalidate_engine_cache_for_project(project_path)
            return _ok({"tables": results, "message": "All tables scheduled for refresh/frame. Changes take effect on next query."})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/tables/{table_name}/storage_mode")
    def runtime_set_storage_mode(table_name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Update the storage mode of a physical table."""
        try:
            from dax_engine.storage_modes import parse_storage_mode, storage_mode_to_str, validate_storage_mode_source

            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)

            tbl = None
            for t in getattr(model, "tables", []) or []:
                if str(getattr(t, "name", "")).strip().upper() == table_name.strip().upper():
                    tbl = t
                    break
            if tbl is None:
                raise ValueError(f"Table not found: {table_name!r}")
            if bool(getattr(tbl, "is_calculated", False)):
                raise ValueError(f"Calculated tables cannot have a storage mode: {table_name!r}")

            new_mode_raw = str((payload or {}).get("storage_mode") or "").strip()
            if not new_mode_raw:
                raise ValueError("storage_mode is required in payload")

            parsed = parse_storage_mode(new_mode_raw)
            src = getattr(tbl, "source", None)
            if isinstance(src, Mapping):
                validate_storage_mode_source(parsed, dict(src), table_name=table_name)

            mode_str = storage_mode_to_str(parsed)

            # Preserve existing fields ΓÇö upsert_table_yaml treats source=None as "remove",
            # so we must pass through the existing source and columns.
            existing_src = dict(src) if isinstance(src, Mapping) else None
            existing_cols = [
                {"name": getattr(c, "name", ""), "type": getattr(c, "type", "UNKNOWN")}
                for c in (getattr(tbl, "columns", []) or [])
            ]
            upsert_table_yaml(
                project_path,
                name=table_name,
                columns=existing_cols if existing_cols else None,
                source=existing_src,
                storage_mode=mode_str,
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"table": table_name, "storage_mode": mode_str})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    # ── Phase 22: Data Source Management ──────────────────────────────────

    @app.put("/runtime/tables/{table_name}/source")
    def runtime_update_table_source(table_name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Update an existing physical table's data source configuration.

        Re-infers columns from the new source automatically.
        Preserves storage_mode, description, folder, table_type unless explicitly changed.
        """
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            model, _pages, _visuals = load_project(project_path)

            tbl = None
            for t in getattr(model, "tables", []) or []:
                if str(getattr(t, "name", "")).strip().upper() == table_name.strip().upper():
                    tbl = t
                    break
            if tbl is None:
                raise ValueError(f"Table not found: {table_name!r}")
            if bool(getattr(tbl, "is_calculated", False)):
                raise ValueError(f"Cannot change source of calculated table: {table_name!r}")

            src_raw = safe.get("source") if isinstance(safe.get("source"), Mapping) else safe
            src = _normalize_import_source(src_raw, project_path=project_path, allow_missing_table=False)

            columns = _infer_columns_from_source(project_path=project_path, src=src)
            if not columns:
                raise ValueError("No columns inferred from new source")

            col_rows = [{"name": c.get("name"), "type": c.get("type") or "UNKNOWN"} for c in columns]

            # Preserve existing table metadata unless overridden in payload.
            existing_storage = getattr(tbl, "storage_mode", None)
            new_storage_raw = str(safe.get("storage_mode") or "").strip().lower()
            storage_mode_val: Optional[str] = None
            if new_storage_raw:
                from dax_engine.storage_modes import parse_storage_mode, storage_mode_to_str, validate_storage_mode_source
                parsed_sm = parse_storage_mode(new_storage_raw)
                validate_storage_mode_source(parsed_sm, src, table_name=table_name)
                storage_mode_val = storage_mode_to_str(parsed_sm)
            elif existing_storage:
                storage_mode_val = str(existing_storage).strip().lower()

            existing_desc = getattr(tbl, "description", None)
            existing_folder = getattr(tbl, "folder", None)
            existing_table_type = getattr(tbl, "table_type", None)

            upsert_table_yaml(
                project_path,
                name=table_name,
                columns=col_rows,
                source=src,
                expression=None,
                is_calculated=False,
                description=str(existing_desc) if existing_desc else None,
                folder=str(existing_folder) if existing_folder else None,
                table_type=str(existing_table_type) if existing_table_type else None,
                storage_mode=storage_mode_val,
            )

            _invalidate_engine_cache_for_project(project_path)
            return _ok({
                "table": {
                    "name": table_name,
                    "columns": col_rows,
                    "source": src,
                    "storage_mode": storage_mode_val or "import",
                }
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/tables/{table_name}")
    def runtime_delete_physical_table(table_name: str, project: Optional[str] = None):
        """Delete a physical (non-calculated) table from the model.

        Removes the YAML file and invalidates the engine cache.
        Calculated tables must use DELETE /runtime/calculated_tables/{name} instead.
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            current = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table_name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Table not found: {table_name!r}")
            if bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Cannot delete calculated table via this endpoint. Use DELETE /runtime/calculated_tables/{table_name!r}")

            removed = delete_table_yaml(project_path, name=str(getattr(current, "name", table_name)))
            if not removed:
                return _err(404, f"Table not found: {table_name!r}")
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"deleted": table_name})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/data_sources/test")
    def runtime_test_data_source(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Test a data source connection without importing.

        Validates the source config and attempts to read schema/columns.
        Returns ok=true with column info if successful, or an error message.
        """
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            src_raw = safe.get("source") if isinstance(safe.get("source"), Mapping) else safe
            src = _normalize_import_source(src_raw, project_path=project_path, allow_missing_table=False)

            columns = _infer_columns_from_source(project_path=project_path, src=src)
            return _ok({
                "connected": True,
                "columns": columns or [],
                "column_count": len(columns) if columns else 0,
                "source": src,
            })
        except Exception as exc:  # noqa: BLE001
            return _ok({
                "connected": False,
                "error": str(exc),
                "source": dict(safe.get("source", {})) if isinstance(safe, Mapping) and isinstance(safe.get("source"), Mapping) else {},
            })

    @app.delete("/runtime/calculated_tables/{name}")
    def runtime_delete_calculated_table(name: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            current = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Table not found: {name!r}")
            if not bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Table is not calculated: {name!r}")

            removed = delete_table_yaml(project_path, name=str(getattr(current, "name", name)))
            if not removed:
                return _err(404, f"Table not found: {name!r}")
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"deleted": name})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/calculated_columns")
    def runtime_list_calculated_columns(request: Request, project: Optional[str] = None, table: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload={})
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        tbl = (table or "").strip()
        
        # If table is specified, return calc columns for that table only
        if tbl:
            t = next(
                (
                    t
                    for t in getattr(model_scoped, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == tbl.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {tbl!r}")

            cols = [
                {
                    "name": str(getattr(c, "name", "")),
                    "type": str(getattr(c, "type", "")),
                    "expression": getattr(c, "expression", None),
                    "is_calculated": bool(getattr(c, "is_calculated", False)),
                }
                for c in getattr(t, "columns", []) or []
                if bool(getattr(c, "is_calculated", False))
            ]
            cols.sort(key=lambda d: str(d.get("name", "")).upper())
            return _ok({"table": str(getattr(t, "name", tbl)), "columns": cols})
        
        # No table specified - return all calc columns across all tables
        all_cols = []
        for t in getattr(model_scoped, "tables", []) or []:
            table_name = str(getattr(t, "name", ""))
            for c in getattr(t, "columns", []) or []:
                if bool(getattr(c, "is_calculated", False)):
                    all_cols.append({
                        "table": table_name,
                        "column": str(getattr(c, "name", "")),
                        "name": str(getattr(c, "name", "")),
                        "type": str(getattr(c, "type", "")),
                        "expression": getattr(c, "expression", None),
                        "dax": getattr(c, "expression", None),
                        "is_calculated": True,
                    })
        all_cols.sort(key=lambda d: (str(d.get("table", "")).upper(), str(d.get("column", "")).upper()))
        return _ok({"calculated_columns": all_cols})

    @app.post("/runtime/calculated_columns/validate")
    def runtime_validate_calculated_column(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        table_name = str(payload.get("table") or "").strip()
        dax_text = payload.get("dax")
        if not table_name:
            return _err(400, "table is required")
        if not isinstance(dax_text, str) or not dax_text.strip():
            return _err(400, "dax is required")

        sql: Optional[str] = None
        try:
            _ensure_mapping_loaded()
            model, _pages, _visuals = load_project(project_path)

            _role_name, role = _resolve_security_for_request(model=model, request=request, payload=payload)
            model_scoped = apply_ols(model, role)

            # Enforce OLS: table must exist in scoped model.
            if not any(
                str(getattr(t, "name", "")).upper() == table_name.upper() for t in getattr(model_scoped, "tables", []) or []
            ):
                return _err(400, f"Unknown or hidden table: {table_name!r}")

            from dax_parser.ir_mapper import ast_to_ir
            from dax_parser.parser import parse_expression
            from dax_engine.sql_utils import as_from_source, quote_ident

            ir = ast_to_ir(parse_expression(dax_text))
            if not isinstance(ir, dax_compiler.ScalarExpr):
                return _err(400, f"Calculated column expression must be scalar; got {type(ir).__name__}")

            # Enforce OLS by validating referenced objects against the role-scoped model.
            from dax_engine.ir import (
                ColumnRef as _ColumnRef,
                DaxBinaryOp as _DaxBinaryOp,
                DaxFunction as _DaxFunction,
                DaxIteratorFunction as _DaxIteratorFunction,
                DaxWindowFunction as _DaxWindowFunction,
                MeasureRef as _MeasureRef,
                ParamRef as _ParamRef,
                SetLiteral as _SetLiteral,
            )

            def walk(e: Any) -> None:
                if isinstance(e, _ColumnRef):
                    _validate_columnref_in_model(model_scoped, e.table, e.column)
                    return
                if isinstance(e, _MeasureRef):
                    _validate_measureref_in_model(model_scoped, e.name)
                    return
                if isinstance(e, _ParamRef):
                    raise ValueError(f"Calculated column validation does not support unresolved field parameter: {e.name!r}")
                if isinstance(e, _SetLiteral):
                    for v in e.values:
                        walk(v)
                    return
                if isinstance(e, _DaxBinaryOp):
                    walk(e.left)
                    walk(e.right)
                    return
                if isinstance(e, _DaxFunction):
                    for a in e.args:
                        walk(a)
                    return
                if isinstance(e, _DaxIteratorFunction):
                    walk(e.table)
                    walk(e.expr)
                    return
                if isinstance(e, _DaxWindowFunction):
                    walk(e.table)
                    walk(e.expr)
                    if e.order_by is not None:
                        for c in e.order_by:
                            walk(c)
                    return

            walk(ir)

            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)
                ctx = dax_compiler.Context()
                sec = _compile_rls_security_predicates(role=role, base_ctx=ctx)
                if sec:
                    ctx = ctx.apply_security_predicates(sec)

                expr_sql = dax_compiler.compile_expr(ir, ctx)
                expr_sql = dax_compiler.rewrite_qualifiers_to_alias(expr_sql, "t")
                from_src = f"{quote_ident(table_name)} AS t"

                table_rls: Optional[str] = None
                for k, v in (sec or {}).items():
                    if str(k).upper() == table_name.upper():
                        table_rls = str(v)
                        break
                where_sql = ""
                if table_rls:
                    where_sql = f" WHERE {dax_compiler.rewrite_qualifiers_to_alias(table_rls, 't')}"
                sql = f"SELECT {expr_sql} AS value FROM {from_src}{where_sql} LIMIT 1"

            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            rows = con.execute(dax_compiler.normalize_sql(sql)).fetchall()
            val = rows[0][0] if rows and rows[0] else None
            return _ok({"table": table_name, "sql": sql, "value": _json_safe(val)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql, details={"endpoint": "calculated_column_validate", "project": project_path, "table": table_name})

    @app.post("/runtime/calculated_columns")
    def runtime_create_calculated_column(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        table_name = str(payload.get("table") or "").strip()
        col_name = str(payload.get("name") or "").strip()
        dax_text = payload.get("dax")
        if not table_name:
            return _err(400, "table is required")
        if not col_name:
            return _err(400, "name is required")
        try:
            _validate_safe_name(col_name, label="column name")
        except ValueError as e:
            return _err(400, str(e))
        if not isinstance(dax_text, str) or not dax_text.strip():
            return _err(400, "dax is required")

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table_name.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table_name!r}")

            # Disallow overwriting a physical/source column via this endpoint.
            for c in getattr(t, "columns", []) or []:
                cname_upper = str(getattr(c, "name", "")).upper()
                if cname_upper == col_name.upper():
                    if not bool(getattr(c, "is_calculated", False)):
                        return _err(409, f"Column exists and is not calculated: {table_name!r}[{col_name!r}]")
                    else:
                        return _err(409, f"Calculated column already exists: {table_name!r}[{col_name!r}] ΓÇö use PUT to update")

            upsert_column_yaml(
                project_path,
                table=str(getattr(t, "name", table_name)),
                name=col_name,
                col_type="UNKNOWN",
                source=None,
                expression=dax_text,
                is_calculated=True,
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"table": table_name, "column": {"name": col_name, "expression": dax_text}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/calculated_columns/{table}/{name}")
    def runtime_update_calculated_column(
        table: str,
        name: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        dax_text = payload.get("dax")
        if not isinstance(dax_text, str) or not dax_text.strip():
            return _err(400, "dax is required")

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table!r}")

            current = next(
                (
                    c
                    for c in getattr(t, "columns", []) or []
                    if str(getattr(c, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Column not found: {table!r}[{name!r}]")
            if not bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Column is not calculated: {table!r}[{name!r}]")

            upsert_column_yaml(
                project_path,
                table=str(getattr(t, "name", table)),
                name=str(getattr(current, "name", name)),
                col_type=str(getattr(current, "type", "UNKNOWN") or "UNKNOWN"),
                source=None,
                expression=dax_text,
                is_calculated=True,
            )
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"table": table, "column": {"name": name, "expression": dax_text}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/calculated_columns/{table}/{name}")
    def runtime_delete_calculated_column(table: str, name: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            t = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == table.upper()
                ),
                None,
            )
            if t is None:
                return _err(404, f"Table not found: {table!r}")

            current = next(
                (
                    c
                    for c in getattr(t, "columns", []) or []
                    if str(getattr(c, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Column not found: {table!r}[{name!r}]")
            if not bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Column is not calculated: {table!r}[{name!r}]")

            removed = delete_column_yaml(project_path, table=str(getattr(t, "name", table)), name=str(getattr(current, "name", name)))
            if not removed:
                return _err(404, f"Column not found: {table!r}[{name!r}]")
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"deleted": {"table": table, "column": name}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/autocomplete")
    def runtime_autocomplete(request: Request, project: Optional[str] = None, prefix: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload=None)
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        from dax_project.introspection import search_symbols

        p = (prefix or "").strip()
        symbols = search_symbols(model_scoped, p)

        # DAX function names from the registry (best-effort; requires mapping loaded).
        try:
            _ensure_mapping_loaded()
            from dax_engine.registry import registry

            p_upper = p.upper()
            functions = [k for k in registry.keys() if str(k).upper().startswith(p_upper)]
            functions = sorted(set(functions), key=lambda s: str(s).upper())
        except Exception:
            functions = []

        return _ok({"prefix": p, **symbols, "functions": functions})

    @app.post("/runtime/measures/validate")
    def runtime_validate_measure(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        dax_text = payload.get("dax")
        name = str(payload.get("name") or "__DRAFT__").strip() or "__DRAFT__"
        if not isinstance(dax_text, str) or not dax_text.strip():
            return _err(400, "dax is required")

        sql: Optional[str] = None
        try:
            _ensure_mapping_loaded()
            model, _pages, _visuals = load_project(project_path)

            role_name, role = _resolve_security_for_request(model=model, request=request, payload=payload)
            model_scoped = apply_ols(model, role)

            from dax_parser.ir_mapper import ast_to_ir
            from dax_parser.parser import parse_expression

            ir = ast_to_ir(parse_expression(dax_text))
            if not isinstance(ir, dax_compiler.ScalarExpr):
                return _err(400, f"Measure expression must be scalar; got {type(ir).__name__}")

            # Enforce OLS by validating referenced objects against the role-scoped model.
            from dax_engine.ir import (
                ColumnRef as _ColumnRef,
                DaxBinaryOp as _DaxBinaryOp,
                DaxFunction as _DaxFunction,
                DaxIteratorFunction as _DaxIteratorFunction,
                DaxWindowFunction as _DaxWindowFunction,
                MeasureRef as _MeasureRef,
                ParamRef as _ParamRef,
                SetLiteral as _SetLiteral,
            )

            def walk(e: Any) -> None:
                if isinstance(e, _ColumnRef):
                    _validate_columnref_in_model(model_scoped, e.table, e.column)
                    return
                if isinstance(e, _MeasureRef):
                    # Allow self-reference to the draft name (handled by engine registry).
                    if str(e.name).upper() != str(name).upper():
                        _validate_measureref_in_model(model_scoped, e.name)
                    return
                if isinstance(e, _ParamRef):
                    raise ValueError(f"Measure validation does not support unresolved field parameter: {e.name!r}")
                if isinstance(e, _SetLiteral):
                    for v in e.values:
                        walk(v)
                    return
                if isinstance(e, _DaxBinaryOp):
                    walk(e.left)
                    walk(e.right)
                    return
                if isinstance(e, _DaxFunction):
                    for a in e.args:
                        walk(a)
                    return
                if isinstance(e, _DaxIteratorFunction):
                    walk(e.table)
                    walk(e.expr)
                    return
                if isinstance(e, _DaxWindowFunction):
                    walk(e.table)
                    walk(e.expr)
                    if e.order_by is not None:
                        for c in e.order_by:
                            walk(c)
                    return

            walk(ir)

            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)
                project_key = _norm_project_key(project_path)
                cached = _ENGINE_CACHE.get(project_key)
                if cached is None or cached.project_key != project_key:
                    return _err(500, "Engine cache not initialized")

                base_measures = dict(cached.measures)
                draft_measures = dict(base_measures)
                draft_measures[name] = ir

                try:
                    dax_compiler.set_measures(draft_measures)

                    ctx = dax_compiler.Context()
                    sec = _compile_rls_security_predicates(role=role, base_ctx=ctx)
                    if sec:
                        ctx = ctx.apply_security_predicates(sec)

                    _table_ir, sql = plan_card_query(
                        MeasureRef(name),
                        filters=[],
                        model=None,
                        ctx=ctx,
                    )
                finally:
                    # Ensure we don't leak the draft measure into the global engine.
                    dax_compiler.set_measures(base_measures)

            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            rows = con.execute(dax_compiler.normalize_sql(f"SELECT * FROM {sql}")).fetchall()
            val = rows[0][0] if rows and rows[0] else None
            return _ok({"name": name, "sql": sql, "value": _json_safe(val)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql, details={"endpoint": "measure_validate", "project": project_path, "name": name})

    @app.post("/runtime/measure/evaluate")
    def runtime_evaluate_measure(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        try:
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        meas_raw = safe.get("measure")
        if not isinstance(meas_raw, Mapping):
            return _err(400, "measure is required", error_code="E_MEASURE_INVALID")

        try:
            meas_expr = parse_expr(dict(meas_raw))
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")
        if not isinstance(meas_expr, MeasureRef):
            return _err(400, "measure must be a MeasureRef", error_code="E_MEASURE_INVALID")

        page_id = safe.get("page_id")
        if page_id is not None and (not isinstance(page_id, str) or not page_id.strip()):
            return _err(400, "page_id must be a non-empty string if provided", error_code="E_MEASURE_INVALID")
        page_id_s = str(page_id).strip() if isinstance(page_id, str) and page_id.strip() else None

        visual_id = safe.get("visual_id")
        if visual_id is not None and (not isinstance(visual_id, str) or not visual_id.strip()):
            return _err(400, "visual_id must be a non-empty string if provided", error_code="E_MEASURE_INVALID")
        visual_id_s = str(visual_id).strip() if isinstance(visual_id, str) and visual_id.strip() else None

        try:
            model, _pages, _visuals = load_project(project_path)
            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=safe)
            _validate_measureref_in_model(sec_state.model_scoped, meas_expr.name)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        try:
            runtime_filters = _parse_scoped_filters_payload(
                safe.get("filters"),
                project_path=project_path,
                model=sec_state.model_scoped,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        try:
            val = _evaluate_measure_ref_scalar(
                project_path=project_path,
                model=model,
                sec_state=sec_state,
                measure_ref=meas_expr,
                duckdb_path=duckdb_path,
                filters=list(runtime_filters),
                page_id=page_id_s,
                visual_id=visual_id_s,
            )
            return _ok({"value": _json_safe(val)})
        except ValueError as exc:
            msg = str(exc)
            if "must return a scalar" in msg.lower():
                return _err(400, msg, error_code="E_MEASURE_INVALID_RETURN_TYPE")
            return _err(400, msg, error_code="E_MEASURE_EVAL_FAILED")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_EVAL_FAILED")

    @app.post("/runtime/measure/evaluate_set")
    def runtime_evaluate_measure_set(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        try:
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        meas_raw = safe.get("measure")
        if not isinstance(meas_raw, Mapping):
            return _err(400, "measure is required", error_code="E_MEASURE_INVALID")

        try:
            meas_expr = parse_expr(dict(meas_raw))
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")
        if not isinstance(meas_expr, MeasureRef):
            return _err(400, "measure must be a MeasureRef", error_code="E_MEASURE_INVALID")

        page_id = safe.get("page_id")
        if page_id is not None and (not isinstance(page_id, str) or not page_id.strip()):
            return _err(400, "page_id must be a non-empty string if provided", error_code="E_MEASURE_INVALID")
        page_id_s = str(page_id).strip() if isinstance(page_id, str) and page_id.strip() else None

        visual_id = safe.get("visual_id")
        if visual_id is not None and (not isinstance(visual_id, str) or not visual_id.strip()):
            return _err(400, "visual_id must be a non-empty string if provided", error_code="E_MEASURE_INVALID")
        visual_id_s = str(visual_id).strip() if isinstance(visual_id, str) and visual_id.strip() else None

        try:
            model, _pages, _visuals = load_project(project_path)
            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=safe)
            _validate_measureref_in_model(sec_state.model_scoped, meas_expr.name)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        try:
            runtime_filters = _parse_scoped_filters_payload(
                safe.get("filters"),
                project_path=project_path,
                model=sec_state.model_scoped,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_INVALID")

        try:
            vals = _evaluate_measure_ref_set(
                project_path=project_path,
                model=model,
                sec_state=sec_state,
                measure_ref=meas_expr,
                duckdb_path=duckdb_path,
                filters=list(runtime_filters),
                page_id=page_id_s,
                visual_id=visual_id_s,
            )
            return _ok({"values": [_json_safe(v) for v in vals]})
        except ValueError as exc:
            msg = str(exc)
            if "1-column table" in msg.lower():
                return _err(400, msg, error_code="E_MEASURE_INVALID_RETURN_TYPE")
            return _err(400, msg, error_code="E_MEASURE_EVAL_FAILED")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_MEASURE_EVAL_FAILED")
