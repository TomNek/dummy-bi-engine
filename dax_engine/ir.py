"""IR node types.

This module defines the compiler's immutable, SQL-agnostic IR.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields
from typing import Any, List, Optional


FilterScope = str  # one of: 'visual' | 'page' | 'interaction' | 'report'


class Expr:
	"""Base class for all expression nodes."""


@dataclass(frozen=True)
class ScalarExpr(Expr):
	"""Base class for scalar expressions returning a single value per rowset."""


@dataclass(frozen=True)
class TableExpr(Expr):
	"""Base class for expressions returning a table (rowset)."""


@dataclass(frozen=True)
class TableRef(Expr):
	"""Reference to a base table by name, e.g. Sales."""

	name: str


@dataclass(frozen=True)
class ContextTransformExpr(Expr):
	"""Base class for context-rewriting expressions (e.g., CALCULATE, ALL)."""


@dataclass(frozen=True)
class WindowExpr(Expr):
	"""Base class for window/analytic expressions (e.g., RANKX)."""


@dataclass(frozen=True)
class ColumnRef(ScalarExpr):
	table: str
	column: str


@dataclass(frozen=True)
class MeasureRef(ScalarExpr):
	"""Reference to a named measure, e.g. [Total]."""

	name: str


@dataclass(frozen=True)
class SelectedMeasureRef(ScalarExpr):
	"""Placeholder for SELECTEDMEASURE() inside calculation item expressions.

	This node is illegal outside calculation items and must be rewritten away
	(planner-time) before compilation.
	"""


@dataclass(frozen=True)
class ParamRef(ScalarExpr):
	"""Planner-time placeholder for project field parameters.

	This must be resolved to a ColumnRef or MeasureRef before lowering.
	"""

	name: str


@dataclass(frozen=True)
class WhatIfRef(ScalarExpr):
	"""Planner-time placeholder for What-If parameter values.

	This resolves to a scalar numeric Literal based on the current selection.
	Used in measure expressions via WHATIFVALUE("ParamName").
	"""

	name: str


@dataclass(frozen=True)
class CalcGroupItemRef(ScalarExpr):
	"""Planner-time placeholder for a calculation group item selection.

	This represents a user's selection of a calculation item (e.g., YTD from TimeIntelligence group).
	The planner will use this to apply the calculation item's transformation to measures.

	- group: the calculation group name
	- item: the calculation item name within the group
	"""

	group: str
	item: str


@dataclass(frozen=True)
class HierarchyRef(Expr):
	"""Reference to a user-defined hierarchy for visual encodings.

	This is a planner-time placeholder that the matrix planner expands into
	multiple ColumnRefs based on the hierarchy's level definitions.
	It cannot be compiled directly to SQL.
	"""

	name: str


@dataclass(frozen=True)
class Literal(ScalarExpr):
	value: Any


@dataclass(frozen=True)
class SetLiteral(Expr):
	# DAX set literals (e.g. {1, 2} or {"a", "b"}) are scalars; keep this
	# flexible to support non-Literal scalar expressions in lowering.
	values: List[ScalarExpr]


@dataclass(frozen=True)
class DaxBinaryOp(ScalarExpr):
	operator: str
	left: ScalarExpr
	right: Expr


@dataclass(frozen=True)
class DaxFunction(ScalarExpr):
	fn: str
	args: List[Expr]


@dataclass(frozen=True)
class DaxIteratorFunction(ScalarExpr):
	"""Represents iterators like SUMX, AVERAGEX, etc."""

	fn: str
	table: TableExpr
	expr: ScalarExpr


@dataclass(frozen=True)
class DaxWindowFunction(WindowExpr):
	fn: str
	table: TableExpr
	expr: ScalarExpr
	order_by: Optional[List[ColumnRef]] = None


# === Filter IR (Phase 1.1) ===


@dataclass(frozen=True)
class FilterCondition:
	"""A SQL-agnostic filter condition.

	This must NOT contain SQL fragments.
	"""

	column: ColumnRef
	operator: str
	values: List[ScalarExpr]


@dataclass(frozen=True)
class ScopedFilter:
	"""A filter with an explicit scope and optional target binding.

	- scope='report': applies to all visuals
	- scope='page': applies when target == page_id
	- scope='interaction': applies to all visuals (UI-generated crossfiltering)
	- scope='visual': applies when target == visual_id

	If keep=True, filters combine with existing filters (KEEPFILTERS semantics).
	"""

	scope: FilterScope
	condition: FilterCondition
	target: Optional[str] = None
	keep: bool = False
	# Optional metadata used by the runtime/UI for deterministic merge ordering and debugging.
	# These fields must not affect SQL compilation beyond ordering/tagging decisions.
	source: Optional[str] = None  # e.g. 'manual' | 'slicer' | 'interaction'
	slicer_id: Optional[str] = None


# === IR Serialisation ===


def ir_to_dict(node: Any) -> Any:
	"""Recursively convert an IR node tree into a JSON-serialisable dict.

	Designed for debugging/inspection in the React UI.
	"""
	if node is None:
		return None

	# Primitives pass through
	if isinstance(node, (str, int, float, bool)):
		return node

	# Lists / tuples
	if isinstance(node, (list, tuple)):
		return [ir_to_dict(v) for v in node]

	# Dataclass IR nodes → {"_type": "ClassName", field: value, ...}
	if hasattr(node, "__dataclass_fields__"):
		d: dict[str, Any] = {"_type": type(node).__name__}
		for f in dc_fields(node):
			val = getattr(node, f.name)
			d[f.name] = ir_to_dict(val)
		return d

	# Fallback: repr
	return repr(node)
