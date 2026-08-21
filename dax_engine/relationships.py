"""Relationship model and rowset builder.

This module defines:
- Relationship data model
- Relationship registry (`RELATIONSHIPS`) + setter
- Rowset builder functions used to construct FROM/JOIN trees
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Dict, List, Optional, Tuple

from .context import Context
from .sql_utils import quote_ident
from .table_sources import resolve_table_source_sql


@dataclass(frozen=True)
class Relationship:
	from_table: str
	from_column: str
	to_table: str
	to_column: str
	active: bool = True
	rel_id: str = ""
	cross_filter_direction: str = "single"
	cardinality: Optional[str] = None

	@property
	def is_active(self) -> bool:
		return bool(self.active)


# Minimal in-code relationship list. Tests can override via set_relationships().
RELATIONSHIPS: List[Relationship] = []


def set_relationships(relationships: List[Relationship]) -> None:
	normalized: List[Relationship] = []
	for rel in relationships:
		rel_id = rel.rel_id
		if not rel_id:
			rel_id = f"{rel.from_table}.{rel.from_column}->{rel.to_table}.{rel.to_column}"
		normalized.append(
			Relationship(
				from_table=rel.from_table,
				from_column=rel.from_column,
				to_table=rel.to_table,
				to_column=rel.to_column,
				active=rel.active,
				rel_id=rel_id,
				cross_filter_direction=(str(getattr(rel, "cross_filter_direction", "single") or "single").strip().lower() or "single"),
				cardinality=(str(getattr(rel, "cardinality", "")).strip() or None),
			)
		)
	# Mutate in-place to keep any imported references in sync.
	RELATIONSHIPS.clear()
	RELATIONSHIPS.extend(normalized)


def build_rowset_from_clause(root_table: str, required_tables: List[str]) -> str:
	"""Build a minimal FROM/JOIN clause connecting required tables.

	Current scope: supports simple star-style joins using RELATIONSHIPS.
	If a table cannot be connected, it is omitted (SQL stays syntactically valid).
	"""

	# Back-compat signature: ctx-aware wrapper below calls this.
	return _build_rowset_from_clause_ctx(root_table, required_tables, None)


def _build_rowset_plan_ctx(
	root_table: str, required_tables: List[str], ctx: Optional[Context]
) -> Tuple[str, set[str], List[Tuple[str, "Relationship", str]]]:
	"""Build a minimal FROM/JOIN clause and return connected tables + M:M info.

	Returns:
		(from_clause, connected_tables, semi_join_candidates)
		- from_clause: complete SQL FROM/JOIN string (includes M:M as LEFT JOINs)
		- connected_tables: set of all tables present in the join tree
		- semi_join_candidates: list of (table, relationship, on_clause) for M:M
		  relationships that *could* be converted to WHERE EXISTS by the caller
		  if the table is only used for filtering (not for projected columns)
	"""

	def _qt(name: str) -> str:
		# Back-compat alias for older code; prefer quote_ident.
		return quote_ident(name)

	def _qs(name: str) -> str:
		# Resolve a logical table name to a FROM/JOIN-safe source.
		return resolve_table_source_sql(name)

	required = [t for t in required_tables if t]
	required_set = set(required)
	if not required_set:
		# Keep FROM clause quoting consistent with the join-building path.
		return (_qs(root_table), {root_table}, [])

	root = root_table
	if root not in required_set:
		required_set.add(root)

	overrides: set[str] = set(ctx.relationship_overrides) if ctx is not None else set()
	filter_tables: set[str] = set()
	if ctx is not None:
		for key in ctx.all_filter_keys():
			if "." in key:
				filter_tables.add(key.split(".", 1)[0])

	# Choose an effective relationship per (unordered) table-pair:
	# - if any relationship in the pair is overridden, pick that one (even if inactive)
	# - else pick an active relationship
	# - else keep one relationship to preserve syntactic validity when referenced
	by_pair: Dict[frozenset[str], List[Relationship]] = {}
	for rel in RELATIONSHIPS:
		by_pair.setdefault(frozenset({rel.from_table, rel.to_table}), []).append(rel)

	effective: List[Relationship] = []
	for _pair, rels in by_pair.items():
		chosen: Optional[Relationship] = None
		for r in rels:
			if r.rel_id in overrides:
				chosen = r
				break
		if chosen is None:
			for r in rels:
				if r.is_active:
					chosen = r
					break
		if chosen is None and rels:
			chosen = rels[0]
		if chosen is not None:
			effective.append(chosen)

	# Build undirected adjacency for join-path reconstruction.
	adj_undirected: Dict[str, List[Tuple[str, Relationship]]] = {}
	# Build directed adjacency for filter-propagation reachability.
	adj_directed: Dict[str, List[str]] = {}

	def _normalize_cardinality(value: Optional[str]) -> Optional[str]:
		raw = str(value or "").strip().lower()
		if not raw:
			return None
		mapping = {
			"many_to_one": "many_to_one",
			"many-to-one": "many_to_one",
			"m:1": "many_to_one",
			"*:1": "many_to_one",
			"n:1": "many_to_one",
			"one_to_many": "one_to_many",
			"one-to-many": "one_to_many",
			"1:m": "one_to_many",
			"1:*": "one_to_many",
			"1:n": "one_to_many",
			"one_to_one": "one_to_one",
			"one-to-one": "one_to_one",
			"1:1": "one_to_one",
			"many_to_many": "many_to_many",
			"many-to-many": "many_to_many",
			"*:*": "many_to_many",
			"n:n": "many_to_many",
		}
		return mapping.get(raw, raw)

	def _single_direction_edges(rel: Relationship) -> list[tuple[str, str]]:
		# For single-direction relationships, default to one->many propagation.
		# Legacy/default orientation in this project often stores many->one as
		# from_table -> to_table, so when cardinality is missing we default to
		# to_table -> from_table to preserve established dim->fact behavior.
		card = _normalize_cardinality(getattr(rel, "cardinality", None))
		if card == "one_to_many":
			return [(rel.from_table, rel.to_table)]
		if card == "one_to_one":
			return [(rel.from_table, rel.to_table), (rel.to_table, rel.from_table)]
		if card == "many_to_many":
			return [(rel.from_table, rel.to_table), (rel.to_table, rel.from_table)]
		# many_to_one and unknown both default to to -> from propagation.
		return [(rel.to_table, rel.from_table)]

	for rel in effective:
		adj_undirected.setdefault(rel.from_table, []).append((rel.to_table, rel))
		adj_undirected.setdefault(rel.to_table, []).append((rel.from_table, rel))

		# Inactive relationships must not propagate filters unless explicitly overridden
		# (e.g., USERELATIONSHIP-like behavior routed via context overrides).
		if rel.is_active or rel.rel_id in overrides:
			dir_mode = str(getattr(rel, "cross_filter_direction", "single") or "single").strip().lower()
			if dir_mode == "both":
				directed_edges = [(rel.from_table, rel.to_table), (rel.to_table, rel.from_table)]
			else:
				directed_edges = _single_direction_edges(rel)
		else:
			directed_edges = []
		for src, dst in directed_edges:
			adj_directed.setdefault(src, []).append(dst)

	def _filter_can_propagate_to_root(source_table: str) -> bool:
		if source_table == root:
			return True
		q = deque([source_table])
		seen = {source_table}
		while q:
			cur = q.popleft()
			for nxt in adj_directed.get(cur, []):
				if nxt in seen:
					continue
				if nxt == root:
					return True
				seen.add(nxt)
				q.append(nxt)
		return False

	connected: set[str] = {root}
	joins: List[str] = []
	semi_joins: List[Tuple[str, Relationship, str]] = []  # (table, rel, on_clause) for M:M

	# Greedy connect remaining tables via BFS.
	remaining = [t for t in required_set if t != root]
	while remaining:
		target = remaining.pop(0)
		if target in connected:
			continue

		# Enforce relationship directionality for filter-propagation tables.
		if target in filter_tables and not _filter_can_propagate_to_root(target):
			continue

		# BFS from root to target.
		prev: Dict[str, Tuple[str, Relationship]] = {}
		q = deque([root])
		seen = {root}
		found = False

		while q and not found:
			cur = q.popleft()
			for nxt, rel in adj_undirected.get(cur, []):
				if nxt in seen:
					continue
				seen.add(nxt)
				prev[nxt] = (cur, rel)
				if nxt == target:
					found = True
					break
				q.append(nxt)

		if not found:
			continue

		# Reconstruct path from root -> target and add joins along the path.
		path_nodes: List[str] = [target]
		cur = target
		while cur != root:
			p, _rel = prev[cur]
			path_nodes.append(p)
			cur = p
		path_nodes.reverse()

		for a, b in zip(path_nodes, path_nodes[1:]):
			if b in connected:
				continue
			parent, rel = prev[b]
			if rel.from_table == parent and rel.to_table == b:
				on = f"{_qt(rel.from_table)}.{_qt(rel.from_column)} = {_qt(rel.to_table)}.{_qt(rel.to_column)}"
			elif rel.to_table == parent and rel.from_table == b:
				on = f"{_qt(rel.to_table)}.{_qt(rel.to_column)} = {_qt(rel.from_table)}.{_qt(rel.from_column)}"
			else:
				on = f"{_qt(rel.from_table)}.{_qt(rel.from_column)} = {_qt(rel.to_table)}.{_qt(rel.to_column)}"
			# M:M relationships: avoid LEFT JOIN (causes row multiplication).
			# Instead, track them for semi-join emission by the caller.
			card = _normalize_cardinality(getattr(rel, "cardinality", None))
			joins.append(f"LEFT JOIN {_qs(b)} ON {on}")
			if card == "many_to_many":
				# Track M:M joins as optimization candidates.
				# The from_clause INCLUDES the JOIN for backward compat;
				# callers may convert filter-only M:M tables to EXISTS.
				semi_joins.append((b, rel, on))
			connected.add(b)

	return (" ".join([_qs(root)] + joins), connected, semi_joins)


def _build_rowset_from_clause_ctx(root_table: str, required_tables: List[str], ctx: Optional[Context]) -> str:
	from_clause, _connected, _semi_joins = _build_rowset_plan_ctx(root_table, required_tables, ctx)
	return from_clause

