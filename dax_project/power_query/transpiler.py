from __future__ import annotations

from typing import Any, Mapping

from .duckdb_emitter import emit_duckdb_sql
from .connector_folding import build_connector_native_plan
from .execution_strategy import (
    classify_step_execution_strategy,
    detect_helper_blockers,
    summarize_plan_execution_strategy,
)
from .helper_analysis import build_pure_helper_registry, inline_pure_helpers_in_ir
from .ir import make_transform_ir_node, serialize_ir
from .parser import parse_m_query
from .registry import classify_function_names
from .schema_probe import build_power_query_schema_probe
from .source_map import map_source_bindings_from_m
from .source_policy import build_source_policy_report
from .sql_ast import build_relational_query_ast


_TABLE_OPERATION_MAP = {
    "TABLE.SELECTROWS": "filter_rows",
    "TABLE.SELECTCOLUMNS": "select_columns",
    "TABLE.REMOVECOLUMNS": "remove_columns",
    "TABLE.RENAMECOLUMNS": "rename_columns",
    "TABLE.DUPLICATECOLUMN": "duplicate_column",
    "TABLE.REORDERCOLUMNS": "reorder_columns",
    "TABLE.TRANSFORMCOLUMNTYPES": "transform_column_types",
    "TABLE.TRANSFORMCOLUMNS": "transform_columns",
    "TABLE.TRANSFORMCOLUMNNAMES": "transform_column_names",
    "TABLE.DISTINCT": "distinct",
    "TABLE.SORT": "sort",
    "TABLE.FIRSTN": "limit_first",
    "TABLE.LASTN": "limit_last",
    "TABLE.SKIP": "skip",
    "TABLE.REMOVEFIRSTN": "remove_first",
    "TABLE.REMOVELASTN": "remove_last",
    "TABLE.RANGE": "range",
    "TABLE.ADDCOLUMN": "add_column",
    "TABLE.ADDINDEXCOLUMN": "add_index_column",
    "TABLE.GROUP": "group",
    "TABLE.FUZZYJOIN": "fuzzy_join",
    "TABLE.FUZZYNESTEDJOIN": "fuzzy_nested_join",
    "TABLE.FUZZYGROUP": "fuzzy_group",
    "TABLE.ADDFUZZYCLUSTERCOLUMN": "fuzzy_cluster",
    "TABLE.NESTEDJOIN": "join_nested",
    "TABLE.JOIN": "join",
    "TABLE.AGGREGATETABLECOLUMN": "aggregate_table_column",
    "TABLE.COMBINE": "append",
    "TABLE.PIVOT": "pivot",
    "TABLE.UNPIVOT": "unpivot",
    "TABLE.UNPIVOTOTHERCOLUMNS": "unpivot_other_columns",
    "TABLE.EXPANDTABLECOLUMN": "expand_table_column",
    "TABLE.EXPANDRECORDCOLUMN": "expand_record_column",
    "TABLE.EXPANDLISTCOLUMN": "expand_list_column",
    "TABLE.REPLACEVALUE": "replace_value",
    "TABLE.REPLACEERRORVALUES": "replace_errors",
    "TABLE.REMOVEROWSWITHERRORS": "remove_rows_with_errors",
    "TABLE.SELECTROWSWITHERRORS": "select_rows_with_errors",
    "TABLE.FILLDOWN": "fill_down",
    "TABLE.FILLUP": "fill_up",
    "VALUE.NATIVEQUERY": "native_query",
    "TABLE.PROMOTEHEADERS": "promote_headers",
    "TABLE.DEMOTEHEADERS": "demote_headers",
    "TABLE.SPLITCOLUMN": "split_column",
    "TABLE.COMBINECOLUMNS": "combine_columns",
    "TABLE.ADDKEY": "table_key",
    "TABLE.BUFFER": "fold_barrier",
    "TABLE.STOPFOLDING": "fold_barrier",
    "VALUE.REPLACETYPE": "type_annotation",
    "#TABLE": "constant_table",
    "TABLE.FROMRECORDS": "constant_table",
    "TABLE.FROMROWS": "constant_table",
    "TABLE.FROMCOLUMNS": "constant_table",
    "TABLE.FROMLIST": "constant_table_from_list",
}

_SOURCE_OPERATIONS = {
    "FILE.CONTENTS": "source_file",
    "FOLDER.FILES": "source_folder",
    "FOLDER.CONTENTS": "source_folder",
    "CSV.DOCUMENT": "source_csv",
    "EXCEL.WORKBOOK": "source_excel",
    "JSON.DOCUMENT": "source_json",
    "XML.TABLES": "source_xml",
    "PARQUET.DOCUMENT": "source_parquet",
    "SQL.DATABASE": "source_sql",
    "ODBC.DATASOURCE": "source_odbc",
    "ODATA.FEED": "source_odata",
    "WEB.CONTENTS": "source_web",
    "SHAREPOINT.FILES": "source_sharepoint",
    "SHAREPOINT.TABLES": "source_sharepoint",
}


def _blockers_by_step(blockers: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    by_step: dict[str, list[str]] = {}
    for blocker in blockers:
        step_id = str(blocker.get("step_id") or "").strip()
        reason = str(blocker.get("reason") or "").strip()
        if not step_id or not reason:
            continue
        reasons = by_step.setdefault(step_id, [])
        if reason not in reasons:
            reasons.append(reason)
    return by_step


def _fold_frontier(plan_steps: list[dict[str, Any]], blockers: list[Mapping[str, Any]]) -> dict[str, Any]:
    foldable_step_ids: list[str] = []
    first_blocked_step_id = ""
    first_blockers: list[str] = []
    blocker_by_step = _blockers_by_step(blockers)
    for step in plan_steps:
        step_id = str(step.get("id") or "")
        step_blockers = []
        step_blockers.extend(str(item) for item in step.get("blockers") or [] if str(item))
        step_blockers.extend(str(item) for item in step.get("relational_blockers") or [] if str(item))
        step_blockers.extend(str(item) for item in step.get("duckdb_blockers") or [] if str(item))
        step_blockers.extend(blocker_by_step.get(step_id, []))
        step_blockers = list(dict.fromkeys(step_blockers))
        if step.get("foldable") and not step_blockers and not first_blocked_step_id:
            foldable_step_ids.append(step_id)
            continue
        if not first_blocked_step_id:
            first_blocked_step_id = step_id
            first_blockers = step_blockers or ["Step is not currently foldable."]
    if not plan_steps:
        status = "no_steps"
    elif not first_blocked_step_id:
        status = "fully_foldable"
    elif foldable_step_ids:
        status = "partially_foldable"
    else:
        status = "not_foldable"
    return {
        "status": status,
        "foldable_step_ids": foldable_step_ids,
        "first_blocked_step_id": first_blocked_step_id or None,
        "blockers": [{"step_id": first_blocked_step_id, "reason": reason} for reason in first_blockers],
    }


def _editor_hints(
    *,
    plan_steps: list[dict[str, Any]],
    diagnostics: list[Any],
    source_policy: Mapping[str, Any],
    fold_frontier: Mapping[str, Any],
    duckdb_sql: Mapping[str, Any],
    strategy_summary: Mapping[str, Any],
    connector_native_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if connector_native_plan and connector_native_plan.get("status") == "candidate":
        suggested = "Review the connector-native preview and run Preview/Profile with the selected credential profile."
    elif duckdb_sql.get("status") == "emit_candidate":
        suggested = "Review generated DuckDB SQL or run Preview/Profile to compare results."
    elif strategy_summary.get("execution_strategy") == "local_exact":
        blocked = fold_frontier.get("first_blocked_step_id")
        suggested = (
            f"Step {blocked} has exact local-evaluator behavior; review the fold frontier before expecting SQL pushdown."
            if blocked else
            "This query has exact local-evaluator steps; review the fold frontier before expecting SQL pushdown."
        )
    elif strategy_summary.get("schema_probe_required"):
        suggested = "Run a schema probe or Preview/Profile so dynamic column operations can be resolved safely."
    elif fold_frontier.get("first_blocked_step_id"):
        suggested = f"Select step {fold_frontier.get('first_blocked_step_id')} to inspect the first folding blocker."
    else:
        suggested = "Run Parse and Source Mapping to inspect this query before editing."
    return {
        "parse_diagnostics": [diag.to_dict() for diag in diagnostics],
        "source_count": source_policy.get("source_count"),
        "credential_required_count": source_policy.get("credential_required_count"),
        "first_blocked_step_id": fold_frontier.get("first_blocked_step_id"),
        "foldable_step_count": len([step for step in plan_steps if step.get("foldable")]),
        "execution_strategy": strategy_summary.get("execution_strategy"),
        "parity_status": strategy_summary.get("parity_status"),
        "schema_probe_required": strategy_summary.get("schema_probe_required"),
        "local_evaluator_reason": strategy_summary.get("local_evaluator_reason"),
        "suggested_next_action": suggested,
    }


def build_neutral_transform_plan(
    raw_m: str,
    *,
    project_root: str | None = None,
    schema_probe_mode: str = "plan",
    credential_profile_id: str | None = None,
    fixture_mode: bool = True,
    execution_target: str = "duckdb",
) -> dict[str, Any]:
    """Return a conservative neutral transform plan for parsed M steps.

    This is a readiness/transpile plan, not full SQL generation. It names the
    operation family and records blockers so the UI can show why a step cannot
    yet become foldable SQL.
    """

    steps, result_expression, functions, diagnostics = parse_m_query(raw_m)
    function_status = classify_function_names(functions)
    source_policy = build_source_policy_report(raw_m)
    source_bindings = [binding.to_dict() for binding in map_source_bindings_from_m(raw_m)]
    pure_helpers = build_pure_helper_registry(steps)
    plan_steps: list[dict[str, Any]] = []
    ir_nodes = []
    blockers: list[dict[str, Any]] = []

    for step in steps:
        op_key = str(step.operation or "").strip().upper()
        operation = _TABLE_OPERATION_MAP.get(op_key) or _SOURCE_OPERATIONS.get(op_key)
        if step.id in pure_helpers:
            operation = "helper_definition"
        elif operation is None and step.operation == "Navigation":
            operation = "navigation"
        elif operation is None:
            operation = "expression"

        step_blockers: list[str] = []
        for fn in step.functions:
            status = function_status.get(fn) or {}
            execution = str(status.get("execution") or "")
            if operation == "transform_column_names" and fn == "Text.Prefix":
                continue
            if execution in {"unsupported", "preserve_only"}:
                step_blockers.append(f"Unsupported function: {fn}")
        step_blockers.extend(
            detect_helper_blockers(
                operation=operation,
                functions=step.functions,
                expression=step.expression,
                pure_helpers=pure_helpers,
            )
        )

        foldable = operation not in {"expression"} and not step_blockers
        if operation in {"source_web", "source_sharepoint", "source_odata", "source_odbc", "source_sql"}:
            foldable = False
            step_blockers.append(f"Connector-specific pushdown requires credential binding/native adapter for {step.operation}")
        if operation == "native_query":
            foldable = False
            step_blockers.append("Value.NativeQuery is preserved but requires approved connector execution and safe parameter binding before refresh.")
        if operation == "fold_barrier":
            foldable = False
            step_blockers.append(f"{step.operation} is executable locally but intentionally stops SQL pushdown after this step.")
        if operation == "helper_definition":
            foldable = True
            step_blockers = []

        ir_node = make_transform_ir_node(
            step=step,
            operation=operation,
            foldable=foldable,
            blockers=step_blockers,
        )
        ir_nodes.append(ir_node)
        plan_steps.append(
            {
                "id": step.id,
                "operation": operation,
                "ir_node_id": ir_node.id,
                "source_operation": step.operation,
                "dependencies": step.dependencies,
                "functions": step.functions,
                "foldable": foldable,
                "execution_lane": ir_node.execution_lane,
                "blockers": step_blockers,
                "expression": step.expression,
            }
        )
        for reason in step_blockers:
            blockers.append({"step_id": step.id, "reason": reason})

    serialized_ir = serialize_ir(ir_nodes)
    serialized_ir = inline_pure_helpers_in_ir(serialized_ir, pure_helpers)
    schema_probe_for_lowering = build_power_query_schema_probe(
        ir_nodes=serialized_ir,
        plan_steps=plan_steps,
        project_root=project_root,
        schema_probe_mode=schema_probe_mode,
        credential_profile_id=credential_profile_id,
        fixture_mode=fixture_mode,
    )
    relational_ast = build_relational_query_ast(
        serialized_ir,
        schema_hints=schema_probe_for_lowering.get("resolved_columns_by_step") if isinstance(schema_probe_for_lowering, Mapping) else None,
    )
    duckdb_sql = emit_duckdb_sql(relational_ast)
    relational_blockers_by_step = _blockers_by_step(relational_ast.get("blockers") or [])
    duckdb_blockers_by_step = _blockers_by_step(duckdb_sql.get("blockers") or [])
    for step in plan_steps:
        step_id = str(step.get("id") or "")
        relational_blockers = relational_blockers_by_step.get(step_id, [])
        duckdb_blockers = duckdb_blockers_by_step.get(step_id, [])
        if relational_blockers:
            step["relational_blockers"] = relational_blockers
            step["foldable"] = False
            step["execution_lane"] = "local_evaluator"
            blockers.extend({"step_id": step_id, "reason": reason} for reason in relational_blockers)
        if duckdb_blockers:
            step["duckdb_blockers"] = duckdb_blockers
            step["foldable"] = False
            step["execution_lane"] = "local_evaluator"
            blockers.extend({"step_id": step_id, "reason": reason} for reason in duckdb_blockers)
    blocker_by_step = _blockers_by_step(blockers)
    for step in plan_steps:
        step_id = str(step.get("id") or "")
        strategy = classify_step_execution_strategy(step, extra_blockers=blocker_by_step.get(step_id, []))
        step.update(strategy)
    if plan_steps and not blockers and relational_ast.get("status") == "emit_candidate" and duckdb_sql.get("status") == "emit_candidate":
        status = "foldable_plan"
    elif plan_steps:
        status = "partial_plan"
    else:
        status = "preserve_only"
    fold_frontier = _fold_frontier(plan_steps, blockers)
    strategy_summary = summarize_plan_execution_strategy(plan_steps)
    local_exact_reasons = [
        {
            "step_id": str(step.get("id") or ""),
            "reason": str(step.get("local_evaluator_reason") or "; ".join(str(item) for item in step.get("blockers") or [])),
        }
        for step in plan_steps
        if step.get("execution_strategy") == "local_exact"
    ]
    schema_probe = build_power_query_schema_probe(
        ir_nodes=serialized_ir,
        plan_steps=plan_steps,
        project_root=project_root,
        schema_probe_mode=schema_probe_mode,
        credential_profile_id=credential_profile_id,
        fixture_mode=fixture_mode,
    )
    connector_native_plan = build_connector_native_plan(
        relational_ast=relational_ast,
        schema_probe=schema_probe,
        credential_profile_id=credential_profile_id,
        fixture_mode=fixture_mode,
        execution_target=execution_target,
    )
    editor_hints = _editor_hints(
        plan_steps=plan_steps,
        diagnostics=diagnostics,
        source_policy=source_policy,
        fold_frontier=fold_frontier,
        duckdb_sql=duckdb_sql,
        strategy_summary=strategy_summary,
        connector_native_plan=connector_native_plan,
    )
    return {
        "ir_version": "pqir.v1",
        "relational_ast_version": "pqrel.v1",
        "status": status,
        **strategy_summary,
        "result_expression": result_expression,
        "ir": serialized_ir,
        "relational_ast": relational_ast,
        "duckdb_sql": duckdb_sql,
        "connector_native_plan": connector_native_plan,
        "source_policy": source_policy,
        "source_bindings": source_bindings,
        "navigation_chain": [
            item
            for binding in source_bindings
            for item in (binding.get("navigation_chain") or [])
            if isinstance(item, Mapping)
        ],
        "fold_frontier": fold_frontier,
        "schema_probe": schema_probe,
        "schema_probe_results": schema_probe,
        "local_exact_reasons": local_exact_reasons,
        "helper_trace": {
            "pure_helpers": sorted(pure_helpers),
            "inlining_status": "eligible_helpers_inlined_before_relational_lowering" if pure_helpers else "no_pure_helpers_detected",
        },
        "editor_hints": editor_hints,
        "steps": plan_steps,
        "blockers": blockers,
        "diagnostics": [diag.to_dict() for diag in diagnostics],
    }
