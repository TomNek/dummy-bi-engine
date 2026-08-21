"""
Visual Calculations — post-processing engine for PBI visual calculations.

Implements common DAX visual calculation patterns as post-processing
over the matrix result set:

- RANK(DENSE, ROWS, ORDERBY(...)) → dense rank over rows
- WINDOW(0, ABS, 0, REL, ...) + SUMX → running/cumulative sum
- COLLAPSEALL([Measure], ROWS) → grand total reference
- FORMAT(DIVIDE(...), "percent") → percentage formatting
- [MeasureName] → simple reference to base measure

These are evaluated AFTER the matrix query returns, operating on
the in-memory cell values rather than being compiled to SQL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class VisualCalc:
    """A parsed visual calculation."""
    name: str
    expression: str
    # Parsed components
    calc_type: str  # 'rank' | 'cumulative' | 'grand_total_pct' | 'ref' | 'unknown'
    ref_measure: Optional[str] = None  # The base measure being referenced
    order_direction: str = 'DESC'
    format_type: Optional[str] = None  # 'percent' | None


def parse_visual_calcs(native_calcs: List[Dict[str, Any]]) -> List[VisualCalc]:
    """Parse native_calcs from visual JSON into VisualCalc objects."""
    results: List[VisualCalc] = []
    for calc in native_calcs:
        name = calc.get("name", "")
        expr = calc.get("expression", "").strip()
        vc = _parse_one_calc(name, expr)
        results.append(vc)
    return results


def _parse_one_calc(name: str, expr: str) -> VisualCalc:
    """Parse a single visual calculation expression."""
    # Normalize whitespace
    norm = " ".join(expr.split())

    # Simple reference: [MeasureName]
    m = re.match(r'^\[([^\]]+)\]$', norm)
    if m:
        return VisualCalc(
            name=name, expression=expr,
            calc_type='ref', ref_measure=m.group(1)
        )

    # RANK(DENSE, ROWS, ORDERBY([Measure], DESC|ASC))
    m = re.match(
        r'RANK\s*+\(\s*+DENSE\s*+,\s*+ROWS\s*+,\s*+ORDERBY\s*+\(\s*+\[([^\]]++)\]\s*+,\s*+(ASC|DESC)\s*+\)\s*+\)',
        norm, re.IGNORECASE
    )
    if m:
        return VisualCalc(
            name=name, expression=expr,
            calc_type='rank', ref_measure=m.group(1),
            order_direction=m.group(2).upper()
        )

    # Cumulative/Running total:
    # SUMX(WINDOW(0, ABS, 0, REL, ROWS, ORDERBY([Measure], DESC)), [Measure])
    m = re.match(
        r'SUMX\s*+\(\s*+WINDOW\s*+\(\s*+0\s*+,\s*+ABS\s*+,\s*+0\s*+,\s*+REL\s*+,\s*+ROWS\s*+,\s*+ORDERBY\s*+\(\s*+\[([^\]]++)\]\s*+,\s*+(ASC|DESC)\s*+\)\s*+\)\s*+,\s*+\[([^\]]++)\]\s*+\)',
        norm, re.IGNORECASE
    )
    if m:
        return VisualCalc(
            name=name, expression=expr,
            calc_type='cumulative', ref_measure=m.group(1),
            order_direction=m.group(2).upper()
        )

    # Grand total percentage:
    # FORMAT(DIVIDE([Measure], COLLAPSEALL([Measure], ROWS)), "percent")
    m = re.match(
        r'FORMAT\s*+\(\s*+DIVIDE\s*+\(\s*+\[([^\]]++)\]\s*+,\s*+COLLAPSEALL\s*+\(\s*+\[([^\]]++)\]\s*+,\s*+ROWS\s*+\)\s*+\)\s*+,\s*+"percent"\s*+\)',
        norm, re.IGNORECASE
    )
    if m:
        return VisualCalc(
            name=name, expression=expr,
            calc_type='grand_total_pct', ref_measure=m.group(1),
            format_type='percent'
        )

    # Cumulative percentage:
    # FORMAT(DIVIDE([CumulativeCalc], COLLAPSEALL([Measure], ROWS)), "percent")
    m = re.match(
        r'FORMAT\s*+\(\s*+DIVIDE\s*+\(\s*+\[([^\]]++)\]\s*+,\s*+COLLAPSEALL\s*+\(\s*+\[([^\]]++)\]\s*+,\s*+ROWS\s*+\)\s*+\)\s*+,\s*+"percent"\s*+\)',
        norm, re.IGNORECASE
    )
    if m:
        return VisualCalc(
            name=name, expression=expr,
            calc_type='grand_total_pct', ref_measure=m.group(1),
            format_type='percent'
        )

    return VisualCalc(
        name=name, expression=expr,
        calc_type='unknown'
    )


def evaluate_visual_calcs(
    visual_calcs: List[VisualCalc],
    values: List[Dict[str, Any]],
    row_order: List[str],
    col_leaf_keys: List[str],
    display_to_actual: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Evaluate visual calculations and return additional measure column dicts.

    Args:
        visual_calcs: Parsed visual calculation definitions
        values: Existing measure column dicts from MatrixResult.to_dict()
                Each has {'measure': {...}, 'cells': {rowKey: {colKey: cellDict}}}
        row_order: Ordered row keys from the matrix result
        col_leaf_keys: Column leaf keys from the matrix result
        display_to_actual: Mapping from display names (used in DAX expressions)
                          to actual measure names (used in the result set)

    Returns:
        List of new measure column dicts to append to values
    """
    _d2a = display_to_actual or {}
    # Build a lookup: measure_name -> {rowKey -> {colKey -> numeric_value}}
    measure_lookup: Dict[str, Dict[str, Dict[str, float]]] = {}
    for mc in values:
        mname = mc.get("measure", {}).get("name", "")
        cells = mc.get("cells", {})
        vals: Dict[str, Dict[str, float]] = {}
        for rk, col_cells in cells.items():
            vals[rk] = {}
            for ck, cv in col_cells.items():
                raw = cv.get("value") if isinstance(cv, dict) else cv
                try:
                    vals[rk][ck] = float(raw) if raw is not None else 0.0
                except (ValueError, TypeError):
                    vals[rk][ck] = 0.0
        measure_lookup[mname] = vals

    # Also keep a lookup for computed calcs (so later calcs can reference earlier ones)
    computed_lookup: Dict[str, Dict[str, Dict[str, float]]] = {}

    # ── Dependency-based topological sort ──
    # Visual calcs may reference other calcs (e.g. Cumulative Value % references
    # Cumulative Value). We need to evaluate dependencies first.
    calc_names = {vc.name for vc in visual_calcs}
    base_measure_names = set(measure_lookup.keys())

    def _all_refs(vc: VisualCalc) -> List[str]:
        """Extract all measure references from the expression."""
        return re.findall(r'\[([^\]]+)\]', vc.expression)

    # Simple topological sort: base-only calcs first, then calcs referencing other calcs
    sorted_calcs: List[VisualCalc] = []
    remaining = list(visual_calcs)
    resolved_names = set(base_measure_names) | set(_d2a.values())
    max_iters = len(remaining) + 1
    for _ in range(max_iters):
        if not remaining:
            break
        progress = False
        next_remaining = []
        for vc in remaining:
            refs = _all_refs(vc)
            # A calc is ready if all its refs are either base measures, already
            # resolved computed calcs, or mapped via display_to_actual
            unresolved = [r for r in refs
                          if r not in resolved_names
                          and _d2a.get(r, r) not in resolved_names
                          and r not in base_measure_names]
            if not unresolved:
                sorted_calcs.append(vc)
                resolved_names.add(vc.name)
                progress = True
            else:
                next_remaining.append(vc)
        remaining = next_remaining
        if not progress:
            # Circular dependency or unresolvable — append remaining as-is
            sorted_calcs.extend(remaining)
            break

    new_columns: List[Dict[str, Any]] = []

    for vc in sorted_calcs:
        if vc.calc_type == 'unknown':
            continue

        # Resolve the reference measure (from base measures or previously computed calcs)
        ref_name = vc.ref_measure or ""
        ref_vals = measure_lookup.get(ref_name) or computed_lookup.get(ref_name)
        if ref_vals is None and vc.calc_type != 'ref':
            continue

        cells: Dict[str, Dict[str, Any]] = {}
        computed_vals: Dict[str, Dict[str, float]] = {}

        if vc.calc_type == 'ref':
            # Simple reference — copy the referenced measure
            ref_vals = measure_lookup.get(ref_name) or computed_lookup.get(ref_name)
            if ref_vals is None:
                continue
            for rk in row_order:
                cells[rk] = {}
                for ck in col_leaf_keys:
                    v = (ref_vals.get(rk) or {}).get(ck, 0.0)
                    cells[rk][ck] = {"value": v, "formatted": _format_number(v)}

        elif vc.calc_type == 'rank':
            # Dense rank over row order based on measure values
            assert ref_vals is not None
            for ck in col_leaf_keys:
                # Collect (rowKey, value) pairs
                pairs: List[Tuple[str, float]] = []
                for rk in row_order:
                    v = (ref_vals.get(rk) or {}).get(ck, 0.0)
                    pairs.append((rk, v))
                # Sort to compute rank
                reverse = vc.order_direction == 'DESC'
                sorted_pairs = sorted(pairs, key=lambda x: x[1], reverse=reverse)
                # Dense rank
                rank_map: Dict[str, int] = {}
                prev_val = None
                rank = 0
                for rk, v in sorted_pairs:
                    if v != prev_val:
                        rank += 1
                        prev_val = v
                    rank_map[rk] = rank
                for rk in row_order:
                    if rk not in cells:
                        cells[rk] = {}
                    r = rank_map.get(rk, 0)
                    cells[rk][ck] = {"value": r, "formatted": str(r)}

        elif vc.calc_type == 'cumulative':
            # Running total over rows in display order
            assert ref_vals is not None
            for ck in col_leaf_keys:
                # Sort rows by value for the running total
                pairs: List[Tuple[str, float]] = []
                for rk in row_order:
                    v = (ref_vals.get(rk) or {}).get(ck, 0.0)
                    pairs.append((rk, v))
                reverse = vc.order_direction == 'DESC'
                sorted_by_val = sorted(pairs, key=lambda x: x[1], reverse=reverse)
                # Cumulative sum in sorted order
                cumsum_map: Dict[str, float] = {}
                running = 0.0
                for rk, v in sorted_by_val:
                    running += v
                    cumsum_map[rk] = running
                for rk in row_order:
                    if rk not in cells:
                        cells[rk] = {}
                    cs = cumsum_map.get(rk, 0.0)
                    cells[rk][ck] = {"value": cs, "formatted": _format_number(cs)}
            # Store for later reference
            for rk in row_order:
                computed_vals[rk] = {}
                for ck in col_leaf_keys:
                    cv = cells.get(rk, {}).get(ck, {})
                    computed_vals[rk][ck] = cv.get("value", 0.0) if isinstance(cv, dict) else 0.0

        elif vc.calc_type == 'grand_total_pct':
            # Value / GrandTotal formatted as percent
            # ref_measure might refer to [Value] (base) or [Cumulative Value] (computed)
            source_vals = measure_lookup.get(ref_name) or computed_lookup.get(ref_name)
            if source_vals is None:
                continue
            # Find the base measure for COLLAPSEALL reference
            # The second capture group in the regex is the COLLAPSEALL measure
            # but we stored ref_measure as the first group — extract base from expr
            base_ref = _extract_collapseall_ref(vc.expression)
            if base_ref:
                # Remap display name to actual name
                base_ref_actual = _d2a.get(base_ref, base_ref)
                base_vals = measure_lookup.get(base_ref_actual) or measure_lookup.get(base_ref) or computed_lookup.get(base_ref)
            else:
                base_vals = source_vals
            if base_vals is None:
                base_vals = source_vals

            for ck in col_leaf_keys:
                # Grand total = sum of all row values for this column
                grand_total = sum(
                    (base_vals.get(rk) or {}).get(ck, 0.0)
                    for rk in row_order
                )
                for rk in row_order:
                    if rk not in cells:
                        cells[rk] = {}
                    v = (source_vals.get(rk) or {}).get(ck, 0.0)
                    pct = v / grand_total if grand_total != 0 else 0.0
                    cells[rk][ck] = {
                        "value": pct,
                        "formatted": f"{pct:.1%}",
                    }

        if cells:
            new_columns.append({
                "measure": {"name": vc.name},
                "cells": cells,
            })
            # Store computed values for cross-referencing
            if vc.name not in computed_lookup:
                cv_store: Dict[str, Dict[str, float]] = {}
                for rk in row_order:
                    cv_store[rk] = {}
                    for ck in col_leaf_keys:
                        c = cells.get(rk, {}).get(ck, {})
                        cv_store[rk][ck] = c.get("value", 0.0) if isinstance(c, dict) else 0.0
                computed_lookup[vc.name] = cv_store

    return new_columns


def _extract_collapseall_ref(expr: str) -> Optional[str]:
    """Extract the measure name from COLLAPSEALL([Measure], ROWS) in an expression."""
    m = re.search(r'COLLAPSEALL\s*\(\s*\[([^\]]+)\]', expr, re.IGNORECASE)
    return m.group(1) if m else None


def _format_number(v: float) -> str:
    """Format a number for display."""
    if v == 0:
        return "0"
    if abs(v) >= 1_000_000:
        return f"{v:,.0f}"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) < 0.01:
        return f"{v:.4f}"
    if v == int(v):
        return str(int(v))
    return f"{v:,.2f}"
