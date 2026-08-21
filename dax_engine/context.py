"""Context model.

The Context tracks filter predicates, grouping scope, relationship overrides,
and What-If parameter values.
It is immutable-by-convention: methods return copied Context instances.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


class Context:
	"""Represents the evaluation context for DAX expressions.

	- filter_predicates: mapping "Table.Column" -> predicate SQL string (INNER)
	- outer_filter_predicates: sticky selections (OUTER)
	- grouping_scope: list of (table, column) for ISINSCOPE/grouping
	- relationship_overrides: activated relationship ids (USERELATIONSHIP)
	- row_context_alias: correlation alias used by iterators/window logic
	- what_if_values: mapping param_name (upper) -> current effective value (float)
	"""

	def __init__(
		self,
		filter_predicates: Optional[Dict[str, str]] = None,
		outer_filter_predicates: Optional[Dict[str, str]] = None,
		security_predicates: Optional[Dict[str, str]] = None,
		grouping_scope: Optional[List[Tuple[str, str]]] = None,
		relationship_overrides: Optional[set[str]] = None,
		row_context_alias: Optional[str] = None,
		what_if_values: Optional[Dict[str, float]] = None,
	):
		self.filter_predicates: Dict[str, str] = dict(filter_predicates) if filter_predicates else {}
		self.outer_filter_predicates: Dict[str, str] = (
			dict(outer_filter_predicates) if outer_filter_predicates else {}
		)
		# Security predicates are non-removable (RLS). They are always ANDed with
		# user filters for the same key and are not affected by REMOVEFILTERS.
		self.security_predicates: Dict[str, str] = dict(security_predicates) if security_predicates else {}
		self.grouping_scope: List[Tuple[str, str]] = list(grouping_scope) if grouping_scope else []
		self.relationship_overrides: set[str] = set(relationship_overrides) if relationship_overrides else set()
		self.row_context_alias: Optional[str] = row_context_alias
		# What-If parameter values: param_name (UPPER) -> float value
		self.what_if_values: Dict[str, float] = dict(what_if_values) if what_if_values else {}
		# When True, aggregate functions (SUM, COUNT, AVG, etc.) with ColumnRef
		# arguments compile as scalar subqueries that query their home table
		# directly.  Prevents fan-out in card queries that join multiple tables.
		# NOTE: This is a dynamic attribute — it is NOT propagated through
		# Context clone methods.  Set it on the final context before compiling.
		self.agg_as_scalar: bool = False

	def set_outer_from_current(self) -> "Context":
		"""Idempotently capture the current filter_predicates as outer filters.

		v1 contract: at query entry, copy inner filters into outer once.
		"""

		if self.outer_filter_predicates:
			return self
		if not self.filter_predicates:
			return self
		return Context(
			dict(self.filter_predicates),
			outer_filter_predicates=dict(self.filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def _effective_predicates(self) -> Dict[str, str]:
		# Outer filters are sticky; inner overrides outer on same key.
		merged = dict(self.outer_filter_predicates)
		merged.update(self.filter_predicates)
		# Security predicates are always applied and cannot be overridden.
		if not self.security_predicates:
			return merged
		out = dict(merged)
		for k, sec in self.security_predicates.items():
			if k in out and out[k]:
				out[k] = f"({sec}) AND ({out[k]})"
			else:
				out[k] = sec
		return out

	def apply_security_predicates(self, filters: Dict[str, str]) -> "Context":
		"""Apply non-removable security predicates (RLS).

		If a key already exists, combine with AND.
		"""

		new_sec = dict(self.security_predicates)
		for k, v in (filters or {}).items():
			ks = str(k)
			vs = str(v)
			if ks in new_sec and new_sec[ks]:
				new_sec[ks] = f"({new_sec[ks]}) AND ({vs})"
			else:
				new_sec[ks] = vs
		return Context(
			filter_predicates=dict(self.filter_predicates),
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=new_sec,
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def all_filter_keys(self) -> List[str]:
		return list(self._effective_predicates().keys())

	def with_row_context(self, alias: Optional[str]) -> "Context":
		return Context(
			filter_predicates=dict(self.filter_predicates),
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=alias,
			what_if_values=dict(self.what_if_values),
		)

	def apply_filters(self, filters: Dict[str, str]) -> "Context":
		new_filters = dict(self.filter_predicates)
		new_filters.update(filters)
		return Context(
			new_filters,
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def apply_filters_keep(self, filters: Dict[str, str]) -> "Context":
		"""Apply filters using KEEPFILTERS semantics: combine same-key filters with AND."""

		new_filters = dict(self.filter_predicates)
		for k, v in filters.items():
			if k in new_filters and new_filters[k]:
				new_filters[k] = f"({new_filters[k]}) AND ({v})"
			else:
				new_filters[k] = v
		return Context(
			new_filters,
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def activate_relationship(self, rel_id: str) -> "Context":
		overrides = set(self.relationship_overrides)
		overrides.add(str(rel_id))
		return Context(
			dict(self.filter_predicates),
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=overrides,
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_filter_key(self, key: str) -> "Context":
		"""Remove an INNER filter by key (back-compat)."""

		k = str(key)
		if k not in self.filter_predicates:
			return Context(
				dict(self.filter_predicates),
				outer_filter_predicates=dict(self.outer_filter_predicates),
				security_predicates=dict(self.security_predicates),
				grouping_scope=list(self.grouping_scope),
				relationship_overrides=set(self.relationship_overrides),
				row_context_alias=self.row_context_alias,
				what_if_values=dict(self.what_if_values),
			)
		new_filters = dict(self.filter_predicates)
		new_filters.pop(k, None)
		return Context(
			new_filters,
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_inner_filters_for_table(self, table: str) -> "Context":
		prefix = f"{table}."
		new_filters: Dict[str, str] = {}
		for k, v in self.filter_predicates.items():
			if not k.startswith(prefix):
				new_filters[k] = v
		return Context(
			new_filters,
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_outer_filters_for_table(self, table: str) -> "Context":
		prefix = f"{table}."
		new_outer: Dict[str, str] = {}
		for k, v in self.outer_filter_predicates.items():
			if not k.startswith(prefix):
				new_outer[k] = v
		return Context(
			dict(self.filter_predicates),
			outer_filter_predicates=new_outer,
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_filters_for_table_both(self, table: str) -> "Context":
		return self.remove_inner_filters_for_table(table).remove_outer_filters_for_table(table)

	def remove_inner_filter_key(self, key: str) -> "Context":
		return self.remove_filter_key(key)

	def remove_outer_filter_key(self, key: str) -> "Context":
		k = str(key)
		if k not in self.outer_filter_predicates:
			return self
		new_outer = dict(self.outer_filter_predicates)
		new_outer.pop(k, None)
		return Context(
			dict(self.filter_predicates),
			outer_filter_predicates=new_outer,
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_filter_key_both(self, key: str) -> "Context":
		return self.remove_inner_filter_key(key).remove_outer_filter_key(key)

	def clear_all_filters_both(self) -> "Context":
		return Context(
			{},
			outer_filter_predicates={},
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_filters_for_table(self, table: str) -> "Context":
		# Back-compat: removes INNER filters only.
		return self.remove_inner_filters_for_table(table)

	def remove_all_except(self, table: str, keep_keys: List[str]) -> "Context":
		# Back-compat: applies to INNER only.
		prefix = f"{table}."
		keep_set = {str(k) for k in keep_keys}
		new_filters: Dict[str, str] = {}
		for k, v in self.filter_predicates.items():
			if not k.startswith(prefix):
				new_filters[k] = v
			elif k in keep_set:
				new_filters[k] = v
		return Context(
			new_filters,
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_all_except_both(self, table: str, keep_keys: List[str]) -> "Context":
		prefix = f"{table}."
		keep_set = {str(k) for k in keep_keys}

		new_inner: Dict[str, str] = {}
		for k, v in self.filter_predicates.items():
			if not k.startswith(prefix) or k in keep_set:
				new_inner[k] = v

		new_outer: Dict[str, str] = {}
		for k, v in self.outer_filter_predicates.items():
			if not k.startswith(prefix) or k in keep_set:
				new_outer[k] = v

		return Context(
			new_inner,
			outer_filter_predicates=new_outer,
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def remove_filters(self, tables: Optional[List[str]] = None) -> "Context":
		if tables is None:
			return Context(
				{},
				outer_filter_predicates=dict(self.outer_filter_predicates),
				security_predicates=dict(self.security_predicates),
				grouping_scope=list(self.grouping_scope),
				relationship_overrides=set(self.relationship_overrides),
				row_context_alias=self.row_context_alias,
				what_if_values=dict(self.what_if_values),
			)
		table_set = set(tables)
		new_filters: Dict[str, str] = {}
		for k, v in self.filter_predicates.items():
			# k is "Table.Column"
			t = k.split(".", 1)[0] if "." in k else k
			if t not in table_set:
				new_filters[k] = v
		return Context(
			new_filters,
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=dict(self.what_if_values),
		)

	def where_clause(self, table: str) -> str:
		clauses: List[str] = []
		prefix = f"{table}."
		for k, predicate in self._effective_predicates().items():
			if k.startswith(prefix):
				clauses.append(predicate)
		return f"WHERE {' AND '.join(clauses)}" if clauses else ""

	def where_clause_for_tables(self, tables: List[str]) -> str:
		clauses: List[str] = []
		prefixes = {f"{t}." for t in tables}
		for k, predicate in self._effective_predicates().items():
			for p in prefixes:
				if k.startswith(p):
					clauses.append(predicate)
					break
		return f"WHERE {' AND '.join(clauses)}" if clauses else ""

	def with_what_if_values(self, values: Optional[Dict[str, float]]) -> "Context":
		"""Return a new context with the specified What-If parameter values.

		Values are stored case-insensitively by parameter name (upper).
		If values is None or empty, returns self.
		"""
		if not values:
			return self
		normalized: Dict[str, float] = {}
		for k, v in values.items():
			if k is None:
				continue
			name = str(k).strip()
			if not name:
				continue
			normalized[name.upper()] = float(v)
		if not normalized:
			return self
		return Context(
			filter_predicates=dict(self.filter_predicates),
			outer_filter_predicates=dict(self.outer_filter_predicates),
			security_predicates=dict(self.security_predicates),
			grouping_scope=list(self.grouping_scope),
			relationship_overrides=set(self.relationship_overrides),
			row_context_alias=self.row_context_alias,
			what_if_values=normalized,
		)

	def get_what_if_value(self, param_name: str) -> Optional[float]:
		"""Get the effective value for a What-If parameter by name.

		Returns None if not set.
		"""
		if not param_name:
			return None
		return self.what_if_values.get(str(param_name).strip().upper())

