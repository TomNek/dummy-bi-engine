from __future__ import annotations

import re
from urllib.parse import urlencode
from typing import Any, Mapping, Sequence

from .execution_strategy import connector_capabilities_for_operation
from .expression_sql import m_row_expression_to_duckdb_sql


_SQL_LIKE_CONNECTORS = {"source_sql", "source_odbc"}
_ODATA_LIKE_CONNECTORS = {"source_odata"}
_REST_NAV_CONNECTORS = {"source_sharepoint", "source_web"}


def _split_top_level_boolean(expression: str, keyword: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_text = False
    i = 0
    lowered = expression.lower()
    token = f" {keyword.lower()} "
    while i < len(expression):
        ch = expression[i]
        if ch == '"':
            current.append(ch)
            if in_text and i + 1 < len(expression) and expression[i + 1] == '"':
                current.append(expression[i + 1])
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
            if depth == 0 and lowered.startswith(token, i):
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
                i += len(token)
                continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _strip_outer_parens(expression: str) -> str:
    text = expression.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        in_text = False
        balanced_outer = True
        for index, ch in enumerate(text):
            if ch == '"':
                in_text = not in_text
            if in_text:
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and index != len(text) - 1:
                    balanced_outer = False
                    break
        if not balanced_outer:
            break
        text = text[1:-1].strip()
    return text


def _odata_identifier(column: str) -> str:
    return "/".join(part.strip().replace(" ", "_x0020_") for part in str(column or "").split(".") if part.strip())


def _odata_literal(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return "'" + text[1:-1].replace('""', '"').replace("'", "''") + "'"
    lowered = text.lower()
    if lowered in {"true", "false", "null"}:
        return lowered
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return text
    raise ValueError(f"Unsupported OData literal: {value!r}")


def _odata_function_call(function: str, expression: str) -> str | None:
    # Use a stricter direct regex first so commas in surrounding expressions do not get swallowed.
    match = re.fullmatch(
        rf"{re.escape(function)}\s*\(\s*\[([^\]]+)\]\s*,\s*(\"(?:\"\"|[^\"])*\")\s*\)",
        expression.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    column = _odata_identifier(match.group(1))
    literal = _odata_literal(match.group(2))
    if function.lower() == "text.contains":
        return f"contains({column},{literal})"
    if function.lower() == "text.startswith":
        return f"startswith({column},{literal})"
    if function.lower() == "text.endswith":
        return f"endswith({column},{literal})"
    return None


def _m_row_expression_to_odata_filter(expression: str) -> str:
    expr = _strip_outer_parens(str(expression or "").strip())
    if expr.lower().startswith("each "):
        expr = expr[5:].strip()

    for keyword in ("or", "and"):
        parts = _split_top_level_boolean(expr, keyword)
        if len(parts) > 1:
            return f" {keyword} ".join(f"({_m_row_expression_to_odata_filter(part)})" for part in parts)

    if expr.lower().startswith("not "):
        return f"not ({_m_row_expression_to_odata_filter(expr[4:].strip())})"

    for function in ("Text.Contains", "Text.StartsWith", "Text.EndsWith"):
        rendered = _odata_function_call(function, expr)
        if rendered:
            return rendered

    match = re.fullmatch(r"\[([^\]]+)\]\s*(=|<>|>=|<=|>|<)\s*(.+)", expr, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Unsupported OData row expression: {expression!r}")
    operator_map = {"=": "eq", "<>": "ne", ">": "gt", ">=": "ge", "<": "lt", "<=": "le"}
    column = _odata_identifier(match.group(1))
    operator = operator_map[match.group(2)]
    literal = _odata_literal(match.group(3))
    return f"{column} {operator} {literal}"


def _connector_source(relational_ast: Mapping[str, Any]) -> Mapping[str, Any] | None:
    source = relational_ast.get("source")
    if isinstance(source, Mapping) and str(source.get("kind") or "") == "connector":
        return source
    return None


def _project_columns(operations: Sequence[Mapping[str, Any]], projection: Sequence[Mapping[str, Any]] | None) -> list[str]:
    for operation in reversed(list(operations)):
        if str(operation.get("op") or "") != "project":
            continue
        cols = [
            str(item.get("alias") or item.get("source") or "")
            for item in operation.get("projection") or []
            if isinstance(item, Mapping) and str(item.get("alias") or item.get("source") or "")
        ]
        if cols:
            return cols
    return [
        str(item.get("alias") or item.get("source") or "")
        for item in projection or []
        if isinstance(item, Mapping) and str(item.get("alias") or item.get("source") or "")
    ]


def _odata_query_options(relational_ast: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    operations = [dict(item) for item in relational_ast.get("operations") or [] if isinstance(item, Mapping)]
    blockers: list[dict[str, Any]] = []
    options: dict[str, Any] = {}
    if relational_ast.get("group_by") or relational_ast.get("aggregations"):
        blockers.append(
            {
                "step_id": "",
                "reason": "OData aggregation folding is not enabled until the adapter declares and tests $apply/groupby support.",
            }
        )
    columns = _project_columns(operations, relational_ast.get("projection") if isinstance(relational_ast.get("projection"), list) else None)
    if columns:
        options["$select"] = ",".join(columns)
    order_by = [
        f"{item.get('column')} {'desc' if str(item.get('direction') or '').lower() == 'desc' else 'asc'}"
        for item in relational_ast.get("order_by") or []
        if isinstance(item, Mapping) and item.get("column")
    ]
    if order_by:
        options["$orderby"] = ",".join(order_by)
    if relational_ast.get("limit") is not None:
        options["$top"] = int(relational_ast.get("limit") or 0)
    filters = [dict(item) for item in relational_ast.get("filters") or [] if isinstance(item, Mapping)]
    rendered_filters: list[str] = []
    for item in filters:
        try:
            rendered_filters.append(_m_row_expression_to_odata_filter(str(item.get("expression") or "")))
        except Exception:
            blockers.append(
                {
                    "step_id": item.get("step_id"),
                    "reason": "OData filter folding supports only simple comparisons, boolean/null/text/number literals, and selected Text predicates.",
                }
            )
    if rendered_filters:
        options["$filter"] = rendered_filters[0] if len(rendered_filters) == 1 else " and ".join(f"({item})" for item in rendered_filters)
    return options, blockers


def _sql_like_aggregation_sql(item: Mapping[str, Any]) -> str | None:
    name = str(item.get("name") or "")
    function = str(item.get("function") or "")
    column = str(item.get("source_column") or "")
    if not name:
        return None
    if function == "Table.RowCount":
        return f'COUNT(*) AS "{name}"'
    if not column:
        return None
    source_sql = f'"{column}"'
    if function == "List.Sum":
        return f'SUM({source_sql}) AS "{name}"'
    if function == "List.Min":
        return f'MIN({source_sql}) AS "{name}"'
    if function == "List.Max":
        return f'MAX({source_sql}) AS "{name}"'
    if function == "List.Average":
        return f'AVG({source_sql}) AS "{name}"'
    if function == "List.Count":
        return f'COUNT({source_sql}) AS "{name}"'
    if function == "List.NonNullCount":
        return f'COUNT({source_sql}) AS "{name}"'
    return None


def _sql_like_preview(relational_ast: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    operations = [dict(item) for item in relational_ast.get("operations") or [] if isinstance(item, Mapping)]
    blockers: list[dict[str, Any]] = []
    columns = _project_columns(operations, relational_ast.get("projection") if isinstance(relational_ast.get("projection"), list) else None)
    group_by = [str(item) for item in relational_ast.get("group_by") or [] if str(item)]
    aggregations = [dict(item) for item in relational_ast.get("aggregations") or [] if isinstance(item, Mapping)]
    aggregation_sql = [sql for sql in (_sql_like_aggregation_sql(item) for item in aggregations) if sql]
    if group_by and aggregations:
        if len(aggregation_sql) != len(aggregations):
            blockers.append(
                {
                    "step_id": "",
                    "reason": "SQL connector group-by folding supports only simple List.* aggregators and Table.RowCount.",
                }
            )
        select_items = [f'"{column}"' for column in group_by] + aggregation_sql
        select_sql = ", ".join(select_items) if select_items else "*"
    else:
        select_sql = ", ".join(f'"{column}"' for column in columns) if columns else "*"
    sql = f"SELECT {select_sql} FROM <bound table/navigation>"
    filters = [dict(item) for item in relational_ast.get("filters") or [] if isinstance(item, Mapping)]
    if filters:
        try:
            where = " AND ".join(m_row_expression_to_duckdb_sql(str(item.get("expression") or "")) for item in filters)
            sql += f" WHERE {where}"
        except Exception:
            blockers.append(
                {
                    "step_id": filters[0].get("step_id"),
                    "reason": "SQL connector filter folding needs a dialect-safe expression renderer for this predicate.",
                }
            )
    order_by = [
        f'"{item.get("column")}" {"DESC" if str(item.get("direction") or "").lower() == "desc" else "ASC"}'
        for item in relational_ast.get("order_by") or []
        if isinstance(item, Mapping) and item.get("column")
    ]
    if order_by:
        sql += " ORDER BY " + ", ".join(order_by)
    if relational_ast.get("limit") is not None:
        sql += f" LIMIT {int(relational_ast.get('limit') or 0)}"
    if group_by and aggregation_sql:
        group_sql = ", ".join(f'"{column}"' for column in group_by)
        marker = " ORDER BY " if " ORDER BY " in sql else " LIMIT " if " LIMIT " in sql else ""
        if marker:
            head, tail = sql.split(marker, 1)
            sql = f"{head} GROUP BY {group_sql}{marker}{tail}"
        else:
            sql += f" GROUP BY {group_sql}"
    return sql, blockers


def build_connector_native_plan(
    *,
    relational_ast: Mapping[str, Any],
    schema_probe: Mapping[str, Any],
    credential_profile_id: str | None = None,
    fixture_mode: bool = True,
    execution_target: str = "duckdb",
) -> dict[str, Any]:
    """Return connector-native fold candidates separate from DuckDB SQL.

    This is intentionally a preview/capability object. It never claims DuckDB
    can execute connector-native SQL/OData, and live mode still requires a
    bound profile before execution.
    """

    source = _connector_source(relational_ast)
    if not source:
        return {"status": "not_applicable", "plans": [], "blockers": []}

    operation = str(source.get("operation") or "")
    capabilities = connector_capabilities_for_operation(operation)
    blockers: list[dict[str, Any]] = []
    if not fixture_mode and not credential_profile_id:
        blockers.append(
            {
                "step_id": source.get("step_id"),
                "reason": "Live connector folding requires a credential profile before pushdown can execute.",
            }
        )

    plan: dict[str, Any] = {
        "source_step_id": source.get("step_id"),
        "operation": operation,
        "function": source.get("function"),
        "execution_target": execution_target,
        "credential_profile_id": credential_profile_id,
        "fixture_mode": fixture_mode,
        "capabilities_required": capabilities,
        "schema_probe_status": schema_probe.get("status"),
        "schema_columns": (schema_probe.get("resolved_columns_by_step") or {}).get(str(source.get("step_id") or ""), []),
        "navigation": dict(source.get("navigation") or {}) if isinstance(source.get("navigation"), Mapping) else {},
        "navigation_field": source.get("navigation_field"),
        "entity": source.get("entity"),
    }

    if operation in _ODATA_LIKE_CONNECTORS:
        options, option_blockers = _odata_query_options(relational_ast)
        blockers.extend(option_blockers)
        base_url = str(source.get("url") or "<odata-service>").rstrip("/")
        plan.update(
            {
                "native_kind": "odata",
                "query_options": options,
                "preview": f"{base_url}?{urlencode(options)}" if options else base_url,
            }
        )
    elif operation in _SQL_LIKE_CONNECTORS:
        sql, sql_blockers = _sql_like_preview(relational_ast)
        blockers.extend(sql_blockers)
        plan.update({"native_kind": "sql_like", "sql": sql, "dialect": "neutral_sql_like"})
    elif operation in _REST_NAV_CONNECTORS:
        columns = _project_columns(
            [dict(item) for item in relational_ast.get("operations") or [] if isinstance(item, Mapping)],
            relational_ast.get("projection") if isinstance(relational_ast.get("projection"), list) else None,
        )
        plan.update(
            {
                "native_kind": "rest_navigation",
                "projection": columns,
                "top": relational_ast.get("limit"),
            }
        )
    else:
        blockers.append(
            {
                "step_id": source.get("step_id"),
                "reason": f"Connector-native folding planner is not implemented for {operation}.",
            }
        )

    if blockers:
        status = "blocked_pending_profile" if not fixture_mode and not credential_profile_id else "partial"
    else:
        status = "candidate"
    return {"status": status, "plans": [plan], "blockers": blockers}
