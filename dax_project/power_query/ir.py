from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Mapping

from .model import MStep


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None and v != [] and v != {}}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _split_top_level_items(text: str, delimiter: str = ",") -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        elif ch == delimiter and depth == 0:
            item = text[start:i].strip()
            if item:
                items.append(item)
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return items


def _call_args(expression: str) -> list[str]:
    text = expression.strip()
    start = text.find("(")
    if start < 0:
        return []
    depth = 0
    in_string = False
    for i in range(start, len(text)):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return _split_top_level_items(text[start + 1 : i])
    return []


def _m_string(value: str) -> str | None:
    text = value.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('""', '"')
    return None


def _culture_arg(value: str) -> str | None:
    literal = _m_string(value)
    if literal:
        return literal
    match = re.search(r"\bCulture\s*=\s*(\"(?:\"\"|[^\"])*\")", value, flags=re.IGNORECASE)
    if match:
        return _m_string(match.group(1))
    return None


def _m_record_items(value: str) -> dict[str, str]:
    text = value.strip()
    if not text.startswith("[") or not text.endswith("]"):
        return {}
    body = text[1:-1]
    items: dict[str, str] = {}
    for item in _split_top_level_items(body):
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        items[key.strip().strip('"')] = raw_value.strip()
    return items


def _m_scalar(value: str) -> Any:
    text = value.strip()
    literal = _m_string(text)
    if literal is not None:
        return literal
    lowered = text.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _missing_field(value: str) -> str | None:
    text = value.strip()
    normalized = text.upper()
    if normalized in {"MISSINGFIELD.IGNORE", "IGNORE", "1"}:
        return "ignore"
    if normalized in {"MISSINGFIELD.USENULL", "USENULL", "USE_NULL", "2"}:
        return "use_null"
    if normalized in {"MISSINGFIELD.ERROR", "ERROR", "0"}:
        return "error"
    return None


def _native_query_parameters(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text or text.lower() == "null":
        return {"kind": "none", "count": 0}
    if text.startswith("[") and text.endswith("]"):
        items = _m_record_items(text)
        return {"kind": "record", "count": len(items), "keys": sorted(items)}
    if text.startswith("{") and text.endswith("}"):
        items = _split_top_level_items(text[1:-1])
        return {"kind": "list", "count": len(items)}
    return {"kind": "expression", "count": None}


def _native_query_options(value: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw_value in _m_record_items(value).items():
        out[key] = _m_scalar(raw_value)
    return out


def _navigation_record_items(expression: str) -> dict[str, Any]:
    match = re.search(r"\{\s*(\[(?:.|\n|\r)*?\])\s*\}", expression)
    if not match:
        return {}
    return {key: _m_scalar(raw_value) for key, raw_value in _m_record_items(match.group(1)).items()}


def _navigation_field(expression: str) -> str | None:
    match = re.search(r"\}\s*\[([^\]]+)\]\s*$", expression.strip())
    if match:
        return match.group(1).strip().strip('"')
    return None


def _csv_document_options(value: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw_value in _m_record_items(value).items():
        normalized = key.strip().lower()
        scalar = _m_scalar(raw_value)
        if normalized == "delimiter":
            out["delimiter"] = scalar
        elif normalized == "columns":
            out["columns"] = scalar
        elif normalized == "encoding":
            out["encoding"] = scalar
        elif normalized == "quotestyle":
            out["quote_style"] = str(raw_value).strip()
        elif normalized == "include?":
            out["include"] = scalar
        else:
            out[key] = scalar
    return out


def _m_ref(value: str) -> str | None:
    text = value.strip()
    if text.startswith('#"') and text.endswith('"'):
        return text[2:-1].replace('""', '"')
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", text):
        return text
    return None


def _leading_m_ref(value: str) -> str | None:
    text = value.strip()
    if text.startswith('#"'):
        end = text.find('"', 2)
        if end > 0:
            return text[2:end].replace('""', '"')
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", text)
    return match.group(1) if match else None


def _quoted_strings(text: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != '"':
            i += 1
            continue
        i += 1
        chars: list[str] = []
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if ch == '"' and nxt == '"':
                chars.append('"')
                i += 2
                continue
            if ch == '"':
                i += 1
                break
            chars.append(ch)
            i += 1
        out.append("".join(chars))
    return out


def _m_refs_from_list(text: str) -> list[str]:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    refs: list[str] = []
    for item in _split_top_level_items(stripped):
        ref = _m_ref(item)
        if ref:
            refs.append(ref)
    return refs


def _int_arg(value: str) -> int | None:
    text = value.strip()
    if re.match(r"^-?\d+$", text):
        return int(text)
    return None


def _pair_specs(text: str) -> list[list[str]]:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    pairs: list[list[str]] = []
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        strings = _quoted_strings(body)
        if strings:
            pairs.append(strings)
    return pairs


def _type_changes(text: str) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        parts = _split_top_level_items(body)
        if len(parts) < 2:
            continue
        name = _m_string(parts[0])
        if name:
            changes.append({"column": name, "type": parts[1].strip()})
    return changes


def _table_type_columns(text: str) -> list[dict[str, str]]:
    match = re.search(r"\btype\s+table\s*\[(.*)\]\s*$", text.strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    columns: list[dict[str, str]] = []
    for item in _split_top_level_items(match.group(1)):
        if "=" not in item:
            continue
        name, type_text = item.split("=", 1)
        column = name.strip().strip('"')
        if column:
            columns.append({"column": column, "type": type_text.strip()})
    return columns


def _sort_specs(text: str) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        parts = _split_top_level_items(body)
        if not parts:
            continue
        column = _m_string(parts[0])
        if not column:
            continue
        direction = "asc"
        if len(parts) > 1 and "DESC" in parts[1].upper():
            direction = "desc"
        specs.append({"column": column, "direction": direction})
    return specs


def _group_aggregations(text: str) -> list[dict[str, str]]:
    aggregations: list[dict[str, str]] = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        parts = _split_top_level_items(body)
        if len(parts) < 2:
            continue
        name = _m_string(parts[0])
        if not name:
            continue
        expression = _after_each(parts[1])
        aggregation: dict[str, str] = {"name": name, "expression": expression}
        function_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", expression)
        if function_match:
            aggregation["function"] = function_match.group(1)
            refs = re.findall(r"\[([^\]]+)\]", function_match.group(2))
            if refs:
                aggregation["source_column"] = refs[0]
        aggregations.append(aggregation)
    return aggregations


def _transform_column_specs(text: str) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        parts = _split_top_level_items(body)
        if len(parts) < 2:
            continue
        column = _m_string(parts[0])
        if not column:
            continue
        expression = parts[1].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", expression):
            expression = f"{expression}(_)"
        spec = {"column": column, "expression": _after_each(expression)}
        if len(parts) >= 3:
            spec["type"] = parts[2].strip()
        specs.append(spec)
    return specs


def _aggregate_table_column_specs(text: str) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        parts = _split_top_level_items(body)
        if len(parts) < 2:
            continue
        source_column = _m_string(parts[0])
        if not source_column:
            continue
        function = _after_each(parts[1])
        if function.endswith("(_)"):
            function = function[:-3].strip()
        name = _m_string(parts[2]) if len(parts) >= 3 else None
        specs.append(
            {
                "source_column": source_column,
                "function": function,
                "name": name or source_column,
            }
        )
    return specs


def _replace_error_specs(text: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    for item in _split_top_level_items(stripped):
        body = item.strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        parts = _split_top_level_items(body)
        if len(parts) < 2:
            continue
        column = _m_string(parts[0])
        if not column:
            continue
        specs.append({"column": column, "replacement": _m_scalar(parts[1])})
    return specs


def _splitter_delimiter(text: str) -> str | None:
    match = re.search(r"Splitter\.SplitTextByDelimiter\s*\(\s*(\"(?:\"\"|[^\"])*\")", text, flags=re.IGNORECASE)
    if not match:
        return None
    return _m_string(match.group(1))


def _combiner_delimiter(text: str) -> str | None:
    match = re.search(r"Combiner\.CombineTextByDelimiter\s*\(\s*(\"(?:\"\"|[^\"])*\")", text, flags=re.IGNORECASE)
    if not match:
        return None
    return _m_string(match.group(1))


def _after_each(value: str) -> str:
    return re.sub(r"^\s*each\s+", "", value.strip(), flags=re.IGNORECASE).strip()


def _constant_table_args(expression: str) -> dict[str, Any]:
    try:
        from .evaluator import _constant_table  # Local import keeps parser-only use lightweight.

        columns, rows = _constant_table(expression)
    except Exception:
        return {}
    names = [
        str(item.get("name") or "")
        for item in columns
        if isinstance(item, Mapping) and str(item.get("name") or "")
    ]
    clean_rows: list[list[Any]] = []
    for row in rows:
        values = list(row) if isinstance(row, list) else [row]
        clean_rows.append(values)
    if not names:
        return {}
    return {"columns": names, "rows": clean_rows}


def build_ir_args(operation: str, expression: str) -> dict[str, Any]:
    args: dict[str, Any] = {"m_expression": expression}
    call_args = _call_args(expression)
    if call_args:
        source_ref = _m_ref(call_args[0])
        if source_ref and not operation.startswith("source_") and operation != "helper_definition":
            args["source_ref"] = source_ref

    if operation in {"source_file", "source_folder", "source_web", "source_odata", "source_sharepoint"} and call_args:
        path = _m_string(call_args[0])
        if path is not None:
            args["path"] = path
            if operation == "source_odata":
                args["url"] = path
        if operation == "source_folder":
            args["mode"] = "contents" if re.search(r"\bFolder\.Contents\s*\(", expression, flags=re.IGNORECASE) else "files"
            args["recursive"] = args["mode"] == "files"
            args["include_folders"] = args["mode"] == "contents"
    elif operation == "source_odbc" and call_args:
        dsn = _m_string(call_args[0])
        if dsn is not None:
            args["dsn"] = dsn
    elif operation == "navigation":
        source_ref = _leading_m_ref(expression)
        if source_ref:
            args["source_ref"] = source_ref
        record = _navigation_record_items(expression)
        if record:
            args["navigation_record"] = record
        field = _navigation_field(expression)
        if field:
            args["navigation_field"] = field
    elif operation == "source_sql" and len(call_args) >= 2:
        server = _m_string(call_args[0])
        database = _m_string(call_args[1])
        if server is not None:
            args["server"] = server
        if database is not None:
            args["database"] = database
    elif operation in {"source_csv", "source_excel", "source_json", "source_xml", "source_parquet"} and call_args:
        ref = _m_ref(call_args[0])
        if ref:
            args["source_ref"] = ref
        if operation == "source_csv" and len(call_args) >= 2:
            options = _csv_document_options(call_args[1])
            if options:
                args["csv_options"] = options
    elif operation in {"select_columns", "remove_columns", "reorder_columns", "fill_down", "fill_up"} and len(call_args) >= 2:
        args["columns"] = _quoted_strings(call_args[1])
        if operation in {"select_columns", "remove_columns", "reorder_columns"} and len(call_args) >= 3:
            missing_field = _missing_field(call_args[2])
            if missing_field:
                args["missing_field"] = missing_field
    elif operation == "rename_columns" and len(call_args) >= 2:
        args["renames"] = [
            {"from": pair[0], "to": pair[1]}
            for pair in _pair_specs(call_args[1])
            if len(pair) >= 2
        ]
        if len(call_args) >= 3:
            missing_field = _missing_field(call_args[2])
            if missing_field:
                args["missing_field"] = missing_field
    elif operation == "transform_column_types" and len(call_args) >= 2:
        args["type_changes"] = _type_changes(call_args[1])
        if len(call_args) >= 3:
            culture = _culture_arg(call_args[2])
            if culture:
                args["culture"] = culture
    elif operation == "transform_columns" and len(call_args) >= 2:
        args["transforms"] = _transform_column_specs(call_args[1])
    elif operation == "native_query" and len(call_args) >= 2:
        target_ref = _m_ref(call_args[0])
        sql = _m_string(call_args[1])
        if target_ref:
            args["target_ref"] = target_ref
        if sql is not None:
            args["sql"] = sql
        if len(call_args) >= 3:
            args["parameters"] = _native_query_parameters(call_args[2])
        else:
            args["parameters"] = {"kind": "none", "count": 0}
        if len(call_args) >= 4:
            options = _native_query_options(call_args[3])
            if options:
                args["options"] = options
    elif operation == "type_annotation" and len(call_args) >= 2:
        args["type_expression"] = call_args[1].strip()
        table_type_columns = _table_type_columns(call_args[1])
        if table_type_columns:
            args["table_type_columns"] = table_type_columns
    elif operation == "table_key" and len(call_args) >= 3:
        args["columns"] = _quoted_strings(call_args[1])
        args["is_primary"] = bool(_m_scalar(call_args[2]))
    elif operation == "fold_barrier":
        if len(call_args) >= 2:
            options = _native_query_options(call_args[1])
            if options:
                args["options"] = options
    elif operation == "transform_column_names" and len(call_args) >= 2:
        args["name_transform"] = call_args[1].strip()
    elif operation == "filter_rows" and len(call_args) >= 2:
        args["predicate"] = _after_each(call_args[1])
    elif operation == "sort" and len(call_args) >= 2:
        args["sort"] = _sort_specs(call_args[1])
    elif operation in {"limit_first", "limit_last", "skip", "remove_first", "remove_last"} and len(call_args) >= 2:
        count = _int_arg(call_args[1])
        if count is not None:
            args["count"] = count
    elif operation == "range" and len(call_args) >= 3:
        offset = _int_arg(call_args[1])
        count = _int_arg(call_args[2])
        if offset is not None:
            args["offset"] = offset
        if count is not None:
            args["count"] = count
    elif operation == "add_column" and len(call_args) >= 3:
        new_column = _m_string(call_args[1])
        if new_column is not None:
            args["new_column"] = new_column
        args["row_expression"] = _after_each(call_args[2])
    elif operation == "duplicate_column" and len(call_args) >= 3:
        source_column = _m_string(call_args[1])
        new_column = _m_string(call_args[2])
        if source_column is not None:
            args["source_column"] = source_column
        if new_column is not None:
            args["new_column"] = new_column
    elif operation == "add_index_column" and len(call_args) >= 2:
        new_column = _m_string(call_args[1])
        if new_column is not None:
            args["new_column"] = new_column
        if len(call_args) >= 3:
            initial = _int_arg(call_args[2])
            if initial is not None:
                args["initial"] = initial
        if len(call_args) >= 4:
            increment = _int_arg(call_args[3])
            if increment is not None:
                args["increment"] = increment
    elif operation == "replace_value" and len(call_args) >= 5:
        args["old_value"] = _m_string(call_args[1]) if _m_string(call_args[1]) is not None else call_args[1].strip()
        args["new_value"] = _m_string(call_args[2]) if _m_string(call_args[2]) is not None else call_args[2].strip()
        args["replacer"] = call_args[3].strip()
        args["columns"] = _quoted_strings(call_args[4])
    elif operation == "replace_errors" and len(call_args) >= 2:
        args["replacements"] = _replace_error_specs(call_args[1])
    elif operation == "remove_rows_with_errors":
        if len(call_args) >= 2:
            args["columns"] = _quoted_strings(call_args[1])
    elif operation == "group" and len(call_args) >= 3:
        args["keys"] = _quoted_strings(call_args[1])
        args["aggregations"] = _group_aggregations(call_args[2])
    elif operation == "append" and call_args:
        refs = _m_refs_from_list(call_args[0])
        if refs:
            args["source_refs"] = refs
    elif operation == "unpivot" and len(call_args) >= 4:
        args["columns"] = _quoted_strings(call_args[1])
        attribute_column = _m_string(call_args[2])
        value_column = _m_string(call_args[3])
        if attribute_column is not None:
            args["attribute_column"] = attribute_column
        if value_column is not None:
            args["value_column"] = value_column
    elif operation == "unpivot_other_columns" and len(call_args) >= 4:
        args["preserve_columns"] = _quoted_strings(call_args[1])
        attribute_column = _m_string(call_args[2])
        value_column = _m_string(call_args[3])
        if attribute_column is not None:
            args["attribute_column"] = attribute_column
        if value_column is not None:
            args["value_column"] = value_column
    elif operation == "pivot" and len(call_args) >= 4:
        values_arg = call_args[1].strip()
        if values_arg.startswith("{") and values_arg.endswith("}"):
            args["values"] = _quoted_strings(values_arg)
        else:
            args["values"] = []
            args["values_expression"] = values_arg
        attribute_column = _m_string(call_args[2])
        value_column = _m_string(call_args[3])
        if attribute_column is not None:
            args["attribute_column"] = attribute_column
        if value_column is not None:
            args["value_column"] = value_column
        if len(call_args) >= 5:
            args["aggregation"] = call_args[4].strip()
    elif operation == "split_column" and len(call_args) >= 4:
        source_column = _m_string(call_args[1])
        delimiter = _splitter_delimiter(call_args[2])
        output_columns = _quoted_strings(call_args[3])
        if source_column is not None:
            args["source_column"] = source_column
        if delimiter is not None:
            args["delimiter"] = delimiter
        if output_columns:
            args["output_columns"] = output_columns
    elif operation == "combine_columns" and len(call_args) >= 4:
        source_columns = _quoted_strings(call_args[1])
        delimiter = _combiner_delimiter(call_args[2])
        output_column = _m_string(call_args[3])
        if source_columns:
            args["source_columns"] = source_columns
        if delimiter is not None:
            args["delimiter"] = delimiter
        if output_column is not None:
            args["output_column"] = output_column
    elif operation in {"join", "join_nested"} and len(call_args) >= 4:
        left = _m_ref(call_args[0])
        right = _m_ref(call_args[2])
        if left:
            args["left_ref"] = left
        if right:
            args["right_ref"] = right
        args["left_keys"] = _quoted_strings(call_args[1])
        args["right_keys"] = _quoted_strings(call_args[3])
        if operation == "join" and len(call_args) >= 5:
            args["join_kind"] = call_args[4].strip()
        if operation == "join_nested" and len(call_args) >= 5:
            nested = _m_string(call_args[4])
            if nested is not None:
                args["nested_column"] = nested
            if len(call_args) >= 6:
                args["join_kind"] = call_args[5].strip()
    elif operation == "aggregate_table_column" and len(call_args) >= 3:
        nested_column = _m_string(call_args[1])
        if nested_column is not None:
            args["nested_column"] = nested_column
        aggregations = _aggregate_table_column_specs(call_args[2])
        if aggregations:
            args["aggregations"] = aggregations
    elif operation == "expand_table_column" and len(call_args) >= 3:
        nested_column = _m_string(call_args[1])
        if nested_column is not None:
            args["nested_column"] = nested_column
        columns = _quoted_strings(call_args[2])
        args["columns"] = columns
        if not columns:
            args["columns_expression"] = call_args[2].strip()
        if len(call_args) >= 4:
            output_columns = _quoted_strings(call_args[3])
            if output_columns:
                args["output_columns"] = output_columns
            else:
                args["output_columns_expression"] = call_args[3].strip()
    elif operation == "expand_record_column" and len(call_args) >= 3:
        record_column = _m_string(call_args[1])
        if record_column is not None:
            args["record_column"] = record_column
        fields = _quoted_strings(call_args[2])
        args["fields"] = fields
        if not fields:
            args["fields_expression"] = call_args[2].strip()
        if len(call_args) >= 4:
            output_columns = _quoted_strings(call_args[3])
            if output_columns:
                args["output_columns"] = output_columns
            else:
                args["output_columns_expression"] = call_args[3].strip()
    elif operation == "expand_list_column" and len(call_args) >= 2:
        list_column = _m_string(call_args[1])
        if list_column is not None:
            args["list_column"] = list_column
    elif operation in {"constant_table", "constant_table_from_list"}:
        args.update(_constant_table_args(expression))
    return args


@dataclass(frozen=True)
class PQTransformIRNode:
    id: str
    op: str
    inputs: list[str] = field(default_factory=list)
    args: dict[str, Any] = field(default_factory=dict)
    m_step_id: str = ""
    m_operation: str = ""
    functions: list[str] = field(default_factory=list)
    foldable: bool = False
    execution_lane: str = "preserve_only"
    blockers: list[str] = field(default_factory=list)
    source_expression: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


def make_transform_ir_node(
    *,
    step: MStep,
    operation: str,
    foldable: bool,
    blockers: list[str],
) -> PQTransformIRNode:
    if foldable:
        lane = "pushdown_candidate"
    elif operation == "expression" or blockers:
        lane = "local_or_preserve"
    else:
        lane = "local_evaluator"
    return PQTransformIRNode(
        id=f"ir_{step.id}",
        op=operation,
        inputs=list(step.dependencies or []),
        args=build_ir_args(operation, step.expression),
        m_step_id=step.id,
        m_operation=step.operation,
        functions=list(step.functions or []),
        foldable=foldable,
        execution_lane=lane,
        blockers=list(blockers or []),
        source_expression=step.expression,
    )


def serialize_ir(nodes: list[PQTransformIRNode]) -> list[dict[str, Any]]:
    return [node.to_dict() for node in nodes]
