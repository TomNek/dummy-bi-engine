"""Iterator lowering helpers.

Implementation moved out of `dax_engine.compiler` to keep that module
orchestration-only.

This file must not import `dax_engine.compiler` to avoid circular imports.
"""

from __future__ import annotations

from typing import Callable, Union

from .context import Context
from .ir import ColumnRef, DaxFunction, DaxIteratorFunction, Expr, Literal, MeasureRef, TableRef
from .sql_utils import as_from_source, rewrite_qualifiers_to_alias, rewrite_table_qualifier_to_alias


CompileExpr = Callable[[Expr, Context], str]
CompileTableExpr = Callable[[Expr, Context], str]
CompileMeasure = Callable[[Expr, Context], str]


def compile_iterator_function(
	expr: Union[DaxFunction, DaxIteratorFunction],
	ctx: Context,
	*,
	compile_expr: CompileExpr,
	compile_table_expr: CompileTableExpr,
	compile_measure: CompileMeasure,
) -> str:
	"""Compile iterators like SUMX, AVERAGEX, etc. to SQL derived tables."""

	ctx = ctx.set_outer_from_current()

	# Support both DaxFunction and DaxIteratorFunction for flexibility.
	if isinstance(expr, DaxIteratorFunction):
		fn_name = expr.fn.upper()
		if expr.table is None or expr.expr is None:
			return "NULL"
		table_expr = expr.table
		scalar_expr = expr.expr
	elif isinstance(expr, DaxFunction):
		fn_name = expr.fn.upper()
		if len(expr.args) < 2:
			return "NULL"
		table_expr = expr.args[0]
		scalar_expr = expr.args[1]
	else:
		raise TypeError("Not an iterator function")

	agg_fn = "SUM" if fn_name == "SUMX" else "AVG" if fn_name == "AVERAGEX" else fn_name.rstrip("X")

	# Extended iterator aggregate mapping
	_ITER_AGG_MAP = {
		"SUMX": "SUM", "AVERAGEX": "AVG", "COUNTX": "COUNT", "COUNTAX": "COUNT",
		"MAXX": "MAX", "MINX": "MIN", "MEDIANX": "MEDIAN",
		"STDEVX.S": "STDDEV_SAMP", "STDEVX.P": "STDDEV_POP",
		"VARX.S": "VAR_SAMP", "VARX.P": "VAR_POP",
		"PERCENTILEX.EXC": "PERCENTILE_DISC", "PERCENTILEX.INC": "PERCENTILE_CONT",
		"LINESTX": "REGR_SLOPE",
	}
	if fn_name in _ITER_AGG_MAP:
		agg_fn = _ITER_AGG_MAP[fn_name]

	try:
		table_sql = compile_table_expr(table_expr, ctx)
	except Exception:
		return "NULL"

	iter_alias = "t"
	from_source = as_from_source(table_sql, iter_alias)
	if from_source == table_sql.strip():
		from_source = f"{table_sql.strip()} AS {iter_alias}"

	local_ctx = ctx

	# Minimal context transition for common iterator table shapes like VALUES(Dim[Key]).
	# This enables AVERAGEX(VALUES(Dim[Key]), [Measure]) patterns by correlating the
	# measure evaluation to the current iterator row.
	if isinstance(table_expr, DaxFunction) and table_expr.args:
		up = table_expr.fn.upper()
		if up in {"VALUES", "DISTINCT", "ALL"} and isinstance(table_expr.args[0], ColumnRef):
			key_col = table_expr.args[0]
			key = f"{key_col.table}.{key_col.column}"

			def _quote_ident(name: str) -> str:
				if name.isidentifier():
					return name
				return '"' + name.replace('"', '""') + '"'

			predicate = f"{compile_expr(key_col, ctx)} = {iter_alias}.{_quote_ident(key_col.column)}"
			local_ctx = local_ctx.apply_filters({key: predicate})
			if up == "ALL":
				local_ctx = local_ctx.remove_filter_key_both(key)

	if isinstance(scalar_expr, MeasureRef):
		# Measures must be evaluated as their own correlated scalar query.
		val_sql = f"({compile_measure(scalar_expr, local_ctx)})"
	else:
		val_sql = compile_expr(scalar_expr, local_ctx)
		# Ensure row references resolve against iterator alias.
		# Use targeted rewriting when we know the specific table name
		# to avoid clobbering subquery aliases (e.g., RELATED's _rel alias).
		_iter_table_name = None
		if isinstance(table_expr, TableRef):
			_iter_table_name = table_expr.name
		elif isinstance(table_expr, DaxFunction) and table_expr.args and isinstance(table_expr.args[0], ColumnRef):
			_iter_table_name = table_expr.args[0].table
		if _iter_table_name:
			val_sql = rewrite_table_qualifier_to_alias(val_sql, _iter_table_name, iter_alias)
		else:
			val_sql = rewrite_qualifiers_to_alias(val_sql, iter_alias)

	# Special iterator functions with non-standard SQL aggregation
	if fn_name == "CONCATENATEX":
		# CONCATENATEX(table, expr, [delimiter], [orderBy])
		delimiter = "', '"
		if isinstance(expr, DaxFunction) and len(expr.args) >= 3:
			delim_arg = expr.args[2]
			if isinstance(delim_arg, Literal) and isinstance(delim_arg.value, str):
				escaped = delim_arg.value.replace("'", "''")
				delimiter = f"'{escaped}'"
			else:
				delimiter = compile_expr(delim_arg, local_ctx)
		inner = f"SELECT {val_sql} AS val FROM {from_source}"
		return f"(SELECT STRING_AGG(CAST(val AS VARCHAR), {delimiter}) FROM ({inner}) AS iter)"

	if fn_name == "GEOMEANX":
		inner = f"SELECT {val_sql} AS val FROM {from_source}"
		return f"(SELECT EXP(AVG(LN(CAST(val AS DOUBLE)))) FROM ({inner}) AS iter WHERE val > 0)"

	if fn_name == "PRODUCTX":
		inner = f"SELECT {val_sql} AS val FROM {from_source}"
		return f"(SELECT LIST_PRODUCT(LIST(CAST(val AS DOUBLE))) FROM ({inner}) AS iter)"

	if fn_name == "LINESTX":
		# LINESTX needs two columns — for now treat val as y, row_number as x
		inner = f"SELECT {val_sql} AS val, ROW_NUMBER() OVER () AS rn FROM {from_source}"
		return f"(SELECT REGR_SLOPE(CAST(val AS DOUBLE), CAST(rn AS DOUBLE)) FROM ({inner}) AS iter)"

	if fn_name in ("PERCENTILEX.EXC", "PERCENTILEX.INC"):
		# PERCENTILEX.EXC/INC(table, expr, k) — 3 args
		k_sql = "0.5"
		if isinstance(expr, DaxFunction) and len(expr.args) >= 3:
			k_sql = compile_expr(expr.args[2], local_ctx)
		qfn = "QUANTILE_DISC" if fn_name == "PERCENTILEX.EXC" else "QUANTILE_CONT"
		inner = f"SELECT {val_sql} AS val FROM {from_source}"
		return f"(SELECT {qfn}(CAST(val AS DOUBLE), {k_sql}) FROM ({inner}) AS iter)"

	inner = f"SELECT {val_sql} AS val FROM {from_source}"
	return f"(SELECT {agg_fn}(val) FROM ({inner}) AS iter)"
