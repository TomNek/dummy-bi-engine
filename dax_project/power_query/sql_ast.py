from __future__ import annotations

import re
from typing import Any, Mapping

from .expression_sql import can_lower_m_row_expression_to_duckdb


def _node_id(node: Mapping[str, Any]) -> str:
    return str(node.get("m_step_id") or node.get("id") or "").strip()


def _args(node: Mapping[str, Any]) -> Mapping[str, Any]:
    args = node.get("args")
    return args if isinstance(args, Mapping) else {}


def _projection_from_columns(columns: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for column in columns:
        name = str(column)
        if name:
            out.append({"source": name, "alias": name})
    return out


def _record_fields_from_rows(columns: list[str], rows: list[list[Any]]) -> dict[str, list[str]]:
    fields_by_column: dict[str, list[str]] = {}
    for index, column in enumerate(columns):
        fields: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if index >= len(row) or not isinstance(row[index], Mapping):
                continue
            for field in row[index].keys():
                name = str(field)
                key = name.strip().upper()
                if name and key not in seen:
                    fields.append(name)
                    seen.add(key)
        if fields:
            fields_by_column[column] = fields
    return fields_by_column


def _projection_from_schema_hint(schema_hints: Mapping[str, Any], step_id: str) -> list[dict[str, str]] | None:
    columns = schema_hints.get(step_id)
    if not isinstance(columns, list) or not columns:
        return None
    projection = _projection_from_columns(columns)
    return projection or None


def _projection_from_schema_hints(schema_hints: Mapping[str, Any], *step_ids: str) -> list[dict[str, str]] | None:
    for step_id in step_ids:
        if not step_id:
            continue
        projection = _projection_from_schema_hint(schema_hints, step_id)
        if projection is not None:
            return projection
    return None


def _projection_match(projection: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = name.strip().upper()
    for item in projection:
        source = str(item.get("source") or "").strip().upper()
        alias = str(item.get("alias") or "").strip().upper()
        if target in {source, alias}:
            return dict(item)
    return None


def _apply_renames(projection: list[dict[str, str]] | None, renames: list[Mapping[str, Any]]) -> list[dict[str, str]] | None:
    if projection is None:
        return None
    rename_map = {str(item.get("from") or ""): str(item.get("to") or "") for item in renames}
    for item in projection:
        source = item.get("source") or ""
        alias = item.get("alias") or source
        if alias in rename_map and rename_map[alias]:
            item["alias"] = rename_map[alias]
        elif source in rename_map and rename_map[source]:
            item["alias"] = rename_map[source]
    return projection


def _is_simple_row_expression(expression: str) -> bool:
    return can_lower_m_row_expression_to_duckdb(expression)


def _is_simple_transform_expression(expression: str, column: str) -> bool:
    return can_lower_m_row_expression_to_duckdb(expression, current_column=column)


def _strip_m_string(value: str) -> str | None:
    text = value.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('""', '"')
    return None


def _split_call_args(value: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    depth = 0
    in_text = False
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == '"':
            current.append(ch)
            if in_text and i + 1 < len(value) and value[i + 1] == '"':
                current.append(value[i + 1])
                i += 2
                continue
            in_text = not in_text
            i += 1
            continue
        if not in_text:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _text_call_args(expression: str, function: str) -> list[str] | None:
    text = expression.strip()
    prefix = f"{function}("
    if not text.lower().startswith(prefix.lower()) or not text.endswith(")"):
        return None
    return _split_call_args(text[len(prefix):-1])


def _eval_column_name_transform(name: str, expression: str) -> str | None:
    expr = expression.strip()
    if expr.lower().startswith("each "):
        expr = expr[5:].strip()
    if expr == "_":
        return name
    direct = {
        "Text.Upper": lambda value: value.upper(),
        "Text.Lower": lambda value: value.lower(),
        "Text.Trim": lambda value: value.strip(),
        "Text.Clean": lambda value: "".join(ch for ch in value if ord(ch) >= 32),
    }
    if expr in direct:
        return direct[expr](name)
    for function, apply in direct.items():
        args = _text_call_args(expr, function)
        if args is not None and len(args) == 1:
            inner = _eval_column_name_transform(name, args[0])
            return None if inner is None else apply(inner)
    args = _text_call_args(expr, "Text.Replace")
    if args is not None and len(args) >= 3:
        inner = _eval_column_name_transform(name, args[0])
        old = _strip_m_string(args[1])
        new = _strip_m_string(args[2])
        if inner is None or old is None or new is None:
            return None
        return inner.replace(old, new)
    args = _text_call_args(expr, "Text.Prefix")
    if args is not None and len(args) >= 2:
        inner = _eval_column_name_transform(name, args[0])
        prefix = _strip_m_string(args[1])
        if inner is None or prefix is None:
            return None
        return f"{prefix}{inner}"
    return None


def _transform_column_name_alias(name: str, expression: str) -> str | None:
    return _eval_column_name_transform(name, expression)


def _apply_column_name_transform(projection: list[dict[str, str]] | None, expression: str) -> list[dict[str, str]] | None:
    if projection is None:
        return None
    transformed: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in projection:
        source = item.get("source") or ""
        alias = item.get("alias") or source
        new_alias = _transform_column_name_alias(alias, expression)
        if new_alias is None or new_alias in seen:
            return None
        seen.add(new_alias)
        transformed.append({"source": source, "alias": new_alias})
    return transformed


def _is_supported_group_aggregation(item: Mapping[str, Any]) -> bool:
    function = str(item.get("function") or "")
    if function == "Table.RowCount":
        return True
    return function in {
        "List.Sum",
        "List.Min",
        "List.Max",
        "List.Average",
        "List.Count",
        "List.NonNullCount",
    } and bool(item.get("source_column"))


def _is_supported_nested_aggregation(item: Mapping[str, Any]) -> bool:
    function = str(item.get("function") or "")
    return function in {
        "List.Sum",
        "List.Min",
        "List.Max",
        "List.Average",
        "List.Count",
        "List.NonNullCount",
    } and bool(item.get("source_column")) and bool(item.get("name"))


def _normalize_join_kind(value: str) -> str | None:
    normalized = value.strip().upper()
    if normalized in {"", "JOINKIND.INNER", "INNER"}:
        return "inner"
    if normalized in {"JOINKIND.LEFTOUTER", "LEFT", "LEFT OUTER"}:
        return "left"
    if normalized in {"JOINKIND.RIGHTOUTER", "RIGHT", "RIGHT OUTER"}:
        return "right"
    if normalized in {"JOINKIND.FULLOUTER", "FULL", "FULL OUTER"}:
        return "full"
    if normalized in {"JOINKIND.LEFTANTI", "LEFTANTI", "LEFT ANTI", "ANTI"}:
        return "left_anti"
    if normalized in {"JOINKIND.RIGHTANTI", "RIGHTANTI", "RIGHT ANTI"}:
        return "right_anti"
    return None


def _promoted_constant_source(source: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(source.get("kind") or "") != "constant_table":
        return None
    rows = [list(row) if isinstance(row, list) else [row] for row in source.get("rows") or []]
    if not rows:
        return None
    header = [str(value) for value in rows[0]]
    if not header or any(not item for item in header) or len(set(header)) != len(header):
        return None
    return {"kind": "constant_table", "columns": header, "rows": rows[1:]}


def _demoted_columns(projection: list[dict[str, Any]] | None) -> list[str]:
    return [
        str(item.get("alias") or item.get("source") or "")
        for item in projection or []
        if str(item.get("alias") or item.get("source") or "")
    ]


def _mark_latest_cast_try(operations: list[dict[str, Any]], columns: list[str]) -> bool:
    wanted = {column.upper() for column in columns if column}
    if not wanted:
        return False
    for operation in reversed(operations):
        if operation.get("op") != "cast":
            continue
        cast_columns = {
            str(item.get("column") or "").upper()
            for item in operation.get("casts") or []
            if isinstance(item, Mapping)
        }
        matched = sorted(wanted.intersection(cast_columns))
        if not matched:
            continue
        existing = {str(item).upper() for item in operation.get("try_cast_columns") or []}
        operation["try_cast_columns"] = sorted(existing.union(matched))
        return True
    return False


def build_relational_query_ast(
    ir_nodes: list[Mapping[str, Any]],
    *,
    schema_hints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Lower conservative PQIR nodes into a neutral relational query AST.

    This is not target SQL. It is the stable contract future DuckDB/Snowflake/
    BigQuery emitters can consume for the foldable table subset.
    """

    sources_by_step: dict[str, dict[str, Any]] = {}
    scan_sources_by_step: dict[str, dict[str, Any]] = {}
    relation_sources_by_step: dict[str, dict[str, Any]] = {}
    operations_by_step: dict[str, list[dict[str, Any]]] = {}
    source: dict[str, Any] | None = None
    projection: list[dict[str, Any]] | None = None
    filters: list[dict[str, Any]] = []
    casts: list[dict[str, Any]] = []
    computed_columns: list[dict[str, Any]] = []
    transformed_columns: list[dict[str, Any]] = []
    column_name_transforms: list[dict[str, Any]] = []
    constant_tables: list[dict[str, Any]] = []
    folder_sources: list[dict[str, Any]] = []
    expanded_record_columns: list[dict[str, Any]] = []
    expanded_list_columns: list[dict[str, Any]] = []
    duplicated_columns: list[dict[str, Any]] = []
    index_columns: list[dict[str, Any]] = []
    removed_columns: list[str] = []
    append_sources: list[dict[str, Any]] = []
    append_relations: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []
    expanded_nested_joins: list[dict[str, Any]] = []
    aggregated_nested_joins: list[dict[str, Any]] = []
    unpivots: list[dict[str, Any]] = []
    pivots: list[dict[str, Any]] = []
    split_columns: list[dict[str, Any]] = []
    combined_columns: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    error_replacements: list[dict[str, Any]] = []
    error_row_filters: list[dict[str, Any]] = []
    header_operations: list[dict[str, Any]] = []
    native_queries: list[dict[str, Any]] = []
    missing_field_policies: list[dict[str, Any]] = []
    type_annotations: list[dict[str, Any]] = []
    table_keys: list[dict[str, Any]] = []
    fold_barriers: list[dict[str, Any]] = []
    group_by: list[str] = []
    aggregations: list[dict[str, Any]] = []
    renames: list[dict[str, str]] = []
    order_by: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    transforms: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    record_fields_by_step_column: dict[tuple[str, str], list[str]] = {}
    limit: int | None = None
    offset: int | None = None
    distinct = False
    pushdown_stopped_by: str | None = None
    schema_hints = schema_hints or {}

    supported_ops = {
        "source_file",
        "source_folder",
        "source_csv",
        "source_json",
        "source_parquet",
        "source_sql",
        "source_odbc",
        "source_odata",
        "source_web",
        "source_sharepoint",
        "navigation",
        "promote_headers",
        "demote_headers",
        "transform_column_types",
        "filter_rows",
        "select_columns",
        "remove_columns",
        "duplicate_column",
        "rename_columns",
        "reorder_columns",
        "transform_columns",
        "transform_column_names",
        "constant_table",
        "constant_table_from_list",
        "distinct",
        "sort",
        "limit_first",
        "limit_last",
        "skip",
        "remove_first",
        "remove_last",
        "range",
        "add_column",
        "add_index_column",
        "append",
        "join",
        "join_nested",
        "expand_table_column",
        "aggregate_table_column",
        "expand_record_column",
        "expand_list_column",
        "replace_value",
        "replace_errors",
        "remove_rows_with_errors",
        "native_query",
        "type_annotation",
        "table_key",
        "fold_barrier",
        "group",
        "fill_down",
        "fill_up",
        "unpivot",
        "unpivot_other_columns",
        "pivot",
        "split_column",
        "combine_columns",
        "helper_definition",
        "expression",
    }

    def remember_relation(step: str, base_ref: str, operation: Mapping[str, Any] | None = None) -> None:
        base_source = relation_sources_by_step.get(base_ref)
        if base_source is None:
            return
        base_operations = list(operations_by_step.get(base_ref, []))
        relation_sources_by_step[step] = dict(base_source)
        operations_by_step[step] = base_operations + ([dict(operation)] if operation else [])
        for (source_step, column), fields in list(record_fields_by_step_column.items()):
            if source_step == base_ref:
                record_fields_by_step_column[(step, column)] = list(fields)

    for node in ir_nodes:
        op = str(node.get("op") or "")
        step_id = _node_id(node)
        args = _args(node)
        base_ref = str(args.get("source_ref") or "")
        transforms.append({"id": node.get("id"), "step_id": step_id, "op": op})
        if pushdown_stopped_by and op not in {"type_annotation", "table_key", "fold_barrier"}:
            blockers.append(
                {
                    "step_id": step_id,
                    "reason": f"SQL pushdown is stopped after {pushdown_stopped_by}; execute this step with the local evaluator.",
                }
            )

        if op == "helper_definition":
            operations.append({"op": "helper_definition", "step_id": step_id})
        elif op == "expression":
            functions = {str(item) for item in node.get("functions") or [] if str(item)}
            if functions and functions.issubset({"List.Distinct", "List.Buffer", "Record.FieldNames", "Table.Column", "Table.ColumnNames"}):
                operations.append({"op": "expression_metadata", "step_id": step_id, "functions": sorted(functions)})
            else:
                blockers.append({"step_id": step_id, "reason": "Relational AST lowering is not implemented for this scalar/list expression"})
        elif op == "source_file":
            src = {"kind": "file", "path": args.get("path")}
            sources_by_step[step_id] = src
        elif op == "source_folder":
            folder = {
                "kind": "folder_inventory",
                "path": args.get("path"),
                "mode": args.get("mode") or "files",
                "recursive": bool(args.get("recursive")),
                "include_folders": bool(args.get("include_folders")),
            }
            source = folder
            sources_by_step[step_id] = folder
            relation_sources_by_step[step_id] = folder
            operations_by_step[step_id] = []
            folder_sources.append({"step_id": step_id, **folder})
            projection = _projection_from_columns([
                "Content",
                "Name",
                "Extension",
                "Date accessed",
                "Date modified",
                "Date created",
                "Attributes",
                "Folder Path",
            ])
            blockers.append(
                {
                    "step_id": step_id,
                    "reason": "Folder inventory previews locally; SQL pushdown/combine-file helper execution is not implemented yet.",
                }
            )
            pushdown_stopped_by = f"Folder.{str(args.get('mode') or 'files').title()} ({step_id})"
        elif op in {"source_csv", "source_parquet", "source_json"}:
            ref = str(args.get("source_ref") or "")
            base = sources_by_step.get(ref, {})
            source = {
                "kind": "file_scan",
                "format": "csv" if op == "source_csv" else "parquet" if op == "source_parquet" else "json",
                "path": base.get("path") or args.get("path"),
                "source_ref": ref or None,
            }
            if op == "source_csv" and isinstance(args.get("csv_options"), Mapping):
                source["csv_options"] = dict(args.get("csv_options") or {})
            sources_by_step[step_id] = source
            scan_sources_by_step[step_id] = source
            relation_sources_by_step[step_id] = source
            operations_by_step[step_id] = []
            hinted_projection = _projection_from_schema_hint(schema_hints, step_id)
            if hinted_projection is not None:
                projection = hinted_projection
        elif op in {"source_sql", "source_odbc", "source_odata", "source_web", "source_sharepoint"}:
            function = str(node.get("m_operation") or "")
            connector = {
                "kind": "connector",
                "operation": op,
                "function": function,
                "step_id": step_id,
                "server": args.get("server"),
                "database": args.get("database"),
                "dsn": args.get("dsn"),
                "url": args.get("url") or args.get("path"),
                "path": args.get("path"),
            }
            source = connector
            sources_by_step[step_id] = connector
            relation_sources_by_step[step_id] = connector
            operations_by_step[step_id] = []
            hinted_projection = _projection_from_schema_hint(schema_hints, step_id)
            if hinted_projection is not None:
                projection = hinted_projection
            blockers.append(
                {
                    "step_id": step_id,
                    "reason": "Connector source requires connector-native folding; DuckDB SQL emission is blocked for this source.",
                }
            )
        elif op in {"constant_table", "constant_table_from_list"}:
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            rows = [list(row) if isinstance(row, list) else [row] for row in args.get("rows") or []]
            if columns and all(len(row) == len(columns) for row in rows):
                source = {"kind": "constant_table", "columns": columns, "rows": rows}
                constant_tables.append({"step_id": step_id, "columns": columns, "row_count": len(rows)})
                sources_by_step[step_id] = source
                relation_sources_by_step[step_id] = source
                operations_by_step[step_id] = []
                projection = _projection_from_columns(columns)
                for column, fields in _record_fields_from_rows(columns, rows).items():
                    record_fields_by_step_column[(step_id, column)] = fields
            else:
                blockers.append({"step_id": step_id, "reason": "constant_table needs scalar rows with a stable column list for relational lowering"})
        elif op == "navigation":
            base_source = relation_sources_by_step.get(base_ref)
            if base_source:
                navigation_record = dict(args.get("navigation_record") or {}) if isinstance(args.get("navigation_record"), Mapping) else {}
                navigation_field = str(args.get("navigation_field") or "")
                navigated_source = dict(base_source)
                navigated_source["navigation"] = navigation_record
                if navigation_field:
                    navigated_source["navigation_field"] = navigation_field
                entity = navigation_record.get("Name") or navigation_record.get("Entity") or navigation_record.get("Item")
                if entity:
                    navigated_source["entity"] = str(entity)
                source = navigated_source
                sources_by_step[step_id] = navigated_source
                relation_sources_by_step[step_id] = navigated_source
                operation = {
                    "op": "navigation",
                    "step_id": step_id,
                    "source_ref": base_ref,
                    "record": navigation_record,
                    "field": navigation_field or None,
                }
                operations.append(operation)
                operations_by_step[step_id] = list(operations_by_step.get(base_ref, [])) + [operation]
                hinted_projection = _projection_from_schema_hint(schema_hints, step_id)
                if hinted_projection is not None:
                    projection = hinted_projection
            else:
                blockers.append({"step_id": step_id, "reason": "navigation needs a known source relation before relational lowering"})
        elif op == "transform_column_types":
            step_casts: list[dict[str, Any]] = []
            culture = str(args.get("culture") or "")
            for change in args.get("type_changes") or []:
                if isinstance(change, Mapping):
                    item = {"column": change.get("column"), "type": change.get("type")}
                    if culture:
                        item["culture"] = culture
                    step_casts.append(item)
            casts.extend(step_casts)
            if step_casts:
                operation = {"op": "cast", "step_id": step_id, "casts": step_casts}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "promote_headers":
            base_source = relation_sources_by_step.get(base_ref)
            if isinstance(base_source, Mapping) and str(base_source.get("kind") or "") == "file_scan" and str(base_source.get("format") or "") == "csv":
                promoted_source = dict(base_source)
                options = dict(promoted_source.get("csv_options") or {})
                options["header"] = True
                promoted_source["csv_options"] = options
                source = promoted_source
                sources_by_step[step_id] = promoted_source
                relation_sources_by_step[step_id] = promoted_source
                operations_by_step[step_id] = list(operations_by_step.get(base_ref, []))
                header_operations.append({"op": "promote_headers", "step_id": step_id, "mode": "csv_header"})
            elif isinstance(base_source, Mapping) and str(base_source.get("kind") or "") == "constant_table":
                promoted_source = _promoted_constant_source(base_source)
                if promoted_source is not None:
                    source = promoted_source
                    sources_by_step[step_id] = promoted_source
                    relation_sources_by_step[step_id] = promoted_source
                    operations_by_step[step_id] = list(operations_by_step.get(base_ref, []))
                    projection = _projection_from_columns([str(column) for column in promoted_source.get("columns") or []])
                    header_operations.append({"op": "promote_headers", "step_id": step_id, "mode": "constant_first_row"})
                else:
                    blockers.append({"step_id": step_id, "reason": "promote_headers over constant tables needs a non-empty unique scalar first row"})
            else:
                blockers.append({"step_id": step_id, "reason": "promote_headers pushdown needs a direct CSV scan or known constant table"})
        elif op == "demote_headers":
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            columns = _demoted_columns(projection)
            if columns:
                output_columns = [f"Column{index}" for index in range(1, len(columns) + 1)]
                operation = {"op": "demote_headers", "step_id": step_id, "columns": columns, "output_columns": output_columns}
                operations.append(operation)
                header_operations.append(operation)
                projection = _projection_from_columns(output_columns)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "demote_headers pushdown needs a known projection"})
        elif op == "filter_rows":
            predicate = str(args.get("predicate") or "")
            if predicate and _is_simple_row_expression(predicate):
                filt = {"expression": predicate, "language": "m_row_expression"}
                filters.append(filt)
                operation = {"op": "filter", "step_id": step_id, **filt}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            elif predicate:
                blockers.append({"step_id": step_id, "reason": "filter_rows predicate contains M syntax/functions that are not safe for DuckDB SQL lowering"})
        elif op == "select_columns":
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            missing_field = str(args.get("missing_field") or "")
            if missing_field:
                missing_field_policies.append({"step_id": step_id, "op": op, "mode": missing_field})
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            if missing_field and projection is None:
                blockers.append({"step_id": step_id, "reason": f"select_columns with MissingField.{missing_field} needs a known projection before SQL pushdown"})
            elif missing_field:
                next_projection: list[dict[str, Any]] = []
                for column in columns:
                    match = _projection_match(projection or [], column)
                    if match is not None:
                        next_projection.append(match)
                    elif missing_field == "use_null":
                        next_projection.append({"literal": None, "alias": column})
                    elif missing_field == "ignore":
                        continue
                    else:
                        blockers.append({"step_id": step_id, "reason": f"select_columns missing required column {column}"})
                projection = next_projection
                operation = {"op": "project", "step_id": step_id, "projection": projection, "missing_field": missing_field}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                projection = _projection_from_columns(columns)
                operation = {"op": "project", "step_id": step_id, "projection": projection}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "reorder_columns":
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            missing_field = str(args.get("missing_field") or "")
            if missing_field:
                missing_field_policies.append({"step_id": step_id, "op": op, "mode": missing_field})
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            if projection is not None:
                next_projection: list[dict[str, Any]] = []
                used: set[tuple[str, str]] = set()
                for column in columns:
                    match = _projection_match(projection, column)
                    if match is not None:
                        next_projection.append(match)
                        used.add((str(match.get("source") or ""), str(match.get("alias") or "")))
                    elif missing_field == "use_null":
                        next_projection.append({"literal": None, "alias": column})
                    elif missing_field == "ignore":
                        continue
                    else:
                        blockers.append({"step_id": step_id, "reason": f"reorder_columns missing required column {column}"})
                for item in projection:
                    key = (str(item.get("source") or ""), str(item.get("alias") or ""))
                    if key not in used:
                        next_projection.append(dict(item))
                projection = next_projection
                operation = {"op": "project", "step_id": step_id, "projection": projection, "missing_field": missing_field or None}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            elif missing_field:
                blockers.append({"step_id": step_id, "reason": f"reorder_columns with MissingField.{missing_field} needs a known projection before SQL pushdown"})
            elif columns:
                operation = {"op": "reorder_columns", "step_id": step_id, "columns": columns}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "remove_columns":
            removed = {str(column) for column in args.get("columns") or []}
            missing_field = str(args.get("missing_field") or "")
            if missing_field:
                missing_field_policies.append({"step_id": step_id, "op": op, "mode": missing_field})
            removed_columns.extend(sorted(removed))
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            if projection is not None:
                existing = {
                    str(item.get("alias") or item.get("source") or "").strip().upper()
                    for item in projection
                }
                missing = [column for column in removed if column.strip().upper() not in existing]
                if missing and missing_field in {"", "error"}:
                    blockers.append({"step_id": step_id, "reason": f"remove_columns missing required column {missing[0]}"})
                projection = [item for item in projection if item.get("alias") not in removed and item.get("source") not in removed]
                operation = {"op": "project", "step_id": step_id, "projection": projection, "missing_field": missing_field or None}
            else:
                if missing_field:
                    blockers.append({"step_id": step_id, "reason": f"remove_columns with MissingField.{missing_field} needs a known projection before SQL pushdown"})
                operation = {"op": "remove_columns", "step_id": step_id, "columns": sorted(removed), "missing_field": missing_field or None}
            operations.append(operation)
            remember_relation(step_id, base_ref, operation)
        elif op == "duplicate_column":
            source_column = str(args.get("source_column") or "")
            new_column = str(args.get("new_column") or "")
            if source_column and new_column:
                duplicate = {"source_column": source_column, "new_column": new_column}
                duplicated_columns.append(duplicate)
                operation = {"op": "duplicate_column", "step_id": step_id, **duplicate}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
                if projection is not None:
                    projection.append({"source": new_column, "alias": new_column})
            else:
                blockers.append({"step_id": step_id, "reason": "duplicate_column needs source and target columns"})
        elif op == "rename_columns":
            step_renames = [
                {"from": str(item.get("from") or ""), "to": str(item.get("to") or "")}
                for item in args.get("renames") or []
                if isinstance(item, Mapping)
            ]
            renames.extend(step_renames)
            missing_field = str(args.get("missing_field") or "")
            if missing_field:
                missing_field_policies.append({"step_id": step_id, "op": op, "mode": missing_field})
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            existing = {
                str(item.get("alias") or item.get("source") or "").strip().upper()
                for item in projection or []
            }
            missing = [item for item in step_renames if str(item.get("from") or "").strip().upper() not in existing]
            projection = _apply_renames(projection, step_renames)
            if projection is not None:
                if missing and missing_field == "use_null":
                    projection.extend({"literal": None, "alias": str(item.get("to") or "")} for item in missing if str(item.get("to") or ""))
                elif missing and missing_field != "ignore":
                    blockers.append({"step_id": step_id, "reason": f"rename_columns missing required column {missing[0].get('from')}"})
                operation = {"op": "project", "step_id": step_id, "projection": projection, "missing_field": missing_field or None}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            elif missing_field:
                blockers.append({"step_id": step_id, "reason": f"rename_columns with MissingField.{missing_field} needs a known projection before SQL pushdown"})
        elif op == "transform_columns":
            step_transforms = [dict(item) for item in args.get("transforms") or [] if isinstance(item, Mapping)]
            unsupported = [
                item
                for item in step_transforms
                if not item.get("column") or not _is_simple_transform_expression(str(item.get("expression") or ""), str(item.get("column") or ""))
            ]
            if step_transforms and not unsupported:
                transformed_columns.extend(step_transforms)
                operation = {"op": "transform_columns", "step_id": step_id, "transforms": step_transforms}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            elif step_transforms:
                blockers.append({"step_id": step_id, "reason": "transform_columns needs deterministic row expressions for relational lowering"})
            else:
                blockers.append({"step_id": step_id, "reason": "transform_columns needs transform metadata"})
        elif op == "transform_column_names":
            expression = str(args.get("name_transform") or "")
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            next_projection = _apply_column_name_transform(projection, expression)
            if expression and next_projection is not None:
                changes = [
                    {
                        "from": item.get("alias") or item.get("source") or "",
                        "to": next_item.get("alias") or next_item.get("source") or "",
                    }
                    for item, next_item in zip(projection or [], next_projection, strict=False)
                ]
                column_name_transforms.append({"step_id": step_id, "expression": expression, "changes": changes})
                projection = next_projection
                operation = {"op": "project", "step_id": step_id, "projection": projection}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "transform_column_names needs a known projection and deterministic non-duplicating Text name transform"})
        elif op == "distinct":
            distinct = True
            operation = {"op": "distinct", "step_id": step_id}
            operations.append(operation)
            remember_relation(step_id, base_ref, operation)
        elif op == "sort":
            step_sort = [dict(item) for item in args.get("sort") or [] if isinstance(item, Mapping)]
            order_by.extend(step_sort)
            if step_sort:
                operation = {"op": "sort", "step_id": step_id, "order_by": step_sort}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "limit_first":
            if isinstance(args.get("count"), int):
                limit = int(args["count"])
                operation = {"op": "limit", "step_id": step_id, "limit": limit}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "limit_last":
            if isinstance(args.get("count"), int):
                operation = {"op": "limit_last", "step_id": step_id, "count": int(args["count"])}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "skip":
            if isinstance(args.get("count"), int):
                offset = int(args["count"])
                operation = {"op": "offset", "step_id": step_id, "offset": offset}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "remove_first":
            if isinstance(args.get("count"), int):
                offset = int(args["count"])
                operation = {"op": "offset", "step_id": step_id, "offset": offset}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "remove_last":
            if isinstance(args.get("count"), int):
                operation = {"op": "remove_last", "step_id": step_id, "count": int(args["count"])}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
        elif op == "range":
            if isinstance(args.get("offset"), int):
                offset = int(args["offset"])
            if isinstance(args.get("count"), int):
                limit = int(args["count"])
            operation = {"op": "range", "step_id": step_id, "offset": offset, "limit": limit}
            operations.append(operation)
            remember_relation(step_id, base_ref, operation)
        elif op == "add_column":
            row_expression = str(args.get("row_expression") or "")
            new_column = str(args.get("new_column") or "")
            if new_column and _is_simple_row_expression(row_expression):
                computed = {"name": new_column, "expression": row_expression, "language": "m_row_expression"}
                computed_columns.append(computed)
                operation = {"op": "add_column", "step_id": step_id, **computed}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
                if projection is not None:
                    projection.append({"source": new_column, "alias": new_column})
            else:
                blockers.append({"step_id": step_id, "reason": "add_column needs a simple row expression for relational lowering"})
        elif op == "add_index_column":
            new_column = str(args.get("new_column") or "")
            initial = int(args.get("initial") or 0)
            increment = int(args.get("increment") or 1)
            if new_column:
                index_column = {"new_column": new_column, "initial": initial, "increment": increment}
                index_columns.append(index_column)
                operation = {"op": "add_index_column", "step_id": step_id, **index_column}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
                if projection is not None:
                    projection.append({"source": new_column, "alias": new_column})
            else:
                blockers.append({"step_id": step_id, "reason": "add_index_column needs a target column name"})
        elif op in {"fill_down", "fill_up"}:
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            if columns:
                operation = {"op": op, "step_id": step_id, "columns": columns}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": f"{op} needs target columns"})
        elif op == "append":
            refs = [str(ref) for ref in args.get("source_refs") or [] if str(ref)]
            resolved_sources = [relation_sources_by_step.get(ref) for ref in refs]
            if refs and all(isinstance(item, Mapping) for item in resolved_sources):
                append_sources = [dict(item) for item in resolved_sources if isinstance(item, Mapping)]
                append_relations = [
                    {
                        "ref": ref,
                        "source": dict(source_item),
                        "operations": list(operations_by_step.get(ref, [])),
                    }
                    for ref, source_item in zip(refs, resolved_sources, strict=False)
                    if isinstance(source_item, Mapping)
                ]
                source = {"kind": "append", "sources": append_sources, "relations": append_relations}
                operation = {"op": "append", "step_id": step_id, "source_refs": refs, "sources": append_sources}
                operations = [operation]
                relation_sources_by_step[step_id] = source
                operations_by_step[step_id] = [operation]
            elif refs:
                unresolved = [ref for ref, item in zip(refs, resolved_sources, strict=False) if item is None]
                blockers.append(
                    {
                        "step_id": step_id,
                        "reason": f"append currently needs direct foldable file-scan refs; unresolved refs: {', '.join(unresolved)}",
                    }
                )
            else:
                blockers.append({"step_id": step_id, "reason": "append needs source refs"})
        elif op == "join":
            left_ref = str(args.get("left_ref") or "")
            right_ref = str(args.get("right_ref") or "")
            left = relation_sources_by_step.get(left_ref)
            right = relation_sources_by_step.get(right_ref)
            left_keys = [str(key) for key in args.get("left_keys") or [] if str(key)]
            right_keys = [str(key) for key in args.get("right_keys") or [] if str(key)]
            join_kind = _normalize_join_kind(str(args.get("join_kind") or "JoinKind.Inner"))
            if left and right and left_keys and right_keys and len(left_keys) == len(right_keys) and join_kind:
                join = {
                    "left_ref": left_ref,
                    "right_ref": right_ref,
                    "left": dict(left),
                    "right": dict(right),
                    "left_keys": left_keys,
                    "right_keys": right_keys,
                    "join_kind": join_kind,
                    "left_relation": {
                        "ref": left_ref,
                        "source": dict(left),
                        "operations": list(operations_by_step.get(left_ref, [])),
                    },
                    "right_relation": {
                        "ref": right_ref,
                        "source": dict(right),
                        "operations": list(operations_by_step.get(right_ref, [])),
                    },
                }
                joins.append(join)
                source = {"kind": "join", **join}
                operation = {"op": "join", "step_id": step_id, **join}
                operations = [operation]
                relation_sources_by_step[step_id] = source
                operations_by_step[step_id] = [operation]
            else:
                blockers.append(
                    {
                        "step_id": step_id,
                        "reason": "join currently needs direct foldable file-scan refs, equal key counts, and a supported join kind",
                    }
                )
        elif op == "join_nested":
            left_ref = str(args.get("left_ref") or "")
            right_ref = str(args.get("right_ref") or "")
            left = relation_sources_by_step.get(left_ref)
            right = relation_sources_by_step.get(right_ref)
            left_keys = [str(key) for key in args.get("left_keys") or [] if str(key)]
            right_keys = [str(key) for key in args.get("right_keys") or [] if str(key)]
            nested_column = str(args.get("nested_column") or "")
            join_kind = _normalize_join_kind(str(args.get("join_kind") or "JoinKind.LeftOuter"))
            if (
                left
                and right
                and left_keys
                and right_keys
                and len(left_keys) == len(right_keys)
                and nested_column
                and join_kind
            ):
                nested_join = {
                    "left_ref": left_ref,
                    "right_ref": right_ref,
                    "left": dict(left),
                    "right": dict(right),
                    "left_keys": left_keys,
                    "right_keys": right_keys,
                    "join_kind": join_kind,
                    "nested_column": nested_column,
                    "left_relation": {
                        "ref": left_ref,
                        "source": dict(left),
                        "operations": list(operations_by_step.get(left_ref, [])),
                    },
                    "right_relation": {
                        "ref": right_ref,
                        "source": dict(right),
                        "operations": list(operations_by_step.get(right_ref, [])),
                    },
                }
                source = {"kind": "nested_join", **nested_join}
                operation = {"op": "join_nested", "step_id": step_id, **nested_join}
                operations = [operation]
                relation_sources_by_step[step_id] = source
                operations_by_step[step_id] = [operation]
            else:
                blockers.append(
                    {
                        "step_id": step_id,
                        "reason": "join_nested currently needs foldable refs, equal key counts, a nested column, and a supported join kind",
                    }
                )
        elif op == "expand_table_column":
            nested_column = str(args.get("nested_column") or "")
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            output_columns = [str(column) for column in args.get("output_columns") or [] if str(column)] or columns
            base_source = relation_sources_by_step.get(base_ref)
            if (
                base_source
                and str(base_source.get("kind") or "") == "nested_join"
                and nested_column
                and nested_column == str(base_source.get("nested_column") or "")
                and columns
                and len(output_columns) == len(columns)
            ):
                expanded = {
                    **dict(base_source),
                    "columns": columns,
                    "output_columns": output_columns,
                }
                expanded_nested_joins.append(expanded)
                source = {**expanded, "kind": "expanded_nested_join"}
                operation = {"op": "expand_nested_join", "step_id": step_id, **expanded}
                operations = [operation]
                projection = None
                relation_sources_by_step[step_id] = source
                operations_by_step[step_id] = [operation]
            else:
                blockers.append({"step_id": step_id, "reason": "expand_table_column currently needs a preceding foldable nested join and explicit columns"})
        elif op == "aggregate_table_column":
            nested_column = str(args.get("nested_column") or args.get("column") or "")
            nested_aggs = [dict(item) for item in args.get("aggregations") or [] if isinstance(item, Mapping)]
            unsupported = [item for item in nested_aggs if not _is_supported_nested_aggregation(item)]
            base_source = relation_sources_by_step.get(base_ref)
            join_kind = str(base_source.get("join_kind") or "") if isinstance(base_source, Mapping) else ""
            if (
                base_source
                and str(base_source.get("kind") or "") == "nested_join"
                and nested_column
                and nested_column == str(base_source.get("nested_column") or "")
                and nested_aggs
                and not unsupported
                and join_kind in {"inner", "left", "left_anti", "right", "full"}
            ):
                aggregated = {
                    **dict(base_source),
                    "aggregations": nested_aggs,
                }
                aggregated_nested_joins.append(aggregated)
                source = {**aggregated, "kind": "aggregated_nested_join"}
                projection = None
                operation = {"op": "aggregate_nested_join", "step_id": step_id, **aggregated}
                operations = [operation]
                relation_sources_by_step[step_id] = source
                operations_by_step[step_id] = [operation]
            elif unsupported:
                blockers.append(
                    {
                        "step_id": step_id,
                        "reason": "aggregate_table_column pushdown supports only List.Sum/List.Min/List.Max/List.Average/List.Count/List.NonNullCount over one nested source column",
                    }
                )
            elif join_kind == "right_anti":
                blockers.append(
                    {
                        "step_id": step_id,
                        "reason": "aggregate_table_column pushdown over nested joins is only implemented for Inner, LeftOuter, RightOuter, FullOuter, and LeftAnti join kinds",
                    }
                )
            else:
                blockers.append(
                    {
                        "step_id": step_id,
                        "reason": "aggregate_table_column currently needs a preceding foldable nested join, matching nested column, and explicit aggregate specs",
                    }
                )
        elif op == "expand_record_column":
            record_column = str(args.get("record_column") or "")
            fields = [str(field) for field in args.get("fields") or [] if str(field)]
            fields_expression = str(args.get("fields_expression") or "")
            if not fields and fields_expression:
                fields = list(record_fields_by_step_column.get((base_ref, record_column), []))
            output_columns = [str(column) for column in args.get("output_columns") or [] if str(column)] or fields
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            if record_column and fields and len(output_columns) == len(fields):
                keep_columns = [
                    str(item.get("alias") or item.get("source") or "")
                    for item in projection or []
                    if str(item.get("alias") or item.get("source") or "") != record_column
                ]
                expanded = {
                    "record_column": record_column,
                    "fields": fields,
                    "output_columns": output_columns,
                    "keep_columns": keep_columns,
                }
                expanded_record_columns.append(expanded)
                projection = _projection_from_columns(keep_columns + output_columns) if keep_columns else projection
                operation = {"op": "expand_record_column", "step_id": step_id, **expanded}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "expand_record_column needs a record column plus matching field/output names"})
        elif op == "expand_list_column":
            list_column = str(args.get("list_column") or "")
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            current_columns = [str(item.get("alias") or item.get("source") or "") for item in projection or []]
            if list_column and list_column in current_columns:
                expanded = {"list_column": list_column, "output_columns": current_columns}
                expanded_list_columns.append(expanded)
                operation = {"op": "expand_list_column", "step_id": step_id, **expanded}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "expand_list_column needs a known projection containing the list column"})
        elif op in {"unpivot", "unpivot_other_columns"}:
            attribute_column = str(args.get("attribute_column") or "")
            value_column = str(args.get("value_column") or "")
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            if op == "unpivot":
                unpivot_columns = [str(column) for column in args.get("columns") or [] if str(column)]
                preserve_columns = [
                    str(item.get("alias") or item.get("source") or "")
                    for item in projection or []
                    if str(item.get("alias") or item.get("source") or "") not in set(unpivot_columns)
                ]
            else:
                preserve_columns = [str(column) for column in args.get("preserve_columns") or [] if str(column)]
                unpivot_columns = [
                    str(item.get("alias") or item.get("source") or "")
                    for item in projection or []
                    if str(item.get("alias") or item.get("source") or "") not in set(preserve_columns)
                ]
            if attribute_column and value_column and unpivot_columns:
                unpivot = {
                    "preserve_columns": preserve_columns,
                    "columns": unpivot_columns,
                    "attribute_column": attribute_column,
                    "value_column": value_column,
                }
                unpivots.append(unpivot)
                projection = _projection_from_columns(preserve_columns + [attribute_column, value_column])
                operation = {"op": "unpivot", "step_id": step_id, **unpivot}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": f"{op} needs target columns plus attribute/value names for relational lowering"})
        elif op == "pivot":
            values = [str(value) for value in args.get("values") or [] if str(value)]
            attribute_column = str(args.get("attribute_column") or "")
            value_column = str(args.get("value_column") or "")
            aggregation = str(args.get("aggregation") or "List.Sum")
            if projection is None:
                projection = _projection_from_schema_hints(schema_hints, base_ref, step_id)
            current_columns = [str(item.get("alias") or item.get("source") or "") for item in projection or []]
            values_expression = str(args.get("values_expression") or "")
            values_source = "literal"
            if not values and values_expression and unpivots:
                prior_unpivot = unpivots[-1]
                if (
                    attribute_column
                    and value_column
                    and attribute_column == str(prior_unpivot.get("attribute_column") or "")
                    and value_column == str(prior_unpivot.get("value_column") or "")
                ):
                    values = [str(item) for item in prior_unpivot.get("columns") or [] if str(item)]
                    values_source = "prior_unpivot"
            group_keys = [column for column in current_columns if column not in {attribute_column, value_column}]
            if values and attribute_column and value_column and aggregation in {"List.Sum", "List.Max", "List.Min", "List.Count"}:
                pivot = {
                    "values": values,
                    "attribute_column": attribute_column,
                    "value_column": value_column,
                    "aggregation": aggregation,
                    "group_keys": group_keys,
                }
                if values_source != "literal":
                    pivot["values_source"] = values_source
                pivots.append(pivot)
                projection = _projection_from_columns(group_keys + values)
                operation = {"op": "pivot", "step_id": step_id, **pivot}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "pivot needs literal values or values derived from a preceding known unpivot, attribute/value columns, and a supported aggregation for relational lowering"})
        elif op == "split_column":
            source_column = str(args.get("source_column") or "")
            delimiter = str(args.get("delimiter") or "")
            output_columns = [str(column) for column in args.get("output_columns") or [] if str(column)]
            if source_column and delimiter and output_columns:
                split = {"source_column": source_column, "delimiter": delimiter, "output_columns": output_columns}
                split_columns.append(split)
                existing_columns = [str(item.get("alias") or item.get("source") or "") for item in projection or []]
                if existing_columns:
                    projection = _projection_from_columns([column for column in existing_columns if column != source_column] + output_columns)
                operation = {"op": "split_column", "step_id": step_id, **split}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "split_column needs source column, delimiter, and output columns for relational lowering"})
        elif op == "combine_columns":
            source_columns = [str(column) for column in args.get("source_columns") or [] if str(column)]
            delimiter_value = args.get("delimiter")
            output_column = str(args.get("output_column") or "")
            if source_columns and delimiter_value is not None and output_column:
                combine = {
                    "source_columns": source_columns,
                    "delimiter": str(delimiter_value),
                    "output_column": output_column,
                }
                existing_columns = [str(item.get("alias") or item.get("source") or "") for item in projection or []]
                if existing_columns:
                    missing = [column for column in source_columns if column not in existing_columns]
                    if missing:
                        blockers.append({"step_id": step_id, "reason": f"combine_columns missing required column {missing[0]}"})
                        continue
                    source_indexes = [existing_columns.index(column) for column in source_columns]
                    source_index_set = set(source_indexes)
                    insert_at = min(source_indexes)
                    result_columns: list[str] = []
                    for index, column in enumerate(existing_columns):
                        if index == insert_at:
                            result_columns.append(output_column)
                        if index not in source_index_set:
                            result_columns.append(column)
                    combine["result_columns"] = result_columns
                    projection = _projection_from_columns(result_columns)
                combined_columns.append(combine)
                operation = {"op": "combine_columns", "step_id": step_id, **combine}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "combine_columns needs source columns, a delimiter combiner, and an output column for relational lowering"})
        elif op == "replace_value":
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            replacer = str(args.get("replacer") or "")
            if columns and replacer in {"Replacer.ReplaceText", "Replacer.ReplaceValue"}:
                replacement = {
                    "columns": columns,
                    "old_value": args.get("old_value"),
                    "new_value": args.get("new_value"),
                    "replacer": replacer,
                }
                replacements.append(replacement)
                operation = {"op": "replace_value", "step_id": step_id, **replacement}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "replace_value needs supported replacer metadata and target columns"})
        elif op == "replace_errors":
            replacements_in = [dict(item) for item in args.get("replacements") or [] if isinstance(item, Mapping)]
            columns = [str(item.get("column") or "") for item in replacements_in if str(item.get("column") or "")]
            if replacements_in and _mark_latest_cast_try(operations, columns):
                operation = {"op": "replace_error_values", "step_id": step_id, "replacements": replacements_in}
                operations.append(operation)
                error_replacements.append(operation)
                remember_relation(step_id, base_ref, operation)
            elif replacements_in:
                blockers.append({"step_id": step_id, "reason": "replace_error_values SQL folding only supports errors introduced by a preceding foldable type cast"})
            else:
                blockers.append({"step_id": step_id, "reason": "replace_error_values needs replacement metadata"})
        elif op == "remove_rows_with_errors":
            columns = [str(column) for column in args.get("columns") or [] if str(column)]
            if not columns and casts:
                columns = [str(item.get("column") or "") for item in casts if isinstance(item, Mapping) and str(item.get("column") or "")]
            if columns and _mark_latest_cast_try(operations, columns):
                operation = {"op": "remove_rows_with_errors", "step_id": step_id, "columns": columns}
                operations.append(operation)
                error_row_filters.append(operation)
                remember_relation(step_id, base_ref, operation)
            elif columns:
                blockers.append({"step_id": step_id, "reason": "remove_rows_with_errors SQL folding only supports errors introduced by a preceding foldable type cast"})
            else:
                blockers.append({"step_id": step_id, "reason": "remove_rows_with_errors needs target columns or preceding cast metadata"})
        elif op == "native_query":
            native = {
                "target_ref": str(args.get("target_ref") or ""),
                "sql": str(args.get("sql") or ""),
                "parameters": dict(args.get("parameters") or {}) if isinstance(args.get("parameters"), Mapping) else {},
                "options": dict(args.get("options") or {}) if isinstance(args.get("options"), Mapping) else {},
            }
            native_queries.append(native)
            blockers.append(
                {
                    "step_id": step_id,
                    "reason": "Value.NativeQuery is preserved but requires approved connector execution and safe parameter binding before SQL pushdown.",
                }
            )
        elif op == "type_annotation":
            annotation = {
                "step_id": step_id,
                "type_expression": str(args.get("type_expression") or ""),
                "table_type_columns": [dict(item) for item in args.get("table_type_columns") or [] if isinstance(item, Mapping)],
            }
            type_annotations.append(annotation)
            operation = {"op": "type_annotation", **annotation}
            operations.append(operation)
            remember_relation(step_id, base_ref, operation)
        elif op == "table_key":
            key = {
                "step_id": step_id,
                "columns": [str(column) for column in args.get("columns") or [] if str(column)],
                "is_primary": bool(args.get("is_primary")),
            }
            table_keys.append(key)
            operation = {"op": "table_key", **key}
            operations.append(operation)
            remember_relation(step_id, base_ref, operation)
        elif op == "fold_barrier":
            barrier = {
                "step_id": step_id,
                "source_ref": base_ref or None,
                "operation": str(node.get("m_operation") or ""),
                "options": dict(args.get("options") or {}) if isinstance(args.get("options"), Mapping) else {},
            }
            fold_barriers.append(barrier)
            pushdown_stopped_by = f"{barrier['operation']} ({step_id})"
            blockers.append(
                {
                    "step_id": step_id,
                    "reason": f"{barrier['operation'] or 'Fold barrier'} is executable locally but intentionally stops SQL pushdown after this step.",
                }
            )
        elif op == "group":
            keys = [str(key) for key in args.get("keys") or [] if str(key)]
            group_aggs = [dict(item) for item in args.get("aggregations") or [] if isinstance(item, Mapping)]
            unsupported = [item for item in group_aggs if not _is_supported_group_aggregation(item)]
            if keys and group_aggs and not unsupported:
                group_by = keys
                aggregations = group_aggs
                projection = _projection_from_columns(keys) + [
                    {"source": str(item.get("name") or ""), "alias": str(item.get("name") or "")}
                    for item in group_aggs
                    if item.get("name")
                ]
                operation = {"op": "group", "step_id": step_id, "keys": keys, "aggregations": group_aggs}
                operations.append(operation)
                remember_relation(step_id, base_ref, operation)
            else:
                blockers.append({"step_id": step_id, "reason": "group needs keys and supported simple aggregations for relational lowering"})

        if op not in supported_ops:
            blockers.append({"step_id": step_id, "reason": f"Relational AST lowering is not implemented for {op}"})

    if source is None:
        blockers.append({"step_id": "", "reason": "No foldable relational source was detected"})

    status = "emit_candidate" if source and not blockers else "partial" if source else "no_source"
    return {
        "version": "pqrel.v1",
        "status": status,
        "source": source,
        "projection": projection,
        "filters": filters,
        "casts": casts,
        "computed_columns": computed_columns,
        "transformed_columns": transformed_columns,
        "column_name_transforms": column_name_transforms,
        "constant_tables": constant_tables,
        "folder_sources": folder_sources,
        "expanded_record_columns": expanded_record_columns,
        "expanded_list_columns": expanded_list_columns,
        "duplicated_columns": duplicated_columns,
        "index_columns": index_columns,
        "removed_columns": removed_columns,
        "append_sources": append_sources,
        "append_relations": append_relations,
        "joins": joins,
        "expanded_nested_joins": expanded_nested_joins,
        "aggregated_nested_joins": aggregated_nested_joins,
        "unpivots": unpivots,
        "pivots": pivots,
        "split_columns": split_columns,
        "combined_columns": combined_columns,
        "replacements": replacements,
        "error_replacements": error_replacements,
        "error_row_filters": error_row_filters,
        "header_operations": header_operations,
        "native_queries": native_queries,
        "missing_field_policies": missing_field_policies,
        "type_annotations": type_annotations,
        "table_keys": table_keys,
        "fold_barriers": fold_barriers,
        "group_by": group_by,
        "aggregations": aggregations,
        "renames": renames,
        "distinct": distinct,
        "order_by": order_by,
        "limit": limit,
        "offset": offset,
        "operations": operations,
        "transforms": transforms,
        "blockers": blockers,
    }
