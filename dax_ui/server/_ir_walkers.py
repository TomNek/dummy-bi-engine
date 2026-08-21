"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from dax_engine import ir as _ir
from dax_project.introspection import list_columns, list_measures, list_tables
_ColumnRef = _ir.ColumnRef
_MeasureRef = _ir.MeasureRef

def _collect_expr_refs_from_json(obj: Any) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Collect (table, column) ColumnRef and MeasureRef names from a JSON-ish structure."""

    cols: list[tuple[str, str, str]] = []
    measures: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, Mapping):
            t = x.get("type")
            if t == "ColumnRef":
                table = str(x.get("table") or "").strip()
                column = str(x.get("column") or "").strip()
                if table and column:
                    cols.append((table, column, "ColumnRef"))
            elif t == "MeasureRef":
                name = str(x.get("name") or "").strip()
                if name:
                    measures.append(name)

            for v in x.values():
                walk(v)
            return

        if isinstance(x, list):
            for it in x:
                walk(it)

    walk(obj)
    return cols, measures

def _ols_hidden_refs_for_visual(*, model_full: Any, model_scoped: Any, visual_json: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return refs that exist in the full model but are hidden in the scoped model."""

    enc = visual_json.get("encodings") or {}
    cols_used, measures_used = _collect_expr_refs_from_json(enc)

    # Build full/scoped symbol sets (case-insensitive).
    full_tables = {str(t).upper() for t in list_tables(model_full)}
    scoped_tables = {str(t).upper() for t in list_tables(model_scoped)}

    full_cols: dict[str, set[str]] = {}
    scoped_cols: dict[str, set[str]] = {}
    for t in full_tables:
        try:
            full_cols[t] = {str(c).upper() for c in list_columns(model_full, t)}
        except Exception:
            full_cols[t] = set()
    for t in scoped_tables:
        try:
            scoped_cols[t] = {str(c).upper() for c in list_columns(model_scoped, t)}
        except Exception:
            scoped_cols[t] = set()

    full_measures = {str(m).upper() for m in list_measures(model_full)}
    scoped_measures = {str(m).upper() for m in list_measures(model_scoped)}

    hidden: list[dict[str, Any]] = []

    for table, column, _kind in cols_used:
        t_key = str(table).upper()
        c_key = str(column).upper()
        if t_key in full_tables and t_key not in scoped_tables:
            hidden.append({"kind": "table", "table": table})
            continue
        if t_key in full_tables and t_key in scoped_tables:
            if c_key in full_cols.get(t_key, set()) and c_key not in scoped_cols.get(t_key, set()):
                hidden.append({"kind": "column", "table": table, "column": column})

    for name in measures_used:
        k = str(name).upper()
        if k in full_measures and k not in scoped_measures:
            hidden.append({"kind": "measure", "name": name})

    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in hidden:
        key = json.dumps(it, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out

def _is_booleanish_security_filter(expr: Any) -> bool:
    """Best-effort boolean check for RLS filters.

    The IR has no formal type system. We conservatively accept:
    - literals (bool/None)
    - comparisons (DaxBinaryOp with comparison ops)
    - IN
    - boolean combinators AND/OR/NOT and boolean-ish functions.
    """

    from dax_engine.ir import DaxBinaryOp as _DaxBinaryOp
    from dax_engine.ir import DaxFunction as _DaxFunction
    from dax_engine.ir import Literal as _Literal

    if isinstance(expr, _Literal):
        return isinstance(expr.value, (bool, type(None)))
    if isinstance(expr, _DaxBinaryOp):
        op = str(expr.operator or "").strip().upper()
        if op in {"=", "==", "<>", "!=", ">", ">=", "<", "<=", "IN"}:
            return True
    if isinstance(expr, _DaxFunction):
        fn = str(expr.fn or "").strip().upper()
        if fn in {"AND", "OR", "NOT", "TRUE", "FALSE", "ISBLANK", "ISERROR"}:
            return True
    return False

