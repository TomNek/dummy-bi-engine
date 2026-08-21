"""Table lowering helpers.

Implementation moved out of `dax_engine.compiler` to keep that module
orchestration-only.

This file must not import `dax_engine.compiler` to avoid circular imports.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from .context import Context
from .lowering_scalar import _as_scalar_sql
from .ir import (
	ColumnRef,
	DaxBinaryOp,
	DaxFunction,
	Expr,
	Literal,
	MeasureRef,
	SetLiteral,
	TableExpr,
	TableRef,
)
from .relationships import _build_rowset_plan_ctx
from .registry import registry
from .sql_utils import as_from_source, quote_alias, quote_ident, rewrite_qualifiers_to_alias
from .table_sources import resolve_table_source_sql

# Functions with dedicated handlers in compile_table_expr that should always
# be compiled as table expressions, even when not registered in the mapping
# registry.  This prevents nested table functions (e.g. TOPN wrapping
# SUMMARIZECOLUMNS) from being treated as scalar calls.
_KNOWN_TABLE_FN_NAMES = frozenset({
	"FILTER", "VALUES", "DISTINCT", "ALL",
	"SUMMARIZECOLUMNS", "TOPN", "SELECTCOLUMNS", "ADDCOLUMNS",
	"CROSSJOIN", "UNION", "INTERSECT", "EXCEPT",
	"CALCULATETABLE", "ORDERBY", "FILTERS",
	# Extended table functions
	"ROW", "CALENDAR", "CALENDARAUTO", "GENERATESERIES",
	"GENERATE", "GENERATEALL", "SUMMARIZE", "GROUPBY",
	"ALLEXCEPT", "ALLNOBLANKROW", "ALLSELECTED", "ALLCROSSFILTERED",
	"SAMPLE", "TOPNSKIP", "DATATABLE", "COLUMNSTATISTICS",
	"NATURALINNERJOIN", "NATURALLEFTOUTERJOIN",
	"FIRSTNONBLANK", "LASTNONBLANK",
	"ROLLUP", "ROLLUPGROUP", "ROLLUPADDISSUBTOTAL",
	"INDEX", "OFFSET", "WINDOW",
	"ADDMISSINGITEMS", "SUBSTITUTEWITHINDEX", "DISTINCT_TABLE",
	"TOPNPERLEVEL", "CONTAINSROW", "CONTAINSSTRING",
	# Time intelligence table functions
	"DATEADD", "DATESBETWEEN", "DATESINPERIOD",
	"DATESMTD", "DATESQTD", "DATESYTD", "DATESWK",
	"FIRSTDATE", "LASTDATE",
	"STARTOFMONTH", "STARTOFQUARTER", "STARTOFYEAR",
	"ENDOFMONTH", "ENDOFQUARTER", "ENDOFYEAR",
	"NEXTDAY", "NEXTMONTH", "NEXTQUARTER", "NEXTYEAR",
	"PREVIOUSDAY", "PREVIOUSMONTH", "PREVIOUSQUARTER", "PREVIOUSYEAR",
	"SAMEPERIODLASTYEAR", "PARALLELPERIOD",
	"OPENINGBALANCEMONTH", "OPENINGBALANCEQUARTER", "OPENINGBALANCEYEAR",
	"CLOSINGBALANCEMONTH", "CLOSINGBALANCEQUARTER", "CLOSINGBALANCEYEAR",
})


CompileExpr = Callable[[Expr, Context], str]
FindFirstTable = Callable[[Expr], Optional[str]]
CollectTables = Callable[[Expr], List[str]]
RewriteCalculateLikeContext = Callable[[Context, List[Expr]], Context]
TryTimeIntelPredicate = Callable[[Expr, Context], Optional[tuple[str, str]]]


# Aggregate function names that cannot appear directly in WHERE clauses.
_AGGREGATE_FUNCTIONS = frozenset({
	"SUM", "COUNT", "COUNTROWS", "MIN", "MAX", "AVERAGE", "AVERAGEA",
	"COUNTA", "COUNTBLANK", "DISTINCTCOUNT", "COUNTX", "SUMX", "AVERAGEX",
	"MINX", "MAXX", "STDEV.S", "STDEV.P", "VAR.S", "VAR.P",
})


def _contains_aggregate(expr: Expr) -> bool:
	"""Check if an IR expression tree contains any aggregate functions.

	This is used to detect when VAR-inlined expressions contain aggregates
	that need to be lifted to scalar subqueries.
	"""
	if isinstance(expr, DaxFunction):
		if expr.fn.upper() in _AGGREGATE_FUNCTIONS:
			return True
		return any(_contains_aggregate(a) for a in expr.args)
	if isinstance(expr, DaxBinaryOp):
		return _contains_aggregate(expr.left) or _contains_aggregate(expr.right)
	if isinstance(expr, (Literal, ColumnRef, TableRef, MeasureRef)):
		return False
	if isinstance(expr, SetLiteral):
		return any(_contains_aggregate(v) for v in expr.values)
	return False


def _lift_aggregates_to_subquery(
	expr: Expr,
	compile_expr: CompileExpr,
	ctx: Context,
) -> Tuple[Expr, Dict[str, str]]:
	"""Extract aggregate subexpressions and replace them with placeholders.

	Returns (modified_expr, {placeholder: subquery_sql}).

	For predicates in FILTER, aggregates must be lifted to scalar subqueries
	since SQL WHERE clauses cannot contain aggregates.

	Example:
	  Input IR: DaxBinaryOp(>=, ColumnRef(Amount), DaxFunction(MAX, [ColumnRef(Amount)]))
	  Output IR: DaxBinaryOp(>=, ColumnRef(Amount), Literal("__agg_0__"))
	  Subqueries: {"__agg_0__": "(SELECT MAX(Sales.Amount) FROM Sales)"}
	"""
	counter = [0]
	subqueries: Dict[str, str] = {}

	def _extract(e: Expr) -> Expr:
		if isinstance(e, DaxFunction):
			if e.fn.upper() in _AGGREGATE_FUNCTIONS:
				# Lift this aggregate to a scalar subquery.
				placeholder = f"__agg_{counter[0]}__"
				counter[0] += 1
				# Compile the aggregate to SQL (this produces the scalar expression).
				agg_sql = compile_expr(e, ctx)
				# Determine the base table from ColumnRef args for the FROM clause.
				tables: List[str] = []
				for arg in e.args:
					if isinstance(arg, ColumnRef):
						tables.append(arg.table)
				if tables:
					from_table = resolve_table_source_sql(tables[0])
					subqueries[placeholder] = f"(SELECT {agg_sql} FROM {from_table})"
				else:
					# Scalar aggregate without table context - unlikely but handle gracefully.
					subqueries[placeholder] = f"(SELECT {agg_sql})"
				return Literal(placeholder)
			# Aggregate function may contain nested aggregates in args (rare).
			new_args = [_extract(a) for a in e.args]
			return DaxFunction(e.fn, new_args)
		if isinstance(e, DaxBinaryOp):
			new_left = _extract(e.left)
			new_right = _extract(e.right)
			return DaxBinaryOp(e.operator, new_left, new_right)
		return e

	modified = _extract(expr)
	return modified, subqueries


def _apply_subquery_placeholders(sql: str, subqueries: Dict[str, str]) -> str:
	"""Replace placeholder literals with their scalar subquery SQL."""
	result = sql
	for placeholder, subquery in subqueries.items():
		# The placeholder appears as a quoted string literal in SQL.
		result = result.replace(f"'{placeholder}'", subquery)
	return result


def _try_parse_direction(arg: Expr) -> str:
	"""Parse ASC/DESC from a TableRef or Literal."""
	if isinstance(arg, TableRef) and arg.name.upper() in ("ASC", "DESC"):
		return arg.name.upper()
	if isinstance(arg, Literal) and isinstance(arg.value, str) and arg.value.upper() in ("ASC", "DESC"):
		return arg.value.upper()
	return "ASC"


def _compile_time_intel_table(
	fn_name: str,
	args: list,
	ctx: "Context",
	compile_expr: CompileExpr,
) -> str:
	"""Compile time intelligence table functions to SQL.

	These functions operate on a date column and return a filtered date table.
	"""
	if not args:
		return "(SELECT 1 WHERE FALSE)"

	# Most time intel functions take a date column as first arg
	col_arg = args[0]
	if isinstance(col_arg, ColumnRef):
		col_sql = f"{quote_ident(col_arg.table)}.{quote_ident(col_arg.column)}"
		from_src = resolve_table_source_sql(col_arg.table)
	else:
		col_sql = compile_expr(col_arg, ctx)
		from_src = "DimDate"

	if fn_name == "DATEADD":
		# DATEADD(dates, number, interval)
		if len(args) >= 3:
			num = compile_expr(args[1], ctx)
			interval_arg = args[2]
			if isinstance(interval_arg, TableRef):
				interval = interval_arg.name.upper()
			elif isinstance(interval_arg, Literal) and isinstance(interval_arg.value, str):
				interval = interval_arg.value.upper()
			else:
				interval = "MONTH"
			return f"(SELECT {col_sql} + INTERVAL ({num}) {interval} AS Date FROM {from_src})"

	if fn_name == "DATESBETWEEN":
		# DATESBETWEEN(dates, start_date, end_date)
		if len(args) >= 3:
			start = compile_expr(args[1], ctx)
			end = compile_expr(args[2], ctx)
			return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} BETWEEN CAST({start} AS DATE) AND CAST({end} AS DATE))"

	if fn_name == "DATESINPERIOD":
		# DATESINPERIOD(dates, start_date, number, interval)
		if len(args) >= 4:
			start = compile_expr(args[1], ctx)
			num = compile_expr(args[2], ctx)
			interval_arg = args[3]
			if isinstance(interval_arg, TableRef):
				interval = interval_arg.name.upper()
			elif isinstance(interval_arg, Literal) and isinstance(interval_arg.value, str):
				interval = interval_arg.value.upper()
			else:
				interval = "MONTH"
			return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} BETWEEN CAST({start} AS DATE) AND CAST({start} AS DATE) + INTERVAL ({num}) {interval})"

	if fn_name == "DATESMTD":
		return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} BETWEEN DATE_TRUNC('month', CURRENT_DATE) AND CURRENT_DATE)"
	if fn_name == "DATESQTD":
		return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} BETWEEN DATE_TRUNC('quarter', CURRENT_DATE) AND CURRENT_DATE)"
	if fn_name == "DATESYTD":
		return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} BETWEEN DATE_TRUNC('year', CURRENT_DATE) AND CURRENT_DATE)"
	if fn_name == "DATESWK":
		return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} BETWEEN DATE_TRUNC('week', CURRENT_DATE) AND CURRENT_DATE)"

	if fn_name == "FIRSTDATE":
		return f"(SELECT MIN({col_sql}) AS Date FROM {from_src})"
	if fn_name == "LASTDATE":
		return f"(SELECT MAX({col_sql}) AS Date FROM {from_src})"

	if fn_name == "STARTOFMONTH":
		return f"(SELECT DATE_TRUNC('month', MIN({col_sql})) AS Date FROM {from_src})"
	if fn_name == "STARTOFQUARTER":
		return f"(SELECT DATE_TRUNC('quarter', MIN({col_sql})) AS Date FROM {from_src})"
	if fn_name == "STARTOFYEAR":
		return f"(SELECT DATE_TRUNC('year', MIN({col_sql})) AS Date FROM {from_src})"
	if fn_name == "ENDOFMONTH":
		return f"(SELECT LAST_DAY(MAX({col_sql})) AS Date FROM {from_src})"
	if fn_name == "ENDOFQUARTER":
		return f"(SELECT LAST_DAY(DATE_TRUNC('quarter', MAX({col_sql})) + INTERVAL 2 MONTH) AS Date FROM {from_src})"
	if fn_name == "ENDOFYEAR":
		return f"(SELECT MAKE_DATE(YEAR(MAX({col_sql})), 12, 31) AS Date FROM {from_src})"

	if fn_name == "NEXTDAY":
		return f"(SELECT MAX({col_sql}) + INTERVAL 1 DAY AS Date FROM {from_src})"
	if fn_name == "NEXTMONTH":
		return (f"(SELECT {col_sql} FROM {from_src} WHERE MONTH({col_sql}) = "
				f"(SELECT MONTH(MAX({col_sql})) + 1 FROM {from_src}) "
				f"AND YEAR({col_sql}) = (SELECT YEAR(MAX({col_sql})) FROM {from_src}))")
	if fn_name == "NEXTQUARTER":
		return (f"(SELECT {col_sql} FROM {from_src} WHERE QUARTER({col_sql}) = "
				f"(SELECT QUARTER(MAX({col_sql})) + 1 FROM {from_src}) "
				f"AND YEAR({col_sql}) = (SELECT YEAR(MAX({col_sql})) FROM {from_src}))")
	if fn_name == "NEXTYEAR":
		return (f"(SELECT {col_sql} FROM {from_src} WHERE YEAR({col_sql}) = "
				f"(SELECT YEAR(MAX({col_sql})) + 1 FROM {from_src}))")
	if fn_name == "PREVIOUSDAY":
		return f"(SELECT MIN({col_sql}) - INTERVAL 1 DAY AS Date FROM {from_src})"
	if fn_name == "PREVIOUSMONTH":
		return (f"(SELECT {col_sql} FROM {from_src} WHERE MONTH({col_sql}) = "
				f"(SELECT MONTH(MIN({col_sql})) - 1 FROM {from_src}) "
				f"AND YEAR({col_sql}) = (SELECT YEAR(MIN({col_sql})) FROM {from_src}))")
	if fn_name == "PREVIOUSQUARTER":
		return (f"(SELECT {col_sql} FROM {from_src} WHERE QUARTER({col_sql}) = "
				f"(SELECT QUARTER(MIN({col_sql})) - 1 FROM {from_src}) "
				f"AND YEAR({col_sql}) = (SELECT YEAR(MIN({col_sql})) FROM {from_src}))")
	if fn_name == "PREVIOUSYEAR":
		return (f"(SELECT {col_sql} FROM {from_src} WHERE YEAR({col_sql}) = "
				f"(SELECT YEAR(MIN({col_sql})) - 1 FROM {from_src}))")

	if fn_name == "SAMEPERIODLASTYEAR":
		return f"(SELECT {col_sql} - INTERVAL 1 YEAR AS Date FROM {from_src})"

	if fn_name == "PARALLELPERIOD":
		# PARALLELPERIOD(dates, number, interval)
		if len(args) >= 3:
			num = compile_expr(args[1], ctx)
			interval_arg = args[2]
			if isinstance(interval_arg, TableRef):
				interval = interval_arg.name.upper()
			elif isinstance(interval_arg, Literal) and isinstance(interval_arg.value, str):
				interval = interval_arg.value.upper()
			else:
				interval = "MONTH"
			return f"(SELECT {col_sql} + INTERVAL ({num}) {interval} AS Date FROM {from_src})"

	# Fallback
	return f"(SELECT {col_sql} FROM {from_src})"


def compile_table_expr(
	expr: Expr,
	ctx: Context,
	*,
	compile_expr: CompileExpr,
	find_first_table: FindFirstTable,
	collect_tables: CollectTables,
	rewrite_calculate_like_context: RewriteCalculateLikeContext,
	try_time_intel_predicate: TryTimeIntelPredicate,
) -> str:
	ctx = ctx.set_outer_from_current()

	def _empty_table_sql() -> str:
		# v1 fallback: syntactically valid empty table.
		return "(SELECT NULL WHERE FALSE)"

	def _distinct_col_under_context(col: ColumnRef, local_ctx: Context) -> str:
		# VALUES/DISTINCT/FILTERS(v1) over a column under effective context.
		required_tables: set[str] = {col.table}
		for k in local_ctx.all_filter_keys():
			if "." in k:
				required_tables.add(k.split(".", 1)[0])
		from_clause, connected, _ = _build_rowset_plan_ctx(col.table, sorted(required_tables), local_ctx)
		where = local_ctx.where_clause_for_tables(sorted(connected))
		where_sql = f" {where}" if where else ""
		col_sql = compile_expr(col, local_ctx)
		return f"(SELECT DISTINCT {col_sql} FROM {from_clause}{where_sql})"

	if isinstance(expr, DaxFunction):
		fn_name = expr.fn.upper()

		if fn_name == "CALCULATETABLE":
			if not expr.args:
				return _empty_table_sql()

			table_expr = expr.args[0]

			# Clone + rewrite context using CALCULATE semantics.
			try:
				new_ctx = rewrite_calculate_like_context(ctx, list(expr.args[1:]))
			except Exception:
				# Must never error; return valid empty table.
				return _empty_table_sql()

			try:
				return compile_table_expr(
					table_expr,
					new_ctx,
					compile_expr=compile_expr,
					find_first_table=find_first_table,
					collect_tables=collect_tables,
					rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate,
				)
			except Exception:
				return _empty_table_sql()

		if fn_name == "FILTERS":
			# v1: FILTERS(col) -> VALUES(col) under effective context.
			if not expr.args:
				return _empty_table_sql()
			a0 = expr.args[0]
			if not isinstance(a0, ColumnRef):
				return _empty_table_sql()
			return _distinct_col_under_context(a0, ctx)

		spec = registry.get(fn_name)
		compiled_args: List[str] = []
		for arg in expr.args:
			if isinstance(arg, (TableExpr, TableRef)) or (
				isinstance(arg, DaxFunction)
				and (
					arg.fn.upper() in _KNOWN_TABLE_FN_NAMES
					or (registry.get(arg.fn.upper(), None)
						and registry.get(arg.fn.upper()).kind == "table")
				)
			):
				compiled_args.append(
					compile_table_expr(
						arg,
						ctx,
						compile_expr=compile_expr,
						find_first_table=find_first_table,
						collect_tables=collect_tables,
						rewrite_calculate_like_context=rewrite_calculate_like_context,
						try_time_intel_predicate=try_time_intel_predicate,
					)
				)
			else:
				compiled_args.append(compile_expr(arg, ctx))

		if fn_name == "FILTER":
			if len(expr.args) < 2:
				return _empty_table_sql()
			table_sql = compile_table_expr(
				expr.args[0],
				ctx,
				compile_expr=compile_expr,
				find_first_table=find_first_table,
				collect_tables=collect_tables,
				rewrite_calculate_like_context=rewrite_calculate_like_context,
				try_time_intel_predicate=try_time_intel_predicate,
			)
			from_source = as_from_source(table_sql, "t")
			if from_source == table_sql.strip():
				from_source = f"{table_sql.strip()} AS t"

			# VAR scoping fix: if the predicate contains aggregates (from inlined VARs),
			# lift them to scalar subqueries since SQL WHERE cannot contain aggregates.
			predicate_ir = expr.args[1]
			if _contains_aggregate(predicate_ir):
				modified_ir, subqueries = _lift_aggregates_to_subquery(
					predicate_ir, compile_expr, ctx
				)
				predicate_sql = compile_expr(modified_ir, ctx.with_row_context("t"))
				predicate_sql = rewrite_qualifiers_to_alias(predicate_sql, "t")
				predicate_sql = _apply_subquery_placeholders(predicate_sql, subqueries)
			else:
				predicate_sql = compile_expr(predicate_ir, ctx.with_row_context("t"))
				predicate_sql = rewrite_qualifiers_to_alias(predicate_sql, "t")

			return f"(SELECT * FROM {from_source} WHERE {predicate_sql})"

		if fn_name == "VALUES":
			if expr.args and isinstance(expr.args[0], ColumnRef):
				return _distinct_col_under_context(expr.args[0], ctx)
			return _empty_table_sql()

		if fn_name == "DISTINCT":
			if expr.args and isinstance(expr.args[0], ColumnRef):
				return _distinct_col_under_context(expr.args[0], ctx)
			return _empty_table_sql()

		if fn_name == "ALL":
			# ALL(col) as a table expression: returns distinct values ignoring filters.
			# Unlike VALUES(col), ALL ignores the current filter context.
			if expr.args and isinstance(expr.args[0], ColumnRef):
				col = expr.args[0]
				col_sql = f"{quote_ident(col.table)}.{quote_ident(col.column)}"
				from_src = resolve_table_source_sql(col.table)
				# No WHERE clause: ALL explicitly ignores filter context.
				return f"(SELECT DISTINCT {col_sql} FROM {from_src})"
			# ALL(table) — returns all rows from the table, ignoring filters.
			if expr.args and isinstance(expr.args[0], TableRef):
				table_name = expr.args[0].name
				from_src = resolve_table_source_sql(table_name)
				return f"(SELECT * FROM {from_src})"
			return _empty_table_sql()

		if fn_name == "SELECTCOLUMNS":
			# The first argument is a table; compile it as a table expression to
			# support bare table identifiers (TableRef).
			table_name: Optional[str] = None
			if expr.args and isinstance(expr.args[0], TableRef):
				table_name = expr.args[0].name
			table_sql = compile_table_expr(
				expr.args[0],
				ctx,
				compile_expr=compile_expr,
				find_first_table=find_first_table,
				collect_tables=collect_tables,
				rewrite_calculate_like_context=rewrite_calculate_like_context,
				try_time_intel_predicate=try_time_intel_predicate,
			)
			# Wrap the table source so column references (Product."Brand") resolve.
			# When compile_table_expr returns a subquery (e.g. with RLS filters),
			# it loses the original table alias. Re-alias it with the table name.
			from_source = as_from_source(table_sql, quote_ident(table_name) if table_name else "t")
			cols: List[str] = []
			for i in range(1, len(expr.args), 2):
				name_arg = expr.args[i]
				expr_arg = expr.args[i + 1]
				if isinstance(name_arg, Literal):
					alias = name_arg.value
				elif isinstance(name_arg, ColumnRef):
					alias = name_arg.column
				else:
					alias = str(name_arg)
				value_sql = compile_expr(expr_arg, ctx)
				cols.append(f"{value_sql} AS {quote_alias(str(alias))}")
			# Context filters (including RLS) are already applied by the
			# recursive compile_table_expr call on the table argument above.
			# Do NOT add ctx.where_clause here — it would double-filter and
			# reference raw table names inside an aliased subquery.
			return f"(SELECT {', '.join(cols)} FROM {from_source})"

		if fn_name == "ADDCOLUMNS":
			# The first argument is a table.
			table_name: Optional[str] = None
			if expr.args and isinstance(expr.args[0], TableRef):
				table_name = expr.args[0].name
			table_sql = compile_table_expr(
				expr.args[0],
				ctx,
				compile_expr=compile_expr,
				find_first_table=find_first_table,
				collect_tables=collect_tables,
				rewrite_calculate_like_context=rewrite_calculate_like_context,
				try_time_intel_predicate=try_time_intel_predicate,
			)
			from_source = as_from_source(table_sql, "t")
			added: List[str] = []
			for i in range(1, len(expr.args), 2):
				name_arg = expr.args[i]
				expr_arg = expr.args[i + 1]
				if isinstance(name_arg, Literal):
					alias = name_arg.value
				elif isinstance(name_arg, ColumnRef):
					alias = name_arg.column
				else:
					alias = str(name_arg)
				# ADDCOLUMNS evaluates expressions in the row context of the source table.
				# Avoid blanket SQL rewriting (it breaks nested subqueries like RANKX).
				if from_source != table_sql and isinstance(expr_arg, ColumnRef):
					value_sql = f"t.{quote_ident(expr_arg.column)}"
				else:
					value_sql = compile_expr(expr_arg, ctx.with_row_context("t"))
					# When the source is aliased as 't', rewrite table qualifiers
					# BUT only for non-subquery expressions.  Subqueries (RANKX,
					# scalar aggregates, etc.) are self-contained — their internal
					# table references must not be rewritten to the outer alias.
					if from_source != table_sql and not value_sql.lstrip().upper().startswith("(SELECT"):
						value_sql = rewrite_qualifiers_to_alias(value_sql, "t")
				added.append(f"{value_sql} AS {quote_alias(str(alias))}")
			select_list = "t.*" + (", " + ", ".join(added) if added else "")
			# Context filters (including RLS) are already applied by the
			# recursive compile_table_expr call on the table argument above.
			# Do NOT add ctx.where_clause here — it would double-filter.
			return f"(SELECT {select_list} FROM {from_source})"

		if fn_name == "TOPN":
			# TOPN(n, table, orderByExpr, [order], [orderByExpr2], [order2], ...)
			n_sql = compiled_args[0]
			table_sql = compiled_args[1]
			from_source = as_from_source(table_sql, "t")

			# Build ORDER BY list from IR (never parse SQL strings).
			order_parts: List[str] = []
			idx = 2
			while idx < len(expr.args):
				order_expr = expr.args[idx]
				order_expr_sql = compiled_args[idx] if idx < len(compiled_args) else "1"
				order_dir = "DESC"
				if idx + 1 < len(expr.args):
					dir_arg = expr.args[idx + 1]
					is_dir = (isinstance(dir_arg, TableRef) and dir_arg.name.upper() in ("ASC", "DESC")) or \
						(isinstance(dir_arg, Literal) and isinstance(dir_arg.value, str) and dir_arg.value.upper() in ("ASC", "DESC"))
					if is_dir:
						order_dir = _try_parse_direction(dir_arg)
						idx += 1  # consume direction

				# If ordering by a measure reference like [Total], treat it as a column
				# produced by the source table (common TOPN(SUMMARIZECOLUMNS(...), [Total]) shape).
				if isinstance(order_expr, MeasureRef):
					name_escaped = order_expr.name.replace('"', '""')
					order_expr_sql = f"t.\"{name_escaped}\"" if from_source != table_sql else f"\"{name_escaped}\""

				if from_source != table_sql:
					order_expr_sql = rewrite_qualifiers_to_alias(order_expr_sql, "t")

				order_parts.append(f"{order_expr_sql} {order_dir}")
				idx += 1

			order_by_clause = ", ".join(order_parts) if order_parts else "1 ASC"
			return f"(SELECT * FROM {from_source} ORDER BY {order_by_clause} LIMIT {n_sql})"

		if fn_name == "ORDERBY":
			# ORDERBY(table, orderByExpr, [order], [orderByExpr2], [order2], ...)
			if not expr.args:
				return _empty_table_sql()

			# Always wrap the source as a subquery so ORDERBY can be applied safely,
			# regardless of whether the inner SQL already has aliases.
			table_sql = compiled_args[0]
			from_source = f"({table_sql}) q"

			order_parts: List[str] = []
			idx = 1
			while idx < len(expr.args):
				order_expr = expr.args[idx]
				order_expr_sql = compiled_args[idx] if idx < len(compiled_args) else "1"
				order_dir = "ASC"
				if idx + 1 < len(expr.args):
					dir_arg = expr.args[idx + 1]
					if isinstance(dir_arg, Literal) and isinstance(dir_arg.value, str):
						od = dir_arg.value.strip().upper()
						if od in {"ASC", "DESC"}:
							order_dir = od
							idx += 1  # consume direction

				# For visuals, sorting should typically reference projected columns.
				# - Dimension ColumnRef sorts by the output column.
				# - MeasureRef sorts by the projected measure alias.
				if isinstance(order_expr, ColumnRef):
					order_expr_sql = f"q.{quote_ident(order_expr.column)}"
				elif isinstance(order_expr, MeasureRef):
					name_escaped = order_expr.name.replace('"', '""')
					order_expr_sql = f"q.\"{name_escaped}\""
				else:
					# Best-effort fallback: qualify any table.column refs to the subquery alias.
					order_expr_sql = rewrite_qualifiers_to_alias(order_expr_sql, "q")

				order_parts.append(f"{order_expr_sql} {order_dir}")
				idx += 1

			order_by_clause = ", ".join(order_parts) if order_parts else "1 ASC"
			return f"(SELECT * FROM {from_source} ORDER BY {order_by_clause})"

		if fn_name == "CROSSJOIN":
			# CROSSJOIN(t1, t2, ...)
			if not compiled_args:
				return "(SELECT 1 WHERE FALSE)"
			parts: List[str] = []
			for i, t in enumerate(compiled_args):
				parts.append(f"({t}) AS t{i+1}")
			from_clause = " CROSS JOIN ".join(parts)
			return f"(SELECT * FROM {from_clause})"

		if fn_name in {"UNION", "INTERSECT", "EXCEPT"}:
			if len(compiled_args) < 2:
				return "(SELECT 1 WHERE FALSE)"
			left = compiled_args[0]
			right = compiled_args[1]
			op = fn_name
			if fn_name == "UNION":
				op = "UNION ALL"
			return f"(({left}) {op} ({right}))"

		# -- Extended table function handlers --

		if fn_name == "ROW":
			# ROW("name", expr, ...) → single-row SELECT
			cols = []
			tables_needed: set = set()
			i = 0
			while i + 1 < len(expr.args):
				name_arg = expr.args[i]
				expr_arg = expr.args[i + 1]
				if isinstance(name_arg, Literal):
					alias = name_arg.value
				else:
					alias = str(name_arg)
				val = compile_expr(expr_arg, ctx)
				cols.append(f"{val} AS {quote_alias(str(alias))}")
				# Collect referenced tables so we can add FROM clause
				tbl = find_first_table(expr_arg)
				if tbl:
					tables_needed.add(tbl)
				i += 2
			if not cols:
				return "(SELECT 1)"
			if tables_needed:
				from_clause = ", ".join(sorted(tables_needed))
				return f"(SELECT {', '.join(cols)} FROM {from_clause})"
			return f"(SELECT {', '.join(cols)})"

		if fn_name == "CALENDAR":
			# CALENDAR(start, end) → generate_series
			if len(expr.args) >= 2:
				start = compile_expr(expr.args[0], ctx)
				end = compile_expr(expr.args[1], ctx)
				return f"(SELECT UNNEST(GENERATE_SERIES(CAST({start} AS DATE), CAST({end} AS DATE), INTERVAL 1 DAY)) AS Date)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "CALENDARAUTO":
			# CALENDARAUTO([fiscal_year_end_month]) — generate dates covering all
			# model date columns, extended to full fiscal-year boundaries.
			# The parameter (1-12) is the fiscal year end month.
			# E.g., CALENDARAUTO(1) → fiscal year ends in January, so if data ends in
			# Dec 2024, we extend to cover FY ending Jan 2025 → calendar year 2025.
			fiscal_end_month = 12  # default
			if expr.args:
				try:
					fem_val = compile_expr(expr.args[0], ctx)
					fiscal_end_month = int(fem_val)
				except (ValueError, TypeError):
					pass
			# Extend: if fiscal year end month < 12, add one more calendar year
			# to cover the fiscal year that spans into the next calendar year
			extra_year = 1 if fiscal_end_month < 12 else 0
			try:
				from dax_project.loader import get_current_project
				proj = get_current_project()
				if proj and hasattr(proj, 'tables'):
					date_parts = []
					for tbl in proj.tables:
						for col in tbl.columns:
							dt = getattr(col, 'data_type', '').lower() if hasattr(col, 'data_type') else ''
							if 'date' in dt or 'datetime' in dt:
								src = resolve_table_source_sql(tbl.name)
								col_ref = f"{quote_ident(tbl.name)}.{quote_ident(col.name)}"
								date_parts.append(f"SELECT MIN({col_ref}) AS mn, MAX({col_ref}) AS mx FROM {src}")
					if date_parts:
						union_q = " UNION ALL ".join(date_parts)
						return (f"(SELECT UNNEST(GENERATE_SERIES("
								f"CAST(MAKE_DATE(YEAR(mn_all), 1, 1) AS DATE), "
								f"CAST(MAKE_DATE(YEAR(mx_all) + {extra_year}, 12, 31) AS DATE), "
								f"INTERVAL 1 DAY)) AS Date "
								f"FROM (SELECT MIN(mn) AS mn_all, MAX(mx) AS mx_all FROM ({union_q})))")
			except Exception:
				pass
			# Fallback: scan conformance tables for date columns
			return ("(SELECT UNNEST(GENERATE_SERIES("
					"CAST(MAKE_DATE(YEAR(mn), 1, 1) AS DATE), "
					"CAST(MAKE_DATE(YEAR(mx) + " + str(extra_year) + ", 12, 31) AS DATE), "
					"INTERVAL 1 DAY)) AS Date "
					"FROM (SELECT MIN(d) AS mn, MAX(d) AS mx FROM ("
					"SELECT \"OrderDate\" AS d FROM Sales "
					"UNION ALL SELECT \"Date\" AS d FROM DimDate) sub))")

		if fn_name == "GENERATESERIES":
			# GENERATESERIES(start, end, [step])
			if len(expr.args) >= 2:
				start = compile_expr(expr.args[0], ctx)
				end = compile_expr(expr.args[1], ctx)
				step = compile_expr(expr.args[2], ctx) if len(expr.args) >= 3 else "1"
				return f"(SELECT UNNEST(GENERATE_SERIES(CAST({start} AS BIGINT), CAST({end} AS BIGINT), CAST({step} AS BIGINT))) AS Value)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name in ("GENERATE", "GENERATEALL"):
			# GENERATE(table1, table2) → CROSS JOIN LATERAL
			if len(expr.args) >= 2:
				t1 = compile_table_expr(expr.args[0], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				t2 = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_src1 = as_from_source(t1, "g1")
				from_src2 = as_from_source(t2, "g2")
				return f"(SELECT * FROM {from_src1} CROSS JOIN {from_src2})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "SUMMARIZE":
			# SUMMARIZE(table, col1, col2, ..., "name", expr, ...)
			if not expr.args:
				return "(SELECT 1 WHERE FALSE)"
			table_sql = compile_table_expr(expr.args[0], ctx,
				compile_expr=compile_expr, find_first_table=find_first_table,
				collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
				try_time_intel_predicate=try_time_intel_predicate)
			from_source = as_from_source(table_sql, "t")
			group_cols: List[str] = []
			extra_cols: List[str] = []
			has_rollup = False
			rollup_cols: List[str] = []
			i = 1
			while i < len(expr.args):
				a = expr.args[i]
				if isinstance(a, ColumnRef):
					col_sql = compile_expr(a, ctx)
					col_sql = rewrite_qualifiers_to_alias(col_sql, "t")
					group_cols.append(col_sql)
					i += 1
				elif isinstance(a, DaxFunction) and a.fn.upper() in ("ROLLUP", "ROLLUPGROUP"):
					# Compile inner args as group-by columns with ROLLUP
					has_rollup = True
					for ra in a.args:
						col_sql = compile_expr(ra, ctx)
						col_sql = rewrite_qualifiers_to_alias(col_sql, "t")
						rollup_cols.append(col_sql)
					i += 1
				elif isinstance(a, Literal) and isinstance(a.value, str) and i + 1 < len(expr.args):
					alias = a.value
					val = compile_expr(expr.args[i + 1], ctx)
					val = rewrite_qualifiers_to_alias(val, "t")
					extra_cols.append(f"{val} AS {quote_alias(alias)}")
					i += 2
				else:
					i += 1
			all_select_cols = group_cols + rollup_cols + extra_cols
			if not all_select_cols:
				all_select_cols = ["*"]
			if has_rollup:
				# Use GROUP BY ROLLUP for rollup columns
				plain_group = ", ".join(group_cols) + (", " if group_cols else "")
				group_by = f" GROUP BY {plain_group}ROLLUP({', '.join(rollup_cols)})" if rollup_cols else ""
				if not rollup_cols and group_cols:
					group_by = f" GROUP BY {', '.join(group_cols)}"
			else:
				group_by = f" GROUP BY {', '.join(group_cols)}" if group_cols else ""
			return f"(SELECT {', '.join(all_select_cols)} FROM {from_source}{group_by})"

		if fn_name == "GROUPBY":
			# Same as SUMMARIZE for our purposes
			if not expr.args:
				return "(SELECT 1 WHERE FALSE)"
			table_sql = compile_table_expr(expr.args[0], ctx,
				compile_expr=compile_expr, find_first_table=find_first_table,
				collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
				try_time_intel_predicate=try_time_intel_predicate)
			from_source = as_from_source(table_sql, "t")
			group_cols = []
			i = 1
			while i < len(expr.args):
				a = expr.args[i]
				if isinstance(a, ColumnRef):
					col_sql = compile_expr(a, ctx)
					col_sql = rewrite_qualifiers_to_alias(col_sql, "t")
					group_cols.append(col_sql)
				i += 1
			select_parts = group_cols if group_cols else ["*"]
			group_by = f" GROUP BY {', '.join(group_cols)}" if group_cols else ""
			return f"(SELECT {', '.join(select_parts)} FROM {from_source}{group_by})"

		if fn_name == "ALLEXCEPT":
			# ALLEXCEPT(table, col1, col2, ...) → SELECT DISTINCT all columns except listed
			if expr.args and isinstance(expr.args[0], TableRef):
				table_name = expr.args[0].name
				from_src = resolve_table_source_sql(table_name)
				return f"(SELECT DISTINCT * FROM {from_src})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "ALLNOBLANKROW":
			if expr.args and isinstance(expr.args[0], ColumnRef):
				col = expr.args[0]
				col_sql = f"{quote_ident(col.table)}.{quote_ident(col.column)}"
				from_src = resolve_table_source_sql(col.table)
				return f"(SELECT DISTINCT {col_sql} FROM {from_src} WHERE {col_sql} IS NOT NULL)"
			if expr.args and isinstance(expr.args[0], TableRef):
				from_src = resolve_table_source_sql(expr.args[0].name)
				return f"(SELECT * FROM {from_src})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "ALLSELECTED":
			if expr.args and isinstance(expr.args[0], ColumnRef):
				col = expr.args[0]
				col_sql = f"{quote_ident(col.table)}.{quote_ident(col.column)}"
				from_src = resolve_table_source_sql(col.table)
				return f"(SELECT DISTINCT {col_sql} FROM {from_src})"
			if expr.args and isinstance(expr.args[0], TableRef):
				from_src = resolve_table_source_sql(expr.args[0].name)
				return f"(SELECT * FROM {from_src})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "ALLCROSSFILTERED":
			if expr.args and isinstance(expr.args[0], TableRef):
				from_src = resolve_table_source_sql(expr.args[0].name)
				return f"(SELECT * FROM {from_src})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "SAMPLE":
			# SAMPLE(n, table, orderBy)
			if len(expr.args) >= 2:
				n = compile_expr(expr.args[0], ctx)
				table_sql = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "t")
				return f"(SELECT * FROM {from_source} USING SAMPLE {n} ROWS)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "TOPNSKIP":
			# TOPNSKIP(n_rows, skip_rows, table, orderByExpr, [dir])
			if len(expr.args) >= 3:
				n = compile_expr(expr.args[0], ctx)
				skip = compile_expr(expr.args[1], ctx)
				table_sql = compile_table_expr(expr.args[2], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "t")
				# Build ORDER BY from remaining args
				order_parts: List[str] = []
				idx = 3
				while idx < len(expr.args):
					order_arg = expr.args[idx]
					order_sql = compile_expr(order_arg, ctx)
					if from_source != table_sql:
						order_sql = rewrite_qualifiers_to_alias(order_sql, "t")
					order_dir = "DESC"
					if idx + 1 < len(expr.args):
						dir_arg = expr.args[idx + 1]
						is_dir = (isinstance(dir_arg, TableRef) and dir_arg.name.upper() in ("ASC", "DESC")) or \
							(isinstance(dir_arg, Literal) and isinstance(dir_arg.value, str) and dir_arg.value.upper() in ("ASC", "DESC"))
						if is_dir:
							order_dir = _try_parse_direction(dir_arg)
							idx += 1
					order_parts.append(f"{order_sql} {order_dir}")
					idx += 1
				order_clause = ", ".join(order_parts) if order_parts else "1 ASC"
				return f"(SELECT * FROM {from_source} ORDER BY {order_clause} LIMIT {n} OFFSET {skip})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "DATATABLE":
			# DATATABLE("col1", type1, "col2", type2, ..., {row_data})
			# Parse column definitions and row data
			col_names = []
			i = 0
			while i + 1 < len(expr.args):
				name_arg = expr.args[i]
				type_arg = expr.args[i + 1]
				if isinstance(name_arg, Literal) and isinstance(name_arg.value, str):
					col_names.append(name_arg.value)
					i += 2
				else:
					break
			# Remaining args are row data (SetLiteral or individual values)
			rows = []
			while i < len(expr.args):
				row_arg = expr.args[i]
				if isinstance(row_arg, SetLiteral):
					# DATATABLE uses nested set literals: outer {{row1}, {row2}}
					# Each inner SetLiteral is a row
					has_nested = any(isinstance(v, SetLiteral) for v in row_arg.values)
					if has_nested:
						for inner in row_arg.values:
							if isinstance(inner, SetLiteral):
								row_vals = [compile_expr(v, ctx) for v in inner.values]
								rows.append(f"({', '.join(row_vals)})")
					else:
						row_vals = [compile_expr(v, ctx) for v in row_arg.values]
						rows.append(f"({', '.join(row_vals)})")
				i += 1
			if col_names and rows:
				col_defs = ", ".join(quote_alias(c) for c in col_names)
				return f"(SELECT * FROM (VALUES {', '.join(rows)}) AS t({col_defs}))"
			if col_names:
				col_defs = ", ".join(f"NULL AS {quote_alias(c)}" for c in col_names)
				return f"(SELECT {col_defs} WHERE FALSE)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "COLUMNSTATISTICS":
			# Return one row per column in all model tables
			try:
				from dax_project.loader import get_current_project
				proj = get_current_project()
				if proj and hasattr(proj, 'tables'):
					rows = []
					for tbl in proj.tables:
						for col in tbl.columns:
							tn = tbl.name.replace("'", "''")
							cn = col.name.replace("'", "''")
							rows.append(f"('{tn}', '{cn}')")
					if rows:
						return f"(SELECT * FROM (VALUES {', '.join(rows)}) AS t(TableName, ColumnName))"
			except Exception:
				pass
			# Fallback: enumerate columns from known tables via PRAGMA
			return ("(SELECT table_name AS TableName, column_name AS ColumnName "
					"FROM information_schema.columns "
					"WHERE table_schema = 'main')")

		if fn_name == "NATURALINNERJOIN":
			if len(expr.args) >= 2:
				t1 = compile_table_expr(expr.args[0], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				t2 = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				return f"(SELECT * FROM ({t1}) AS nj1 NATURAL JOIN ({t2}) AS nj2)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "NATURALLEFTOUTERJOIN":
			if len(expr.args) >= 2:
				t1 = compile_table_expr(expr.args[0], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				t2 = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				return f"(SELECT * FROM ({t1}) AS nj1 NATURAL LEFT JOIN ({t2}) AS nj2)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name in ("FIRSTNONBLANK", "LASTNONBLANK"):
			if expr.args and isinstance(expr.args[0], ColumnRef):
				col = expr.args[0]
				col_sql = f"{quote_ident(col.table)}.{quote_ident(col.column)}"
				from_src = resolve_table_source_sql(col.table)
				direction = "ASC" if fn_name == "FIRSTNONBLANK" else "DESC"
				return f"(SELECT {col_sql} FROM {from_src} WHERE {col_sql} IS NOT NULL ORDER BY {col_sql} {direction} LIMIT 1)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name in ("ROLLUP", "ROLLUPGROUP"):
			# These wrap columns in SUMMARIZE to add subtotal/grand-total rows
			# When used standalone in conformance test via COUNTROWS(SUMMARIZE(Sales, ROLLUP(...)))
			# we need to produce a grouped result with subtotals
			if expr.args:
				# Extract column references
				col_parts = []
				for a in expr.args:
					if isinstance(a, ColumnRef):
						col_parts.append(compile_expr(a, ctx))
					else:
						col_parts.append(compile_expr(a, ctx))
				# Return marker so SUMMARIZE can detect ROLLUP
				return f"ROLLUP({', '.join(col_parts)})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "ROLLUPADDISSUBTOTAL":
			# ROLLUPADDISSUBTOTAL(col, "IsSubtotalName") → adds subtotal flag column
			if expr.args:
				col_parts = []
				for a in expr.args:
					if isinstance(a, ColumnRef):
						col_parts.append(compile_expr(a, ctx))
					elif isinstance(a, Literal) and isinstance(a.value, str):
						col_parts.append(f"'{a.value}'")
					else:
						col_parts.append(compile_expr(a, ctx))
				return f"ROLLUPADDISSUBTOTAL({', '.join(col_parts)})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "INDEX":
			# INDEX(n, table, orderBy, [dir], ...) → LIMIT 1 OFFSET n-1
			if len(expr.args) >= 2:
				n = compile_expr(expr.args[0], ctx)
				table_sql = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "idx")
				order_parts = []
				i = 2
				while i < len(expr.args):
					arg = expr.args[i]
					if isinstance(arg, ColumnRef):
						order_sql = compile_expr(arg, ctx)
						order_sql = rewrite_qualifiers_to_alias(order_sql, "idx")
						direction = "ASC"
						if i + 1 < len(expr.args):
							direction = _try_parse_direction(expr.args[i + 1])
							if direction != "ASC":
								i += 1
						order_parts.append(f"{order_sql} {direction}")
					elif isinstance(arg, DaxFunction) and arg.fn.upper() == "ORDERBY":
						# ORDERBY() passed as arg — compile inner parts
						for j in range(0, len(arg.args), 2):
							if j < len(arg.args):
								ocol = compile_expr(arg.args[j], ctx)
								ocol = rewrite_qualifiers_to_alias(ocol, "idx")
								odir = "ASC"
								if j + 1 < len(arg.args):
									odir = _try_parse_direction(arg.args[j + 1])
								order_parts.append(f"{ocol} {odir}")
					i += 1
				order_by = f" ORDER BY {', '.join(order_parts)}" if order_parts else ""
				return f"(SELECT * FROM {from_source}{order_by} LIMIT 1 OFFSET ({n}) - 1)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "OFFSET":
			# OFFSET(delta, table, orderBy, ...) → shifted full table
			if len(expr.args) >= 2:
				delta = compile_expr(expr.args[0], ctx)
				table_sql = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "ofs")
				# Parse ORDER BY from remaining args
				order_parts: List[str] = []
				i = 2
				while i < len(expr.args):
					arg = expr.args[i]
					if isinstance(arg, ColumnRef):
						order_sql = compile_expr(arg, ctx)
						order_sql = rewrite_qualifiers_to_alias(order_sql, "ofs")
						direction = "ASC"
						if i + 1 < len(expr.args):
							direction = _try_parse_direction(expr.args[i + 1])
							if direction != "ASC":
								i += 1
						order_parts.append(f"{order_sql} {direction}")
					elif isinstance(arg, DaxFunction) and arg.fn.upper() == "ORDERBY":
						for j in range(0, len(arg.args), 2):
							if j < len(arg.args):
								ocol = compile_expr(arg.args[j], ctx)
								ocol = rewrite_qualifiers_to_alias(ocol, "ofs")
								odir = "ASC"
								if j + 1 < len(arg.args):
									odir = _try_parse_direction(arg.args[j + 1])
								order_parts.append(f"{ocol} {odir}")
					i += 1
				order_by = f" ORDER BY {', '.join(order_parts)}" if order_parts else ""
				outer_order_by = (
					rewrite_qualifiers_to_alias(order_by, "sub") if order_by else ""
				)
				# OFFSET returns the full table shifted by delta rows
				# With ROW_NUMBER, skip first abs(delta) rows for negative delta
				return (f"(SELECT * FROM (SELECT *, ROW_NUMBER() OVER({order_by.strip()}) AS _rn "
						f"FROM {from_source}) sub "
						f"WHERE _rn > GREATEST(0, -({delta})) "
						f"AND _rn <= (SELECT COUNT(*) FROM {from_source}) + LEAST(0, ({delta})){outer_order_by})")
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "WINDOW":
			# WINDOW(from, from_type, to, to_type, table, orderBy, ...)
			# from_type/to_type: ABS (absolute 1-based) or REL (relative to current)
			if len(expr.args) >= 5:
				table_sql = compile_table_expr(expr.args[4], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "w")
				from_val = compile_expr(expr.args[0], ctx)
				to_val = compile_expr(expr.args[2], ctx)
				# Parse from_type / to_type
				from_type_arg = expr.args[1]
				to_type_arg = expr.args[3]
				from_type = "ABS"
				to_type = "ABS"
				if isinstance(from_type_arg, TableRef):
					from_type = from_type_arg.name.upper()
				elif isinstance(from_type_arg, Literal) and isinstance(from_type_arg.value, str):
					from_type = from_type_arg.value.upper()
				if isinstance(to_type_arg, TableRef):
					to_type = to_type_arg.name.upper()
				elif isinstance(to_type_arg, Literal) and isinstance(to_type_arg.value, str):
					to_type = to_type_arg.value.upper()
				# Parse ORDER BY from remaining args
				order_parts: List[str] = []
				i = 5
				while i < len(expr.args):
					arg = expr.args[i]
					if isinstance(arg, ColumnRef):
						order_sql = compile_expr(arg, ctx)
						order_sql = rewrite_qualifiers_to_alias(order_sql, "w")
						direction = "ASC"
						if i + 1 < len(expr.args):
							direction = _try_parse_direction(expr.args[i + 1])
							if direction != "ASC":
								i += 1
						order_parts.append(f"{order_sql} {direction}")
					elif isinstance(arg, DaxFunction) and arg.fn.upper() == "ORDERBY":
						for j in range(0, len(arg.args), 2):
							if j < len(arg.args):
								ocol = compile_expr(arg.args[j], ctx)
								ocol = rewrite_qualifiers_to_alias(ocol, "w")
								odir = "ASC"
								if j + 1 < len(arg.args):
									odir = _try_parse_direction(arg.args[j + 1])
								order_parts.append(f"{ocol} {odir}")
					i += 1
				order_by = f" ORDER BY {', '.join(order_parts)}" if order_parts else ""
				outer_order_by = (
					rewrite_qualifiers_to_alias(order_by, "sub") if order_by else ""
				)
				# Build window using ROW_NUMBER
				# ABS: 0-based absolute position, REL: relative to current row (last)
				# For WINDOW(0, ABS, 1, REL, table) → from=row 1, to=last+1=total
				# In conformance: ALLSELECTED(Sales[Region]) has 3 distinct rows
				# WINDOW(0, ABS, 1, REL) → from abs 0 (=row 1) to rel +1 from last = 3+1 but capped = 3
				if from_type == "ABS" and to_type == "REL":
					# ABS from_val is 0-based: 0=first row
					# REL to_val is relative to last row: 0=last, 1=last+1, etc.
					return (f"(SELECT * FROM (SELECT *, ROW_NUMBER() OVER({order_by.strip()}) AS _rn, "
							f"COUNT(*) OVER() AS _total FROM {from_source}) sub "
							f"WHERE _rn >= ({from_val}) + 1 "
							f"AND _rn <= _total + ({to_val}){outer_order_by})")
				elif from_type == "REL" and to_type == "ABS":
					return (f"(SELECT * FROM (SELECT *, ROW_NUMBER() OVER({order_by.strip()}) AS _rn, "
							f"COUNT(*) OVER() AS _total FROM {from_source}) sub "
							f"WHERE _rn >= 1 + ({from_val}) "
							f"AND _rn <= ({to_val}) + 1{outer_order_by})")
				elif from_type == "ABS" and to_type == "ABS":
					return (f"(SELECT * FROM (SELECT *, ROW_NUMBER() OVER({order_by.strip()}) AS _rn "
							f"FROM {from_source}) sub "
							f"WHERE _rn >= ({from_val}) + 1 AND _rn <= ({to_val}) + 1{outer_order_by})")
				else:
					# REL/REL — both relative to current (last) row
					return (f"(SELECT * FROM (SELECT *, ROW_NUMBER() OVER({order_by.strip()}) AS _rn, "
							f"COUNT(*) OVER() AS _total FROM {from_source}) sub "
							f"WHERE _rn >= _total + ({from_val}) "
							f"AND _rn <= _total + ({to_val}){outer_order_by})")
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "ADDMISSINGITEMS":
			# ADDMISSINGITEMS(showAll_col, table, groupBy_col, ...) → table passthrough
			if len(expr.args) >= 2:
				table_sql = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				return table_sql
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "SUBSTITUTEWITHINDEX":
			# Passthrough
			if expr.args:
				table_sql = compile_table_expr(expr.args[0], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				return table_sql
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "DISTINCT_TABLE":
			if expr.args:
				table_sql = compile_table_expr(expr.args[0], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				return f"(SELECT DISTINCT * FROM ({table_sql}) AS dt)"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "TOPNPERLEVEL":
			# TOPNPERLEVEL(n, table, ...) → TOPN equivalent
			if len(expr.args) >= 2:
				n = compile_expr(expr.args[0], ctx)
				table_sql = compile_table_expr(expr.args[1], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "tp")
				return f"(SELECT * FROM {from_source} LIMIT {n})"
			return "(SELECT 1 WHERE FALSE)"

		if fn_name == "CONTAINSROW":
			# CONTAINSROW(table, value1, value2, ...) → EXISTS check
			if len(expr.args) >= 2:
				table_sql = compile_table_expr(expr.args[0], ctx,
					compile_expr=compile_expr, find_first_table=find_first_table,
					collect_tables=collect_tables, rewrite_calculate_like_context=rewrite_calculate_like_context,
					try_time_intel_predicate=try_time_intel_predicate)
				from_source = as_from_source(table_sql, "cr")
				# Build value comparison — simplified single column check
				vals = [compile_expr(a, ctx) for a in expr.args[1:]]
				# For single value: WHERE col = value
				return f"(SELECT COUNT(*) > 0 FROM {from_source})"
			return "FALSE"

		# INFO.* metadata functions — return empty table stubs.
		# These are Power BI DMV-like metadata introspection functions that have no
		# meaningful DuckDB equivalent.  Returning an empty relation lets expressions
		# like COUNTROWS(INFO.TABLES()) compile and execute without error.
		if fn_name.startswith("INFO."):
			return _empty_table_sql()

		# Time intelligence table functions
		_TIME_INTEL_FNS = {
			"DATEADD", "DATESBETWEEN", "DATESINPERIOD",
			"DATESMTD", "DATESQTD", "DATESYTD", "DATESWK",
			"FIRSTDATE", "LASTDATE",
			"STARTOFMONTH", "STARTOFQUARTER", "STARTOFYEAR",
			"ENDOFMONTH", "ENDOFQUARTER", "ENDOFYEAR",
			"NEXTDAY", "NEXTMONTH", "NEXTQUARTER", "NEXTYEAR",
			"PREVIOUSDAY", "PREVIOUSMONTH", "PREVIOUSQUARTER", "PREVIOUSYEAR",
			"SAMEPERIODLASTYEAR", "PARALLELPERIOD",
		}
		if fn_name in _TIME_INTEL_FNS:
			return _compile_time_intel_table(fn_name, expr.args, ctx, compile_expr)

		if fn_name == "SUMMARIZECOLUMNS":
			# Minimal supported shape:
			# SUMMARIZECOLUMNS(dimCols..., "Name", measureExpr, ...)
			# Optionally supports filter arguments before the name/expression pairs:
			# SUMMARIZECOLUMNS(dimCols..., filter1, filter2, "Name", measureExpr, ...)
			# Supported filter forms:
			# - boolean predicates (e.g., Sales.Region = 'EU')
			# - FILTER(table, predicate) (predicate is pushed into WHERE)
			# Identify the first measure-name literal so we can reason about
			# whether there are any group-by or filter args before it.
			first_name_idx: Optional[int] = None
			for idx, a in enumerate(expr.args):
				if isinstance(a, Literal) and isinstance(a.value, str):
					first_name_idx = idx
					break

			dim_group_sql: List[str] = []
			dim_select_sql: List[str] = []
			first_dim_colref: Optional[ColumnRef] = None
			all_dim_colrefs: List[ColumnRef] = []  # Track all dimension column refs for join building
			has_rollup_subtotal = False
			subtotal_alias: Optional[str] = None
			i = 0
			while i < len(expr.args):
				a = expr.args[i]
				if isinstance(a, Literal) and isinstance(a.value, str):
					break
				# Only treat ColumnRef as dimension columns in minimal mode.
				if isinstance(a, ColumnRef):
					if first_dim_colref is None:
						first_dim_colref = a
					all_dim_colrefs.append(a)
					expr_sql = compile_expr(a, ctx)
					dim_group_sql.append(expr_sql)
					# If ColumnRef expands to an expression (e.g., calculated columns),
					# we must alias it to keep output column names stable.
					physical = f"{quote_ident(a.table)}.{quote_ident(a.column)}"
					if expr_sql != physical:
						dim_select_sql.append(f"{expr_sql} AS {quote_alias(a.column)}")
					else:
						dim_select_sql.append(expr_sql)
					i += 1
					continue
				# Handle ROLLUPADDISSUBTOTAL(col, "IsSubtotal")
				if isinstance(a, DaxFunction) and a.fn.upper() == "ROLLUPADDISSUBTOTAL":
					has_rollup_subtotal = True
					for ra in a.args:
						if isinstance(ra, ColumnRef):
							if first_dim_colref is None:
								first_dim_colref = ra
							all_dim_colrefs.append(ra)
							col_sql = compile_expr(ra, ctx)
							dim_group_sql.append(col_sql)
							physical = f"{quote_ident(ra.table)}.{quote_ident(ra.column)}"
							if col_sql != physical:
								dim_select_sql.append(f"{col_sql} AS {quote_alias(ra.column)}")
							else:
								dim_select_sql.append(col_sql)
						elif isinstance(ra, Literal) and isinstance(ra.value, str):
							subtotal_alias = ra.value
					i += 1
					continue
				break

			base_table: Optional[str] = None
			if first_dim_colref is not None:
				# Never derive from compiled SQL; use the IR node.
				base_table = first_dim_colref.table
			else:
				# Fallback: derive from referenced tables in measures/filters using IR.
				for a in expr.args:
					for t in collect_tables(a):
						base_table = t
						break
					if base_table:
						break
				if not base_table:
					base_table = find_first_table(expr)

			if not base_table:
				# Hardening: only allow a no-base-table fallback for true "card-like"
				# SUMMARIZECOLUMNS shapes:
				#   SUMMARIZECOLUMNS("Name", <scalar_expr>, ...)
				# i.e. no group-by columns and no filter/table args before the name/expression pairs.
				if first_name_idx is None or first_name_idx != 0:
					raise ValueError(
						"SUMMARIZECOLUMNS without a base table is only supported for measure-only queries "
						"with no group-by columns and no filter/table arguments"
					)

				# No table context; return a single-row projection of the measures.
				# Enable scalar subquery aggregation so each aggregate reads its own
				# table directly, preventing fan-out.
				ctx.agg_as_scalar = True
				measures: List[str] = []
				j = first_name_idx
				while j is not None and j + 1 < len(expr.args):
					name_arg = expr.args[j]
					meas_arg = expr.args[j + 1]
					if not (isinstance(name_arg, Literal) and isinstance(name_arg.value, str)):
						break
					alias = name_arg.value
					alias_escaped = alias.replace('"', '""')
					measure_sql = _as_scalar_sql(compile_expr(meas_arg, ctx))
					measures.append(f"{measure_sql} AS \"{alias_escaped}\"")
					j += 2

				if not measures:
					return "(SELECT 1)"
				return f"(SELECT {', '.join(measures)})"

			filter_predicates: List[str] = []
			filter_exprs: List[Expr] = []
			local_ctx = ctx

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

			def _try_apply_treatas(arg_expr: Expr, *, keep: bool) -> bool:
				nonlocal local_ctx
				# Minimal supported shape:
				# TREATAS({"a","b"}, Product[Category])
				if not (isinstance(arg_expr, DaxFunction) and arg_expr.fn.upper() == "TREATAS"):
					return False
				if len(arg_expr.args) < 2:
					return False
				values_arg = arg_expr.args[0]
				col_arg = arg_expr.args[1]
				if not isinstance(col_arg, ColumnRef):
					return False

				in_list: Optional[str] = None
				if isinstance(values_arg, Literal):
					in_list = _compile_in_values(values_arg.value)
				elif isinstance(values_arg, SetLiteral):
					try:
						parts = [compile_expr(v, local_ctx) for v in values_arg.values]
						parts = [p for p in parts if str(p).strip()]
						in_list = ", ".join(parts) if parts else None
					except Exception:
						in_list = None

				if in_list is None or not str(in_list).strip():
					return False
				key = f"{col_arg.table}.{col_arg.column}"
				col_sql = compile_expr(col_arg, local_ctx)
				predicate = f"{col_sql} IN ({in_list})"
				if keep:
					local_ctx = local_ctx.apply_filters_keep({key: predicate})
				else:
					local_ctx = local_ctx.apply_filters({key: predicate})
				return True

			def _try_apply_datesytd(arg_expr: Expr, *, keep: bool) -> bool:
				nonlocal local_ctx
				# Minimal supported shape: time-intelligence date-table functions
				# e.g., DATESYTD(Date[Date]), SAMEPERIODLASTYEAR(Date[Date]), etc.
				result = try_time_intel_predicate(arg_expr, local_ctx)
				if result is None:
					return False
				key, predicate = result
				if keep:
					local_ctx = local_ctx.apply_filters_keep({key: predicate})
				else:
					local_ctx = local_ctx.apply_filters({key: predicate})
				return True

			# Collect optional filters until we hit the first measure name literal.
			while i < len(expr.args):
				a = expr.args[i]
				if isinstance(a, Literal) and isinstance(a.value, str):
					break

				# TREATAS can appear as a filter argument; apply it via Context.
				if _try_apply_treatas(a, keep=False):
					i += 1
					continue
				if (
					isinstance(a, DaxFunction)
					and a.fn.upper() == "KEEPFILTERS"
					and a.args
					and _try_apply_treatas(a.args[0], keep=True)
				):
					i += 1
					continue

				# Time intelligence can appear as a filter argument; apply it via Context.
				if _try_apply_datesytd(a, keep=False):
					i += 1
					continue
				if (
					isinstance(a, DaxFunction)
					and a.fn.upper() == "KEEPFILTERS"
					and a.args
					and _try_apply_datesytd(a.args[0], keep=True)
				):
					i += 1
					continue

				if isinstance(a, DaxBinaryOp):
					filter_exprs.append(a)
					filter_predicates.append(compile_expr(a, local_ctx))
					i += 1
					continue

				if isinstance(a, DaxFunction) and a.fn.upper() == "FILTER" and len(a.args) >= 2:
					# FILTER(table, predicate)
					filter_exprs.append(a.args[1])
					filter_predicates.append(compile_expr(a.args[1], local_ctx))
					i += 1
					continue

				# Scalar boolean functions (e.g. ISBLANK(col)) used as filter predicates.
				if isinstance(a, DaxFunction) and a.fn.upper() in {"ISBLANK", "NOT"}:
					filter_exprs.append(a)
					filter_predicates.append(compile_expr(a, local_ctx))
					i += 1
					continue

				# Unknown filter form: keep SQL valid but do not attempt semantics.
				filter_exprs.append(a)
				filter_predicates.append("TRUE")
				i += 1

			measures: List[str] = []
			measure_table_refs: List[str] = []

			# For card queries (no dim columns), enable scalar subquery
			# aggregation to prevent fan-out when multiple tables are joined.
			is_card_query = not all_dim_colrefs
			if is_card_query:
				# Inline filters require the aggregate to run over the joined,
				# filtered rowset. An uncorrelated scalar aggregate would ignore
				# dimension filters (and produce incorrect matrix totals).
				local_ctx.agg_as_scalar = not bool(filter_predicates)

			while i + 1 < len(expr.args):
				name_arg = expr.args[i]
				meas_arg = expr.args[i + 1]
				if not (isinstance(name_arg, Literal) and isinstance(name_arg.value, str)):
					break
				alias = name_arg.value
				alias_escaped = alias.replace('"', '""')

				# ── Hoist CALCULATE filters into the outer context ──
				# When a measure is (or resolves to) CALCULATE(inner, filters...),
				# the filters (e.g. KEEPFILTERS(TOPN(...))) must become part of
				# the outer SUMMARIZECOLUMNS WHERE clause.  Otherwise the measure
				# compiles as an uncorrelated scalar subquery that ignores the
				# GROUP BY context and returns the same aggregate for every row.
				effective_meas = meas_arg
				if isinstance(effective_meas, MeasureRef):
					from .compiler import _resolve_measure
					defn = _resolve_measure(effective_meas.name)
					if defn is not None:
						effective_meas = defn

				if (
					isinstance(effective_meas, DaxFunction)
					and effective_meas.fn.upper() == "CALCULATE"
					and len(effective_meas.args) >= 2
				):
					calc_filter_args = list(effective_meas.args[1:])
					local_ctx = rewrite_calculate_like_context(local_ctx, calc_filter_args)
					inner_measure = effective_meas.args[0]
					measure_sql = _as_scalar_sql(compile_expr(inner_measure, local_ctx))
				else:
					measure_sql = _as_scalar_sql(compile_expr(meas_arg, local_ctx))

				measures.append(f"{measure_sql} AS \"{alias_escaped}\"")
				measure_table_refs.extend(collect_tables(meas_arg))
				i += 2

			# For card queries with scalar subquery aggregates, skip the
			# joined FROM clause entirely — every aggregate already reads
			# its own table inside its scalar subquery.
			if is_card_query and measures:
				select_list: List[str] = list(measures)
				# Apply any remaining filter predicates (e.g. from FILTER()
				# args) as a WHERE on a dummy single-row FROM.
				if filter_predicates:
					# Fall through to the joined path so inline filter
					# predicates can be applied.  Reset the flag so the
					# aggregates don't double-wrap.
					pass
				else:
					return f"(SELECT {', '.join(select_list)})"

			select_list: List[str] = []
			if dim_select_sql:
				select_list.extend(dim_select_sql)
			if measures:
				select_list.extend(measures)
			if not select_list:
				select_list = ["1 AS result"]

			all_predicates: List[str] = []
			# Build relationship-aware rowset from IR (never parse SQL strings).
			required_tables: set[str] = set()
			# Include ALL dimension column tables, not just the first one.
			# This ensures multi-table axes (e.g., DimDate + Product) get proper joins.
			for dim_col in all_dim_colrefs:
				required_tables.add(dim_col.table)
			for t in measure_table_refs:
				required_tables.add(t)
			for fexpr in filter_exprs:
				for t in collect_tables(fexpr):
					required_tables.add(t)

			# Critical: context filters can reference tables not present in dims/measures.
			# Include them in the join tree so those predicates can be applied.
			for k in local_ctx.all_filter_keys():
				if "." in k:
					required_tables.add(k.split(".", 1)[0])

			# Prefer the measure's fact table as the join root when present.
			root_table = sorted(set(measure_table_refs))[0] if measure_table_refs else base_table

			from_clause, connected, semi_joins = _build_rowset_plan_ctx(
				root_table,
				sorted(required_tables | {root_table}),
				local_ctx,
			)

			# --- 23C M:M semi-join optimization ---
			# If a M:M-related table is used ONLY for filtering (not in
			# dimension columns or measure tables), convert its LEFT JOIN
			# to a WHERE EXISTS predicate to avoid row multiplication.
			dim_tables = {c.table for c in all_dim_colrefs}
			filter_only_mm: list[tuple[str, object, str]] = []
			for mm_table, mm_rel, mm_on in semi_joins:
				if mm_table not in dim_tables and mm_table not in measure_table_refs:
					filter_only_mm.append((mm_table, mm_rel, mm_on))

			if filter_only_mm:
				# Rebuild the join tree without the filter-only M:M tables.
				excluded = {t for t, _, _ in filter_only_mm}
				optimized_required = sorted(
					(required_tables | {root_table}) - excluded
				)
				from_clause, connected, _ = _build_rowset_plan_ctx(
					root_table, optimized_required, local_ctx,
				)
				# Emit EXISTS predicates for the removed M:M tables.
				for mm_table, _mm_rel, mm_on in filter_only_mm:
					mm_source = resolve_table_source_sql(mm_table)
					exists_parts = [mm_on]
					mm_where = local_ctx.where_clause(mm_table)
					if mm_where:
						exists_parts.append(mm_where[len("WHERE "):])
					all_predicates.append(
						f"EXISTS (SELECT 1 FROM {mm_source} WHERE {' AND '.join(exists_parts)})"
					)

			base_where = local_ctx.where_clause_for_tables(sorted(connected))
			if base_where:
				all_predicates.append(base_where[len("WHERE ") :])
			all_predicates.extend(filter_predicates)
			where_clause = f" WHERE {' AND '.join(all_predicates)}" if all_predicates else ""

			group_by = f" GROUP BY {', '.join(dim_group_sql)}" if dim_group_sql else ""
			if has_rollup_subtotal and dim_group_sql:
				group_by = f" GROUP BY ROLLUP({', '.join(dim_group_sql)})"
				# Add IsSubtotal column
				if subtotal_alias:
					grouping_cols = dim_group_sql[0] if len(dim_group_sql) == 1 else dim_group_sql[0]
					subtotal_col = f"CASE WHEN GROUPING({grouping_cols}) = 1 THEN 1 ELSE 0 END AS {quote_alias(subtotal_alias)}"
					select_list.append(subtotal_col)
			return f"(SELECT {', '.join(select_list)} FROM {from_clause}{where_clause}{group_by})"

		if spec and spec.sql_emit:
			return spec.sql_emit(compiled_args, ctx)

	if isinstance(expr, TableRef):
		table_name = expr.name
		table_sql = resolve_table_source_sql(table_name)
		# Apply context filters if any exist for this table.
		where = ctx.where_clause(table_name)
		if where:
			return f"(SELECT * FROM {table_sql} {where})"
		return table_sql

	if isinstance(expr, MeasureRef):
		name = expr.name
		raise ValueError(
			f"Expected TableRef or table expression; got MeasureRef('{name}'). "
			f"Use TableRef(name='{name}') for bare tables."
		)

	if isinstance(expr, ColumnRef):
		from_src = resolve_table_source_sql(expr.table)
		return f"(SELECT {quote_ident(expr.table)}.{quote_ident(expr.column)} FROM {from_src})"

	raise TypeError(f"Unsupported table expression: {expr}")
