"""
IMPORTANT:
This file must follow the rules in instructions.md.

- DuckDB-first execution
- No Python evaluation
- Context rewrites only
- Dynamic DAX function registry

A scalable DAX → DuckDB SQL compiler skeleton.

This module defines:
 - Immutable IR classes for DAX expressions (scalar, table, context, window).
 - A Context object (copied, never mutated).
 - DaxFnSpec registry with dynamic fallback for 100% function coverage.
 - SQL lowering for scalar, table, context, iterator, and window expressions.
 - SQL normalization for deterministic output.
 - TODO stubs for relationships, time intelligence, and windowing.

See instructions.md for non-negotiable rules.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import threading
from typing import Callable, List, Dict, Optional, Any, Tuple, Union

from .ir import (
    ColumnRef,
    ContextTransformExpr,
    DaxBinaryOp,
    DaxFunction,
    DaxIteratorFunction,
    DaxWindowFunction,
    Expr,
    Literal,
    MeasureRef,
    SelectedMeasureRef,
    ScalarExpr,
    SetLiteral,
    TableRef,
    TableExpr,
    WhatIfRef,
    WindowExpr,
)

from .context import Context

from .relationships import (
    RELATIONSHIPS,
    Relationship,
    _build_rowset_from_clause_ctx,
    _build_rowset_plan_ctx,
    build_rowset_from_clause,
    set_relationships,
)

from .registry import (
    DaxFnSpec,
    get_or_register_spec,
    load_default_mapping,
    load_sql_mapping,
    register,
    registry,
)

from .lowering_scalar import (
    compile_coalesce,
    compile_concatenatex,
    compile_divide,
    compile_hasonefilter,
    compile_hasonevalue,
    compile_iferror,
    compile_isblank,
    compile_iscrossfiltered,
    compile_isfiltered,
    compile_selectedvalue,
    compile_switch,
    _as_scalar_sql,
)

from .lowering_table import compile_table_expr as _compile_table_expr, _KNOWN_TABLE_FN_NAMES

from .lowering_iterators import compile_iterator_function as _compile_iterator_function

from .sql_utils import (
    as_from_source,
    normalize_sql,
    quote_ident,
    rewrite_table_qualifier_to_alias,
    rewrite_qualifiers_to_alias,
)

from .table_sources import resolve_table_source_sql, set_table_sources, clear_table_sources


# === Calculated column registry (virtual-only) ===

# Keyed case-insensitively by (TABLE, COLUMN). Values are scalar SQL expressions.
CALCULATED_COLUMN_SQL: Dict[Tuple[str, str], str] = {}
_CALC_COL_TLS = threading.local()


def clear_calculated_columns() -> None:
    CALCULATED_COLUMN_SQL.clear()


def set_calculated_column_sql(mapping: Dict[str, str] | Dict[Tuple[str, str], str]) -> None:
    """Replace the in-memory calculated column SQL registry.

    Accepts either:
    - dict[(table, column)] -> sql
    - dict["Table.Column"] -> sql
    """

    CALCULATED_COLUMN_SQL.clear()
    for k, v in dict(mapping or {}).items():
        if not v:
            continue
        sql = str(v).strip()
        if not sql:
            continue

        if isinstance(k, tuple) and len(k) == 2:
            table, column = k
        else:
            s = str(k or "").strip()
            if "." not in s:
                continue
            table, column = s.split(".", 1)

        t = str(table or "").strip()
        c = str(column or "").strip()
        if not t or not c:
            continue
        CALCULATED_COLUMN_SQL[(t.upper(), c.upper())] = sql


def _resolve_calculated_column_sql(table: str, column: str) -> Optional[str]:
    t = str(table or "").strip().upper()
    c = str(column or "").strip().upper()
    if not t or not c:
        return None
    return CALCULATED_COLUMN_SQL.get((t, c))


def _calc_col_stack() -> list[Tuple[str, str]]:
    stack = getattr(_CALC_COL_TLS, "stack", None)
    if stack is None:
        stack = []
        _CALC_COL_TLS.stack = stack
    return stack


# === Measure registry ===

# Measure name -> expression definition. Keep this dict object stable.
MEASURES: Dict[str, ScalarExpr] = {}


def reset_engine_state() -> None:
    """Reset per-project mutable engine state.

    This clears measures and relationships (which are global, process-wide state).
    It intentionally does NOT clear the DAX function registry / verified mappings.
    """

    set_measures({})
    set_relationships([])
    clear_table_sources()
    clear_calculated_columns()


def set_measures(measures: Dict[str, ScalarExpr]) -> None:
    """Replace the in-memory measure registry.

    Measures are stored case-insensitively by name.
    """

    MEASURES.clear()
    for k, v in dict(measures).items():
        if k is None:
            continue
        name = str(k).strip()
        if not name:
            continue
        MEASURES[name.upper()] = v


def define_measure(name: str, expr: ScalarExpr) -> None:
    """Define or overwrite a measure in the in-memory registry."""

    n = str(name).strip()
    if not n:
        return
    MEASURES[n.upper()] = expr


def _resolve_measure(name: str) -> Optional[ScalarExpr]:
    if name is None:
        return None
    return MEASURES.get(str(name).strip().upper())


def _compile_date_scalar(expr: "Expr", ctx: "Context") -> str:
    """Compile a scalar that is expected to be a DATE-like value.

    If the argument is a string literal, cast it to DATE to keep SQL valid in DuckDB.
    """

    if isinstance(expr, Literal) and isinstance(expr.value, str):
        escaped = expr.value.replace("'", "''")
        return f"CAST('{escaped}' AS DATE)"
    return compile_expr(expr, ctx)


def _parse_time_unit(unit_expr: "Expr") -> Optional[str]:
    """Parse DAX time unit argument to a normalized unit string.

    Supported: DAY, MONTH, QUARTER, YEAR.
    """

    if isinstance(unit_expr, Literal) and isinstance(unit_expr.value, str):
        u = unit_expr.value.strip().upper()
        if u in {"DAY", "DAYS"}:
            return "DAY"
        if u in {"MONTH", "MONTHS"}:
            return "MONTH"
        if u in {"QUARTER", "QUARTERS"}:
            return "QUARTER"
        if u in {"YEAR", "YEARS"}:
            return "YEAR"
    return None


def _interval_one_for_unit(unit: str) -> str:
    u = unit.upper()
    if u == "DAY":
        return "INTERVAL '1 day'"
    if u == "MONTH":
        return "INTERVAL '1 month'"
    if u == "QUARTER":
        return "INTERVAL '3 month'"
    # YEAR
    return "INTERVAL '1 year'"


def _visible_date_minmax_subqueries(col: "ColumnRef", ctx: "Context") -> Tuple[str, str]:
    where = ctx.where_clause(col.table)
    min_date = f"(SELECT MIN({col.table}.{col.column}) FROM {col.table} {where})"
    max_date = f"(SELECT MAX({col.table}.{col.column}) FROM {col.table} {where})"
    return min_date, max_date


def _try_time_intel_predicate(inner_expr: "Expr", base_ctx: "Context") -> Optional[Tuple[str, str]]:
    """Recognize supported time-intelligence table functions and return a context predicate.

    Returns (key, predicate_sql) where key is "Table.Column".
    Unsupported shapes return None (safe no-op at call sites).
    """

    if not isinstance(inner_expr, DaxFunction):
        return None
    fn = inner_expr.fn.upper()

    def _col0() -> Optional[ColumnRef]:
        if not inner_expr.args:
            return None
        a0 = inner_expr.args[0]
        return a0 if isinstance(a0, ColumnRef) else None

    def _key(col: ColumnRef) -> str:
        return f"{col.table}.{col.column}"

    # Period-to-date table functions
    if fn in {"DATESYTD", "DATESMTD", "DATESQTD"}:
        col = _col0()
        if col is None:
            return None
        key = _key(col)
        _, max_date = _visible_date_minmax_subqueries(col, base_ctx)
        grain = "year" if fn == "DATESYTD" else "month" if fn == "DATESMTD" else "quarter"
        start = f"DATE_TRUNC('{grain}', {max_date})"
        predicate = f"{col.table}.{col.column} BETWEEN {start} AND {max_date}"
        return (key, predicate)

    # Inclusive explicit range
    if fn == "DATESBETWEEN":
        if len(inner_expr.args) < 3:
            return None
        col = inner_expr.args[0]
        if not isinstance(col, ColumnRef):
            return None
        start_sql = _compile_date_scalar(inner_expr.args[1], base_ctx)
        end_sql = _compile_date_scalar(inner_expr.args[2], base_ctx)
        key = _key(col)
        predicate = f"{col.table}.{col.column} BETWEEN {start_sql} AND {end_sql}"
        return (key, predicate)

    # Relative range from a start date by an interval
    if fn == "DATESINPERIOD":
        if len(inner_expr.args) < 4:
            return None
        col = inner_expr.args[0]
        if not isinstance(col, ColumnRef):
            return None
        start_sql = _compile_date_scalar(inner_expr.args[1], base_ctx)
        n_sql = compile_expr(inner_expr.args[2], base_ctx)
        unit = _parse_time_unit(inner_expr.args[3])
        if unit is None:
            return None
        key = _key(col)
        interval = _interval_one_for_unit(unit)
        other_end = f"({start_sql} + ({n_sql}) * {interval})"
        predicate = (
            f"{col.table}.{col.column} BETWEEN LEAST({start_sql}, {other_end}) "
            f"AND GREATEST({start_sql}, {other_end})"
        )
        return (key, predicate)

    # Whole-period shifting based on the max visible date.
    if fn in {"PREVIOUSMONTH", "NEXTMONTH", "PREVIOUSQUARTER", "NEXTQUARTER"}:
        col = _col0()
        if col is None:
            return None
        key = _key(col)
        _, max_date = _visible_date_minmax_subqueries(col, base_ctx)

        if fn == "PREVIOUSMONTH":
            start = f"DATE_TRUNC('month', {max_date} - INTERVAL '1 month')"
            end = f"(DATE_TRUNC('month', {max_date}) - INTERVAL '1 day')"
        elif fn == "NEXTMONTH":
            start = f"DATE_TRUNC('month', {max_date} + INTERVAL '1 month')"
            end = f"(DATE_TRUNC('month', {max_date} + INTERVAL '2 month') - INTERVAL '1 day')"
        elif fn == "PREVIOUSQUARTER":
            start = f"DATE_TRUNC('quarter', {max_date} - INTERVAL '3 month')"
            end = f"(DATE_TRUNC('quarter', {max_date}) - INTERVAL '1 day')"
        else:  # NEXTQUARTER
            start = f"DATE_TRUNC('quarter', {max_date} + INTERVAL '3 month')"
            end = f"(DATE_TRUNC('quarter', {max_date} + INTERVAL '6 month') - INTERVAL '1 day')"

        predicate = f"{col.table}.{col.column} BETWEEN {start} AND {end}"
        return (key, predicate)

    # Boundary helpers: constrain to a single boundary date in the current context.
    if fn in {
        "STARTOFMONTH",
        "ENDOFMONTH",
        "STARTOFQUARTER",
        "ENDOFQUARTER",
        "STARTOFYEAR",
        "ENDOFYEAR",
    }:
        col = _col0()
        if col is None:
            return None
        key = _key(col)
        min_date, max_date = _visible_date_minmax_subqueries(col, base_ctx)

        boundary = min_date if fn.startswith("START") else max_date
        predicate = f"{col.table}.{col.column} = {boundary}"
        return (key, predicate)

    return None


def collect_tables(expr: Expr) -> List[str]:
    """Collect referenced table names from an expression.

    This is used for best-effort FROM/JOIN planning and context predicate application.
    """

    seen: set[str] = set()

    def walk(e: Expr) -> None:
        if isinstance(e, ColumnRef):
            seen.add(e.table)
            return
        if isinstance(e, TableRef):
            seen.add(e.name)
            return
        if isinstance(e, MeasureRef):
            d = _resolve_measure(e.name)
            if d is not None:
                walk(d)
            return
        if isinstance(e, Literal):
            return
        if isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
            return
        if isinstance(e, DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by:
                for c in e.order_by:
                    walk(c)
            return

    walk(expr)
    return sorted(seen)


def _rewrite_qualifiers_to_alias(expr_sql: str, alias: str) -> str:
    # Back-compat alias for older internal callsites.
    return rewrite_qualifiers_to_alias(expr_sql, alias)


def _as_from_source(table_sql: str, alias: str = "t") -> str:
    # Back-compat alias for older internal callsites.
    return as_from_source(table_sql, alias)

# === Compile functions ===

def compile_expr(expr: Expr, ctx: Context) -> str:
    if isinstance(expr, TableRef):
        # The parser sometimes emits keywords as TableRef nodes.
        name_upper = expr.name.upper()
        if name_upper == "TRUE":
            return "TRUE"
        if name_upper == "FALSE":
            return "FALSE"
        if name_upper in ("ASC", "DESC"):
            return f"'{expr.name.upper()}'"
        raise TypeError(f"TableRef cannot be compiled as a scalar: {expr.name!r}")
    if isinstance(expr, SelectedMeasureRef):
        raise ValueError("SELECTEDMEASURE() is only valid inside calculation item expressions")
    if isinstance(expr, ColumnRef):
        calc_sql = _resolve_calculated_column_sql(expr.table, expr.column)
        if calc_sql is not None:
            key = (str(expr.table).strip().upper(), str(expr.column).strip().upper())
            stack = _calc_col_stack()
            if key in stack:
                # Break cycles conservatively.
                return f"{quote_ident(expr.table)}.{quote_ident(expr.column)}"
            stack.append(key)
            try:
                s = calc_sql
                if getattr(ctx, "row_context_alias", None):
                    s = rewrite_table_qualifier_to_alias(s, expr.table, str(ctx.row_context_alias))
                return f"({s})"
            finally:
                stack.pop()

        return f"{quote_ident(expr.table)}.{quote_ident(expr.column)}"
    if isinstance(expr, MeasureRef):
        definition = _resolve_measure(expr.name)
        if definition is None:
            # In row context (e.g., inside ADDCOLUMNS / SELECTCOLUMNS),
            # unresolved [Name] should be treated as a column reference
            # from the source table — DAX semantics resolve [Name] as a
            # column first, measure second.
            if getattr(ctx, "row_context_alias", None):
                return f"{ctx.row_context_alias}.{quote_ident(expr.name)}"
            # Keep 100% compilation coverage: unknown measures become a generic SQL call.
            safe_name = expr.name.strip().upper().replace(" ", "_")
            if not safe_name:
                safe_name = "MEASURE"
            return f"DAX_MEASURE_{safe_name}()"
        return compile_expr(definition, ctx)
    if isinstance(expr, WhatIfRef):
        # Resolve What-If parameter to its current effective value from context.
        param_name = str(expr.name).strip().upper()
        value = ctx.get_what_if_value(param_name)
        if value is not None:
            return str(float(value))
        # If no value is set in context, default to 0 to avoid compilation failure.
        return "0"
    if isinstance(expr, Literal):
        if isinstance(expr.value, str):
            escaped = expr.value.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(expr.value, bool):
            return "TRUE" if expr.value else "FALSE"
        if expr.value is None:
            return "NULL"
        return str(expr.value)
    if isinstance(expr, SetLiteral):
        parts: List[str] = []
        for v in expr.values:
            parts.append(compile_expr(v, ctx))
        return f"{', '.join(parts)}"
    if isinstance(expr, DaxBinaryOp):
        left_sql = _as_scalar_sql(compile_expr(expr.left, ctx))
        if expr.operator.upper() == "IN":
            if isinstance(expr.right, SetLiteral):
                right_sql = _as_scalar_sql(compile_expr(expr.right, ctx))
                return f"({left_sql} IN ({right_sql}))"

            # Support IN with a single-column table expression RHS:
            # lhs IN VALUES(Table[Col])
            # lhs IN DISTINCT(Table[Col])
            if isinstance(expr.right, DaxFunction) and expr.right.fn.upper() in {"VALUES", "DISTINCT"}:
                if expr.right.args and isinstance(expr.right.args[0], ColumnRef):
                    col = expr.right.args[0]
                    col_sql = compile_expr(col, ctx)

                    required_tables: set[str] = {col.table}
                    for key in ctx.all_filter_keys():
                        if "." in key:
                            required_tables.add(key.split(".", 1)[0])

                    from_clause, connected, _ = _build_rowset_plan_ctx(col.table, sorted(required_tables), ctx)
                    where = ctx.where_clause_for_tables(sorted(connected))
                    where_sql = f" {where}" if where else ""
                    subquery = f"SELECT DISTINCT {col_sql} FROM {from_clause}{where_sql}"
                    return f"({left_sql} IN ({subquery}))"

        right_sql = _as_scalar_sql(compile_expr(expr.right, ctx))
        if expr.operator == "||":
            # DAX & (string concatenation): numeric values like ROUND(x,0)=199.0
            # must display as "199" (no trailing ".0").  Use REGEXP_REPLACE to
            # strip a trailing ".0" after CAST to VARCHAR.
            def _dax_text(sql: str) -> str:
                return f"REGEXP_REPLACE(CAST({sql} AS VARCHAR), '\\.0$', '')"
            return f"({_dax_text(left_sql)} || {_dax_text(right_sql)})"
        return f"({left_sql} {expr.operator} {right_sql})"
    if isinstance(expr, DaxFunction):
        fn_name = expr.fn.upper()

        # SWITCH is a scalar rewrite to CASE; it must always compile.
        if fn_name == "SWITCH":
            return compile_switch(expr, ctx, compile_expr=compile_expr)

        # Utility & error-handling functions.
        if fn_name == "COALESCE":
            return compile_coalesce(expr, ctx, compile_expr=compile_expr)
        if fn_name == "ISBLANK":
            return compile_isblank(expr, ctx, compile_expr=compile_expr)
        if fn_name == "IFERROR":
            return compile_iferror(expr, ctx, compile_expr=compile_expr)
        if fn_name == "DIVIDE":
            return compile_divide(expr, ctx, compile_expr=compile_expr)

        # Context introspection.
        if fn_name == "HASONEVALUE":
            return compile_hasonevalue(expr, ctx, compile_expr=compile_expr)
        if fn_name == "SELECTEDVALUE":
            return compile_selectedvalue(expr, ctx, compile_expr=compile_expr)
        if fn_name == "HASONEFILTER":
            return compile_hasonefilter(expr, ctx)
        if fn_name == "ISFILTERED":
            return compile_isfiltered(expr, ctx)
        if fn_name == "ISCROSSFILTERED":
            return compile_iscrossfiltered(expr, ctx)
        if fn_name == "CONCATENATEX":
            return compile_concatenatex(
                expr,
                ctx,
                compile_expr=compile_expr,
                compile_table_expr=compile_table_expr,
                collect_tables=collect_tables,
                as_from_source=_as_from_source,
                rewrite_qualifiers_to_alias=_rewrite_qualifiers_to_alias,
            )

        if fn_name == "COUNTROWS":
            # COUNTROWS(table) -> (SELECT COUNT(*) FROM <table_expr>)
            if not expr.args:
                return "NULL"
            # Relationship-aware: if context has cross-table filters, include
            # JOINs so that predicates on related tables are applied.
            arg0 = expr.args[0]
            if isinstance(arg0, TableRef):
                base_table = arg0.name
                required_tables: set[str] = {base_table}
                for k in ctx.all_filter_keys():
                    if "." in k:
                        required_tables.add(k.split(".", 1)[0])
                if len(required_tables) > 1:
                    from_clause, connected, _ = _build_rowset_plan_ctx(
                        base_table, sorted(required_tables), ctx
                    )
                    where = ctx.where_clause_for_tables(sorted(connected))
                    return f"(SELECT COUNT(*) FROM {from_clause} {where})"
            table_sql = compile_table_expr(arg0, ctx)
            from_source = _as_from_source(table_sql, "t")
            return f"(SELECT COUNT(*) FROM {from_source})"

        # Logical operators: DAX AND/OR map to SQL infix operators
        if fn_name == "AND":
            if len(expr.args) >= 2:
                compiled = [_as_scalar_sql(compile_expr(a, ctx)) for a in expr.args]
                return f"({' AND '.join(compiled)})"
            return "TRUE"
        if fn_name == "OR":
            if len(expr.args) >= 2:
                compiled = [_as_scalar_sql(compile_expr(a, ctx)) for a in expr.args]
                return f"({' OR '.join(compiled)})"
            return "FALSE"
        if fn_name == "NOT":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"(NOT {inner})"
            return "FALSE"

        # -- Special handlers for functions that need custom compilation --

        if fn_name == "CONTAINS":
            # CONTAINS(table, col, value, ...) → EXISTS subquery
            if len(expr.args) >= 3:
                table_sql = compile_table_expr(expr.args[0], ctx)
                from_source = _as_from_source(table_sql, "ct")
                pairs = []
                i = 1
                while i + 1 < len(expr.args):
                    col_sql = compile_expr(expr.args[i], ctx)
                    col_sql = rewrite_qualifiers_to_alias(col_sql, "ct")
                    val_sql = _as_scalar_sql(compile_expr(expr.args[i + 1], ctx))
                    pairs.append(f"{col_sql} = {val_sql}")
                    i += 2
                where = " AND ".join(pairs) if pairs else "TRUE"
                return f"(EXISTS (SELECT 1 FROM {from_source} WHERE {where}))"

        if fn_name == "CONTAINSROW":
            # CONTAINSROW(table, value1, value2, ...) → value IN (SELECT col FROM table)
            if len(expr.args) >= 2:
                table_arg = expr.args[0]
                vals = [_as_scalar_sql(compile_expr(a, ctx)) for a in expr.args[1:]]
                table_sql = compile_table_expr(table_arg, ctx)
                from_source = _as_from_source(table_sql, "cr")
                if len(vals) == 1:
                    return f"({vals[0]} IN (SELECT * FROM {from_source}))"
                return f"(EXISTS (SELECT 1 FROM {from_source}))"

        if fn_name == "ISEMPTY":
            # ISEMPTY(table) → NOT EXISTS
            if expr.args:
                table_sql = compile_table_expr(expr.args[0], ctx)
                from_source = _as_from_source(table_sql, "ie")
                return f"(NOT EXISTS (SELECT 1 FROM {from_source}))"

        if fn_name == "TOCSV":
            if expr.args:
                table_sql = compile_table_expr(expr.args[0], ctx)
                from_source = _as_from_source(table_sql, "tc")
                return f"(SELECT GROUP_CONCAT(COLUMNS(*), ',') FROM {from_source} LIMIT 1)"

        if fn_name == "TOJSON":
            if expr.args:
                table_sql = compile_table_expr(expr.args[0], ctx)
                from_source = _as_from_source(table_sql, "tj")
                return f"(SELECT TO_JSON(LIST(COLUMNS(*))) FROM {from_source})"

        if fn_name == "RELATED":
            # RELATED(col) → scalar subquery with relationship join
            if expr.args and isinstance(expr.args[0], ColumnRef):
                col = expr.args[0]
                from_src = resolve_table_source_sql(col.table)
                # Find the relationship that connects the current context to col.table
                from .relationships import RELATIONSHIPS
                join_pred = None
                for rel in RELATIONSHIPS:
                    if rel.to_table == col.table:
                        # FK is from_table.from_column, PK is to_table.to_column
                        # Use bare from_column for the FK side so the iterator alias rewrite picks it up
                        fk = f"{quote_ident(rel.from_table)}.{quote_ident(rel.from_column)}"
                        pk = f"{quote_ident('_rel')}.{quote_ident(rel.to_column)}"
                        join_pred = f"{fk} = {pk}"
                        col_sql = f"{quote_ident('_rel')}.{quote_ident(col.column)}"
                        return f"(SELECT {col_sql} FROM {from_src} AS _rel WHERE {join_pred} LIMIT 1)"
                    if rel.from_table == col.table:
                        fk = f"{quote_ident(rel.to_table)}.{quote_ident(rel.to_column)}"
                        pk = f"{quote_ident('_rel')}.{quote_ident(rel.from_column)}"
                        join_pred = f"{fk} = {pk}"
                        col_sql = f"{quote_ident('_rel')}.{quote_ident(col.column)}"
                        return f"(SELECT {col_sql} FROM {from_src} AS _rel WHERE {join_pred} LIMIT 1)"
                col_sql = f"{quote_ident(col.table)}.{quote_ident(col.column)}"
                return f"(SELECT {col_sql} FROM {from_src} LIMIT 1)"

        if fn_name == "IGNORE":
            # IGNORE(expr) → passthrough
            if expr.args:
                return compile_expr(expr.args[0], ctx)
            return "NULL"

        if fn_name in ("FIRSTNONBLANKVALUE", "LASTNONBLANKVALUE"):
            # FIRSTNONBLANKVALUE(col, expr) → evaluate expr for each distinct value of col,
            # return the value of expr for the first/last non-blank result.
            # Key: the expression must be scoped to each group (filter context
            # per distinct col value), so aggregates like COUNTROWS must become
            # COUNT(*) inside the GROUP BY, not a global scalar subquery.
            if len(expr.args) >= 2:
                col_arg = expr.args[0]
                val_expr = expr.args[1]
                table_name = col_arg.table if isinstance(col_arg, ColumnRef) else None
                from_src = resolve_table_source_sql(table_name) if table_name else "Sales"
                col_sql = _as_scalar_sql(compile_expr(col_arg, ctx))
                direction = "ASC" if fn_name == "FIRSTNONBLANKVALUE" else "DESC"

                # Detect aggregate patterns and rewrite to GROUP BY-compatible SQL
                agg_sql = None
                if isinstance(val_expr, DaxFunction):
                    vfn = val_expr.fn.upper()
                    if vfn == "COUNTROWS" and val_expr.args:
                        agg_sql = "COUNT(*)"
                    elif vfn in ("SUM", "AVERAGE", "AVG", "MIN", "MAX") and val_expr.args:
                        inner = _as_scalar_sql(compile_expr(val_expr.args[0], ctx))
                        sql_fn = {"SUM": "SUM", "AVERAGE": "AVG", "AVG": "AVG",
                                  "MIN": "MIN", "MAX": "MAX"}[vfn]
                        agg_sql = f"{sql_fn}({inner})"

                if agg_sql is not None:
                    return (f"(SELECT sub_val FROM ("
                            f"SELECT {col_sql} AS sub_key, {agg_sql} AS sub_val "
                            f"FROM {from_src} GROUP BY {col_sql}"
                            f") sub WHERE sub_val IS NOT NULL "
                            f"ORDER BY sub_key {direction} LIMIT 1)")

                # Fallback: compile val_expr as-is (may be inaccurate for aggregates)
                val_sql = _as_scalar_sql(compile_expr(val_expr, ctx))
                return (f"(SELECT sub_val FROM ("
                        f"SELECT {col_sql} AS sub_key, {val_sql} AS sub_val "
                        f"FROM {from_src} GROUP BY {col_sql}"
                        f") sub WHERE sub_val IS NOT NULL "
                        f"ORDER BY sub_key {direction} LIMIT 1)")

        if fn_name in ("ISAFTER", "ISONORAFTER"):
            # ISAFTER(val1, val2, [order]) → comparison
            if len(expr.args) >= 2:
                v1 = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                v2 = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                direction = "ASC"
                if len(expr.args) >= 3:
                    d = expr.args[2]
                    if isinstance(d, TableRef) and d.name.upper() in ("ASC", "DESC"):
                        direction = d.name.upper()
                    elif isinstance(d, Literal) and isinstance(d.value, str) and d.value.upper() in ("ASC", "DESC"):
                        direction = d.value.upper()
                if fn_name == "ISAFTER":
                    op = ">" if direction == "ASC" else "<"
                else:
                    op = ">=" if direction == "ASC" else "<="
                return f"({v1} {op} {v2})"

        # -- Dot-notation functions: DAX uses dots but DuckDB interprets as schema --
        _DOT_TO_UDF = {
            "BETA.DIST": "BETA_DIST", "BETA.INV": "BETA_INV",
            "CHISQ.DIST": "CHISQ_DIST", "CHISQ.DIST.RT": "CHISQ_DIST_RT",
            "CHISQ.INV": "CHISQ_INV", "CHISQ.INV.RT": "CHISQ_INV_RT",
            "EXPON.DIST": "EXPON_DIST",
            "NORM.DIST": "NORM_DIST", "NORM.INV": "NORM_INV",
            "NORM.S.DIST": "NORM_S_DIST", "NORM.S.INV": "NORM_S_INV",
            "POISSON.DIST": "POISSON_DIST",
            "T.DIST": "T_DIST", "T.DIST.RT": "T_DIST_RT", "T.DIST.2T": "T_DIST_2T",
            "T.INV": "T_INV", "T.INV.2T": "T_INV_2T",
            "CONFIDENCE.NORM": "CONFIDENCE_NORM", "CONFIDENCE.T": "CONFIDENCE_T",
            "STDEV.S": "DAX_STDEV_S", "STDEV.P": "DAX_STDEV_P",
            "VAR.S": "DAX_VAR_S", "VAR.P": "DAX_VAR_P",
            "ISO.CEILING": "DAX_ISO_CEILING",
            "IF.EAGER": "IF",
        }
        if fn_name in _DOT_TO_UDF:
            udf_name = _DOT_TO_UDF[fn_name]
            compiled_args = [_as_scalar_sql(compile_expr(arg, ctx)) for arg in expr.args]
            return f"{udf_name}({', '.join(compiled_args)})"

        # -- Functions that need SQL syntax rewrites --
        if fn_name == "INT":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                # DAX INT() rounds toward negative infinity (like FLOOR).
                # DuckDB CAST rounds, and TRUNC goes toward zero.
                # Use FLOOR to match DAX semantics, then cast to BIGINT.
                return f"CAST(FLOOR({inner}) AS BIGINT)"
            return "NULL"

        if fn_name == "LOG":
            # DAX LOG(number, base) — number first, base second.
            # DuckDB LOG(base, number) — base first, number second.
            # Swap the arguments to match DAX semantics.
            if len(expr.args) >= 2:
                number_sql = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                base_sql = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                return f"LOG({base_sql}, {number_sql})"
            if expr.args:
                # LOG(number) with no base defaults to base 10 in DAX.
                number_sql = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"LOG(10, {number_sql})"
            return "NULL"

        if fn_name == "CONVERT":
            # CONVERT(expr, type) → CAST(expr AS type)
            if len(expr.args) >= 2:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                type_arg = expr.args[1]
                if isinstance(type_arg, Literal) and isinstance(type_arg.value, str):
                    type_name = type_arg.value.upper()
                elif isinstance(type_arg, TableRef):
                    type_name = type_arg.name.upper()
                else:
                    type_name = "VARCHAR"
                return f"CAST({inner} AS {type_name})"
            return "NULL"

        if fn_name == "FIXED":
            # FIXED(number, [decimals], [no_commas]) → UDF registered in duckdb_udfs.py
            if expr.args:
                num = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                decimals = "2"
                no_commas = "0"
                if len(expr.args) >= 2:
                    decimals = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                if len(expr.args) >= 3:
                    no_commas = _as_scalar_sql(compile_expr(expr.args[2], ctx))
                return f"FIXED(CAST({num} AS DOUBLE), CAST({decimals} AS DOUBLE), CAST({no_commas} AS DOUBLE))"
            return "NULL"

        if fn_name == "TIME":
            # TIME(hour, minute, second) → MAKE_TIME
            if len(expr.args) >= 3:
                h = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                m = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                s = _as_scalar_sql(compile_expr(expr.args[2], ctx))
                return f"MAKE_TIME({h}, {m}, {s})"
            return "NULL"

        if fn_name == "DATEDIFF":
            # DAX: DATEDIFF(start, end, interval)  DuckDB: DATE_DIFF(interval, start, end)
            if len(expr.args) >= 3:
                start = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                end = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                interval_arg = expr.args[2]
                if isinstance(interval_arg, TableRef):
                    interval = f"'{interval_arg.name.lower()}'"
                elif isinstance(interval_arg, Literal) and isinstance(interval_arg.value, str):
                    interval = f"'{interval_arg.value.lower()}'"
                else:
                    interval = _as_scalar_sql(compile_expr(interval_arg, ctx))
                return f"DATE_DIFF({interval}, CAST({start} AS DATE), CAST({end} AS DATE))"
            return "NULL"

        if fn_name == "HOUR":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"CAST(DATE_PART('hour', {inner}) AS INTEGER)"
            return "NULL"

        if fn_name == "MINUTE":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"CAST(DATE_PART('minute', {inner}) AS INTEGER)"
            return "NULL"

        if fn_name == "SECOND":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"CAST(DATE_PART('second', {inner}) AS INTEGER)"
            return "NULL"

        if fn_name == "QUARTER":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"DATE_PART('quarter', CAST({inner} AS DATE))"
            return "NULL"

        if fn_name == "WEEKDAY":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"(DAYOFWEEK(CAST({inner} AS DATE)) + 1)"
            return "NULL"

        if fn_name == "WEEKNUM":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"WEEKOFYEAR(CAST({inner} AS DATE))"
            return "NULL"

        if fn_name == "CEILING":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                if len(expr.args) >= 2:
                    sig = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                    return f"(CEIL(CAST({inner} AS DOUBLE) / {sig}) * {sig})"
                return f"CEIL(CAST({inner} AS DOUBLE))"
            return "NULL"

        if fn_name == "FLOOR":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                if len(expr.args) >= 2:
                    sig = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                    return f"(FLOOR(CAST({inner} AS DOUBLE) / {sig}) * {sig})"
                return f"FLOOR(CAST({inner} AS DOUBLE))"
            return "NULL"

        if fn_name == "REPLACE":
            # DAX REPLACE(old_text, start_pos, num_chars, new_text)
            # DuckDB: CONCAT(LEFT(text, start-1), new_text, SUBSTR(text, start+num_chars))
            if len(expr.args) >= 4:
                text = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                start = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                num = _as_scalar_sql(compile_expr(expr.args[2], ctx))
                new_text = _as_scalar_sql(compile_expr(expr.args[3], ctx))
                return f"CONCAT(LEFT(CAST({text} AS VARCHAR), {start} - 1), CAST({new_text} AS VARCHAR), SUBSTR(CAST({text} AS VARCHAR), {start} + {num}))"
            return "NULL"

        if fn_name == "LOWER":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"LOWER(CAST({inner} AS VARCHAR))"
            return "NULL"

        if fn_name == "UPPER":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"UPPER(CAST({inner} AS VARCHAR))"
            return "NULL"

        if fn_name == "UNICODE":
            if expr.args:
                inner = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"UNICODE(CAST({inner} AS VARCHAR))"
            return "NULL"

        if fn_name == "USERNAME":
            return "'DaxEngine'"

        if fn_name == "PATH":
            # PATH(id_col, parent_col) → simplified scalar
            if len(expr.args) >= 2:
                id_col = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                return f"CAST({id_col} AS VARCHAR)"
            return "NULL"

        if fn_name == "KEYWORDMATCH":
            # KEYWORDMATCH(text, keyword) → CONTAINS(text, keyword)
            if len(expr.args) >= 2:
                text = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                keyword = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                return f"(CAST({text} AS VARCHAR) LIKE '%' || CAST({keyword} AS VARCHAR) || '%')"
            return "NULL"

        if fn_name == "LINEST":
            # LINEST(known_y, known_x, [const], [stats]) → REGR_SLOPE
            if len(expr.args) >= 2:
                y = _as_scalar_sql(compile_expr(expr.args[0], ctx))
                x = _as_scalar_sql(compile_expr(expr.args[1], ctx))
                return f"REGR_SLOPE(CAST({y} AS DOUBLE), CAST({x} AS DOUBLE))"
            return "NULL"

        spec = registry.get(fn_name) or get_or_register_spec(fn_name)
        if spec.rewrite:
            rewritten = spec.rewrite(expr.args)
            return compile_expr(rewritten, ctx)
        if spec.kind == "scalar":
            compiled_args = [_as_scalar_sql(compile_expr(arg, ctx)) for arg in expr.args]
            if spec.sql_emit:
                return spec.sql_emit(compiled_args, ctx)
            return f"{fn_name}({', '.join(compiled_args)})"
        if spec.kind == "agg":
            # When agg_as_scalar is set (card query), each aggregate with a
            # ColumnRef argument is compiled as a scalar subquery that reads
            # from its home table with relationship-aware JOINs for any
            # cross-table filters.  This prevents fan-out when the outer FROM
            # clause joins multiple tables while still propagating filters
            # from related tables (e.g. Product filter on a Sales aggregate).
            if getattr(ctx, "agg_as_scalar", False) and expr.args and isinstance(expr.args[0], ColumnRef):
                col_ref: ColumnRef = expr.args[0]
                col_sql = f"{quote_ident(col_ref.table)}.{quote_ident(col_ref.column)}"
                compiled_args = [col_sql]
                agg_sql = spec.sql_emit(compiled_args, ctx) if spec.sql_emit else f"{fn_name}({col_sql})"

                # Collect all tables that have active filters.
                filter_tables: set[str] = set()
                for key in ctx.all_filter_keys():
                    if "." in key:
                        filter_tables.add(key.split(".", 1)[0])
                filter_tables.discard(col_ref.table)  # home table handled by FROM

                if filter_tables:
                    # Use relationship-aware JOIN plan for cross-table filters.
                    required = sorted(filter_tables | {col_ref.table})
                    from_clause, connected, _ = _build_rowset_plan_ctx(col_ref.table, required, ctx)
                    where = ctx.where_clause_for_tables(sorted(connected))
                else:
                    from_source = _as_from_source(resolve_table_source_sql(col_ref.table), quote_ident(col_ref.table))
                    from_clause = from_source
                    where = ctx.where_clause(col_ref.table)

                return f"(SELECT {agg_sql} FROM {from_clause}{' ' + where if where else ''})"
            compiled_args = [_as_scalar_sql(compile_expr(arg, ctx)) for arg in expr.args]
            if spec.sql_emit:
                return spec.sql_emit(compiled_args, ctx)
            return f"{fn_name}({', '.join(compiled_args)})"
        if spec.kind == "table":
            return compile_table_expr(expr, ctx)
        if spec.kind == "context":
            return compile_context_function(expr, ctx)
        if spec.kind == "iterator":
            return compile_iterator_function(expr, ctx)
        if spec.kind == "window":
            return compile_window_function(expr, ctx)
        if spec.kind == "info":
            compiled_args = [_as_scalar_sql(compile_expr(arg, ctx)) for arg in expr.args]
            if spec.sql_emit:
                return spec.sql_emit(compiled_args, ctx)
            return f"{fn_name}({', '.join(compiled_args)})"
        compiled_args = [_as_scalar_sql(compile_expr(arg, ctx)) for arg in expr.args]
        if spec.sql_emit:
            return spec.sql_emit(compiled_args, ctx)
        return f"{fn_name}({', '.join(compiled_args)})"
    if isinstance(expr, DaxIteratorFunction):
        return compile_iterator_function(expr, ctx)
    if isinstance(expr, DaxWindowFunction):
        return compile_window_function(expr, ctx)
    raise TypeError(f"Unsupported expression type: {expr}")

def compile_table_expr(expr: Expr, ctx: Context) -> str:
    if isinstance(expr, MeasureRef):
        name = expr.name
        raise ValueError(
            f"Expected TableRef or table expression; got MeasureRef('{name}'). "
            f"Use TableRef(name='{name}') for bare tables."
        )
    if isinstance(expr, TableRef):
        table_name = expr.name
        table_sql = resolve_table_source_sql(table_name)
        where = ctx.where_clause(table_name)
        if not where:
            return table_sql

        head = table_sql.lstrip().upper()
        # If the source is itself a query, alias it and rewrite qualifiers.
        if head.startswith("SELECT") or head.startswith("WITH") or head.startswith("CREATE"):
            from_source = _as_from_source(table_sql, "t")
            pred = where[len("WHERE ") :] if where.startswith("WHERE ") else where
            pred = rewrite_qualifiers_to_alias(pred, "t")
            return normalize_sql(f"(SELECT * FROM {from_source} WHERE {pred})")

        return normalize_sql(f"(SELECT * FROM {table_sql} {where})")
    return _compile_table_expr(
        expr,
        ctx,
        compile_expr=compile_expr,
        find_first_table=find_first_table,
        collect_tables=collect_tables,
        rewrite_calculate_like_context=_rewrite_calculate_like_context,
        try_time_intel_predicate=_try_time_intel_predicate,
    )


def _extract_table_filter_column(expr: Expr) -> Optional[ColumnRef]:
    """Extract the primary ColumnRef from a table expression used as a CALCULATE filter.

    When a table expression like TOPN(...), VALUES(...), ALLSELECTED(...) is used
    as a CALCULATE filter argument, it restricts evaluation to rows where the column
    values are IN the result set.  This helper finds which column that is.

    Patterns:
      TOPN(n, inner_table, order_expr, ...) → recurse into inner_table (arg[1])
      ALLSELECTED(col)                      → col
      VALUES(col)                           → col
      DISTINCT(col)                         → col
      ALL(col)                              → col
      FILTER(table, pred)                   → recurse into table (arg[0])
    """
    if isinstance(expr, ColumnRef):
        return expr
    if isinstance(expr, DaxFunction):
        fn = expr.fn.upper()
        # Single-column table functions
        if fn in ("ALLSELECTED", "VALUES", "DISTINCT", "ALL", "ALLNOBLANKROW"):
            if expr.args and isinstance(expr.args[0], ColumnRef):
                return expr.args[0]
            return None
        # TOPN(n, table_expr, ...) — column comes from the source table (arg[1])
        if fn == "TOPN" and len(expr.args) >= 2:
            return _extract_table_filter_column(expr.args[1])
        # FILTER(table_expr, pred) — column comes from the source table (arg[0])
        if fn == "FILTER" and expr.args:
            return _extract_table_filter_column(expr.args[0])
        # CALCULATETABLE(table_expr, ...) — column comes from arg[0]
        if fn == "CALCULATETABLE" and expr.args:
            return _extract_table_filter_column(expr.args[0])
    return None


def _compile_topn_filter_sql(
    expr: Expr,
    filter_col: ColumnRef,
    ctx: Context,
) -> Optional[str]:
    """Compile a table expression used as a CALCULATE filter into a subquery
    that returns distinct filter-column values.

    Handles the common TOPN pattern:
        TOPN(n, ALLSELECTED(DimTable[Col]), [Measure])
    where the measure references a fact table related to the dimension.

    Returns a SELECT subquery string (without wrapping parens), or None if the
    pattern cannot be compiled with this specialised path.
    """
    if not isinstance(expr, DaxFunction):
        return None

    fn = expr.fn.upper()

    # ── TOPN(n, source, order_expr ...) ──
    if fn == "TOPN" and len(expr.args) >= 3:
        n_sql = compile_expr(expr.args[0], ctx)
        source_expr = expr.args[1]

        # Parse ordering pairs: (expr, direction), ...
        order_pairs: list[tuple[Expr, str]] = []
        idx = 2
        while idx < len(expr.args):
            order_e = expr.args[idx]
            direction = "DESC"  # TOPN default is DESC
            if idx + 1 < len(expr.args):
                next_arg = expr.args[idx + 1]
                is_dir = (
                    (isinstance(next_arg, TableRef) and next_arg.name.upper() in ("ASC", "DESC"))
                    or (isinstance(next_arg, Literal) and isinstance(next_arg.value, str) and next_arg.value.upper() in ("ASC", "DESC"))
                )
                if is_dir:
                    direction = next_arg.name.upper() if isinstance(next_arg, TableRef) else next_arg.value.upper()
                    idx += 1
            order_pairs.append((order_e, direction))
            idx += 1

        # Determine if any order expression is a MeasureRef that needs special
        # relationship-aware compilation (the most common TOPN-as-filter pattern).
        has_measure_order = any(isinstance(o, MeasureRef) for o, _d in order_pairs)

        if has_measure_order:
            # Build a relationship-aware query:
            #   SELECT filter_col FROM (
            #       SELECT dim.filter_col, <compiled_measure> AS "__order_0", ...
            #       FROM dim JOIN fact ON ...
            #       GROUP BY dim.filter_col
            #   ) t ORDER BY t.__order_0 <dir> ... LIMIT n
            dim_table = filter_col.table
            dim_col = filter_col.column

            # Collect all tables referenced by the order measures.
            measure_tables: set[str] = set()
            for order_e, _ in order_pairs:
                if isinstance(order_e, MeasureRef):
                    measure_ir = MEASURES.get(order_e.name.upper())
                    if measure_ir is not None:
                        measure_tables.update(collect_tables(measure_ir))

            # Build the FROM clause with relationships.
            all_tables = measure_tables | {dim_table}
            from_clause, connected, _ = _build_rowset_plan_ctx(dim_table, sorted(all_tables), ctx)

            # Build the ORDER BY expressions.
            order_sql_parts: list[str] = []
            select_extras: list[str] = []
            for i, (order_e, direction) in enumerate(order_pairs):
                alias = f'"__order_{i}"'
                # Use a clean context without agg_as_scalar so that
                # aggregate functions compile as raw aggregates (e.g.
                # SUM(Sales.Sales)) rather than scalar subqueries.  In
                # the TOPN GROUP BY context the raw aggregate is correct.
                topn_ctx = ctx.apply_filters({})  # clones; agg_as_scalar defaults to False

                if isinstance(order_e, MeasureRef):
                    measure_ir = MEASURES.get(order_e.name.upper())
                    if measure_ir is not None:
                        raw_sql = compile_expr(measure_ir, topn_ctx)
                        select_extras.append(f'{raw_sql} AS {alias}')
                    else:
                        raw_sql = compile_expr(order_e, topn_ctx)
                        select_extras.append(f'{raw_sql} AS {alias}')
                else:
                    raw_sql = compile_expr(order_e, topn_ctx)
                    select_extras.append(f'{raw_sql} AS {alias}')
                order_sql_parts.append(f't.{alias} {direction}')

            group_col = f'{quote_ident(dim_table)}.{quote_ident(dim_col)}'
            select_list = f'{group_col}'
            if select_extras:
                select_list += ', ' + ', '.join(select_extras)

            where = ctx.where_clause_for_tables(sorted(connected))
            where_sql = f' {where}' if where else ''

            inner = normalize_sql(
                f'SELECT {select_list} FROM {from_clause}{where_sql} GROUP BY {group_col}'
            )
            order_by = ', '.join(order_sql_parts) if order_sql_parts else '1'

            result_sql = f'SELECT {quote_ident(dim_col)} FROM ({inner}) AS t ORDER BY {order_by} LIMIT {n_sql}'
            return result_sql

        # Non-measure ordering: fall back to generic table expression compilation.
        return None

    # ── Simple single-column table functions: VALUES, ALLSELECTED, DISTINCT, ALL ──
    if fn in ("ALLSELECTED", "VALUES", "DISTINCT", "ALL", "ALLNOBLANKROW"):
        if expr.args and isinstance(expr.args[0], ColumnRef):
            col = expr.args[0]
            from_src = resolve_table_source_sql(col.table)
            return f'SELECT DISTINCT {quote_ident(col.table)}.{quote_ident(col.column)} FROM {from_src}'
        return None

    return None


def _rewrite_calculate_like_context(ctx: Context, filter_args: List[Expr]) -> Context:
    """Apply CALCULATE/CALCULATETABLE filter arguments to produce a rewritten Context.

    v1: supports ALL/REMOVEFILTERS/KEEPFILTERS/ALLSELECTED/ALLEXCEPT/USERELATIONSHIP/TREATAS
    and time-intel predicates.
    """

    replace_filters: Dict[str, str] = {}
    keep_filters: Dict[str, str] = {}
    working_ctx = ctx

    pending_allselected_tables: set[str] = set()
    pending_allselected_keys: set[str] = set()

    def _table_name_from_arg(a0: Expr) -> Optional[str]:
        if isinstance(a0, Literal) and isinstance(a0.value, str):
            return a0.value
        if isinstance(a0, ColumnRef):
            return a0.table
        if isinstance(a0, TableRef):
            return a0.name
        return None

    def _add_filter(col: ColumnRef, predicate_sql: str, keep: bool) -> None:
        key = f"{col.table}.{col.column}"
        if keep:
            if key in keep_filters:
                keep_filters[key] = f"({keep_filters[key]}) AND ({predicate_sql})"
            else:
                keep_filters[key] = predicate_sql
        else:
            if key in replace_filters:
                replace_filters[key] = f"({replace_filters[key]}) AND ({predicate_sql})"
            else:
                replace_filters[key] = predicate_sql

    def _compile_in_values(values: Any) -> Optional[str]:
        if not isinstance(values, (list, tuple, set)):
            return None
        parts: List[str] = []
        for v in list(values):
            if isinstance(v, str):
                parts.append("'" + v.replace("'", "''") + "'")
            elif v is None:
                parts.append("NULL")
            else:
                parts.append(str(v))
        if not parts:
            return None
        return ", ".join(parts)

    def _try_treatas(inner_expr: Expr) -> Optional[Tuple[ColumnRef, str]]:
        if not (isinstance(inner_expr, DaxFunction) and inner_expr.fn.upper() == "TREATAS"):
            return None
        if len(inner_expr.args) < 2:
            return None
        values_arg = inner_expr.args[0]
        col_arg = inner_expr.args[1]
        if not isinstance(col_arg, ColumnRef):
            return None
        in_list: Optional[str] = None
        if isinstance(values_arg, Literal):
            in_list = _compile_in_values(values_arg.value)
        elif isinstance(values_arg, SetLiteral):
            in_list = compile_expr(values_arg, ctx)
        if in_list is None or not str(in_list).strip():
            return None
        col_sql = compile_expr(col_arg, ctx)
        predicate = f"{col_sql} IN ({in_list})"
        return (col_arg, predicate)

    def _apply_removefilters(arg_expr: Expr) -> bool:
        nonlocal working_ctx
        if not (isinstance(arg_expr, DaxFunction) and arg_expr.fn.upper() == "REMOVEFILTERS"):
            return False
        if not arg_expr.args:
            working_ctx = working_ctx.clear_all_filters_both()
            return True
        a0 = arg_expr.args[0]
        if isinstance(a0, ColumnRef):
            working_ctx = working_ctx.remove_filter_key_both(f"{a0.table}.{a0.column}")
            return True
        table_name = _table_name_from_arg(a0)
        if table_name:
            working_ctx = working_ctx.remove_filters_for_table_both(table_name)
            return True
        return False

    def _apply_all(arg_expr: Expr) -> bool:
        nonlocal working_ctx
        if not (isinstance(arg_expr, DaxFunction) and arg_expr.fn.upper() == "ALL"):
            return False
        if not arg_expr.args:
            working_ctx = working_ctx.clear_all_filters_both()
            return True
        a0 = arg_expr.args[0]
        table_name = _table_name_from_arg(a0)
        if table_name:
            working_ctx = working_ctx.remove_filters_for_table_both(table_name)
            return True
        if isinstance(a0, ColumnRef):
            working_ctx = working_ctx.remove_filter_key_both(f"{a0.table}.{a0.column}")
            return True
        return False

    def _apply_allselected(arg_expr: Expr) -> bool:
        if not (isinstance(arg_expr, DaxFunction) and arg_expr.fn.upper() == "ALLSELECTED"):
            return False
        if not arg_expr.args:
            return True
        a0 = arg_expr.args[0]
        if isinstance(a0, ColumnRef):
            pending_allselected_keys.add(f"{a0.table}.{a0.column}")
            return True
        table_name = _table_name_from_arg(a0)
        if table_name:
            pending_allselected_tables.add(table_name)
            return True
        return True

    def _apply_allexcept(arg_expr: Expr) -> bool:
        nonlocal working_ctx
        if not (isinstance(arg_expr, DaxFunction) and arg_expr.fn.upper() == "ALLEXCEPT"):
            return False
        if len(arg_expr.args) < 1:
            return False
        table_arg = arg_expr.args[0]
        table_name = _table_name_from_arg(table_arg)
        if not table_name:
            return False
        keep_keys: List[str] = []
        for a in arg_expr.args[1:]:
            if isinstance(a, ColumnRef):
                keep_keys.append(f"{a.table}.{a.column}")
        working_ctx = working_ctx.remove_all_except_both(table_name, keep_keys)
        return True

    def _apply_userelationship(arg_expr: Expr) -> bool:
        nonlocal working_ctx
        if not (isinstance(arg_expr, DaxFunction) and arg_expr.fn.upper() == "USERELATIONSHIP"):
            return False
        if len(arg_expr.args) < 2:
            return True
        a = arg_expr.args[0]
        b = arg_expr.args[1]
        if not (isinstance(a, ColumnRef) and isinstance(b, ColumnRef)):
            return True

        def _matches(rel: Relationship) -> bool:
            e1 = (rel.from_table, rel.from_column)
            e2 = (rel.to_table, rel.to_column)
            x = (a.table, a.column)
            y = (b.table, b.column)
            return (x == e1 and y == e2) or (x == e2 and y == e1)

        for rel in RELATIONSHIPS:
            if _matches(rel):
                working_ctx = working_ctx.activate_relationship(rel.rel_id)
                break
        return True

    for filter_arg in filter_args:
        keep = False
        inner = filter_arg
        if isinstance(filter_arg, DaxFunction) and filter_arg.fn.upper() == "KEEPFILTERS" and filter_arg.args:
            keep = True
            inner = filter_arg.args[0]

        if (
            _apply_removefilters(inner)
            or _apply_all(inner)
            or _apply_allselected(inner)
            or _apply_allexcept(inner)
            or _apply_userelationship(inner)
        ):
            continue

        time_result = _try_time_intel_predicate(inner, working_ctx)
        if time_result is not None:
            key, predicate_sql = time_result
            if keep:
                working_ctx = working_ctx.apply_filters_keep({key: predicate_sql})
            else:
                working_ctx = working_ctx.apply_filters({key: predicate_sql})
            continue

        treatas_result = _try_treatas(inner)
        if treatas_result is not None:
            col, predicate_sql = treatas_result
            _add_filter(col, predicate_sql, keep)
            continue

        # FILTER(table_expr, predicate) as a CALCULATE argument:
        # Evaluate the predicate over the (possibly ALL-cleared) table and
        # apply it as a context filter.
        if isinstance(inner, DaxFunction) and inner.fn.upper() == "FILTER" and len(inner.args) >= 2:
            table_arg = inner.args[0]
            pred_arg = inner.args[1]
            # If the table_expr is ALL(table), clear existing filters first.
            if isinstance(table_arg, DaxFunction) and table_arg.fn.upper() == "ALL":
                _apply_all(table_arg)
            # Compile the predicate and discover the column(s) it references.
            predicate_sql = compile_expr(pred_arg, ctx)
            if isinstance(pred_arg, DaxBinaryOp) and isinstance(pred_arg.left, ColumnRef):
                _add_filter(pred_arg.left, predicate_sql, keep)
            else:
                # Fallback: route the filter to the first table found in the predicate.
                tbl = find_first_table(pred_arg) or find_first_table(table_arg)
                if tbl:
                    # Use a synthetic key to avoid overwriting real column filters.
                    synthetic_col = ColumnRef(table=tbl, column=f"__filter_expr_{len(replace_filters) + len(keep_filters)}")
                    _add_filter(synthetic_col, predicate_sql, keep)
            continue

        if isinstance(inner, DaxBinaryOp) and isinstance(inner.left, ColumnRef):
            column_ref: ColumnRef = inner.left
            predicate_sql = compile_expr(inner, ctx)
            _add_filter(column_ref, predicate_sql, keep)
            continue

        # ── Table expression as CALCULATE filter (TOPN, VALUES, ALLSELECTED, …) ──
        # E.g. CALCULATE([M], KEEPFILTERS(TOPN(5, ALLSELECTED(Reseller[Reseller]), [Sales Sum])))
        # Compiles the table expression to SQL and creates an IN predicate.
        if isinstance(inner, DaxFunction) and inner.fn.upper() in _KNOWN_TABLE_FN_NAMES:
            filter_col = _extract_table_filter_column(inner)
            if filter_col is not None:
                topn_sql = _compile_topn_filter_sql(inner, filter_col, ctx)
                if topn_sql is not None:
                    col_sql = f'{quote_ident(filter_col.table)}.{quote_ident(filter_col.column)}'
                    predicate = f'{col_sql} IN ({topn_sql})'
                    _add_filter(filter_col, predicate, keep)
                else:
                    # Fallback: generic table expression compilation
                    table_sql = _compile_table_expr(
                        inner, ctx,
                        compile_expr=compile_expr,
                        find_first_table=find_first_table,
                        collect_tables=collect_tables,
                        rewrite_calculate_like_context=_rewrite_calculate_like_context,
                        try_time_intel_predicate=_try_time_intel_predicate,
                    )
                    col_sql = f'{quote_ident(filter_col.table)}.{quote_ident(filter_col.column)}'
                    predicate = f'{col_sql} IN (SELECT {quote_ident(filter_col.column)} FROM ({table_sql}) AS "__tbl_filter__")'
                    _add_filter(filter_col, predicate, keep)
            continue

    new_ctx = working_ctx.apply_filters(replace_filters)
    if keep_filters:
        new_ctx = new_ctx.apply_filters_keep(keep_filters)

    for t in pending_allselected_tables:
        new_ctx = new_ctx.remove_inner_filters_for_table(t)
    for k in pending_allselected_keys:
        new_ctx = new_ctx.remove_inner_filter_key(k)

    return new_ctx

def compile_context_function(expr: DaxFunction, ctx: Context) -> str:
    ctx = ctx.set_outer_from_current()
    fn_name = expr.fn.upper()
    if fn_name == "TOTALMTD":
        # TOTALMTD(expr, Date[Date]) => CALCULATE(expr, DATESMTD(Date[Date]))
        if len(expr.args) < 2:
            if expr.args:
                return compile_measure(expr.args[0], ctx)  # type: ignore[arg-type]
            return normalize_sql("SELECT NULL")
        inner_expr = expr.args[0]
        date_col = expr.args[1]
        rewritten = DaxFunction(
            "CALCULATE",
            [
                inner_expr,
                DaxFunction("DATESMTD", [date_col]),
            ],
        )
        return compile_context_function(rewritten, ctx)
    if fn_name == "TOTALQTD":
        # TOTALQTD(expr, Date[Date]) => CALCULATE(expr, DATESQTD(Date[Date]))
        if len(expr.args) < 2:
            if expr.args:
                return compile_measure(expr.args[0], ctx)  # type: ignore[arg-type]
            return normalize_sql("SELECT NULL")
        inner_expr = expr.args[0]
        date_col = expr.args[1]
        rewritten = DaxFunction(
            "CALCULATE",
            [
                inner_expr,
                DaxFunction("DATESQTD", [date_col]),
            ],
        )
        return compile_context_function(rewritten, ctx)
    if fn_name == "TOTALYTD":
        # TOTALYTD(expr, Date[Date]) => CALCULATE(expr, DATESYTD(Date[Date]))
        if len(expr.args) < 2:
            # Safe fallback: compile the first arg under current context.
            if expr.args:
                return compile_measure(expr.args[0], ctx)  # type: ignore[arg-type]
            return normalize_sql("SELECT NULL")
        inner_expr = expr.args[0]
        date_col = expr.args[1]
        rewritten = DaxFunction(
            "CALCULATE",
            [
                inner_expr,
                DaxFunction("DATESYTD", [date_col]),
            ],
        )
        return compile_context_function(rewritten, ctx)
    if fn_name == "CALCULATE":
        measure_expr = expr.args[0]
        new_ctx = _rewrite_calculate_like_context(ctx, list(expr.args[1:]))
        return compile_measure(measure_expr, new_ctx)
    elif fn_name == "ALL":
        # Context-only function: it should disappear from final SQL.
        return "SELECT 1"  # placeholder
    return compile_expr(expr.args[0], ctx)

def compile_iterator_function(expr: Union[DaxFunction, DaxIteratorFunction], ctx: Context) -> str:
    return _compile_iterator_function(
        expr,
        ctx,
        compile_expr=compile_expr,
        compile_table_expr=compile_table_expr,
        compile_measure=compile_measure,
    )

def compile_window_function(expr: Union[DaxFunction, DaxWindowFunction], ctx: Context) -> str:
    """Lower window/analytic functions.

    v1: implement RANKX in common Power BI patterns.
    """

    def _quote_ident(name: str) -> str:
        if name.isidentifier():
            return name
        return '"' + name.replace('"', '""') + '"'

    def _parse_order_dir(arg: Expr) -> str:
        if isinstance(arg, Literal) and isinstance(arg.value, str):
            v = arg.value.strip().upper()
            if v in {"ASC", "DESC"}:
                return v
        return "ASC"

    def _parse_ties(arg: Expr) -> str:
        if isinstance(arg, Literal) and isinstance(arg.value, str):
            v = arg.value.strip().upper()
            if v in {"SKIP", "DENSE"}:
                return v
        return "SKIP"

    if isinstance(expr, DaxWindowFunction):
        fn_name = expr.fn.upper()
        # Current parser/IR mostly produces DaxFunction; keep placeholder coverage.
        if fn_name != "RANKX":
            return f"{fn_name}()"

        table_expr = expr.table
        scalar_expr = expr.expr
        order_dir = "DESC"
        ties = "SKIP"
    else:
        fn_name = expr.fn.upper()
        if fn_name != "RANKX":
            return f"{fn_name}({', '.join(compile_expr(a, ctx) for a in expr.args)})"

        if len(expr.args) < 2:
            return "NULL"

        table_expr = expr.args[0]
        scalar_expr = expr.args[1]
        # args[2] is [value] (ignored v1)
        order_dir = _parse_order_dir(expr.args[3]) if len(expr.args) >= 4 else "DESC"
        ties = _parse_ties(expr.args[4]) if len(expr.args) >= 5 else "SKIP"

    # Extract key column for common shapes: VALUES/ALL/DISTINCT(Table[Col])
    key_col: Optional[ColumnRef] = None
    table_is_all = False
    table_is_all_table = False
    all_table_name: Optional[str] = None
    if isinstance(table_expr, DaxFunction) and table_expr.args:
        up = table_expr.fn.upper()
        if up in {"VALUES", "DISTINCT", "ALL"} and isinstance(table_expr.args[0], ColumnRef):
            key_col = table_expr.args[0]
            table_is_all = up == "ALL"
        elif up == "ALL" and isinstance(table_expr.args[0], TableRef):
            # ALL(Table) — table-level ALL, use the scalar_expr column as key
            table_is_all = True
            table_is_all_table = True
            all_table_name = table_expr.args[0].name

    if key_col is None and not table_is_all_table:
        # No reliable correlation key available; keep SQL valid.
        return "(SELECT NULL)"

    # For ALL(Table) pattern: extract column from scalar_expr to use as ranking key
    if table_is_all_table and all_table_name:
        # RANKX(ALL(Sales), Sales[Amount], value) — rank value among all amounts
        val_sql = compile_expr(scalar_expr, ctx)
        from_src = resolve_table_source_sql(all_table_name)
        rank_value = None
        if isinstance(expr, DaxFunction) and len(expr.args) >= 3:
            rank_value = compile_expr(expr.args[2], ctx)
        rank_fn = "DENSE_RANK" if ties == "DENSE" else "RANK"
        base = f"SELECT {val_sql} AS val FROM {from_src}"
        if rank_value is not None:
            # Add the target value and rank it
            ranked = (
                f"SELECT {rank_fn}() OVER (ORDER BY val {order_dir}) AS rnk, val "
                f"FROM ({base}) AS t"
            )
            return f"(SELECT rnk FROM ({ranked}) AS r WHERE r.val = {rank_value} LIMIT 1)"
        ranked = (
            f"SELECT {rank_fn}() OVER (ORDER BY val {order_dir}) AS rnk "
            f"FROM ({base}) AS t"
        )
        return f"(SELECT r.rnk FROM ({ranked}) AS r ORDER BY r.rnk LIMIT 1)"

    local_ctx = ctx
    if table_is_all:
        local_ctx = local_ctx.remove_filter_key_both(f"{key_col.table}.{key_col.column}")

    required_tables: set[str] = {key_col.table}
    for t in collect_tables(scalar_expr):
        required_tables.add(t)
    for k in local_ctx.all_filter_keys():
        if "." in k:
            required_tables.add(k.split(".", 1)[0])

    root_table = key_col.table
    from_clause, connected, _ = _build_rowset_plan_ctx(root_table, sorted(required_tables), local_ctx)
    where = local_ctx.where_clause_for_tables(sorted(connected))
    where_sql = f" {where}" if where else ""

    key_sql = compile_expr(key_col, local_ctx)
    val_sql = compile_expr(scalar_expr, local_ctx)

    base = f"SELECT {key_sql} AS key, {val_sql} AS val FROM {from_clause}{where_sql} GROUP BY {key_sql}"
    rank_fn = "DENSE_RANK" if ties == "DENSE" else "RANK"
    ranked = (
        f"SELECT key, {rank_fn}() OVER (ORDER BY val {order_dir}) AS rnk "
        f"FROM ({base}) AS t"
    )

    # Correlate to current row when evaluated inside ADDCOLUMNS/SELECTCOLUMNS.
    if ctx.row_context_alias:
        outer_key = f"{ctx.row_context_alias}.{_quote_ident(key_col.column)}"
        return f"(SELECT r.rnk FROM ({ranked}) AS r WHERE r.key = {outer_key} LIMIT 1)"

    # No row context: return the first rank (or NULL if empty).
    return f"(SELECT r.rnk FROM ({ranked}) AS r ORDER BY r.rnk LIMIT 1)"

def find_first_table(expr: Expr) -> Optional[str]:
    if isinstance(expr, ColumnRef):
        return expr.table
    if isinstance(expr, TableRef):
        # Keywords parsed as TableRef should not be treated as tables.
        if expr.name.upper() in ("TRUE", "FALSE", "ASC", "DESC"):
            return None
        return expr.name
    if isinstance(expr, MeasureRef):
        definition = _resolve_measure(expr.name)
        if definition is None:
            return None
        return find_first_table(definition)
    if isinstance(expr, DaxBinaryOp):
        left_table = find_first_table(expr.left)
        if left_table:
            return left_table
        return find_first_table(expr.right)
    if isinstance(expr, DaxFunction):
        # These compile to self-contained scalar subqueries and should not force
        # an outer FROM that would multiply rows.
        if expr.fn.upper() in {
            "HASONEVALUE",
            "SELECTEDVALUE",
            "HASONEFILTER",
            "ISFILTERED",
            "ISCROSSFILTERED",
            "CONCATENATEX",
            "COUNTROWS",
            "RANKX",
            "SUMX",
            "AVERAGEX",
            "COUNTX",
            "COUNTAX",
            "MAXX",
            "MINX",
            "PRODUCTX",
            "GEOMEANX",
            "MEDIANX",
            "LINESTX",
            "PERCENTILEX.EXC",
            "PERCENTILEX.INC",
            "STDEVX.S",
            "STDEVX.P",
            "VARX.S",
            "VARX.P",
        }:
            return None
        for arg in expr.args:
            tbl = find_first_table(arg)
            if tbl:
                return tbl
    if isinstance(expr, DaxIteratorFunction):
        return find_first_table(expr.table)
    if isinstance(expr, DaxWindowFunction):
        return find_first_table(expr.table)
    return None

def compile_measure(expr: ScalarExpr, ctx: Context) -> str:
    ctx = ctx.set_outer_from_current()
    base_table = find_first_table(expr)
    compiled_expr = compile_expr(expr, ctx)
    # If the compiled expression is itself a full query (e.g., context function like CALCULATE),
    # return it directly to avoid wrapping with another SELECT.
    s = compiled_expr.strip()
    # Unwrap BALANCED outer parens only (not bare subquery arithmetic like "(SELECT ...) - (SELECT ...)")
    inner = s
    while inner.startswith("("):
        depth = 0
        balanced_end = -1
        for i, c in enumerate(inner):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            if depth == 0:
                balanced_end = i
                break
        if balanced_end == len(inner) - 1:
            # Outer parens wrap the entire expression — safe to strip
            inner = inner[1:-1].strip()
        else:
            # First ( closes before end — this is subquery arithmetic, stop stripping
            break
    head = inner.upper()
    if head.startswith("SELECT") or head.startswith("WITH") or head.startswith("CREATE"):
        return normalize_sql(compiled_expr)
    if not base_table:
        return normalize_sql(f"SELECT {compiled_expr}")
    # Relationship-aware rowset: if context filters reference other tables, include them
    # in the FROM/JOIN tree so those predicates can be applied.
    required_tables: set[str] = {base_table}
    for k in ctx.all_filter_keys():
        if "." in k:
            required_tables.add(k.split(".", 1)[0])
    from_clause, connected, _ = _build_rowset_plan_ctx(base_table, sorted(required_tables), ctx)
    where = ctx.where_clause_for_tables(sorted(connected))
    return normalize_sql(f"SELECT {compiled_expr} AS result FROM {from_clause} {where}")

# === Register built-in functions ===

# Scalar, agg, table, context, iterator, window, info
register(DaxFnSpec(
    name="CALCULATE",
    kind="context",
    arity_min=1,
    arity_max=999,
    description="Context transform: CALCULATE(expr, filters...).",
))
register(DaxFnSpec(
    name="CALCULATETABLE",
    kind="table",
    arity_min=1,
    arity_max=999,
    description="Context transform (table): CALCULATETABLE(tableExpr, filters...).",
))
register(DaxFnSpec(
    name="FILTERS",
    kind="table",
    arity_min=1,
    arity_max=1,
    description="Table introspection v1: FILTERS(col) => VALUES(col) under effective context.",
))
register(DaxFnSpec(
    name="TOTALYTD",
    kind="context",
    arity_min=1,
    arity_max=2,
    description="Time intelligence: TOTALYTD(expr, date_col) => CALCULATE(expr, DATESYTD(date_col)).",
))
register(DaxFnSpec(
    name="TOTALMTD",
    kind="context",
    arity_min=1,
    arity_max=2,
    description="Time intelligence: TOTALMTD(expr, date_col) => CALCULATE(expr, DATESMTD(date_col)).",
))
register(DaxFnSpec(
    name="TOTALQTD",
    kind="context",
    arity_min=1,
    arity_max=2,
    description="Time intelligence: TOTALQTD(expr, date_col) => CALCULATE(expr, DATESQTD(date_col)).",
))
register(DaxFnSpec(
    name="SUM",
    kind="agg",
    arity_min=1,
    arity_max=1,
    sql_emit=lambda args, ctx: f"SUM({args[0]})",
    description="Sum aggregator.",
))
register(DaxFnSpec(
    name="AVERAGE",
    kind="agg",
    arity_min=1,
    arity_max=1,
    sql_emit=lambda args, ctx: f"AVG({args[0]})",
    description="Average aggregator. DAX AVERAGE → SQL AVG.",
))
register(DaxFnSpec(
    name="COUNT",
    kind="agg",
    arity_min=1,
    arity_max=1,
    sql_emit=lambda args, ctx: f"COUNT({args[0]})",
    description="Count aggregator.",
))
register(DaxFnSpec(
    name="COUNTA",
    kind="agg",
    arity_min=1,
    arity_max=1,
    sql_emit=lambda args, ctx: f"COUNT({args[0]})",
    description="Count non-blank aggregator. Maps to SQL COUNT().",
))
register(DaxFnSpec(
    name="DISTINCTCOUNT",
    kind="agg",
    arity_min=1,
    arity_max=1,
    sql_emit=lambda args, ctx: f"COUNT(DISTINCT {args[0]})",
    description="Distinct count aggregator. DAX DISTINCTCOUNT → SQL COUNT(DISTINCT ...).",
))
register(DaxFnSpec(
    name="SUMX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: SUMX(table, expr)."
))
register(DaxFnSpec(
    name="AVERAGEX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: AVERAGEX(table, expr)."
))
register(DaxFnSpec(
    name="COUNTX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: COUNTX(table, expr)."
))
register(DaxFnSpec(
    name="COUNTAX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: COUNTAX(table, expr)."
))
register(DaxFnSpec(
    name="MAXX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: MAXX(table, expr)."
))
register(DaxFnSpec(
    name="MINX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: MINX(table, expr)."
))
register(DaxFnSpec(
    name="PRODUCTX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: PRODUCTX(table, expr)."
))
register(DaxFnSpec(
    name="GEOMEANX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: GEOMEANX(table, expr)."
))
register(DaxFnSpec(
    name="MEDIANX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: MEDIANX(table, expr)."
))
register(DaxFnSpec(
    name="CONCATENATEX",
    kind="iterator",
    arity_min=2,
    arity_max=4,
    description="Iterator: CONCATENATEX(table, expr, [delimiter], [orderBy])."
))
register(DaxFnSpec(
    name="LINESTX",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: LINESTX(table, expr)."
))
register(DaxFnSpec(
    name="PERCENTILEX.EXC",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: PERCENTILEX.EXC(table, expr)."
))
register(DaxFnSpec(
    name="PERCENTILEX.INC",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: PERCENTILEX.INC(table, expr)."
))
register(DaxFnSpec(
    name="STDEVX.S",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: STDEVX.S(table, expr)."
))
register(DaxFnSpec(
    name="STDEVX.P",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: STDEVX.P(table, expr)."
))
register(DaxFnSpec(
    name="VARX.S",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: VARX.S(table, expr)."
))
register(DaxFnSpec(
    name="VARX.P",
    kind="iterator",
    arity_min=2,
    arity_max=2,
    description="Iterator: VARX.P(table, expr)."
))
register(DaxFnSpec(
    name="RANKX",
    kind="window",
    arity_min=2,
    arity_max=5,
    description="Window: RANKX(table, expr, ...)."
))
# ... (register all other built-ins as before, omitted for brevity) ...

# === TODO stubs for future expansion ===

# TODO: Relationship graph & join rewriting (USERELATIONSHIP, CROSSFILTER)
# TODO: Time intelligence rewrite strategy (DATESYTD, SAMEPERIODLASTYEAR, etc.)
# TODO: Full window function lowering (RANKX, etc.)
if __name__ == "__main__":
    from .demo import main

    main()