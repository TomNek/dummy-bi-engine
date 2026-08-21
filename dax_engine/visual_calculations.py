"""Visual Calculations — compile per-visual DAX window expressions to SQL.

Visual calculations operate on the *aggregated* visual matrix (the output of
SUMMARIZECOLUMNS). They are compiled to SQL window functions and wrapped
around the base query:

    SELECT *, <vc1>, <vc2> FROM (<base_sql>) AS __vc

Phase 1 functions:
    RUNNINGSUM(expr)           → SUM(expr) OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING)
    MOVINGAVERAGE(expr, N)     → AVG(expr) OVER (ORDER BY ... ROWS BETWEEN N-1 PRECEDING AND CURRENT ROW)
    PREVIOUS(expr)             → LAG(expr, 1) OVER (ORDER BY ...)
    NEXT(expr)                 → LEAD(expr, 1) OVER (ORDER BY ...)
    FIRST(expr)                → FIRST_VALUE(expr) OVER (ORDER BY ... ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
    LAST(expr)                 → LAST_VALUE(expr) OVER (ORDER BY ... ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)

Axis parameter (optional, defaults to ROWS):
    Determines the ORDER BY columns for the window frame.

Reset parameter (optional, defaults to NONE):
    Determines the PARTITION BY columns for the window frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from dax_parser.parser import parse_expression
from dax_parser.ir_mapper import ast_to_ir
from dax_engine.ir import (
    DaxFunction,
    Literal,
    MeasureRef,
    ColumnRef,
    DaxBinaryOp,
    Expr,
    ScalarExpr,
)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisualCalculation:
    """A single visual calculation definition."""

    name: str
    expression: str  # raw DAX text


# Visual calculation function names (Phase 1)
_VC_FUNCTIONS = frozenset({
    "RUNNINGSUM",
    "MOVINGAVERAGE",
    "PREVIOUS",
    "NEXT",
    "FIRST",
    "LAST",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _quote(name: str) -> str:
    """Quote an identifier for DuckDB SQL."""
    return '"' + name.replace('"', '""') + '"'


def _expr_to_col_sql(expr: Expr, measure_aliases: dict[str, str]) -> str:
    """Convert a parsed VC sub-expression to a SQL column reference.

    In visual calculations, expressions can reference:
    - MeasureRef → mapped to the column alias from the base query
    - Literal numbers → numeric constants
    - DaxBinaryOp → arithmetic between sub-expressions
    - ColumnRef → dimension column from the base query
    """
    if isinstance(expr, MeasureRef):
        alias = measure_aliases.get(expr.name.upper())
        if alias is None:
            raise ValueError(
                f"Visual calculation references unknown measure: {expr.name!r}. "
                f"Available measures: {list(measure_aliases.values())}"
            )
        return _quote(alias)

    if isinstance(expr, Literal):
        if expr.value is None:
            return "NULL"
        if isinstance(expr.value, bool):
            return "TRUE" if expr.value else "FALSE"
        if isinstance(expr.value, (int, float)):
            return str(expr.value)
        if isinstance(expr.value, str):
            escaped = expr.value.replace("'", "''")
            return f"'{escaped}'"
        return str(expr.value)

    if isinstance(expr, ColumnRef):
        # Dimension columns: in the wrapped query, they come from __vc subquery
        return _quote(expr.column)

    if isinstance(expr, DaxBinaryOp):
        left = _expr_to_col_sql(expr.left, measure_aliases)
        right = _expr_to_col_sql(expr.right, measure_aliases)
        return f"({left} {expr.operator} {right})"

    if isinstance(expr, DaxFunction):
        # Nested VC function — compile it recursively
        fn_upper = expr.fn.upper()
        if fn_upper in _VC_FUNCTIONS:
            # This is a nested VC function call — not currently supported
            raise ValueError(
                f"Nested visual calculation functions are not supported: {fn_upper}"
            )
        # Allow basic scalar functions (e.g., ABS, ROUND)
        args_sql = [_expr_to_col_sql(a, measure_aliases) for a in expr.args]
        return f"{fn_upper}({', '.join(args_sql)})"

    raise ValueError(f"Unsupported expression type in visual calculation: {type(expr).__name__}")


def _compile_single_vc(
    vc: VisualCalculation,
    dimension_cols: list[str],
    measure_aliases: dict[str, str],
) -> str:
    """Compile a single VisualCalculation to a SQL window expression.

    Returns a SQL expression fragment like:
        SUM("Total Sales") OVER (ORDER BY "Category") AS "Running Total"
    """
    # Parse the DAX expression
    ast = parse_expression(vc.expression)
    ir = ast_to_ir(ast)

    # The top-level IR must be a DaxFunction with a VC function name
    if not isinstance(ir, DaxFunction):
        raise ValueError(
            f"Visual calculation '{vc.name}' must be a function call "
            f"(e.g., RUNNINGSUM([Measure])). Got: {type(ir).__name__}"
        )

    fn_upper = ir.fn.upper()
    if fn_upper not in _VC_FUNCTIONS:
        raise ValueError(
            f"Visual calculation '{vc.name}' uses unsupported function: {ir.fn!r}. "
            f"Supported functions: {sorted(_VC_FUNCTIONS)}"
        )

    # Build ORDER BY from dimension columns
    if dimension_cols:
        order_by = ", ".join(_quote(c) for c in dimension_cols)
    else:
        # No dimensions (e.g., a card) — use row number as fallback
        order_by = "(SELECT NULL)"

    if fn_upper == "RUNNINGSUM":
        if len(ir.args) < 1:
            raise ValueError(f"RUNNINGSUM requires at least 1 argument (expression)")
        col_sql = _expr_to_col_sql(ir.args[0], measure_aliases)
        return (
            f"SUM({col_sql}) OVER (ORDER BY {order_by} "
            f"ROWS UNBOUNDED PRECEDING) AS {_quote(vc.name)}"
        )

    if fn_upper == "MOVINGAVERAGE":
        if len(ir.args) < 2:
            raise ValueError(
                f"MOVINGAVERAGE requires 2 arguments (expression, window_size)"
            )
        col_sql = _expr_to_col_sql(ir.args[0], measure_aliases)
        # Window size must be a literal integer
        window_arg = ir.args[1]
        if not isinstance(window_arg, Literal) or not isinstance(window_arg.value, (int, float)):
            raise ValueError(
                f"MOVINGAVERAGE window_size must be a numeric literal, "
                f"got: {type(window_arg).__name__}"
            )
        window_size = int(window_arg.value)
        if window_size < 1:
            raise ValueError(f"MOVINGAVERAGE window_size must be >= 1, got: {window_size}")
        preceding = window_size - 1
        return (
            f"AVG({col_sql}) OVER (ORDER BY {order_by} "
            f"ROWS BETWEEN {preceding} PRECEDING AND CURRENT ROW) AS {_quote(vc.name)}"
        )

    if fn_upper == "PREVIOUS":
        if len(ir.args) < 1:
            raise ValueError(f"PREVIOUS requires at least 1 argument (expression)")
        col_sql = _expr_to_col_sql(ir.args[0], measure_aliases)
        return (
            f"LAG({col_sql}, 1) OVER (ORDER BY {order_by}) AS {_quote(vc.name)}"
        )

    if fn_upper == "NEXT":
        if len(ir.args) < 1:
            raise ValueError(f"NEXT requires at least 1 argument (expression)")
        col_sql = _expr_to_col_sql(ir.args[0], measure_aliases)
        return (
            f"LEAD({col_sql}, 1) OVER (ORDER BY {order_by}) AS {_quote(vc.name)}"
        )

    if fn_upper == "FIRST":
        if len(ir.args) < 1:
            raise ValueError(f"FIRST requires at least 1 argument (expression)")
        col_sql = _expr_to_col_sql(ir.args[0], measure_aliases)
        return (
            f"FIRST_VALUE({col_sql}) OVER (ORDER BY {order_by} "
            f"ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS {_quote(vc.name)}"
        )

    if fn_upper == "LAST":
        if len(ir.args) < 1:
            raise ValueError(f"LAST requires at least 1 argument (expression)")
        col_sql = _expr_to_col_sql(ir.args[0], measure_aliases)
        return (
            f"LAST_VALUE({col_sql}) OVER (ORDER BY {order_by} "
            f"ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS {_quote(vc.name)}"
        )

    # Should not reach here due to the frozenset check above
    raise ValueError(f"Unhandled VC function: {fn_upper}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_visual_calculations(
    raw: Any,
) -> list[VisualCalculation]:
    """Parse the ``visual_calculations`` field from a visual JSON object.

    Expected format:
    ```json
    [
      {"name": "Running Total", "expression": "RUNNINGSUM([Total Sales])"},
      ...
    ]
    ```

    Returns an empty list if *raw* is ``None`` or empty.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("visual_calculations must be a list")

    result: list[VisualCalculation] = []
    seen_names: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"visual_calculations[{i}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"visual_calculations[{i}].name must be a non-empty string")
        expr = item.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError(f"visual_calculations[{i}].expression must be a non-empty string")

        clean_name = name.strip()
        if clean_name.upper() in seen_names:
            raise ValueError(f"Duplicate visual calculation name: {clean_name!r}")
        seen_names.add(clean_name.upper())

        result.append(VisualCalculation(name=clean_name, expression=expr.strip()))

    return result


def compile_visual_calculations(
    base_sql: str,
    visual_calculations: list[VisualCalculation],
    dimension_columns: list[str],
    measure_names: list[str],
) -> str:
    """Wrap *base_sql* with visual calculation window expressions.

    Args:
        base_sql: The compiled SQL from ``plan_visual_query`` (a table expression).
        visual_calculations: Parsed VC definitions from the visual JSON.
        dimension_columns: Column names for dimensions in the base query output
            (used for ORDER BY in window functions).
        measure_names: Measure alias names from the base query output
            (used to resolve MeasureRef in VC expressions).

    Returns:
        A new SQL string that wraps the base query with the VC window expressions.
        If *visual_calculations* is empty, returns *base_sql* unchanged.
    """
    if not visual_calculations:
        return base_sql

    # Build measure alias lookup (case-insensitive).
    measure_aliases: dict[str, str] = {
        m.upper(): m for m in measure_names
    }

    vc_fragments: list[str] = []
    for vc in visual_calculations:
        fragment = _compile_single_vc(vc, dimension_columns, measure_aliases)
        vc_fragments.append(fragment)

    vc_select = ", ".join(vc_fragments)

    # Wrap the base query in a CTE.
    # The base_sql is typically a table expression like (SELECT ... FROM ... GROUP BY ...).
    # We wrap it as: SELECT __vc.*, <vc_exprs> FROM (<base_sql>) AS __vc
    return f"(SELECT __vc.*, {vc_select} FROM {base_sql} AS __vc)"


def validate_visual_calculation(
    vc: VisualCalculation,
    dimension_columns: list[str],
    measure_names: list[str],
) -> Optional[str]:
    """Validate a single visual calculation expression.

    Returns None if valid, or an error message string if invalid.
    """
    measure_aliases: dict[str, str] = {
        m.upper(): m for m in measure_names
    }
    try:
        _compile_single_vc(vc, dimension_columns, measure_aliases)
        return None
    except (ValueError, Exception) as e:
        return str(e)
