"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

import dax_compiler
from dax_engine.ir import MeasureRef
from dax_engine.planner import plan_card_query

from dax_project import load_project

from dax_ui.server._duckdb import _connect_duckdb_for_project
from dax_ui.server._engine import ValidateResult, _ENGINE_LOCK, _ensure_mapping_loaded, get_prepared_engine

logger = logging.getLogger(__name__)


def _validate_measure(project_path: str, name: str) -> ValidateResult:
    try:
        _ensure_mapping_loaded()
        model, _pages, _visuals = load_project(project_path)
        with _ENGINE_LOCK:
            get_prepared_engine(project_path, model)
            _table_ir, sql = plan_card_query(
                MeasureRef(name),
                filters=[],
                model=model,
                ctx=dax_compiler.Context(),
            )

        con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=None, model=model)
        rows = con.execute(dax_compiler.normalize_sql(f"SELECT * FROM {sql}")).fetchall()
        val = rows[0][0] if rows and rows[0] else None
        return ValidateResult(ok=True, value=val, sql=sql)
    except Exception as exc:  # noqa: BLE001
        return ValidateResult(ok=False, error=str(exc), sql=locals().get("sql"))

def _analyze_ir_complexity(ir: Any, model: Any) -> dict[str, Any]:
    """Walk the IR tree and compute complexity metrics."""
    from dax_engine.ir import (
        MeasureRef as MR,
        ColumnRef as CR,
        DaxFunction as DF,
        DaxIteratorFunction as DIF,
        DaxBinaryOp as DBO,
        Literal as LIT,
        TableRef as TR,
        DaxWindowFunction as DWF,
    )

    measure_refs: list[str] = []
    tables: set[str] = set()
    filter_contexts = 0
    iterator_count = 0
    max_depth = 0

    def walk(node: Any, depth: int = 0) -> None:
        nonlocal filter_contexts, iterator_count, max_depth
        if node is None:
            return
        max_depth = max(max_depth, depth)

        if isinstance(node, MR):
            if node.name not in measure_refs:
                measure_refs.append(node.name)
        elif isinstance(node, CR):
            tables.add(node.table)
        elif isinstance(node, TR):
            tables.add(node.name)
        elif isinstance(node, DF):
            fn_upper = (node.fn or "").upper()
            if fn_upper in ("CALCULATE", "CALCULATETABLE"):
                filter_contexts += 1
            for arg in (node.args or []):
                walk(arg, depth + 1)
        elif isinstance(node, DIF):
            iterator_count += 1
            walk(node.table, depth + 1)
            walk(node.expr, depth + 1)
        elif isinstance(node, DWF):
            walk(node.table, depth + 1)
            walk(node.expr, depth + 1)
        elif isinstance(node, DBO):
            walk(node.left, depth + 1)
            walk(node.right, depth + 1)

        # Recurse args for generic Expr-like nodes
        for attr_name in ("args", "table", "expr", "left", "right"):
            val = getattr(node, attr_name, None)
            if val is None:
                continue
            if attr_name == "args" and isinstance(val, (list, tuple)):
                # Already handled in DF branch above, skip to avoid double-count
                if isinstance(node, DF):
                    continue
                for v in val:
                    walk(v, depth + 1)

    walk(ir)

    # Also collect tables from model measures that we reference
    all_measure_names = {str(getattr(m, "name", "")).upper() for m in getattr(model, "measures", []) or []}
    for mref_name in measure_refs:
        if mref_name.upper() in all_measure_names:
            # Referenced measure exists ΓÇö could add transitive analysis here
            pass

    # Classify pattern
    pattern = "simple_aggregation"
    if iterator_count > 0 and filter_contexts > 0:
        pattern = "iterator_with_context_transition"
    elif iterator_count > 0:
        pattern = "iterator_pattern"
    elif filter_contexts > 1:
        pattern = "complex_calculate"
    elif filter_contexts == 1:
        pattern = "calculate_with_filter"
    elif len(measure_refs) > 0:
        pattern = "measure_composition"

    return {
        "nesting_depth": max_depth,
        "filter_contexts": filter_contexts,
        "iterator_count": iterator_count,
        "measure_refs": measure_refs,
        "tables_referenced": sorted(tables),
        "pattern": pattern,
    }

def _generate_dax_suggestions(complexity: dict[str, Any], dax_text: str) -> list[str]:
    """Generate optimization suggestions based on complexity metrics."""
    suggestions: list[str] = []

    nesting = complexity.get("nesting_depth", 0)
    filters = complexity.get("filter_contexts", 0)
    iterators = complexity.get("iterator_count", 0)
    mrefs = complexity.get("measure_refs", [])
    tables = complexity.get("tables_referenced", [])
    pattern = complexity.get("pattern", "")

    if pattern == "simple_aggregation":
        suggestions.append("Simple aggregation ΓÇö performance should be good.")
    elif pattern == "iterator_with_context_transition":
        suggestions.append(
            f"Uses {iterators} iterator(s) with {filters} CALCULATE context(s). "
            "Iterator + context transition is the most expensive DAX pattern. "
            "Consider pre-aggregating or using SUMMARIZE where possible."
        )
    elif pattern == "iterator_pattern":
        suggestions.append(
            f"Uses {iterators} iterator(s) (SUMX/AVERAGEX/etc.). "
            "Iterators scan row-by-row. Ensure the iterated table is as small as possible."
        )
    elif pattern == "complex_calculate":
        suggestions.append(
            f"Uses {filters} CALCULATE contexts. Complex filter stacking can slow evaluation. "
            "Check if some filters can be consolidated."
        )
    elif pattern == "calculate_with_filter":
        suggestions.append("Single CALCULATE with filter ΓÇö typical pattern, generally fine.")
    elif pattern == "measure_composition":
        suggestions.append(
            f"References {len(mrefs)} other measure(s): {', '.join('[' + m + ']' for m in mrefs[:5])}. "
            "Ensure referenced measures are not themselves expensive."
        )

    if nesting > 4:
        suggestions.append(
            f"Deep nesting depth ({nesting}). Consider breaking this into smaller, intermediate measures."
        )

    if len(tables) > 4:
        suggestions.append(
            f"References {len(tables)} tables. Many table references may indicate complex joins. "
            "Verify relationships are set up correctly."
        )

    if len(mrefs) > 5:
        suggestions.append(
            f"References {len(mrefs)} other measures. Deep measure chains can multiply evaluation cost."
        )

    dax_upper = dax_text.upper()
    if "REMOVEFILTERS" in dax_upper or "ALL(" in dax_upper:
        suggestions.append("Uses ALL/REMOVEFILTERS ΓÇö removes filter context. Verify this is intentional.")

    if "CROSSJOIN" in dax_upper:
        suggestions.append("Uses CROSSJOIN ΓÇö can produce very large intermediate tables.")

    if "ADDCOLUMNS" in dax_upper and "SUMMARIZE" in dax_upper:
        suggestions.append(
            "Uses SUMMARIZE + ADDCOLUMNS pattern. Ensure SUMMARIZE only groups columns, "
            "with measures in ADDCOLUMNS (best practice)."
        )

    return suggestions

