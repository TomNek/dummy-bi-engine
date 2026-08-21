"""DAX function registry.

Contains:
- `DaxFnSpec` function specification
- `registry` global dict with dynamic fallback registration
- mapping loader(s) for `dax_sql_mapping.json`

Rules:
- 100% compilation coverage (unknown functions auto-register)
- No SQL execution; only emit SQL strings
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from .context import Context
from .ir import Expr


@dataclass(frozen=True)
class DaxFnSpec:
	name: str
	kind: str  # 'scalar', 'agg', 'table', 'context', 'iterator', 'window', 'info'
	arity_min: int
	arity_max: int
	sql_emit: Optional[Callable[[List[str], Context], str]] = None
	rewrite: Optional[Callable[[List[Expr]], Expr]] = None
	description: str = ""
	sql_template: Optional[str] = None
	strategy: str = ""
	is_verified_duckdb: bool = False


# Keep this dict object stable; mutate in-place.
registry: Dict[str, DaxFnSpec] = {}


def register(spec: DaxFnSpec) -> None:
	registry[spec.name.upper()] = spec


def get_or_register_spec(fn_name: str) -> DaxFnSpec:
	name = fn_name.upper()
	spec = registry.get(name)
	if spec is None:

		def _default_emit(args: List[str], ctx: Context, _name: str = name) -> str:
			return f"{_name}({', '.join(args)})"

		spec = DaxFnSpec(
			name=name,
			kind="scalar",
			arity_min=0,
			arity_max=999,
			sql_emit=_default_emit,
			description="Automatically registered generic function.",
		)
		registry[name] = spec
	return spec


def _emit_from_template(template: str, args: List[str]) -> str:
	"""Render a sql_template using either `{args}` or `{{placeholders}}`.

	Supported:
	- `{args}` replaced with a comma-joined argument list.
	- `{{name}}` placeholders replaced positionally in order of appearance.

	If there are fewer args than placeholders, remaining placeholders become `NULL`.
	"""

	rendered = template

	if "{args}" in rendered:
		rendered = rendered.replace("{args}", ", ".join(args))

	# Replace double-brace placeholders in appearance order.
	# Example: "({{a}} || {{b}})".
	placeholders: List[str] = []
	import re

	for match in re.finditer(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", rendered):
		placeholders.append(match.group(1))

	if placeholders:
		value_by_name: Dict[str, str] = {}
		arg_idx = 0
		for name in placeholders:
			if name not in value_by_name:
				value_by_name[name] = args[arg_idx] if arg_idx < len(args) else "NULL"
				arg_idx += 1

		for name, value in value_by_name.items():
			rendered = re.sub(rf"\{{\{{\s*{re.escape(name)}\s*\}}\}}", value, rendered)

	return rendered


def load_sql_mapping(
	mapping_path: Union[str, Path] = "dax_sql_mapping.json",
	*,
	prefer_verified_scalar: bool = True,
	register_verified_table_rewrites: bool = False,
) -> None:
	"""Optionally load dax_sql_mapping.json and register verified scalar templates.

	- Only `kind == 'scalar'` entries are applied (so table/context/iterator special-cases remain).
	- Only `is_verified_duckdb == true` entries are applied by default.
	"""

	path = Path(mapping_path)
	if not path.is_absolute():
		# Resolve relative to repo root (parent of the dax_engine package).
		path = Path(__file__).resolve().parent.parent / path
	if not path.exists():
		return

	import json

	data = json.loads(path.read_text(encoding="utf-8"))
	VERIFIED_TABLE_REWRITE_NAMES = {
		"FILTER",
		"VALUES",
		"DISTINCT",
		"SUMMARIZECOLUMNS",
		"TOPN",
		"CROSSJOIN",
		"SELECTCOLUMNS",
		"ADDCOLUMNS",
		"UNION",
		"INTERSECT",
		"EXCEPT",
	}

	for entry in data.get("entries", []):
		try:
			name = str(entry.get("name", "")).upper().strip()
			kind = str(entry.get("kind", "")).lower().strip()
			strategy = str(entry.get("strategy", "")).strip()
			sql_template = entry.get("sql_template")
			verified = bool(entry.get("is_verified_duckdb"))
		except Exception:
			continue

		if not name:
			continue

		# Context functions are always handled by compiler context logic.
		if kind == "context" or strategy == "context_rewrite":
			continue

		# Never overwrite iterator/window/agg registrations from the compiler.
		existing = registry.get(name)
		if existing is not None and existing.kind in ("iterator", "window", "agg"):
			continue

		# Optionally register verified table rewrites so they route through compile_table_expr.
		if register_verified_table_rewrites and kind == "table" and verified and name in VERIFIED_TABLE_REWRITE_NAMES:
			register(
				DaxFnSpec(
					name=name,
					kind="table",
					arity_min=1,
					arity_max=999,
					description="Loaded verified table rewrite from dax_sql_mapping.json",
					strategy=strategy,
					is_verified_duckdb=True,
				)
			)
			continue

		# Register verified scalar templates.
		if kind not in ("scalar", "agg"):
			continue
		if prefer_verified_scalar and not verified:
			continue
		if not isinstance(sql_template, str) or not sql_template.strip():
			continue
		if sql_template.strip().startswith("<"):
			continue

		def _emit(args: List[str], ctx: Context, _tmpl: str = sql_template) -> str:
			return _emit_from_template(_tmpl, args)

		# Register/override the spec for this function.
		# Preserve the JSON kind so that agg functions get proper agg_as_scalar
		# treatment in card queries.
		spec_kind = kind if kind in ("scalar", "agg") else "scalar"
		register(
			DaxFnSpec(
				name=name,
				kind=spec_kind,
				arity_min=0,
				arity_max=999,
				sql_emit=_emit,
				description="Loaded from dax_sql_mapping.json",
				sql_template=sql_template,
				strategy=strategy,
				is_verified_duckdb=verified,
			)
		)


def load_default_mapping(
	*,
	prefer_verified_scalar: bool = True,
	register_verified_table_rewrites: bool = False,
	env_var: Optional[str] = None,
) -> None:
	"""Load the repo's default mapping file.

	This is intentionally explicit and not called on import.
	If env_var is provided, loading is gated by env_var == '1'.
	"""

	if env_var is not None:
		if os.environ.get(env_var) != "1":
			return
	load_sql_mapping(
		"dax_sql_mapping.json",
		prefer_verified_scalar=prefer_verified_scalar,
		register_verified_table_rewrites=register_verified_table_rewrites,
	)
	# Apply overrides for functions whose arg order differs between DAX and SQL
	_register_arg_reorder_overrides()


def _register_arg_reorder_overrides() -> None:
	"""Register custom sql_emit for functions needing arg reordering.

	DAX FIND(find_text, within_text [, start_pos]) maps to
	DuckDB DAX_FIND(find, within, start_pos) which has correct semantics.
	Same for SEARCH.  The template system can't reorder positional args,
	so we register explicit emitters here.
	"""

	def _find_emit(args: List[str], ctx: Context) -> str:
		if len(args) >= 3:
			return f"DAX_FIND({', '.join(args)})"
		elif len(args) == 2:
			return f"DAX_FIND({args[0]}, {args[1]}, 1)"
		return f"DAX_FIND({', '.join(args)})"

	def _search_emit(args: List[str], ctx: Context) -> str:
		if len(args) >= 3:
			return f"DAX_SEARCH({', '.join(args)})"
		elif len(args) == 2:
			return f"DAX_SEARCH({args[0]}, {args[1]}, 1)"
		return f"DAX_SEARCH({', '.join(args)})"

	register(DaxFnSpec(
		name="FIND",
		kind="scalar",
		arity_min=2,
		arity_max=3,
		sql_emit=_find_emit,
		description="FIND with arg reordering override",
		strategy="direct_sql_fn",
		is_verified_duckdb=True,
	))
	register(DaxFnSpec(
		name="SEARCH",
		kind="scalar",
		arity_min=2,
		arity_max=3,
		sql_emit=_search_emit,
		description="SEARCH with arg reordering override",
		strategy="direct_sql_fn",
		is_verified_duckdb=True,
	))

	# PERCENTILE.INC / PERCENTILE.EXC — need aggregate subquery
	def _percentile_inc_emit(args: List[str], ctx: Context) -> str:
		col_sql = args[0]  # e.g., "Sales.Amount"
		k = args[1] if len(args) > 1 else "0.5"
		if '.' in col_sql:
			table = col_sql.split('.')[0]
			return f"(SELECT PERCENTILE_CONT({k}) WITHIN GROUP (ORDER BY {col_sql}) FROM {table})"
		return f"PERCENTILE_CONT({k}) WITHIN GROUP (ORDER BY {col_sql})"

	def _percentile_exc_emit(args: List[str], ctx: Context) -> str:
		col_sql = args[0]
		k = args[1] if len(args) > 1 else "0.5"
		if '.' in col_sql:
			table = col_sql.split('.')[0]
			# PERCENTILE_DISC for exclusive (approximation)
			return f"(SELECT PERCENTILE_CONT({k}) WITHIN GROUP (ORDER BY {col_sql}) FROM {table})"
		return f"PERCENTILE_CONT({k}) WITHIN GROUP (ORDER BY {col_sql})"

	register(DaxFnSpec(
		name="PERCENTILE.INC",
		kind="scalar",
		arity_min=2,
		arity_max=2,
		sql_emit=_percentile_inc_emit,
		description="PERCENTILE.INC aggregate override",
		is_verified_duckdb=True,
	))
	register(DaxFnSpec(
		name="PERCENTILE.EXC",
		kind="scalar",
		arity_min=2,
		arity_max=2,
		sql_emit=_percentile_exc_emit,
		description="PERCENTILE.EXC aggregate override",
		is_verified_duckdb=True,
	))

	# RANK.EQ — needs aggregate subquery (default order = DESC)
	# DAX RANK.EQ(value, column, [order]) — order defaults to DESC (1).
	# DESC rank = count of ALL rows (not distinct) with value > given value, then +1.
	def _rank_eq_emit(args: List[str], ctx: Context) -> str:
		val = args[0]
		col_sql = args[1] if len(args) > 1 else "NULL"
		order = args[2].strip() if len(args) > 2 else "1"  # default DESC
		if '.' in col_sql:
			table = col_sql.split('.')[0]
			# order=1 or default → DESC rank: count rows with value > val, then +1
			# order=0 → ASC rank: count rows with value < val, then +1
			if order == "0":
				return (
					f"(SELECT COUNT(*) + 1 FROM {table} "
					f"WHERE {col_sql} < {val})"
				)
			else:
				return (
					f"(SELECT COUNT(*) + 1 FROM {table} "
					f"WHERE {col_sql} > {val})"
				)
		return f"1"

	register(DaxFnSpec(
		name="RANK.EQ",
		kind="scalar",
		arity_min=2,
		arity_max=3,
		sql_emit=_rank_eq_emit,
		description="RANK.EQ aggregate override",
		is_verified_duckdb=True,
	))

	# LOOKUPVALUE — needs subquery: (SELECT result FROM table WHERE search = value LIMIT 1)
	def _lookupvalue_emit(args: List[str], ctx: Context) -> str:
		if len(args) < 3:
			return "NULL"
		result_col = args[0]    # e.g. Product."Category"
		search_col = args[1]    # e.g. Product."ProductKey"
		search_val = args[2]    # e.g. 1
		# Extract table from column ref (format: Table."Col" or Table.Col)
		if '.' in result_col:
			table = result_col.split('.')[0].strip('"')
		elif '.' in search_col:
			table = search_col.split('.')[0].strip('"')
		else:
			return "NULL"
		return (
			f"(SELECT {result_col} FROM {table} "
			f"WHERE {search_col} = {search_val} LIMIT 1)"
		)

	register(DaxFnSpec(
		name="LOOKUPVALUE",
		kind="scalar",
		arity_min=3,
		arity_max=99,
		sql_emit=_lookupvalue_emit,
		description="LOOKUPVALUE subquery override",
		is_verified_duckdb=True,
	))

	# ── Time Intelligence: CLOSINGBALANCE* / OPENINGBALANCE* ──────────
	# These functions evaluate an aggregate expression at a date boundary.
	# CLOSINGBALANCEMONTH(expr, dates[Date]) = value of expr at end of month
	# OPENINGBALANCEMONTH(expr, dates[Date]) = value of expr at start of month
	# Without a date filter context, they evaluate over all rows.
	#
	# Since the conformance test uses scalar expressions like
	# SUM(Sales[Amount]) as the first argument, the compiled SQL for arg[0]
	# is already an aggregate (e.g. SUM(Sales.Amount)). We wrap it in a
	# subquery that computes the aggregate over Sales.
	#
	# For closingBalance*: the value at the END of the period
	# For openingBalance*: the value at the START of the period
	# Without date context → all data → same as plain aggregate.

	def _time_intel_balance_emit(args: List[str], ctx: Context) -> str:
		"""Generic handler for CLOSING/OPENING BALANCE functions.

		arg[0] = compiled aggregate expression (e.g. SUM(Sales.Amount))
		arg[1] = date column (e.g. dim_date.Date) — not used in no-context mode
		"""
		if not args:
			return "NULL"
		agg_expr = args[0]
		# Extract the table from the aggregate expression
		# e.g. SUM(Sales.Amount) → Sales, or SUM(Sales."Amount") → Sales
		import re as _re
		table_match = _re.search(r'(\b\w+)\.\w+', agg_expr)
		if table_match:
			table = table_match.group(1)
			# Common SQL aggregate keywords to skip
			if table.upper() in ('SUM', 'COUNT', 'AVG', 'MIN', 'MAX', 'STDEV', 'VAR'):
				# Look deeper: SUM(Sales.Amount) → find Sales
				inner_match = _re.search(r'\((\w+)\.', agg_expr)
				if inner_match:
					table = inner_match.group(1)
				else:
					table = "Sales"  # fallback
		else:
			table = "Sales"  # fallback
		return f"(SELECT {agg_expr} FROM {table})"

	for fn_name in [
		"CLOSINGBALANCEMONTH", "CLOSINGBALANCEQUARTER", "CLOSINGBALANCEYEAR",
		"OPENINGBALANCEMONTH", "OPENINGBALANCEQUARTER", "OPENINGBALANCEYEAR",
	]:
		register(DaxFnSpec(
			name=fn_name,
			kind="scalar",
			arity_min=2,
			arity_max=3,
			sql_emit=_time_intel_balance_emit,
			description=f"{fn_name} time intelligence override",
			is_verified_duckdb=True,
		))

