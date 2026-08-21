"""Scoped filter IR compilation helpers.

Phase 1.1 contract:
- Filters are represented as explicit IR nodes (no SQL fragments stored in the filter IR).
- SQL is a compile target only.
- No SQL parsing / string inspection.

This module compiles FilterCondition/ScopedFilter into DuckDB predicate SQL using
existing IR compilation (`compiler.compile_expr`).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Optional, Sequence

from dax_engine.context import Context
from dax_engine.ir import ColumnRef, FilterCondition, Literal, ScopedFilter


_LIKE_ESCAPE_CHAR = "!"


def _escape_like_pattern(value: str) -> str:
	# Escape LIKE wildcards and the escape char itself.
	# DuckDB requires ESCAPE to be a *single character* string.
	# We use '!' to avoid SQL backslash escaping ambiguity.
	s = str(value)
	s = s.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR + _LIKE_ESCAPE_CHAR)
	s = s.replace("%", _LIKE_ESCAPE_CHAR + "%")
	s = s.replace("_", _LIKE_ESCAPE_CHAR + "_")
	return s


def _norm_scope(scope: str) -> str:
	s = str(scope or "").strip().lower()
	if s in {"report", "page", "interaction", "visual", "drillthrough"}:
		return s
	raise ValueError(
		f"Invalid filter scope: {scope!r} (expected 'report', 'page', 'interaction', 'visual', or 'drillthrough')"
	)


def _condition_key(cond: FilterCondition) -> str:
	col = cond.column
	return f"{col.table}.{col.column}"


def compile_filter_condition_to_sql(cond: FilterCondition, ctx: Context) -> tuple[str, str]:
	"""Compile a FilterCondition to (key, predicate_sql)."""

	from dax_engine.compiler import compile_expr  # local import avoids cycles

	if not isinstance(cond.column, ColumnRef):
		raise TypeError("FilterCondition.column must be ColumnRef")

	op_raw = str(cond.operator or "").strip()
	if not op_raw:
		raise ValueError("FilterCondition.operator is required")
	op = op_raw.strip().lower()
	# Normalize convenience aliases from filters.yaml / UI
	if op == "eq":
		op = "in"
	elif op == "neq":
		op = "!="
	elif op == "gt":
		op = ">"
	elif op == "gte":
		op = ">="
	elif op == "lt":
		op = "<"
	elif op == "lte":
		op = "<="
	elif op in {"not_in", "notin", "not-in", "isnotany", "is_not_any", "is-not-any"}:
		op = "not_in"
	elif op in {"containsany", "contains-any"}:
		op = "contains_any"
	elif op in {"containsall", "contains-all"}:
		op = "contains_all"
	elif op in {"notcontains", "not_contains", "not-contains", "doesnotcontain", "does-not-contain", "doesnotcontainany", "does-not-contain-any"}:
		op = "notcontains_any"
	elif op in {"startswithany", "starts-with-any"}:
		op = "startswith_any"
	elif op in {"notstartswith", "not_startswith", "not-startswith", "doesnotstartwith", "does-not-start-with", "doesnotstartwithany", "does-not-start-with-any"}:
		op = "notstartswith_any"
	elif op in {"endswithany", "ends-with-any"}:
		op = "endswith_any"
	elif op in {"notendswith", "not_endswith", "not-endswith", "doesnotendwith", "does-not-end-with", "doesnotendwithany", "does-not-end-with-any"}:
		op = "notendswith_any"

	values = list(cond.values or [])
	col_sql = compile_expr(cond.column, ctx)
	key = _condition_key(cond)

	def _is_blank_token(v: Any) -> bool:
		return isinstance(v, Literal) and str(getattr(v, "value", None)) == "__BLANK__"

	if op in {"=", "==", "!=", "<>", ">", ">=", "<", "<="}:
		if len(values) != 1:
			raise ValueError(f"Operator {op_raw!r} requires exactly 1 value")
		if _is_blank_token(values[0]):
			# Deterministic blank token semantics: __BLANK__ => IS NULL
			if op in {"!=", "<>"}:
				return (key, f"({col_sql} IS NOT NULL)")
			# Treat '=' and all ordered comparisons as NULL check errors.
			if op not in {"=", "=="}:
				raise ValueError(f"Operator {op_raw!r} is not supported with __BLANK__")
			return (key, f"({col_sql} IS NULL)")
		right_sql = compile_expr(values[0], ctx)
		op_sql = "=" if op == "==" else "<>" if op == "!=" else op
		return (key, f"({col_sql} {op_sql} {right_sql})")

	if op == "in":
		if not values:
			raise ValueError("Operator 'in' requires at least 1 value")
		blank = [v for v in values if _is_blank_token(v)]
		non_blank = [v for v in values if not _is_blank_token(v)]

		parts = [compile_expr(v, ctx) for v in non_blank]
		in_sql = f"({col_sql} IN ({', '.join(parts)}))" if parts else None
		null_sql = f"({col_sql} IS NULL)" if blank else None

		if in_sql and null_sql:
			return (key, f"({in_sql} OR {null_sql})")
		if in_sql:
			return (key, in_sql)
		if null_sql:
			return (key, null_sql)
		raise ValueError("Operator 'in' requires at least 1 non-__BLANK__ value")

	if op == "not_in":
		if not values:
			raise ValueError("Operator 'not_in' requires at least 1 value")
		blank = [v for v in values if _is_blank_token(v)]
		non_blank = [v for v in values if not _is_blank_token(v)]
		parts = [compile_expr(v, ctx) for v in non_blank]
		not_in_sql = f"({col_sql} NOT IN ({', '.join(parts)}))" if parts else None
		not_null_sql = f"({col_sql} IS NOT NULL)" if blank else None

		if not_in_sql and not_null_sql:
			return (key, f"({not_in_sql} AND {not_null_sql})")
		if not_in_sql:
			return (key, not_in_sql)
		if not_null_sql:
			return (key, not_null_sql)
		raise ValueError("Operator 'not_in' requires at least 1 non-__BLANK__ value")

	# Text operators (Power BI-like)
	text_ops = {
		"contains": ("contains", "single", False),
		"startswith": ("startswith", "single", False),
		"endswith": ("endswith", "single", False),
		"contains_any": ("contains", "any", False),
		"contains_all": ("contains", "all", False),
		"notcontains_any": ("contains", "all", True),
		"startswith_any": ("startswith", "any", False),
		"notstartswith_any": ("startswith", "all", True),
		"endswith_any": ("endswith", "any", False),
		"notendswith_any": ("endswith", "all", True),
	}
	if op in text_ops:
		kind, join_mode, negate = text_ops[op]
		if not values:
			raise ValueError(f"Operator {op_raw!r} requires at least 1 value")
		if join_mode == "single" and len(values) != 1:
			raise ValueError(f"Operator {op_raw!r} requires exactly 1 value")
		for v in values:
			if not isinstance(v, Literal):
				raise ValueError(f"Operator {op_raw!r} requires literal values")
		hay_sql = f"CAST({col_sql} AS VARCHAR)"
		predicates: list[str] = []
		for v in values:
			needle = "" if v.value is None else str(v.value)
			esc = _escape_like_pattern(needle)
			if kind == "contains":
				pattern = f"%{esc}%"
			elif kind == "startswith":
				pattern = f"{esc}%"
			else:
				pattern = f"%{esc}"
			pattern_sql = compile_expr(Literal(pattern), ctx)
			match_sql = f"({hay_sql} ILIKE {pattern_sql} ESCAPE '{_LIKE_ESCAPE_CHAR}')"
			if negate:
				predicates.append(f"(({col_sql} IS NULL) OR NOT {match_sql})")
			else:
				predicates.append(match_sql)
		joiner = " OR " if join_mode == "any" else " AND "
		return (key, f"({joiner.join(predicates)})")

	if op == "isblank":
		if values:
			raise ValueError("Operator 'isblank' does not accept values")
		# v1 contract: treat NULL as blank; for text-like, also treat empty/whitespace as blank.
		as_text = f"TRIM(CAST({col_sql} AS VARCHAR))"
		return (key, f"(({col_sql} IS NULL) OR ({as_text} = ''))")

	if op == "isnotblank":
		if values:
			raise ValueError("Operator 'isnotblank' does not accept values")
		as_text = f"TRIM(CAST({col_sql} AS VARCHAR))"
		return (key, f"NOT (({col_sql} IS NULL) OR ({as_text} = ''))")

	# PBI "exists" filter on a ColumnRef means "column IS NOT NULL".
	if op == "exists":
		return (key, f"({col_sql} IS NOT NULL)")

	raise ValueError(f"Unsupported filter operator: {op_raw!r}")


def applicable_scoped_filters(
	filters: Sequence[ScopedFilter], *, page_id: Optional[str], visual_id: Optional[str]
) -> list[ScopedFilter]:
	out: list[ScopedFilter] = []
	for f in list(filters or []):
		scope = _norm_scope(f.scope)
		if scope == "report":
			out.append(f)
			continue
		if scope == "interaction":
			# Interaction filters may be globally-scoped (target=None) or bound to a
			# target visual (target==visual_id). This allows deterministic "overlay"
			# behavior without persisting interaction state.
			if f.target is None:
				out.append(f)
				continue
			if visual_id is not None and str(f.target or "").strip() == str(visual_id):
				out.append(f)
			continue
		if scope == "page":
			if page_id is not None and str(f.target or "").strip() == str(page_id):
				out.append(f)
			continue
		# visual
		if visual_id is not None and str(f.target or "").strip() == str(visual_id):
			out.append(f)
	return out


def apply_scoped_filters_to_context(
	ctx: Context,
	filters: Sequence[ScopedFilter],
	*,
	page_id: Optional[str],
	visual_id: Optional[str],
) -> tuple[Context, list[dict[str, Any]]]:
	"""Apply scoped filters into Context with deterministic precedence.

	Merge order (lowest → highest):
	1) report manual filters
	2) report slicers
	3) page manual filters
	4) page slicers
	5) visual manual filters
	6) (reserved) visual slicers (not supported)
	7) interaction filters (exploratory overlays)

	Returns (new_ctx, applied_metadata).
	"""

	working = ctx
	applied_meta: list[dict[str, Any]] = []

	def _apply(scope: str, subset: Iterable[ScopedFilter]) -> None:
		nonlocal working
		for f in subset:
			key, pred_sql = compile_filter_condition_to_sql(f.condition, working)
			if f.keep:
				working = working.apply_filters_keep({key: pred_sql})
			else:
				working = working.apply_filters({key: pred_sql})
			applied_meta.append(
				{
					"scope": _norm_scope(scope),
					"target": f.target,
					"keep": bool(f.keep),
					"source": getattr(f, "source", None),
					"slicer_id": getattr(f, "slicer_id", None),
					"key": key,
					"condition": {
						"column": {"type": "ColumnRef", "table": f.condition.column.table, "column": f.condition.column.column},
						"operator": f.condition.operator,
						"values": [asdict(v) if hasattr(v, "__dataclass_fields__") else getattr(v, "value", v) for v in (f.condition.values or [])],
					},
				}
			)

	filters_list = applicable_scoped_filters(list(filters or []), page_id=page_id, visual_id=visual_id)

	def _src(f: ScopedFilter) -> str:
		return str(getattr(f, "source", None) or "manual").strip().lower() or "manual"

	report_manual = [f for f in filters_list if _norm_scope(f.scope) == "report" and _src(f) != "slicer"]
	report_slicers = [f for f in filters_list if _norm_scope(f.scope) == "report" and _src(f) == "slicer"]

	page_manual = [f for f in filters_list if _norm_scope(f.scope) == "page" and _src(f) != "slicer"]
	page_slicers = [f for f in filters_list if _norm_scope(f.scope) == "page" and _src(f) == "slicer"]

	visual_manual = [f for f in filters_list if _norm_scope(f.scope) == "visual" and _src(f) != "slicer"]
	visual_slicers = [f for f in filters_list if _norm_scope(f.scope) == "visual" and _src(f) == "slicer"]
	if visual_slicers:
		raise ValueError("visual slicers are reserved and not supported")

	interaction = [f for f in filters_list if _norm_scope(f.scope) == "interaction"]

	_apply("report", report_manual)
	_apply("report", report_slicers)
	_apply("page", page_manual)
	_apply("page", page_slicers)
	_apply("visual", visual_manual)
	_apply("interaction", interaction)
	return working, applied_meta
