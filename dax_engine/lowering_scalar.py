"""Scalar lowering helpers.

These helpers implement special-case scalar semantics that would otherwise be
awkward to represent via plain SQL templates.

To avoid circular imports, helpers accept compiler callbacks like `compile_expr`.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Protocol

from .context import Context
from .ir import ColumnRef, DaxFunction, Expr, Literal
from .relationships import _build_rowset_plan_ctx


class CompileExprFn(Protocol):
	def __call__(self, expr: Expr, ctx: Context) -> str: ...


class CompileTableExprFn(Protocol):
	def __call__(self, expr: Expr, ctx: Context) -> str: ...


class CollectTablesFn(Protocol):
	def __call__(self, expr: Expr) -> List[str]: ...


class AsFromSourceFn(Protocol):
	def __call__(self, table_sql: str, alias: str = "t") -> str: ...


class RewriteQualifiersFn(Protocol):
	def __call__(self, expr_sql: str, alias: str) -> str: ...


def emit_case_when(args: List[str], ctx: Context) -> str:
	pieces: List[str] = []
	n = len(args)
	default = args[-1] if (n % 2 == 1) else "NULL"
	limit = n - 1 if (n % 2 == 1) else n
	for i in range(0, limit, 2):
		cond = args[i]
		val = args[i + 1]
		pieces.append(f"WHEN {cond} THEN {val}")
	return f"(CASE {' '.join(pieces)} ELSE {default} END)"


def _as_scalar_sql(expr_sql: str) -> str:
	"""Ensure compiled SQL can be used as a scalar expression.

	Some scalar DAX expressions (notably CALCULATE / measure compilation) lower to a
	full SQL query like "SELECT ... AS result FROM ...". When such SQL is embedded
	into larger expressions (CASE, comparisons, arithmetic), it must be wrapped as
	a scalar subquery.
	"""
	s = expr_sql.strip()
	if not s:
		return expr_sql

	def _has_single_outer_parens(text: str) -> bool:
		if not (text.startswith("(") and text.endswith(")")):
			return False
		depth = 0
		for i, ch in enumerate(text):
			if ch == "(":
				depth += 1
			elif ch == ")":
				depth -= 1
				if depth == 0 and i != len(text) - 1:
					return False
		return depth == 0

	upper = s.upper()
	if upper.startswith("SELECT") or upper.startswith("WITH"):
		return f"({expr_sql})"

	# Avoid double-wrapping already-parenthesized scalar subqueries.
	if _has_single_outer_parens(s):
		inner = s[1:-1].strip()
		inner_upper = inner.upper()
		if inner_upper.startswith("SELECT") or inner_upper.startswith("WITH"):
			return expr_sql

	return expr_sql


def compile_switch(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	"""Lower DAX SWITCH to DuckDB CASE.

	Supported forms:
	- SWITCH(TRUE(), cond1, res1, ..., [else]) => CASE WHEN cond1 THEN res1 ... ELSE else_or_NULL END
	- SWITCH(x, val1, res1, ..., [else])      => CASE x WHEN val1 THEN res1 ... ELSE else_or_NULL END

	Malformed shapes must compile to syntactically valid SQL (fallback: NULL).
	"""

	if not expr.args:
		return "NULL"

	first = expr.args[0]

	is_true_form = isinstance(first, Literal) and first.value is True
	remaining = expr.args[1:]

	if not remaining:
		return "NULL"

	# Determine optional ELSE.
	else_sql = "NULL"
	if len(remaining) % 2 == 1:
		else_sql = _as_scalar_sql(compile_expr(remaining[-1], ctx))
		pair_args = remaining[:-1]
	else:
		pair_args = remaining

	pair_count = len(pair_args) // 2
	if pair_count <= 0:
		return "NULL"

	if is_true_form:
		# CASE WHEN cond THEN result ...
		whens: List[str] = []
		for i in range(pair_count):
			cond_expr = pair_args[2 * i]
			res_expr = pair_args[2 * i + 1]
			cond_sql = _as_scalar_sql(compile_expr(cond_expr, ctx))
			res_sql = _as_scalar_sql(compile_expr(res_expr, ctx))
			whens.append(f"WHEN {cond_sql} THEN {res_sql}")
		return f"(CASE {' '.join(whens)} ELSE {else_sql} END)"

	# CASE <expr> WHEN value THEN result ...
	base_sql = _as_scalar_sql(compile_expr(first, ctx))
	whens = []
	for i in range(pair_count):
		val_expr = pair_args[2 * i]
		res_expr = pair_args[2 * i + 1]
		val_sql = _as_scalar_sql(compile_expr(val_expr, ctx))
		res_sql = _as_scalar_sql(compile_expr(res_expr, ctx))
		whens.append(f"WHEN {val_sql} THEN {res_sql}")
	return f"(CASE {base_sql} {' '.join(whens)} ELSE {else_sql} END)"


def compile_coalesce(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	if not expr.args:
		return "NULL"
	if len(expr.args) == 1:
		return _as_scalar_sql(compile_expr(expr.args[0], ctx))
	return f"COALESCE({', '.join(_as_scalar_sql(compile_expr(a, ctx)) for a in expr.args)})"


def compile_isblank(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	inner = expr.args[0] if expr.args else Literal(None)
	inner_sql = _as_scalar_sql(compile_expr(inner, ctx))
	return f"({inner_sql} IS NULL)"


def compile_iferror(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	if not expr.args:
		return "NULL"
	child_raw_sql = compile_expr(expr.args[0], ctx)
	child_sql = _as_scalar_sql(child_raw_sql)
	fallback_sql = _as_scalar_sql(compile_expr(expr.args[1], ctx)) if len(expr.args) >= 2 else "NULL"

	def _is_query_shaped(sql: str) -> bool:
		head = sql.strip().upper()
		return head.startswith("SELECT") or head.startswith("WITH")

	def _has_single_outer_parens(text: str) -> bool:
		s = text.strip()
		if not (s.startswith("(") and s.endswith(")")):
			return False
		depth = 0
		for i, ch in enumerate(s):
			if ch == "(":
				depth += 1
			elif ch == ")":
				depth -= 1
				if depth == 0 and i != len(s) - 1:
					return False
		return depth == 0

	def _is_scalar_subquery_wrapper(sql: str) -> bool:
		s = sql.strip()
		if not _has_single_outer_parens(s):
			return False
		inner = s[1:-1].strip()
		return _is_query_shaped(inner)

	# DuckDB limitation: TRY(...) cannot wrap scalar subqueries.
	if _is_query_shaped(child_raw_sql) or _is_scalar_subquery_wrapper(child_sql):
		# Preserve previous NULL-fallback behavior.
		return f"COALESCE({child_sql}, {fallback_sql})"

	# DuckDB treats division-by-zero as inf (not error), so TRY() won't
	# catch it.  Add an explicit infinity check alongside TRY().
	#
	# Crucially, DAX IFERROR catches only *errors*, NOT BLANK/NULL.
	# DIVIDE(x, 0) returns BLANK (NULL), and IFERROR should NOT catch it.
	# To distinguish "child errored" from "child returned NULL naturally",
	# we use: TRY((child_sql) IS NOT NULL) IS NULL
	#   - If child errors: IS NOT NULL also errors → TRY returns NULL → IS NULL = TRUE
	#   - If child returns NULL normally: IS NOT NULL = FALSE → TRY(FALSE) = FALSE → IS NULL = FALSE
	#   - If child returns a value: IS NOT NULL = TRUE → TRY(TRUE) = TRUE → IS NULL = FALSE
	error_check = f"TRY(({child_sql}) IS NOT NULL) IS NULL"
	inf_check = f"ISINF(CAST(TRY({child_sql}) AS DOUBLE))"
	return (
		f"(CASE WHEN {error_check} THEN {fallback_sql}"
		f" WHEN {inf_check} THEN {fallback_sql}"
		f" ELSE {child_sql} END)"
	)




def compile_divide(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	if len(expr.args) < 2:
		return "NULL"
	numerator_sql = _as_scalar_sql(compile_expr(expr.args[0], ctx))
	denom_sql = _as_scalar_sql(compile_expr(expr.args[1], ctx))
	alt_sql = _as_scalar_sql(compile_expr(expr.args[2], ctx)) if len(expr.args) >= 3 else "NULL"
	return (
		f"(CASE WHEN ({denom_sql} = 0 OR {denom_sql} IS NULL) THEN {alt_sql} "
		f"ELSE ({numerator_sql} / {denom_sql}) END)"
	)


def compile_hasonevalue(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	if not expr.args or not isinstance(expr.args[0], ColumnRef):
		return "FALSE"

	col = expr.args[0]
	col_sql = compile_expr(col, ctx)

	required_tables: set[str] = {col.table}
	for key in ctx.all_filter_keys():
		if "." in key:
			required_tables.add(key.split(".", 1)[0])

	from_clause, connected, _ = _build_rowset_plan_ctx(col.table, sorted(required_tables), ctx)
	where = ctx.where_clause_for_tables(sorted(connected))
	where_sql = f" {where}" if where else ""

	return f"(SELECT COUNT(DISTINCT {col_sql}) = 1 FROM {from_clause}{where_sql})"


def compile_selectedvalue(expr: DaxFunction, ctx: Context, *, compile_expr: CompileExprFn) -> str:
	if not expr.args or not isinstance(expr.args[0], ColumnRef):
		return "NULL"

	col = expr.args[0]
	col_sql = compile_expr(col, ctx)
	alt_sql = _as_scalar_sql(compile_expr(expr.args[1], ctx)) if len(expr.args) >= 2 else "NULL"

	required_tables: set[str] = {col.table}
	for key in ctx.all_filter_keys():
		if "." in key:
			required_tables.add(key.split(".", 1)[0])

	from_clause, connected, _ = _build_rowset_plan_ctx(col.table, sorted(required_tables), ctx)
	where = ctx.where_clause_for_tables(sorted(connected))
	where_sql = f" {where}" if where else ""

	return (
		"(SELECT CASE "
		f"WHEN COUNT(DISTINCT {col_sql}) = 1 THEN MIN({col_sql}) "
		f"ELSE {alt_sql} END FROM {from_clause}{where_sql})"
	)


def compile_hasonefilter(expr: DaxFunction, ctx: Context) -> str:
	if not expr.args or not isinstance(expr.args[0], ColumnRef):
		return "FALSE"
	key = f"{expr.args[0].table}.{expr.args[0].column}"
	return "TRUE" if key in ctx._effective_predicates() else "FALSE"


def compile_isfiltered(expr: DaxFunction, ctx: Context) -> str:
	return compile_hasonefilter(expr, ctx)


def compile_iscrossfiltered(expr: DaxFunction, ctx: Context) -> str:
	if not expr.args or not isinstance(expr.args[0], ColumnRef):
		return "FALSE"

	col = expr.args[0]
	key = f"{col.table}.{col.column}"
	eff = ctx._effective_predicates()
	if key in eff:
		return "TRUE"

	prefix = f"{col.table}."
	for k in eff.keys():
		if k.startswith(prefix):
			return "TRUE"
	return "FALSE"


def compile_concatenatex(
	expr: DaxFunction,
	ctx: Context,
	*,
	compile_expr: CompileExprFn,
	compile_table_expr: CompileTableExprFn,
	collect_tables: CollectTablesFn,
	as_from_source: AsFromSourceFn,
	rewrite_qualifiers_to_alias: RewriteQualifiersFn,
) -> str:
	"""DAX: CONCATENATEX(tableExpr, scalarExpr, delimiter, [orderByExpr], [order], [ignoreEmpty])."""

	def _is_compile_time_true(arg: Expr) -> bool:
		if isinstance(arg, Literal) and arg.value is True:
			return True
		if isinstance(arg, DaxFunction) and arg.fn.upper() == "TRUE":
			return True
		return False

	def _parse_order_dir(arg: Expr) -> str:
		if isinstance(arg, Literal) and isinstance(arg.value, str):
			v = arg.value.strip().upper()
			if v in {"ASC", "DESC"}:
				return v
		return "ASC"

	if len(expr.args) < 2:
		return "NULL"

	table_expr = expr.args[0]
	scalar_expr = expr.args[1]
	delim_sql = "''"
	if len(expr.args) >= 3:
		try:
			delim_sql = compile_expr(expr.args[2], ctx)
		except Exception:
			delim_sql = "''"

	order_by_expr: Optional[Expr] = expr.args[3] if len(expr.args) >= 4 else None
	order_dir = _parse_order_dir(expr.args[4]) if len(expr.args) >= 5 else "ASC"
	ignore_empty = _is_compile_time_true(expr.args[5]) if len(expr.args) >= 6 else False

	try:
		table_sql = compile_table_expr(table_expr, ctx)
	except Exception:
		return "NULL"

	from_source = as_from_source(table_sql, "src")

	try:
		val_sql = compile_expr(scalar_expr, ctx)
	except Exception:
		return "NULL"

	ord_sql: Optional[str] = None
	if order_by_expr is not None:
		try:
			ord_sql = compile_expr(order_by_expr, ctx)
		except Exception:
			ord_sql = None

	if from_source != table_sql:
		val_sql = rewrite_qualifiers_to_alias(val_sql, "src")
		if ord_sql is not None:
			ord_sql = rewrite_qualifiers_to_alias(ord_sql, "src")

	tables_in_scope = collect_tables(table_expr)
	where = ctx.where_clause_for_tables(tables_in_scope)
	where_sql = f" {where}" if where else ""
	if where_sql and from_source != table_sql:
		where_sql = " " + rewrite_qualifiers_to_alias(where_sql.strip(), "src")

	extra_predicates: List[str] = []
	if ignore_empty:
		extra_predicates.append(f"({val_sql} IS NOT NULL)")
	if extra_predicates:
		if where_sql:
			where_sql = where_sql + " AND " + " AND ".join(extra_predicates)
		else:
			where_sql = " WHERE " + " AND ".join(extra_predicates)

	ord_select = f", {ord_sql} AS ord" if ord_sql is not None else ""
	inner = f"SELECT {val_sql} AS val{ord_select} FROM {from_source}{where_sql}"

	if ord_sql is not None:
		agg = f"STRING_AGG(CAST(t.val AS VARCHAR), {delim_sql} ORDER BY t.ord {order_dir})"
	else:
		agg = f"STRING_AGG(CAST(t.val AS VARCHAR), {delim_sql} ORDER BY t.val ASC)"

	return f"(SELECT {agg} FROM ({inner}) AS t)"

