"""Read-only SemanticModel introspection.

This module provides lightweight metadata APIs for:
- autocomplete (tables/columns/measures)
- documentation (measure description)
- dependency inspection (best-effort ref extraction)

Guardrails:
- No DAX evaluation
- No SQL compilation
- No context/lowering behavior changes

Dependency extraction is best-effort:
- Preferred: parse DAX text -> AST -> IR (dax_parser) and walk IR nodes.
- Fallback: conservative token extraction for patterns like [Measure] and Table[Column].

Limitations (fallback mode):
- Can over-approximate dependencies when strings/comments contain token-like text.
- Cannot resolve table names for unqualified [Column] references.
- Does not attempt full DAX grammar coverage; parsing may fail for unsupported syntax.
"""

from __future__ import annotations

import re
from typing import Dict

from dax_engine.ir import (
    ColumnRef,
    DaxBinaryOp,
    DaxFunction,
    DaxIteratorFunction,
    DaxWindowFunction,
    Expr,
    MeasureRef,
    ParamRef,
    SetLiteral,
)

from .model import CalculationGroup, FieldParameter, MeasureDefinition, SemanticModel


def list_tables(model: SemanticModel) -> list[str]:
    return sorted({t.name for t in model.tables}, key=lambda s: s.upper())


def list_columns(model: SemanticModel, table: str) -> list[str]:
    tbl = _get_table(model, table)
    return sorted({c.name for c in tbl.columns}, key=lambda s: s.upper())


def list_measures(model: SemanticModel) -> list[str]:
    return sorted({m.name for m in model.measures}, key=lambda s: s.upper())


def get_measure(model: SemanticModel, name: str) -> MeasureDefinition:
    m = _get_measure_or_none(model, name)
    if m is None:
        raise KeyError(f"Unknown measure: {name!r}")
    return m


def describe_measure(model: SemanticModel, name: str) -> dict:
    m = get_measure(model, name)
    refs = _extract_measure_dependencies(model, m.dax)
    return {
        "name": m.name,
        "expression": m.dax,
        "referenced_tables": sorted(refs["tables"], key=lambda s: s.upper()),
        "referenced_columns": sorted(refs["columns"], key=lambda s: (s.split("[", 1)[0].upper(), s.upper())),
        "referenced_measures": sorted(refs["measures"], key=lambda s: s.upper()),
        "format": m.format,
        "description": m.description,
    }


def search_symbols(model: SemanticModel, prefix: str) -> dict:
    """Prefix-search symbols.

    Matching is case-insensitive and deterministic (sorted output).
    Columns are returned as "Table[Column]" strings.
    Measures are returned as "[Measure]" strings.
    """

    p = (prefix or "").strip()
    p_upper = p.upper()

    def starts(name: str) -> bool:
        return name.upper().startswith(p_upper)

    tables = [t for t in list_tables(model) if starts(t)]

    columns: list[str] = []
    for t in model.tables:
        for c in t.columns:
            disp = f"{t.name}[{c.name}]"
            if disp.upper().startswith(p_upper):
                columns.append(disp)

    measures: list[str] = []
    for m in list_measures(model):
        bracketed = f"[{m}]"
        if m.upper().startswith(p_upper) or bracketed.upper().startswith(p_upper):
            measures.append(bracketed)

    field_parameters = _search_field_parameters(model.field_parameters, p_upper)
    calculation_groups = _search_calc_groups(model.calculation_groups, p_upper)

    return {
        "tables": sorted(tables, key=lambda s: s.upper()),
        "columns": sorted(set(columns), key=lambda s: s.upper()),
        "measures": sorted(measures, key=lambda s: s.upper()),
        "field_parameters": sorted(field_parameters, key=lambda s: s.upper()),
        "calculation_groups": sorted(calculation_groups, key=lambda s: s.upper()),
    }


def _get_table(model: SemanticModel, name: str):
    n = (name or "").strip()
    for t in model.tables:
        if t.name.upper() == n.upper():
            return t
    raise KeyError(f"Unknown table: {name!r}")


def _get_measure_or_none(model: SemanticModel, name: str) -> MeasureDefinition | None:
    n = (name or "").strip()
    for m in model.measures:
        if m.name.upper() == n.upper():
            return m
    return None


def _search_field_parameters(field_parameters: Dict[str, FieldParameter], p_upper: str) -> list[str]:
    out: set[str] = set()
    include_items = ":" in (p_upper or "")
    for key, fp in field_parameters.items():
        if str(key).upper().startswith(p_upper) or fp.name.upper().startswith(p_upper):
            out.add(fp.name)
        for item in fp.items:
            token = f"{fp.name}:{item.name}"
            # Only include item tokens when the user is searching for items.
            if include_items:
                if token.upper().startswith(p_upper) or item.name.upper().startswith(p_upper):
                    out.add(token)
            else:
                if item.name.upper().startswith(p_upper):
                    out.add(token)
    return sorted(out, key=lambda s: s.upper())


def _search_calc_groups(calc_groups: Dict[str, CalculationGroup], p_upper: str) -> list[str]:
    out: set[str] = set()
    for key, cg in calc_groups.items():
        if str(key).upper().startswith(p_upper) or cg.name.upper().startswith(p_upper):
            out.add(cg.name)
        for item in cg.items:
            token = f"{cg.name}:{item.key}"
            if token.upper().startswith(p_upper) or item.key.upper().startswith(p_upper):
                out.add(token)
    return sorted(out, key=lambda s: s.upper())


def _extract_measure_dependencies(model: SemanticModel, dax_text: str) -> dict:
    """Return sets: tables, columns (Table[Col]), measures (MeasureName)."""

    # Preferred: IR walk.
    try:
        from dax_parser.ir_mapper import ast_to_ir
        from dax_parser.parser import parse_expression

        ast = parse_expression(dax_text)
        ir = ast_to_ir(ast)
        return _refs_from_ir(model, ir)
    except Exception:
        return _refs_from_tokens(model, dax_text)


def _refs_from_ir(model: SemanticModel, expr: Expr) -> dict:
    tables: set[str] = set()
    columns: set[str] = set()
    measures: set[str] = set()

    canon_measures = {m.name.upper(): m.name for m in model.measures}

    def walk(e: Expr) -> None:
        if isinstance(e, ColumnRef):
            tables.add(e.table)
            columns.add(f"{e.table}[{e.column}]")
            return
        if isinstance(e, MeasureRef):
            name = canon_measures.get(e.name.upper(), e.name)
            measures.add(f"[{name}]")
            return
        if isinstance(e, ParamRef):
            # ParamRef is planner-time; treat as unknown dependency.
            return
        if isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
            return
        if isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
            return
        if isinstance(e, DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by is not None:
                for c in e.order_by:
                    walk(c)
            return

    walk(expr)
    return {"tables": tables, "columns": columns, "measures": measures}


_MEASURE_TOKEN_RE = re.compile(r"\[([^\]]+)\]")
_COLUMN_TOKEN_RE = re.compile(r"([A-Za-z_][\w ]*)\[([^\]]+)\]")


def _strip_strings_and_comments(dax: str) -> str:
    """Replace string/comment spans with spaces (conservative)."""

    if not dax:
        return ""

    out = list(dax)
    i = 0
    n = len(out)
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False

    def _blank(start: int, end: int) -> None:
        for j in range(start, end):
            out[j] = " "

    while i < n:
        ch = out[i]
        nxt = out[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            else:
                out[i] = " "
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                out[i] = " "
                out[i + 1] = " "
                in_block_comment = False
                i += 2
            else:
                out[i] = " "
                i += 1
            continue

        if in_single:
            out[i] = " "
            if ch == "'":
                # DAX escape for single quote in single-quoted string: ''
                if nxt == "'":
                    out[i + 1] = " "
                    i += 2
                    continue
                in_single = False
            i += 1
            continue

        if in_double:
            out[i] = " "
            if ch == '"':
                # DAX escape for double quote in double-quoted string: ""
                if nxt == '"':
                    out[i + 1] = " "
                    i += 2
                    continue
                in_double = False
            i += 1
            continue

        # Not in any span.
        if ch == "/" and nxt == "/":
            out[i] = " "
            out[i + 1] = " "
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            out[i] = " "
            out[i + 1] = " "
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            out[i] = " "
            in_single = True
            i += 1
            continue
        if ch == '"':
            out[i] = " "
            in_double = True
            i += 1
            continue

        i += 1

    return "".join(out)


def _refs_from_tokens(model: SemanticModel, dax_text: str) -> dict:
    """Conservative token extraction fallback (model-validated)."""

    tables: set[str] = set()
    columns: set[str] = set()
    measures: set[str] = set()

    stripped = _strip_strings_and_comments(dax_text or "")

    canon_tables = {t.name.upper(): t.name for t in model.tables}
    canon_columns: dict[str, dict[str, str]] = {}
    for t in model.tables:
        canon_columns[t.name.upper()] = {c.name.upper(): c.name for c in t.columns}

    canon_measures = {m.name.upper(): m.name for m in model.measures}

    # Measure tokens are ambiguous with [Column] references in DAX; treat as measures
    # only if they are not part of a *valid* qualified Table[Column] token.
    qualified_spans: list[tuple[int, int]] = []
    for m in _COLUMN_TOKEN_RE.finditer(stripped):
        t_raw, c_raw = m.group(1), m.group(2)
        t_key = t_raw.strip().upper()
        if t_key not in canon_tables:
            continue
        c_map = canon_columns.get(t_key, {})
        c_key = c_raw.strip().upper()
        if c_key not in c_map:
            continue

        t_name = canon_tables[t_key]
        c_name = c_map[c_key]
        tables.add(t_name)
        columns.add(f"{t_name}[{c_name}]")
        qualified_spans.append((m.start(), m.end()))

    def _in_qualified_span(idx: int) -> bool:
        for a, b in qualified_spans:
            if a <= idx < b:
                return True
        return False

    for m in _MEASURE_TOKEN_RE.finditer(stripped):
        if _in_qualified_span(m.start()):
            continue
        token = m.group(1).strip()
        if not token:
            continue

        canon = canon_measures.get(token.upper())
        if canon is None:
            continue
        measures.add(f"[{canon}]")

    return {"tables": tables, "columns": columns, "measures": measures}
