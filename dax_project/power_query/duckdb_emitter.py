from __future__ import annotations

import re
from typing import Any, Mapping

from .expression_sql import m_row_expression_to_duckdb_sql, quote_duckdb_identifier, quote_duckdb_literal


def _quote_ident(name: str) -> str:
    return quote_duckdb_identifier(name)


def _quote_literal(value: Any) -> str:
    return quote_duckdb_literal(value)


def _quote_m_value_literal(value: Any) -> str:
    if isinstance(value, Mapping):
        parts = [
            f"{_quote_literal(str(key))}: {_quote_m_value_literal(item)}"
            for key, item in value.items()
        ]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_quote_m_value_literal(item) for item in value) + "]"
    return _quote_literal(value)


def _duckdb_type(m_type: str) -> str:
    value = (m_type or "").strip().lower()
    value = re.sub(r"\btype\s+nullable\s+", "type ", value)
    if value in {"type number", "number.type", "double.type", "type double"}:
        return "DOUBLE"
    if value in {"type text", "text.type"}:
        return "VARCHAR"
    if value in {"byte.type", "type byte"}:
        return "UTINYINT"
    if value in {"int8.type", "type int8"}:
        return "TINYINT"
    if value in {"int16.type", "type int16"}:
        return "SMALLINT"
    if value in {"int32.type", "type int32", "type integer", "integer.type"}:
        return "INTEGER"
    if value in {"int64.type", "type int64"}:
        return "BIGINT"
    if value in {"decimal.type", "type decimal"}:
        return "DECIMAL(38,10)"
    if value in {"currency.type", "type currency"}:
        return "DECIMAL(19,4)"
    if value in {"percentage.type", "type percentage"}:
        return "DOUBLE"
    if value in {"single.type", "type single"}:
        return "FLOAT"
    if value in {"type date", "date.type"}:
        return "DATE"
    if value in {"type datetime", "datetime.type"}:
        return "TIMESTAMP"
    if value in {"type time", "time.type"}:
        return "TIME"
    if value in {"type logical", "logical.type", "type boolean", "boolean.type"}:
        return "BOOLEAN"
    return "VARCHAR"


def _culture_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _culture_number_cast_sql(column: str, culture: str) -> str:
    ident = _quote_ident(column)
    value = f"CAST({ident} AS VARCHAR)"
    if culture.startswith(("de", "fr", "it", "es", "pt")):
        return f"CAST(replace(replace(replace({value}, ' ', ''), '.', ''), ',', '.') AS DOUBLE)"
    if culture.startswith("en"):
        return f"CAST(replace({value}, ',', '') AS DOUBLE)"
    return f"CAST({ident} AS DOUBLE)"


def _culture_date_cast_sql(column: str, culture: str, *, timestamp: bool = False) -> str:
    ident = _quote_ident(column)
    value = f"CAST({ident} AS VARCHAR)"
    if culture.startswith(("de", "fr", "it", "es", "pt")):
        fmt = "%d.%m.%Y %H:%M:%S" if timestamp else "%d.%m.%Y"
        expr = f"strptime({value}, {_quote_literal(fmt)})"
        return expr if timestamp else f"CAST({expr} AS DATE)"
    if culture.startswith("en"):
        fmt = "%m/%d/%Y %H:%M:%S" if timestamp else "%m/%d/%Y"
        expr = f"strptime({value}, {_quote_literal(fmt)})"
        return expr if timestamp else f"CAST({expr} AS DATE)"
    return f"CAST({ident} AS {'TIMESTAMP' if timestamp else 'DATE'})"


def _cast_sql(cast: Mapping[str, Any], *, try_cast: bool = False) -> str | None:
    column = str(cast.get("column") or "")
    if not column:
        return None
    culture = _culture_key(cast.get("culture"))
    target_type = _duckdb_type(str(cast.get("type") or ""))
    ident = _quote_ident(column)
    if culture and target_type == "DOUBLE":
        expr = _culture_number_cast_sql(column, culture)
    elif culture and target_type == "DATE":
        expr = _culture_date_cast_sql(column, culture)
    elif culture and target_type == "TIMESTAMP":
        expr = _culture_date_cast_sql(column, culture, timestamp=True)
    elif try_cast:
        expr = f"TRY_CAST({ident} AS {target_type})"
    else:
        expr = f"CAST({ident} AS {target_type})"
    return f"{expr} AS {ident}"


def _cast_error_flag_sql(cast: Mapping[str, Any]) -> str | None:
    column = str(cast.get("column") or "")
    if not column:
        return None
    culture = _culture_key(cast.get("culture"))
    target_type = _duckdb_type(str(cast.get("type") or ""))
    ident = _quote_ident(column)
    if culture and target_type == "DOUBLE":
        expr = _culture_number_cast_sql(column, culture).replace("CAST(", "TRY_CAST(", 1)
    elif culture and target_type in {"DATE", "TIMESTAMP"}:
        expr = f"TRY_CAST({ident} AS {target_type})"
    else:
        expr = f"TRY_CAST({ident} AS {target_type})"
    return f"({ident} IS NOT NULL AND {expr} IS NULL) AS {_quote_ident('__pq_error_' + column)}"


def _m_row_expression_to_sql(expression: str, *, current_column: str | None = None) -> str:
    return m_row_expression_to_duckdb_sql(expression, current_column=current_column)


def _projection_sql(projection: list[Any]) -> str:
    parts: list[str] = []
    for item in projection:
        if not isinstance(item, Mapping):
            continue
        if "literal" in item:
            alias = str(item.get("alias") or "")
            if alias:
                parts.append(f"{_quote_literal(item.get('literal'))} AS {_quote_ident(alias)}")
            continue
        source_col = str(item.get("source") or "")
        alias = str(item.get("alias") or source_col)
        if source_col:
            parts.append(f"{_quote_ident(source_col)} AS {_quote_ident(alias)}")
    return ", ".join(parts) if parts else "*"


def _replacement_sql(item: Mapping[str, Any]) -> list[str]:
    replacer = str(item.get("replacer") or "")
    old_value = item.get("old_value")
    new_value = item.get("new_value")
    parts: list[str] = []
    for column in item.get("columns") or []:
        col = str(column)
        if not col:
            continue
        ident = _quote_ident(col)
        if replacer == "Replacer.ReplaceText":
            expr = f"replace(CAST({ident} AS VARCHAR), {_quote_literal(old_value)}, {_quote_literal(new_value)})"
        else:
            expr = f"CASE WHEN {ident} = {_quote_literal(old_value)} THEN {_quote_literal(new_value)} ELSE {ident} END"
        parts.append(f"{expr} AS {ident}")
    return parts


def _transform_columns_sql(items: list[Mapping[str, Any]]) -> list[str]:
    parts: list[str] = []
    for item in items:
        column = str(item.get("column") or "")
        expression = str(item.get("expression") or "")
        if not column or not expression:
            continue
        parts.append(f"({_m_row_expression_to_sql(expression, current_column=column)}) AS {_quote_ident(column)}")
    return parts


def _expand_record_sql(item: Mapping[str, Any]) -> str:
    record_column = str(item.get("record_column") or "")
    fields = [str(field) for field in item.get("fields") or [] if str(field)]
    output_columns = [str(column) for column in item.get("output_columns") or [] if str(column)]
    keep_columns = [str(column) for column in item.get("keep_columns") or [] if str(column)]
    if not output_columns:
        output_columns = fields
    parts = [_quote_ident(column) for column in keep_columns]
    parts.extend(
        f"struct_extract({_quote_ident(record_column)}, {_quote_literal(field)}) AS {_quote_ident(alias)}"
        for field, alias in zip(fields, output_columns, strict=False)
    )
    if parts:
        return ", ".join(parts)
    expanded = [
        f"struct_extract({_quote_ident(record_column)}, {_quote_literal(field)}) AS {_quote_ident(alias)}"
        for field, alias in zip(fields, output_columns, strict=False)
    ]
    return f"* EXCLUDE ({_quote_ident(record_column)}), {', '.join(expanded)}"


def _expand_list_sql(item: Mapping[str, Any]) -> str:
    list_column = str(item.get("list_column") or "")
    output_columns = [str(column) for column in item.get("output_columns") or [] if str(column)]
    if output_columns:
        parts = []
        for column in output_columns:
            if column == list_column:
                list_expr = f"CASE WHEN {_quote_ident(column)} IS NULL OR len({_quote_ident(column)}) = 0 THEN [NULL] ELSE {_quote_ident(column)} END"
                parts.append(f"unnest({list_expr}) AS {_quote_ident(column)}")
            else:
                parts.append(_quote_ident(column))
        return ", ".join(parts)
    list_expr = f"CASE WHEN {_quote_ident(list_column)} IS NULL OR len({_quote_ident(list_column)}) = 0 THEN [NULL] ELSE {_quote_ident(list_column)} END"
    return f"* EXCLUDE ({_quote_ident(list_column)}), unnest({list_expr}) AS {_quote_ident(list_column)}"


def _aggregation_sql(item: Mapping[str, Any]) -> str | None:
    name = str(item.get("name") or "")
    function = str(item.get("function") or "")
    column = str(item.get("source_column") or "")
    if not name:
        return None
    if function == "Table.RowCount":
        expr = "COUNT(*)"
    elif function == "List.Sum" and column:
        expr = f"SUM({_quote_ident(column)})"
    elif function == "List.Min" and column:
        expr = f"MIN({_quote_ident(column)})"
    elif function == "List.Max" and column:
        expr = f"MAX({_quote_ident(column)})"
    elif function == "List.Average" and column:
        expr = f"AVG({_quote_ident(column)})"
    elif function == "List.Count" and column:
        expr = f"COUNT({_quote_ident(column)})"
    elif function == "List.NonNullCount" and column:
        expr = f"COUNT({_quote_ident(column)})"
    else:
        return None
    return f"{expr} AS {_quote_ident(name)}"


def _nested_aggregation_sql(item: Mapping[str, Any]) -> str | None:
    name = str(item.get("name") or "")
    function = str(item.get("function") or "")
    column = str(item.get("source_column") or "")
    if not name or not column:
        return None
    if function == "List.Sum":
        expr = f"SUM({_quote_ident(column)})"
    elif function == "List.Min":
        expr = f"MIN({_quote_ident(column)})"
    elif function == "List.Max":
        expr = f"MAX({_quote_ident(column)})"
    elif function == "List.Average":
        expr = f"AVG({_quote_ident(column)})"
    elif function == "List.Count":
        expr = "COUNT(*)"
    elif function == "List.NonNullCount":
        expr = f"COUNT({_quote_ident(column)})"
    else:
        return None
    return f"{expr} AS {_quote_ident(name)}"


def _nested_aggregation_default_sql(item: Mapping[str, Any]) -> str:
    name = str(item.get("name") or "")
    function = str(item.get("function") or "")
    default = "0" if function in {"List.Count", "List.NonNullCount"} else "NULL"
    return f"{default} AS {_quote_ident(name)}"


def _nested_aggregation_projection_sql(item: Mapping[str, Any]) -> str:
    name = str(item.get("name") or "")
    function = str(item.get("function") or "")
    ident = f"a.{_quote_ident(name)}"
    if function in {"List.Count", "List.NonNullCount"}:
        return f"COALESCE({ident}, 0) AS {_quote_ident(name)}"
    return f"{ident} AS {_quote_ident(name)}"


def _nested_singleton_aggregation_sql(item: Mapping[str, Any], prefix: str = "r") -> str | None:
    name = str(item.get("name") or "")
    function = str(item.get("function") or "")
    column = str(item.get("source_column") or "")
    if not name or not column:
        return None
    ident = f"{prefix}.{_quote_ident(column)}"
    if function in {"List.Sum", "List.Min", "List.Max", "List.Average"}:
        expr = ident
    elif function == "List.Count":
        expr = "1"
    elif function == "List.NonNullCount":
        expr = f"CASE WHEN {ident} IS NULL THEN 0 ELSE 1 END"
    else:
        return None
    return f"{expr} AS {_quote_ident(name)}"


def _pivot_aggregation_sql(function: str, value_expr: str) -> str:
    if function == "List.Max":
        return f"MAX({value_expr})"
    if function == "List.Min":
        return f"MIN({value_expr})"
    if function == "List.Count":
        return f"COUNT({value_expr})"
    return f"SUM({value_expr})"


def _combine_columns_expr(source_columns: list[str], delimiter: str) -> str:
    parts: list[str] = []
    for index, column in enumerate(source_columns):
        if index:
            parts.append(_quote_literal(delimiter))
        parts.append(f"COALESCE(CAST({_quote_ident(column)} AS VARCHAR), '')")
    return " || ".join(parts) if parts else "''"


def _constant_table_sql(source: Mapping[str, Any]) -> str | None:
    columns = [str(column) for column in source.get("columns") or [] if str(column)]
    rows = [list(row) if isinstance(row, list) else [row] for row in source.get("rows") or []]
    if not columns or not all(len(row) == len(columns) for row in rows):
        return None
    column_sql = ", ".join(_quote_ident(column) for column in columns)
    if not rows:
        empty_select = ", ".join(f"CAST(NULL AS VARCHAR) AS {_quote_ident(column)}" for column in columns)
        return f"(SELECT {empty_select} WHERE FALSE) AS v"
    value_rows = []
    for row in rows:
        value_rows.append("(" + ", ".join(_quote_m_value_literal(value) for value in row) + ")")
    return f"(VALUES {', '.join(value_rows)}) AS v({column_sql})"


def _source_scan_sql(source: Mapping[str, Any]) -> str | None:
    if str(source.get("kind") or "") == "constant_table":
        return _constant_table_sql(source)
    fmt = str(source.get("format") or "").lower()
    path = str(source.get("path") or "")
    if not path:
        return None
    if fmt == "csv":
        options = source.get("csv_options") if isinstance(source.get("csv_options"), Mapping) else {}
        option_sql: list[str] = []
        delimiter = options.get("delimiter")
        if delimiter is not None and str(delimiter) != "":
            option_sql.append(f"delim={_quote_literal(str(delimiter))}")
        if "header" in options:
            option_sql.append(f"header={'true' if bool(options.get('header')) else 'false'}")
        if str(options.get("quote_style") or "").strip().upper() == "QUOTESTYLE.NONE":
            option_sql.append("quote=''")
        columns = options.get("columns")
        if isinstance(columns, int) and columns > 0:
            col_spec = ", ".join(f"{_quote_literal(f'Column{index}')}:'VARCHAR'" for index in range(1, columns + 1))
            option_sql.append(f"columns={{{col_spec}}}")
            option_sql.append("auto_detect=false")
            return f"read_csv({_quote_literal(path)}, {', '.join(option_sql)})"
        if option_sql:
            return f"read_csv_auto({_quote_literal(path)}, {', '.join(option_sql)})"
        return f"read_csv_auto({_quote_literal(path)})"
    if fmt == "json":
        return f"read_json_auto({_quote_literal(path)})"
    if fmt == "parquet":
        return f"read_parquet({_quote_literal(path)})"
    return None


def _join_keyword(join_kind: str) -> str:
    value = join_kind.lower()
    if value == "left":
        return "LEFT JOIN"
    if value == "right":
        return "RIGHT JOIN"
    if value == "full":
        return "FULL OUTER JOIN"
    return "INNER JOIN"


def emit_duckdb_sql(relational_ast: Mapping[str, Any]) -> dict[str, Any]:
    """Emit preview DuckDB SQL from the neutral relational AST.

    This intentionally supports only the first foldable subset. Unsupported
    relational ASTs return blockers instead of fake SQL.
    """

    blockers = list(relational_ast.get("blockers") or [])
    source = relational_ast.get("source") if isinstance(relational_ast.get("source"), Mapping) else None
    if blockers or not source:
        return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": blockers}

    ctes: list[str] = []
    current = "source"
    cte_index = 0

    def add_cte(prefix: str, select_sql: str) -> str:
        nonlocal current, cte_index
        cte_index += 1
        name = f"{prefix}_{cte_index}"
        ctes.append(f"{name} AS ({select_sql})")
        current = name
        return name

    def scoped(prefix: str, name: str) -> str:
        return f"{prefix}_{name}" if prefix else name

    def apply_operation(operation: Mapping[str, Any], current_name: str, *, prefix: str = "") -> tuple[str, list[Mapping[str, Any]], int | None, int | None]:
        op = str(operation.get("op") or "")
        order_by: list[Mapping[str, Any]] = []
        limit_value: int | None = None
        offset_value: int | None = None
        if op in {"append", "join", "aggregate_nested_join"}:
            return current_name, order_by, limit_value, offset_value
        if op == "cast":
            replace_parts = []
            extra_parts = []
            try_columns = {str(column).upper() for column in operation.get("try_cast_columns") or []}
            for cast in operation.get("casts") or []:
                if not isinstance(cast, Mapping):
                    continue
                column = str(cast.get("column") or "")
                use_try = column.upper() in try_columns
                cast_sql = _cast_sql(cast, try_cast=use_try)
                if cast_sql:
                    replace_parts.append(cast_sql)
                if use_try:
                    flag_sql = _cast_error_flag_sql(cast)
                    if flag_sql:
                        extra_parts.append(flag_sql)
            if replace_parts:
                suffix = f", {', '.join(extra_parts)}" if extra_parts else ""
                current_name = add_cte(scoped(prefix, "typed"), f"SELECT * REPLACE ({', '.join(replace_parts)}){suffix} FROM {current_name}")
        elif op == "replace_value":
            replace_parts = _replacement_sql(operation)
            if replace_parts:
                current_name = add_cte(scoped(prefix, "replaced"), f"SELECT * REPLACE ({', '.join(replace_parts)}) FROM {current_name}")
        elif op == "transform_columns":
            replace_parts = _transform_columns_sql([item for item in operation.get("transforms") or [] if isinstance(item, Mapping)])
            if replace_parts:
                current_name = add_cte(scoped(prefix, "transformed"), f"SELECT * REPLACE ({', '.join(replace_parts)}) FROM {current_name}")
        elif op == "duplicate_column":
            source_column = str(operation.get("source_column") or "")
            new_column = str(operation.get("new_column") or "")
            if source_column and new_column:
                current_name = add_cte(scoped(prefix, "duplicated"), f"SELECT *, {_quote_ident(source_column)} AS {_quote_ident(new_column)} FROM {current_name}")
        elif op == "add_index_column":
            new_column = str(operation.get("new_column") or "")
            initial = int(operation.get("initial") or 0)
            increment = int(operation.get("increment") or 1)
            if new_column:
                expr = f"((row_number() OVER ()) - 1) * {increment} + {initial}"
                current_name = add_cte(scoped(prefix, "indexed"), f"SELECT *, ({expr}) AS {_quote_ident(new_column)} FROM {current_name}")
        elif op == "fill_down":
            parts = [
                f"last_value({_quote_ident(str(column))} IGNORE NULLS) OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS {_quote_ident(str(column))}"
                for column in operation.get("columns") or []
                if str(column)
            ]
            if parts:
                current_name = add_cte(scoped(prefix, "filled_down"), f"SELECT * REPLACE ({', '.join(parts)}) FROM {current_name}")
        elif op == "fill_up":
            parts = [
                f"first_value({_quote_ident(str(column))} IGNORE NULLS) OVER (ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING) AS {_quote_ident(str(column))}"
                for column in operation.get("columns") or []
                if str(column)
            ]
            if parts:
                current_name = add_cte(scoped(prefix, "filled_up"), f"SELECT * REPLACE ({', '.join(parts)}) FROM {current_name}")
        elif op == "add_column":
            name = str(operation.get("name") or "")
            expression = str(operation.get("expression") or "")
            if name and expression:
                current_name = add_cte(scoped(prefix, "computed"), f"SELECT *, ({_m_row_expression_to_sql(expression)}) AS {_quote_ident(name)} FROM {current_name}")
        elif op == "filter":
            expression = str(operation.get("expression") or "")
            if expression:
                current_name = add_cte(scoped(prefix, "filtered"), f"SELECT * FROM {current_name} WHERE {_m_row_expression_to_sql(expression)}")
        elif op == "project":
            projection = [item for item in operation.get("projection") or [] if isinstance(item, Mapping)]
            if projection:
                current_name = add_cte(scoped(prefix, "projected"), f"SELECT {_projection_sql(projection)} FROM {current_name}")
        elif op == "reorder_columns":
            columns = [str(column) for column in operation.get("columns") or [] if str(column)]
            if columns:
                first = ", ".join(_quote_ident(column) for column in columns)
                exclude = ", ".join(_quote_ident(column) for column in columns)
                current_name = add_cte(scoped(prefix, "reordered"), f"SELECT {first}, * EXCLUDE ({exclude}) FROM {current_name}")
        elif op == "remove_columns":
            columns = [str(column) for column in operation.get("columns") or [] if str(column)]
            if columns:
                exclude_sql = ", ".join(_quote_ident(column) for column in columns)
                current_name = add_cte(scoped(prefix, "removed"), f"SELECT * EXCLUDE ({exclude_sql}) FROM {current_name}")
        elif op == "distinct":
            current_name = add_cte(scoped(prefix, "distincted"), f"SELECT DISTINCT * FROM {current_name}")
        elif op == "group":
            keys = [str(key) for key in operation.get("keys") or [] if str(key)]
            aggs = [item for item in operation.get("aggregations") or [] if isinstance(item, Mapping)]
            select_parts = [_quote_ident(key) for key in keys]
            select_parts.extend(part for part in (_aggregation_sql(item) for item in aggs) if part)
            if keys and len(select_parts) > len(keys):
                group_sql = ", ".join(_quote_ident(key) for key in keys)
                current_name = add_cte(scoped(prefix, "grouped"), f"SELECT {', '.join(select_parts)} FROM {current_name} GROUP BY {group_sql}")
        elif op == "unpivot":
            preserve_columns = [str(column) for column in operation.get("preserve_columns") or [] if str(column)]
            unpivot_columns = [str(column) for column in operation.get("columns") or [] if str(column)]
            attribute_column = str(operation.get("attribute_column") or "")
            value_column = str(operation.get("value_column") or "")
            select_parts = [_quote_ident(column) for column in preserve_columns]
            if unpivot_columns and attribute_column and value_column:
                branches = []
                for column in unpivot_columns:
                    branch_parts = list(select_parts)
                    branch_parts.append(f"{_quote_literal(column)} AS {_quote_ident(attribute_column)}")
                    branch_parts.append(f"{_quote_ident(column)} AS {_quote_ident(value_column)}")
                    branches.append(f"SELECT {', '.join(branch_parts)} FROM {current_name}")
                current_name = add_cte(scoped(prefix, "unpivoted"), " UNION ALL ".join(branches))
        elif op == "pivot":
            values = [str(value) for value in operation.get("values") or [] if str(value)]
            group_keys = [str(column) for column in operation.get("group_keys") or [] if str(column)]
            attribute_column = str(operation.get("attribute_column") or "")
            value_column = str(operation.get("value_column") or "")
            aggregation = str(operation.get("aggregation") or "List.Sum")
            if values and attribute_column and value_column:
                select_parts = [_quote_ident(column) for column in group_keys]
                for value in values:
                    case_expr = f"CASE WHEN {_quote_ident(attribute_column)} = {_quote_literal(value)} THEN {_quote_ident(value_column)} ELSE NULL END"
                    select_parts.append(f"{_pivot_aggregation_sql(aggregation, case_expr)} AS {_quote_ident(value)}")
                group_sql = ", ".join(_quote_ident(column) for column in group_keys)
                group_clause = f" GROUP BY {group_sql}" if group_sql else ""
                current_name = add_cte(scoped(prefix, "pivoted"), f"SELECT {', '.join(select_parts)} FROM {current_name}{group_clause}")
        elif op == "split_column":
            source_column = str(operation.get("source_column") or "")
            delimiter = str(operation.get("delimiter") or "")
            output_columns = [str(column) for column in operation.get("output_columns") or [] if str(column)]
            if source_column and delimiter and output_columns:
                parts = [f"split_part(CAST({_quote_ident(source_column)} AS VARCHAR), {_quote_literal(delimiter)}, {index}) AS {_quote_ident(column)}" for index, column in enumerate(output_columns, start=1)]
                current_name = add_cte(scoped(prefix, "split"), f"SELECT * EXCLUDE ({_quote_ident(source_column)}), {', '.join(parts)} FROM {current_name}")
        elif op == "combine_columns":
            source_columns = [str(column) for column in operation.get("source_columns") or [] if str(column)]
            output_column = str(operation.get("output_column") or "")
            if source_columns and output_column:
                expr = _combine_columns_expr(source_columns, str(operation.get("delimiter") or ""))
                result_columns = [str(column) for column in operation.get("result_columns") or [] if str(column)]
                if result_columns:
                    source_column_set = set(source_columns)
                    select_parts = [
                        f"{expr} AS {_quote_ident(column)}" if column == output_column else _quote_ident(column)
                        for column in result_columns
                        if column == output_column or column not in source_column_set
                    ]
                    current_name = add_cte(scoped(prefix, "combined"), f"SELECT {', '.join(select_parts)} FROM {current_name}")
                else:
                    exclude_sql = ", ".join(_quote_ident(column) for column in source_columns)
                    current_name = add_cte(scoped(prefix, "combined"), f"SELECT * EXCLUDE ({exclude_sql}), {expr} AS {_quote_ident(output_column)} FROM {current_name}")
        elif op == "demote_headers":
            columns = [str(column) for column in operation.get("columns") or [] if str(column)]
            output_columns = [str(column) for column in operation.get("output_columns") or [] if str(column)]
            if columns and output_columns and len(columns) == len(output_columns):
                header_values = [
                    f"{_quote_literal(column)} AS {_quote_ident(output)}"
                    for column, output in zip(columns, output_columns, strict=False)
                ]
                row_values = [
                    f"CAST({_quote_ident(column)} AS VARCHAR) AS {_quote_ident(output)}"
                    for column, output in zip(columns, output_columns, strict=False)
                ]
                current_name = add_cte(scoped(prefix, "demoted_headers"), f"SELECT {', '.join(header_values)} UNION ALL SELECT {', '.join(row_values)} FROM {current_name}")
        elif op == "remove_rows_with_errors":
            columns = [str(column) for column in operation.get("columns") or [] if str(column)]
            flags = [_quote_ident("__pq_error_" + column) for column in columns]
            if flags:
                predicate = " AND ".join(f"NOT COALESCE({flag}, false)" for flag in flags)
                current_name = add_cte(scoped(prefix, "removed_errors"), f"SELECT * EXCLUDE ({', '.join(flags)}) FROM {current_name} WHERE {predicate}")
        elif op == "replace_error_values":
            replacements = [item for item in operation.get("replacements") or [] if isinstance(item, Mapping)]
            replace_parts = []
            flags = []
            for item in replacements:
                column = str(item.get("column") or "")
                if not column:
                    continue
                flag = _quote_ident("__pq_error_" + column)
                flags.append(flag)
                replace_parts.append(f"CASE WHEN COALESCE({flag}, false) THEN {_quote_literal(item.get('replacement'))} ELSE {_quote_ident(column)} END AS {_quote_ident(column)}")
            if replace_parts and flags:
                replaced_name = add_cte(scoped(prefix, "replaced_errors"), f"SELECT * REPLACE ({', '.join(replace_parts)}) FROM {current_name}")
                current_name = add_cte(scoped(prefix, "replaced_error_flags_removed"), f"SELECT * EXCLUDE ({', '.join(flags)}) FROM {replaced_name}")
        elif op == "expand_record_column":
            record_column = str(operation.get("record_column") or "")
            fields = [str(field) for field in operation.get("fields") or [] if str(field)]
            if record_column and fields:
                current_name = add_cte(scoped(prefix, "expanded_record"), f"SELECT {_expand_record_sql(operation)} FROM {current_name}")
        elif op == "expand_list_column":
            list_column = str(operation.get("list_column") or "")
            if list_column:
                current_name = add_cte(scoped(prefix, "expanded_list"), f"SELECT {_expand_list_sql(operation)} FROM {current_name}")
        elif op == "sort":
            order_by = [item for item in operation.get("order_by") or [] if isinstance(item, Mapping)]
        elif op in {"limit", "range"}:
            if isinstance(operation.get("limit"), int):
                limit_value = int(operation["limit"])
            if isinstance(operation.get("offset"), int):
                offset_value = int(operation["offset"])
        elif op == "limit_last":
            if isinstance(operation.get("count"), int):
                count = int(operation["count"])
                current_name = add_cte(
                    scoped(prefix, "last_rows"),
                    f"SELECT * EXCLUDE (__pq_rn, __pq_total) FROM (SELECT *, row_number() OVER () AS __pq_rn, count(*) OVER () AS __pq_total FROM {current_name}) WHERE __pq_rn > __pq_total - {count}",
                )
        elif op == "remove_last":
            if isinstance(operation.get("count"), int):
                count = int(operation["count"])
                current_name = add_cte(
                    scoped(prefix, "removed_last"),
                    f"SELECT * EXCLUDE (__pq_rn, __pq_total) FROM (SELECT *, row_number() OVER () AS __pq_rn, count(*) OVER () AS __pq_total FROM {current_name}) WHERE __pq_rn <= __pq_total - {count}",
                )
        elif op == "offset":
            if isinstance(operation.get("offset"), int):
                offset_value = int(operation["offset"])
        return current_name, order_by, limit_value, offset_value

    def select_with_modifiers(current_name: str, order_by: list[Mapping[str, Any]], limit_value: int | None, offset_value: int | None) -> str:
        sql = f"SELECT * FROM {current_name}"
        if order_by:
            order_parts = []
            for item in order_by:
                column = str(item.get("column") or "")
                direction = "DESC" if str(item.get("direction") or "").lower() == "desc" else "ASC"
                if column:
                    order_parts.append(f"{_quote_ident(column)} {direction}")
            if order_parts:
                sql += " ORDER BY " + ", ".join(order_parts)
        if isinstance(limit_value, int):
            sql += f" LIMIT {int(limit_value)}"
        if isinstance(offset_value, int):
            sql += f" OFFSET {int(offset_value)}"
        return sql

    def materialize_relation(relation: Mapping[str, Any], fallback_source: Mapping[str, Any], prefix: str) -> str | None:
        relation_source = relation.get("source") if isinstance(relation.get("source"), Mapping) else fallback_source
        source_sql = _source_scan_sql(relation_source or {})
        if source_sql is None:
            return None
        name = prefix
        ctes.append(f"{name} AS (SELECT * FROM {source_sql})")
        for branch_operation in relation.get("operations") or []:
            if isinstance(branch_operation, Mapping):
                name, _, _, _ = apply_operation(branch_operation, name, prefix=prefix)
        return name

    kind = str(source.get("kind") or "")
    if kind == "append":
        append_relations = [item for item in source.get("relations") or [] if isinstance(item, Mapping)]
        append_sources = [item for item in source.get("sources") or [] if isinstance(item, Mapping)]
        if append_relations:
            union_names: list[str] = []
            for index, relation in enumerate(append_relations, start=1):
                relation_source = relation.get("source") if isinstance(relation.get("source"), Mapping) else None
                source_sql = _source_scan_sql(relation_source or {})
                if source_sql is None:
                    return {
                        "dialect": "duckdb",
                        "status": "blocked",
                        "sql": None,
                        "blockers": [{"reason": f"Unsupported append relation source format or path at input {index}"}],
                    }
                branch_name = f"source_{index}"
                ctes.append(f"{branch_name} AS (SELECT * FROM {source_sql})")
                branch_order: list[Mapping[str, Any]] = []
                branch_limit: int | None = None
                branch_offset: int | None = None
                for branch_operation in relation.get("operations") or []:
                    if isinstance(branch_operation, Mapping):
                        branch_name, next_order, next_limit, next_offset = apply_operation(branch_operation, branch_name, prefix=f"source_{index}")
                        branch_order = next_order or branch_order
                        branch_limit = next_limit if next_limit is not None else branch_limit
                        branch_offset = next_offset if next_offset is not None else branch_offset
                if branch_order or branch_limit is not None or branch_offset is not None:
                    branch_name = add_cte(f"source_{index}_final", select_with_modifiers(branch_name, branch_order, branch_limit, branch_offset))
                union_names.append(branch_name)
        elif append_sources:
            union_names = []
            for index, item in enumerate(append_sources, start=1):
                source_sql = _source_scan_sql(item)
                if source_sql is None:
                    return {
                        "dialect": "duckdb",
                        "status": "blocked",
                        "sql": None,
                        "blockers": [{"reason": f"Unsupported append source format or path at input {index}"}],
                    }
                name = f"source_{index}"
                ctes.append(f"{name} AS (SELECT * FROM {source_sql})")
                union_names.append(name)
        else:
            return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": [{"reason": "Append source needs at least one foldable input"}]}
        union_sql = " UNION ALL BY NAME ".join(f"SELECT * FROM {name}" for name in union_names)
        ctes.append(f"source AS ({union_sql})")
    elif kind == "join":
        left_relation = source.get("left_relation") if isinstance(source.get("left_relation"), Mapping) else {}
        right_relation = source.get("right_relation") if isinstance(source.get("right_relation"), Mapping) else {}
        left = left_relation.get("source") if isinstance(left_relation, Mapping) and isinstance(left_relation.get("source"), Mapping) else source.get("left")
        right = right_relation.get("source") if isinstance(right_relation, Mapping) and isinstance(right_relation.get("source"), Mapping) else source.get("right")
        left = left if isinstance(left, Mapping) else None
        right = right if isinstance(right, Mapping) else None
        left_keys = [str(key) for key in source.get("left_keys") or [] if str(key)]
        right_keys = [str(key) for key in source.get("right_keys") or [] if str(key)]
        left_name = materialize_relation(left_relation, left or {}, "source_left")
        right_name = materialize_relation(right_relation, right or {}, "source_right")
        if left_name is None or right_name is None or not left_keys or len(left_keys) != len(right_keys):
            return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": [{"reason": "Join source needs two foldable inputs and matching keys"}]}
        conditions = [
            f"l.{_quote_ident(left_key)} = r.{_quote_ident(right_key)}"
            for left_key, right_key in zip(left_keys, right_keys, strict=False)
        ]
        join_kind = str(source.get("join_kind") or "inner").lower()
        if join_kind == "left_anti":
            ctes.append(f"source AS (SELECT l.* FROM {left_name} l WHERE NOT EXISTS (SELECT 1 FROM {right_name} r WHERE {' AND '.join(conditions)}))")
        elif join_kind == "right_anti":
            ctes.append(f"source AS (SELECT r.* FROM {right_name} r WHERE NOT EXISTS (SELECT 1 FROM {left_name} l WHERE {' AND '.join(conditions)}))")
        else:
            join_keyword = _join_keyword(join_kind)
            ctes.append(f"source AS (SELECT * FROM {left_name} l {join_keyword} {right_name} r ON {' AND '.join(conditions)})")
    elif kind == "expanded_nested_join":
        left_relation = source.get("left_relation") if isinstance(source.get("left_relation"), Mapping) else {}
        right_relation = source.get("right_relation") if isinstance(source.get("right_relation"), Mapping) else {}
        left = left_relation.get("source") if isinstance(left_relation, Mapping) and isinstance(left_relation.get("source"), Mapping) else source.get("left")
        right = right_relation.get("source") if isinstance(right_relation, Mapping) and isinstance(right_relation.get("source"), Mapping) else source.get("right")
        left = left if isinstance(left, Mapping) else None
        right = right if isinstance(right, Mapping) else None
        left_keys = [str(key) for key in source.get("left_keys") or [] if str(key)]
        right_keys = [str(key) for key in source.get("right_keys") or [] if str(key)]
        columns = [str(column) for column in source.get("columns") or [] if str(column)]
        output_columns = [str(column) for column in source.get("output_columns") or [] if str(column)]
        left_name = materialize_relation(left_relation, left or {}, "source_left")
        right_name = materialize_relation(right_relation, right or {}, "source_right")
        if left_name is None or right_name is None or not left_keys or len(left_keys) != len(right_keys) or not columns or len(columns) != len(output_columns):
            return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": [{"reason": "Expanded nested join needs two foldable inputs, matching keys, and explicit expand columns"}]}
        conditions = [
            f"l.{_quote_ident(left_key)} = r.{_quote_ident(right_key)}"
            for left_key, right_key in zip(left_keys, right_keys, strict=False)
        ]
        expanded_columns = [
            f"r.{_quote_ident(column)} AS {_quote_ident(alias)}"
            for column, alias in zip(columns, output_columns, strict=False)
        ]
        join_kind = str(source.get("join_kind") or "left").lower()
        if join_kind == "left_anti":
            null_columns = [
                f"NULL AS {_quote_ident(alias)}"
                for alias in output_columns
            ]
            ctes.append(f"source AS (SELECT l.*, {', '.join(null_columns)} FROM {left_name} l WHERE NOT EXISTS (SELECT 1 FROM {right_name} r WHERE {' AND '.join(conditions)}))")
        elif join_kind == "right_anti":
            right_anti_conditions = [
                f"l.{_quote_ident(left_key)} = r.{_quote_ident(right_key)}"
                for left_key, right_key in zip(left_keys, right_keys, strict=False)
            ]
            null_match_checks = [
                f"l.{_quote_ident(left_key)} IS NULL"
                for left_key in left_keys
            ]
            ctes.append(f"source AS (SELECT l.*, {', '.join(expanded_columns)} FROM {right_name} r LEFT JOIN {left_name} l ON {' AND '.join(right_anti_conditions)} WHERE {' AND '.join(null_match_checks)}))")
        else:
            join_keyword = _join_keyword(join_kind)
            ctes.append(f"source AS (SELECT l.*, {', '.join(expanded_columns)} FROM {left_name} l {join_keyword} {right_name} r ON {' AND '.join(conditions)})")
    elif kind == "aggregated_nested_join":
        left_relation = source.get("left_relation") if isinstance(source.get("left_relation"), Mapping) else {}
        right_relation = source.get("right_relation") if isinstance(source.get("right_relation"), Mapping) else {}
        left = left_relation.get("source") if isinstance(left_relation, Mapping) and isinstance(left_relation.get("source"), Mapping) else source.get("left")
        right = right_relation.get("source") if isinstance(right_relation, Mapping) and isinstance(right_relation.get("source"), Mapping) else source.get("right")
        left = left if isinstance(left, Mapping) else None
        right = right if isinstance(right, Mapping) else None
        left_keys = [str(key) for key in source.get("left_keys") or [] if str(key)]
        right_keys = [str(key) for key in source.get("right_keys") or [] if str(key)]
        aggs = [item for item in source.get("aggregations") or [] if isinstance(item, Mapping)]
        left_name = materialize_relation(left_relation, left or {}, "source_left")
        right_name = materialize_relation(right_relation, right or {}, "source_right")
        agg_parts = [part for part in (_nested_aggregation_sql(item) for item in aggs) if part]
        if left_name is None or right_name is None or not left_keys or len(left_keys) != len(right_keys) or not aggs or len(agg_parts) != len(aggs):
            return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": [{"reason": "Aggregated nested join needs two foldable inputs, matching keys, and supported aggregate specs"}]}
        conditions = [
            f"l.{_quote_ident(left_key)} = a.{_quote_ident(right_key)}"
            for left_key, right_key in zip(left_keys, right_keys, strict=False)
        ]
        exists_conditions = [
            f"l.{_quote_ident(left_key)} = r.{_quote_ident(right_key)}"
            for left_key, right_key in zip(left_keys, right_keys, strict=False)
        ]
        group_keys = ", ".join(_quote_ident(key) for key in right_keys)
        ctes.append(f"source_right_aggregated AS (SELECT {group_keys}, {', '.join(agg_parts)} FROM {right_name} GROUP BY {group_keys})")
        join_kind = str(source.get("join_kind") or "left").lower()
        if join_kind == "left_anti":
            default_columns = [_nested_aggregation_default_sql(item) for item in aggs]
            ctes.append(f"source AS (SELECT l.*, {', '.join(default_columns)} FROM {left_name} l WHERE NOT EXISTS (SELECT 1 FROM {right_name} r WHERE {' AND '.join(exists_conditions)}))")
        elif join_kind in {"right", "full"}:
            singleton_parts = [part for part in (_nested_singleton_aggregation_sql(item) for item in aggs) if part]
            if len(singleton_parts) != len(aggs):
                return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": [{"reason": "Aggregated nested join needs supported aggregate specs"}]}
            ctes.append(f"source_left_numbered AS (SELECT *, row_number() OVER () AS __pq_left_row_id FROM {left_name})")
            ctes.append(f"source_right_numbered AS (SELECT *, row_number() OVER () AS __pq_right_row_id FROM {right_name})")
            numbered_conditions = [
                f"l.{_quote_ident(left_key)} = a.{_quote_ident(right_key)}"
                for left_key, right_key in zip(left_keys, right_keys, strict=False)
            ]
            numbered_exists_conditions = [
                f"lx.{_quote_ident(left_key)} = r.{_quote_ident(right_key)}"
                for left_key, right_key in zip(left_keys, right_keys, strict=False)
            ]
            matched_join_keyword = "LEFT JOIN" if join_kind == "full" else "INNER JOIN"
            aggregate_columns = [_nested_aggregation_projection_sql(item) for item in aggs]
            ctes.append(
                "source_matched_left AS "
                f"(SELECT l.* EXCLUDE (__pq_left_row_id), {', '.join(aggregate_columns)} "
                f"FROM source_left_numbered l {matched_join_keyword} source_right_aggregated a ON {' AND '.join(numbered_conditions)})"
            )
            ctes.append(
                "source_unmatched_right AS "
                f"(SELECT l.* EXCLUDE (__pq_left_row_id), {', '.join(singleton_parts)} "
                f"FROM (SELECT * FROM source_left_numbered WHERE FALSE) l "
                "RIGHT JOIN source_right_numbered r ON TRUE "
                f"WHERE NOT EXISTS (SELECT 1 FROM source_left_numbered lx WHERE {' AND '.join(numbered_exists_conditions)}))"
            )
            ctes.append("source AS (SELECT * FROM source_matched_left UNION ALL BY NAME SELECT * FROM source_unmatched_right)")
        else:
            join_keyword = "INNER JOIN" if join_kind == "inner" else "LEFT JOIN"
            aggregate_columns = [_nested_aggregation_projection_sql(item) for item in aggs]
            ctes.append(f"source AS (SELECT l.*, {', '.join(aggregate_columns)} FROM {left_name} l {join_keyword} source_right_aggregated a ON {' AND '.join(conditions)})")
    else:
        source_sql = _source_scan_sql(source)
        if source_sql is None:
            fmt = str(source.get("format") or "").lower()
            reason = "Source path is required" if not str(source.get("path") or "") else f"Unsupported source format: {fmt}"
            return {"dialect": "duckdb", "status": "blocked", "sql": None, "blockers": [{"reason": reason}]}
        ctes.append(f"source AS (SELECT * FROM {source_sql})")
    current = "source"

    operations = [item for item in relational_ast.get("operations") or [] if isinstance(item, Mapping)]
    if not operations:
        if relational_ast.get("casts"):
            operations.append({"op": "cast", "casts": relational_ast.get("casts")})
        if relational_ast.get("filters"):
            for item in relational_ast.get("filters") or []:
                if isinstance(item, Mapping):
                    operations.append({"op": "filter", **item})
        if relational_ast.get("projection"):
            operations.append({"op": "project", "projection": relational_ast.get("projection")})

    final_order_by: list[Mapping[str, Any]] = []
    final_limit = relational_ast.get("limit") if isinstance(relational_ast.get("limit"), int) else None
    final_offset = relational_ast.get("offset") if isinstance(relational_ast.get("offset"), int) else None

    for operation in operations:
        current, next_order, next_limit, next_offset = apply_operation(operation, current)
        final_order_by = next_order or final_order_by
        final_limit = next_limit if next_limit is not None else final_limit
        final_offset = next_offset if next_offset is not None else final_offset

    projection = relational_ast.get("projection")
    if not any(str(operation.get("op") or "") == "project" for operation in operations) and isinstance(projection, list) and projection:
        add_cte("projected", f"SELECT {_projection_sql(projection)} FROM {current}")

    sql = f"WITH {', '.join(ctes)} SELECT * FROM {current}"
    order_by = final_order_by or [item for item in relational_ast.get("order_by") or [] if isinstance(item, Mapping)]
    if order_by:
        order_parts = []
        for item in order_by:
            column = str(item.get("column") or "")
            direction = "DESC" if str(item.get("direction") or "").lower() == "desc" else "ASC"
            if column:
                order_parts.append(f"{_quote_ident(column)} {direction}")
        if order_parts:
            sql += " ORDER BY " + ", ".join(order_parts)
    if isinstance(final_limit, int):
        sql += f" LIMIT {int(final_limit)}"
    if isinstance(final_offset, int):
        sql += f" OFFSET {int(final_offset)}"
    return {"dialect": "duckdb", "status": "emit_candidate", "sql": sql, "blockers": []}
