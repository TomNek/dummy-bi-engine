"""Visual query planner.

Non-goals:
- No DAX query grammar (no EVALUATE)
- No new semantics in lowering/context
- No SQL-string parsing or inference

The planner only composes IR and delegates to the existing compiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal as TypingLiteral
from typing import Mapping, Optional, Sequence, Tuple, cast

from dax_engine.context import Context
from dax_engine.ir import (
    CalcGroupItemRef,
    ColumnRef,
    DaxBinaryOp,
    DaxFunction,
    DaxIteratorFunction,
    DaxWindowFunction,
    Expr,
    Literal,
    MeasureRef,
    ParamRef,
    ScalarExpr,
    SelectedMeasureRef,
    SetLiteral,
    TableRef,
    WhatIfRef,
)
from dax_engine.registry import registry

SortDir = TypingLiteral["ASC", "DESC"]


@dataclass(frozen=True)
class SortSpec:
    expr: ScalarExpr
    direction: SortDir = "ASC"


@dataclass(frozen=True)
class VisualQuerySpec:
    dimensions: Sequence[ColumnRef]
    measures: Sequence[MeasureRef]
    filters: Sequence[Expr] = ()
    sort: Sequence[SortSpec] = ()
    limit: Optional[int] = None
    measure_scope_overrides: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    """Per-measure scope overrides mapped by measure name.

    Each override is a dict describing a filter context modification:
      {"mode": "remove_all"}
      {"mode": "remove_specific", "table": "T", "column": "C"}
      {"mode": "ignore_except", "table": "T", "columns": ["C1", "C2"]}
      {"mode": "ignore_visual"}
      {"mode": "keep_intersect", "table": "T", "column": "C", "values": [...]}
      {"mode": "fixed_value", "table": "T", "column": "C", "value": "v"}
      {"mode": "cross_table", "values": [...], "target_table": "T", "target_column": "C"}

    When present, the planner wraps the measure in CALCULATE(..., override_filters...).
    """


_REQUIRED_TABLE_FNS: tuple[str, ...] = (
    "SUMMARIZECOLUMNS",
    "TOPN",
    "FILTER",
    "VALUES",
    "DISTINCT",
    "SELECTCOLUMNS",
    "ADDCOLUMNS",
)


def _preflight_registry_for_table_fns() -> None:
    missing: list[str] = []
    wrong_kind: list[str] = []

    for name in _REQUIRED_TABLE_FNS:
        spec = registry.get(name)
        if spec is None:
            missing.append(name)
            continue
        if spec.kind != "table":
            wrong_kind.append(f"{name} (kind={spec.kind!r})")

    if missing or wrong_kind:
        parts: list[str] = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if wrong_kind:
            parts.append("not table: " + ", ".join(wrong_kind))

        hint = (
            "Ensure you loaded/registered table rewrites before planning, e.g. "
            "`load_default_mapping(register_verified_table_rewrites=True)` or manual registry.register(...)."
        )
        raise RuntimeError("Visual planner registry preflight failed (" + "; ".join(parts) + "). " + hint)


def _default_measure_alias(m: MeasureRef) -> str:
    # Keep alias stable and human-facing.
    return m.name


def _validate_sort_exprs(spec: VisualQuerySpec) -> None:
    if not spec.sort:
        return

    dims = list(spec.dimensions)
    measure_names = {m.name.upper() for m in spec.measures}

    for i, s in enumerate(spec.sort):
        e = s.expr
        if isinstance(e, ColumnRef):
            if any((d.table == e.table and d.column == e.column) for d in dims):
                continue
            raise ValueError(
                f"SortSpec[{i}].expr must be one of spec.dimensions or spec.measures; got ColumnRef({e.table!r}, {e.column!r})"
            )
        if isinstance(e, MeasureRef):
            if e.name.upper() in measure_names:
                continue
            raise ValueError(
                f"SortSpec[{i}].expr must be one of spec.dimensions or spec.measures; got MeasureRef({e.name!r})"
            )

        raise ValueError(
            f"SortSpec[{i}].expr must be a ColumnRef or MeasureRef from the spec; got {type(e).__name__}"
        )


def resolve_what_if_params(expr: Expr, model: object, what_if_values: Mapping[str, float] | None) -> Expr:
    """Resolve WhatIfRef placeholders using model.what_if_parameters.

    model is expected to have `what_if_parameters: dict[str, WhatIfParameter]`.
    Each WhatIfParameter is expected to have `.default_value`.
    what_if_values is a dict of param_name -> current_value.
    """

    values = what_if_values or {}

    wip_map = getattr(model, "what_if_parameters", None)
    if not isinstance(wip_map, Mapping):
        # No What-If parameters configured; leave expressions unchanged.
        return expr

    def resolve_wip(w: WhatIfRef) -> Expr:
        wip = None
        for k, v in wip_map.items():
            if isinstance(k, str) and k.upper() == w.name.upper():
                wip = v
                break
        if wip is None:
            raise ValueError(f"Unknown What-If parameter: {w.name!r}")

        # Get the current value from selections, or use the default.
        param_name = getattr(wip, "name", w.name)
        current_value = values.get(param_name.upper(), getattr(wip, "default_value", 0))
        return Literal(float(current_value))

    def walk(e: Expr) -> Expr:
        if isinstance(e, WhatIfRef):
            return walk(resolve_wip(e))
        if isinstance(e, DaxFunction):
            return DaxFunction(e.fn, [walk(a) for a in e.args])
        if isinstance(e, SetLiteral):
            return SetLiteral([walk(v) for v in e.values])  # type: ignore[arg-type]
        if isinstance(e, DaxBinaryOp):
            return DaxBinaryOp(e.operator, walk(e.left), walk(e.right))  # type: ignore[arg-type]
        if isinstance(e, DaxIteratorFunction):
            return DaxIteratorFunction(e.fn, walk(e.table), walk(e.expr))  # type: ignore[arg-type]
        if isinstance(e, DaxWindowFunction):
            order_by = e.order_by
            if order_by is not None:
                order_by = list(order_by)
            return DaxWindowFunction(e.fn, walk(e.table), walk(e.expr), order_by=order_by)  # type: ignore[arg-type]
        return e

    return walk(expr)


def resolve_facade_column_refs(expr: Expr, model: object, param_values: Mapping[str, str] | None) -> Expr:
    """Resolve facade ColumnRefs for virtual tables (Field Parameters, Calc Groups, What-If).

    Power BI parity: When a facade ColumnRef (e.g., FieldParams_Country[Country]) is used
    in a visual, it should be resolved to the appropriate semantic reference:
    - FieldParams_X[<primary>] → ParamRef(X) (resolved via resolve_params later)
    - CalcGroup_X[<item>] → CalcGroupItemRef(X, <item>)
    - WhatIf_X[Value] → WhatIfRef(X)

    This function is called before resolve_params to translate facade table references
    to the proper IR types.
    """

    fp_map = getattr(model, "field_parameters", None) or {}
    cg_map = getattr(model, "calculation_groups", None) or {}
    wip_map = getattr(model, "what_if_parameters", None) or {}

    def resolve_facade(c: ColumnRef) -> Expr:
        tname = c.table
        cname = c.column

        # Field Parameters: FieldParams_<Name>[<Name>] → ParamRef
        if tname.startswith("FieldParams_"):
            param_name = tname[len("FieldParams_"):]
            # Find the matching field parameter
            fp = None
            for k, v in fp_map.items():
                if str(getattr(v, "name", k) or "").strip().upper() == param_name.upper():
                    fp = v
                    break
            if fp is None:
                # Not a recognized field parameter facade; keep as-is
                return c
            fp_name = str(getattr(fp, "name", param_name) or "").strip()
            # Only the primary column (the field parameter name) resolves to ParamRef
            if cname.upper() == fp_name.upper():
                return ParamRef(fp_name)
            # Other columns (Label, Sort, Hierarchy) are not resolvable - keep as ColumnRef
            # (they would be used for slicer display purposes only and query the DuckDB table)
            return c

        # Field Parameters (unprefixed Power BI name): <Name>[Column] → ParamRef or keep ColumnRef
        # Power BI visuals reference field parameter tables by their unprefixed name.
        _matched_fp = None
        _matched_fp_name = ""
        for k, v in fp_map.items():
            nm = str(getattr(v, "name", k) or "").strip()
            if nm.upper() == tname.upper():
                _matched_fp = v
                _matched_fp_name = nm
                break
        if _matched_fp is not None:
            # Primary column → ParamRef (for measure/column resolution)
            if cname.upper() == _matched_fp_name.upper():
                return ParamRef(_matched_fp_name)
            # Other columns (Hierarchy, Sort, etc.) → keep as ColumnRef
            # The DuckDB table is materialized by _materialize_field_parameter_tables
            return c

        # Calculation Groups: CalcGroup_<Group>[<Item>] → CalcGroupItemRef
        if tname.startswith("CalcGroup_"):
            group_name = tname[len("CalcGroup_"):]
            # Find the matching calculation group
            cg = None
            for k, v in cg_map.items():
                if str(getattr(v, "name", k) or "").strip().upper() == group_name.upper():
                    cg = v
                    break
            if cg is None:
                return c
            cg_name = str(getattr(cg, "name", group_name) or "").strip()
            # For calc groups, the column name represents the selected item
            # When used in a slicer, cname equals the group name and values are item names
            # When the column matches the group name, we need to look at the actual value selected
            # This is handled at runtime via context; here we return a CalcGroupItemRef placeholder
            # For now, if the column is the group name, return the column as-is (used for grouping)
            if cname.upper() == cg_name.upper():
                # This column is for slicer use - keep as ColumnRef for distinct values
                return c
            # Otherwise the column name might be an item name (legacy format)
            items = list(getattr(cg, "items", []) or [])
            for item in items:
                item_name = str(getattr(item, "name", getattr(item, "key", "")) or "").strip()
                if item_name.upper() == cname.upper():
                    return CalcGroupItemRef(cg_name, item_name)
            return c

        # What-If Parameters: WhatIf_<Name>[Value] → WhatIfRef
        if tname.startswith("WhatIf_"):
            param_name = tname[len("WhatIf_"):]
            # Find the matching what-if parameter
            wip = None
            for k, v in wip_map.items():
                if str(getattr(v, "name", k) or "").strip().upper() == param_name.upper():
                    wip = v
                    break
            if wip is None:
                return c
            wip_name = str(getattr(wip, "name", param_name) or "").strip()
            # Only the Value column resolves to WhatIfRef
            if cname.upper() == "VALUE":
                return WhatIfRef(wip_name)
            return c

        return c

    def walk(e: Expr) -> Expr:
        if isinstance(e, ColumnRef):
            return resolve_facade(e)
        if isinstance(e, DaxFunction):
            return DaxFunction(e.fn, [walk(a) for a in e.args])
        if isinstance(e, SetLiteral):
            return SetLiteral([walk(v) for v in e.values])  # type: ignore[arg-type]
        if isinstance(e, DaxBinaryOp):
            return DaxBinaryOp(e.operator, walk(e.left), walk(e.right))  # type: ignore[arg-type]
        if isinstance(e, DaxIteratorFunction):
            return DaxIteratorFunction(e.fn, walk(e.table), walk(e.expr))  # type: ignore[arg-type]
        if isinstance(e, DaxWindowFunction):
            order_by = e.order_by
            if order_by is not None:
                order_by = [cast(ColumnRef, walk(c)) for c in order_by]
            return DaxWindowFunction(e.fn, walk(e.table), walk(e.expr), order_by=order_by)  # type: ignore[arg-type]
        return e

    return walk(expr)


def resolve_params(expr: Expr, model: object, param_values: Mapping[str, str] | None) -> Expr:
    """Resolve ParamRef placeholders using model.field_parameters.

    model is expected to have `field_parameters: dict[str, FieldParameter]`.
    Each FieldParameter is expected to have `.default_item` and `.items`.
    Each item is expected to have `.name` and `.ref`.
    """

    values = param_values or {}

    fp_map = getattr(model, "field_parameters", None)
    if not isinstance(fp_map, Mapping):
        # No field parameters configured; leave expressions unchanged.
        return expr

    def resolve_param(p: ParamRef) -> Expr:
        fp = None
        for k, v in fp_map.items():
            if isinstance(k, str) and k.upper() == p.name.upper():
                fp = v
                break
        if fp is None:
            raise ValueError(f"Unknown field parameter: {p.name!r}")

        selected = values.get(getattr(fp, "name", p.name), getattr(fp, "default_item", ""))
        items = getattr(fp, "items", [])
        names = [getattr(item, "name", "") for item in items]
        item = next((item for item in items if getattr(item, "name", None) == selected), None)
        if item is None:
            raise ValueError(
                f"Invalid field parameter value for {p.name!r}: {selected!r}; valid names: {names}"
            )
        return getattr(item, "ref")

    def walk(e: Expr) -> Expr:
        if isinstance(e, ParamRef):
            return walk(resolve_param(e))
        if isinstance(e, DaxFunction):
            return DaxFunction(e.fn, [walk(a) for a in e.args])
        if isinstance(e, SetLiteral):
            # SetLiteral values are ScalarExpr.
            return SetLiteral([walk(v) for v in e.values])  # type: ignore[arg-type]
        if isinstance(e, DaxBinaryOp):
            return DaxBinaryOp(e.operator, walk(e.left), walk(e.right))  # type: ignore[arg-type]
        if isinstance(e, DaxIteratorFunction):
            return DaxIteratorFunction(e.fn, walk(e.table), walk(e.expr))  # type: ignore[arg-type]
        if isinstance(e, DaxWindowFunction):
            order_by = e.order_by
            if order_by is not None:
                # ColumnRef cannot contain ParamRef; keep as-is.
                order_by = list(order_by)
            return DaxWindowFunction(e.fn, walk(e.table), walk(e.expr), order_by=order_by)  # type: ignore[arg-type]
        return e

    return walk(expr)


def _expand_measure_ref_with_calc_groups(*, m: MeasureRef, model: object, calc_groups: Mapping[str, str]) -> ScalarExpr:
    """Expand a MeasureRef by applying selected calculation items.

    - Base measure DAX is parsed to IR.
    - Each calculation item expression is parsed with SELECTEDMEASURE() enabled.
    - SelectedMeasureRef nodes are rewritten to the current scalar IR.
    - Items apply in ascending CalculationGroup.precedence (tie-break by group name).
    """

    def _contains_selected_measure(e: Expr) -> bool:
        if isinstance(e, SelectedMeasureRef):
            return True
        if isinstance(e, (ColumnRef, MeasureRef, ParamRef, Literal, TableRef, WhatIfRef)):
            return False
        if isinstance(e, SetLiteral):
            return any(_contains_selected_measure(v) for v in e.values)
        if isinstance(e, DaxBinaryOp):
            return _contains_selected_measure(e.left) or _contains_selected_measure(e.right)
        if isinstance(e, DaxFunction):
            return any(_contains_selected_measure(a) for a in e.args)
        if isinstance(e, DaxIteratorFunction):
            return _contains_selected_measure(e.table) or _contains_selected_measure(e.expr)
        if isinstance(e, DaxWindowFunction):
            if _contains_selected_measure(e.table) or _contains_selected_measure(e.expr):
                return True
            if e.order_by:
                return any(_contains_selected_measure(c) for c in e.order_by)
            return False
        raise TypeError(f"Unsupported IR node in SELECTEDMEASURE() detection: {type(e).__name__}")

    def _rewrite_selected_measure(e: Expr, replacement: ScalarExpr) -> Expr:
        if isinstance(e, SelectedMeasureRef):
            return replacement
        if isinstance(e, (ColumnRef, MeasureRef, ParamRef, Literal, TableRef, WhatIfRef)):
            return e
        if isinstance(e, SetLiteral):
            return SetLiteral([cast(ScalarExpr, _rewrite_selected_measure(v, replacement)) for v in e.values])
        if isinstance(e, DaxBinaryOp):
            return DaxBinaryOp(
                e.operator,
                cast(ScalarExpr, _rewrite_selected_measure(e.left, replacement)),
                _rewrite_selected_measure(e.right, replacement),
            )
        if isinstance(e, DaxFunction):
            return DaxFunction(e.fn, [_rewrite_selected_measure(a, replacement) for a in e.args])
        if isinstance(e, DaxIteratorFunction):
            return DaxIteratorFunction(
                e.fn,
                cast(Expr, _rewrite_selected_measure(e.table, replacement)),
                cast(ScalarExpr, _rewrite_selected_measure(e.expr, replacement)),
            )
        if isinstance(e, DaxWindowFunction):
            order_by = e.order_by
            if order_by:
                order_by = [cast(ColumnRef, _rewrite_selected_measure(c, replacement)) for c in order_by]
            return DaxWindowFunction(
                e.fn,
                cast(Expr, _rewrite_selected_measure(e.table, replacement)),
                cast(ScalarExpr, _rewrite_selected_measure(e.expr, replacement)),
                order_by=order_by,
            )
        raise TypeError(f"Unsupported IR node in SELECTEDMEASURE() rewrite: {type(e).__name__}")

    # Model contract: list of measures with .name and .dax.
    measures_list = getattr(model, "measures", [])
    base = next((md for md in measures_list if getattr(md, "name", "").upper() == m.name.upper()), None)
    if base is None:
        raise ValueError(f"Unknown measure in model for calc group expansion: {m.name!r}")

    dax_text = getattr(base, "dax", None)
    if not isinstance(dax_text, str) or not dax_text.strip():
        raise ValueError(f"Measure {m.name!r} has no DAX text in model")

    groups_map = getattr(model, "calculation_groups", {})
    if not isinstance(groups_map, Mapping):
        raise ValueError("Model.calculation_groups must be a mapping")

    from dax_parser.ir_mapper import ast_to_ir
    from dax_parser.parser import parse_expression

    base_ast = parse_expression(dax_text)
    base_ir = ast_to_ir(base_ast)
    if not isinstance(base_ir, ScalarExpr):
        raise TypeError(f"Measure {m.name!r} must map to a scalar expression; got {type(base_ir).__name__}")
    if _contains_selected_measure(base_ir):
        raise ValueError("SELECTEDMEASURE() is only valid inside calculation item expressions")

    # Normalize model groups for lookups.
    norm_to_group: dict[str, object] = {}
    for k, v in groups_map.items():
        if isinstance(k, str):
            norm_to_group[k.upper()] = v

    ordered: list[tuple[int, str, object, str]] = []  # (prec, group_name, group_obj, item_key)
    for group_name_raw, item_key in calc_groups.items():
        if not isinstance(group_name_raw, str):
            raise ValueError("calc_groups keys must be strings")
        if not isinstance(item_key, str):
            raise ValueError("calc_groups values must be strings")
        group = norm_to_group.get(group_name_raw.upper())
        if group is None:
            raise ValueError(f"Unknown calculation group: {group_name_raw!r}")
        prec = getattr(group, "precedence", 0)
        if not isinstance(prec, int):
            raise ValueError(
                f"CalculationGroup.precedence must be int; got {type(prec).__name__} for {group_name_raw!r}"
            )
        ordered.append((prec, group_name_raw, group, item_key))

    ordered.sort(key=lambda t: (t[0], str(t[1]).upper()))

    current: ScalarExpr = base_ir
    for _prec, group_name, group, item_key in ordered:
        items = getattr(group, "items", [])
        item = next((it for it in items if getattr(it, "key", None) == item_key), None)
        if item is None:
            valid = [getattr(it, "key", "") for it in items]
            raise ValueError(f"Unknown calculation item for {group_name!r}: {item_key!r}; valid keys: {valid}")

        expr_text = getattr(item, "expression", None)
        if isinstance(expr_text, str) and expr_text.strip():
            item_dax = expr_text
        else:
            # Back-compat: legacy CalcItem.template with '{{MEASURE}}' sugar.
            template = getattr(item, "template", "")
            if not isinstance(template, str) or "{{MEASURE}}" not in template:
                raise ValueError(f"Invalid calculation item for {group_name!r}/{item_key!r}: missing expression/template")
            item_dax = template.replace("{{MEASURE}}", "SELECTEDMEASURE()")

        item_ast = parse_expression(item_dax)
        item_ir = ast_to_ir(item_ast, allow_selected_measure=True)
        if not isinstance(item_ir, ScalarExpr):
            raise TypeError(f"Calculation item {group_name!r}/{item_key!r} must be scalar; got {type(item_ir).__name__}")
        if not _contains_selected_measure(item_ir):
            raise ValueError(f"Calculation item {group_name!r}/{item_key!r} must reference SELECTEDMEASURE()")

        rewritten = cast(ScalarExpr, _rewrite_selected_measure(item_ir, current))
        if _contains_selected_measure(rewritten):
            raise ValueError(f"Internal error: SELECTEDMEASURE() rewrite incomplete for {group_name!r}/{item_key!r}")
        current = rewritten

    return current


def apply_calc_transforms(
    measure: MeasureRef,
    model: object,
    calc_groups: Mapping[str, str] | None = None,
) -> ScalarExpr:
    """Apply calculation group transforms to a measure expression.

    This is the public API for formalizing calculation item transforms.
    The function applies calculation items in a deterministic order:
    - Primary sort: ascending CalculationGroup.precedence (integer)
    - Tie-breaker: ascending group name (case-insensitive)

    Args:
        measure: The MeasureRef to transform.
        model: The model object with calculation_groups and measures.
        calc_groups: Mapping of group_name -> selected_item_key.

    Returns:
        The transformed scalar expression (may be the original MeasureRef
        if no calc_groups are provided).

    Raises:
        ValueError: If any calc group or item is unknown, or if items don't
                    contain SELECTEDMEASURE().
    """
    if not calc_groups:
        return measure
    return _expand_measure_ref_with_calc_groups(m=measure, model=model, calc_groups=calc_groups)


def collect_calc_group_refs(expr: Expr) -> list[CalcGroupItemRef]:
    """Collect all CalcGroupItemRef nodes from an expression tree.

    This utility helps extract calculation item selections from encodings
    so they can be processed through apply_calc_transforms.

    Returns a list of CalcGroupItemRef in depth-first order.
    """
    refs: list[CalcGroupItemRef] = []

    def walk(e: Expr) -> None:
        if isinstance(e, CalcGroupItemRef):
            refs.append(e)
        elif isinstance(e, (ColumnRef, MeasureRef, ParamRef, Literal, TableRef, WhatIfRef, SelectedMeasureRef)):
            pass
        elif isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
        elif isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
        elif isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
        elif isinstance(e, DaxIteratorFunction):
            walk(e.table)
            walk(e.expr)
        elif isinstance(e, DaxWindowFunction):
            walk(e.table)
            walk(e.expr)
            if e.order_by:
                for c in e.order_by:
                    walk(c)

    walk(expr)
    return refs


def calc_group_refs_to_mapping(refs: Sequence[CalcGroupItemRef]) -> dict[str, str]:
    """Convert a list of CalcGroupItemRef to the calc_groups mapping format.

    If multiple refs for the same group exist, later ones win (last-write-wins).

    Returns:
        dict mapping group_name -> item_name
    """
    out: dict[str, str] = {}
    for ref in refs:
        out[ref.group] = ref.item
    return out


def assert_no_paramref(expr: Expr) -> None:
    """Fail fast if ParamRef escapes planner-time resolution."""

    def walk(e: Expr) -> None:
        if isinstance(e, ParamRef):
            raise ValueError(
                f"Unresolved ParamRef {e.name!r} reached planner output; ensure param_values/default exist."
            )
        if isinstance(e, DaxFunction):
            for a in e.args:
                walk(a)
            return
        if isinstance(e, SetLiteral):
            for v in e.values:
                walk(v)
            return
        if isinstance(e, DaxBinaryOp):
            walk(e.left)
            walk(e.right)
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


# ── Scope override → IR conversion ──────────────────────────────────


def _scope_override_to_ir(override: Mapping[str, Any]) -> Expr:
    """Convert a single scope override dict to a DAX IR filter argument for CALCULATE.

    Supported modes:
    - remove_all          → ALL()
    - remove_specific     → REMOVEFILTERS(Table[Column])
    - ignore_except       → ALLEXCEPT(Table, Table[Col1], Table[Col2], ...)
    - ignore_visual       → ALLSELECTED()
    - keep_intersect      → KEEPFILTERS(Table[Column] IN {...})
    - fixed_value         → Table[Column] = "value"
    - cross_table         → TREATAS({"v1", "v2", ...}, Table[Column])
    """
    mode = override.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError("scope_override.mode must be a non-empty string")

    mode = mode.strip().lower()

    if mode == "remove_all":
        return DaxFunction("ALL", [])

    if mode == "remove_specific":
        table = override.get("table")
        column = override.get("column")
        if not table or not column:
            raise ValueError("remove_specific requires 'table' and 'column'")
        return DaxFunction("REMOVEFILTERS", [ColumnRef(str(table), str(column))])

    if mode == "ignore_except":
        table = override.get("table")
        columns = override.get("columns")
        if not table:
            raise ValueError("ignore_except requires 'table'")
        if not isinstance(columns, list) or not columns:
            raise ValueError("ignore_except requires 'columns' as a non-empty list")
        args: list[Expr] = [TableRef(str(table))]
        for col in columns:
            args.append(ColumnRef(str(table), str(col)))
        return DaxFunction("ALLEXCEPT", args)

    if mode == "ignore_visual":
        return DaxFunction("ALLSELECTED", [])

    if mode == "keep_intersect":
        table = override.get("table")
        column = override.get("column")
        values = override.get("values")
        if not table or not column:
            raise ValueError("keep_intersect requires 'table' and 'column'")
        col_ref = ColumnRef(str(table), str(column))
        if values is not None and isinstance(values, list):
            set_lit = SetLiteral([Literal(v) for v in values])
            predicate = DaxBinaryOp("in", col_ref, set_lit)
            return DaxFunction("KEEPFILTERS", [predicate])
        # No values = keep all existing filters for this column (intersect mode)
        return DaxFunction("KEEPFILTERS", [col_ref])

    if mode == "fixed_value":
        table = override.get("table")
        column = override.get("column")
        value = override.get("value")
        if not table or not column:
            raise ValueError("fixed_value requires 'table' and 'column'")
        if value is None:
            raise ValueError("fixed_value requires 'value'")
        return DaxBinaryOp("==", ColumnRef(str(table), str(column)), Literal(value))

    if mode == "cross_table":
        target_table = override.get("target_table")
        target_column = override.get("target_column")
        values = override.get("values")
        if not target_table or not target_column:
            raise ValueError("cross_table requires 'target_table' and 'target_column'")
        if not isinstance(values, list) or not values:
            raise ValueError("cross_table requires 'values' as a non-empty list")
        set_lit = SetLiteral([Literal(v) for v in values])
        return DaxFunction("TREATAS", [set_lit, ColumnRef(str(target_table), str(target_column))])

    raise ValueError(f"Unknown scope_override mode: {mode!r}")


def _wrap_measure_with_scope_overrides(
    measure_expr: ScalarExpr,
    overrides: Sequence[Mapping[str, Any]],
) -> ScalarExpr:
    """Wrap a measure expression in CALCULATE with scope override filters.

    If overrides is empty, returns the measure expression unchanged.
    """
    if not overrides:
        return measure_expr
    filter_args: list[Expr] = []
    for ovr in overrides:
        filter_args.append(_scope_override_to_ir(ovr))
    return DaxFunction("CALCULATE", [measure_expr] + filter_args)


def plan_visual_query(
    spec: VisualQuerySpec,
    *,
    ctx: Optional[Context] = None,
    model: object | None = None,
    param_values: Mapping[str, str] | None = None,
    calc_groups: Mapping[str, str] | None = None,
    what_if_values: Mapping[str, float] | None = None,
) -> tuple[Expr, str]:
    """Plan a visual query as IR and compiled DuckDB SQL.

    Returns:
    - table_ir: usually SUMMARIZECOLUMNS(...) optionally wrapped in TOPN(...)
    - sql: DuckDB SQL string compiled via the existing compiler
    """

    _preflight_registry_for_table_fns()

    resolved_spec = spec
    if model is not None:
        # Step 1: Resolve facade ColumnRefs (virtual table references) first
        facade_dims = [resolve_facade_column_refs(d, model, param_values) for d in spec.dimensions]
        facade_measures = [resolve_facade_column_refs(m, model, param_values) for m in spec.measures]
        facade_filters = [resolve_facade_column_refs(f, model, param_values) for f in spec.filters]
        facade_sort = [
            SortSpec(expr=resolve_facade_column_refs(s.expr, model, param_values), direction=s.direction)  # type: ignore[arg-type]
            for s in spec.sort
        ]
        # Step 2: Resolve ParamRefs to actual ColumnRefs
        resolved_dims = [resolve_params(d, model, param_values) for d in facade_dims]
        resolved_measures = [resolve_params(m, model, param_values) for m in facade_measures]
        resolved_filters = [resolve_params(f, model, param_values) for f in facade_filters]
        resolved_sort = [
            SortSpec(expr=resolve_params(s.expr, model, param_values), direction=s.direction)  # type: ignore[arg-type]
            for s in facade_sort
        ]

        # ParamRef must never escape planner-time resolution.
        for e in resolved_dims:
            assert_no_paramref(e)
        for e in resolved_measures:
            assert_no_paramref(e)
        for e in resolved_filters:
            assert_no_paramref(e)
        for s in resolved_sort:
            assert_no_paramref(s.expr)

        # Enforce resolved types before lowering.
        if not all(isinstance(d, ColumnRef) for d in resolved_dims):
            raise ValueError("All visual dimensions must resolve to ColumnRef")
        if not all(isinstance(m, MeasureRef) for m in resolved_measures):
            raise ValueError("All visual measures must resolve to MeasureRef")

        resolved_spec = VisualQuerySpec(
            dimensions=resolved_dims,  # type: ignore[arg-type]
            measures=resolved_measures,  # type: ignore[arg-type]
            filters=resolved_filters,
            sort=resolved_sort,
            limit=spec.limit,
            measure_scope_overrides=spec.measure_scope_overrides,
        )

    # Optional calc group expansion (applies to all measures in the visual).
    def _apply_calc_groups_to_measure_ref(m: MeasureRef) -> ScalarExpr:
        if model is None or not calc_groups:
            return m
        return _expand_measure_ref_with_calc_groups(m=m, model=model, calc_groups=calc_groups)

    # Optional What-If parameter resolution (applies after calc group expansion).
    def _resolve_what_if_in_expr(e: ScalarExpr) -> ScalarExpr:
        if model is None:
            return e
        resolved = resolve_what_if_params(e, model, what_if_values)
        if not isinstance(resolved, (ColumnRef, MeasureRef, Literal, DaxFunction, DaxBinaryOp, DaxIteratorFunction, DaxWindowFunction, SetLiteral)):
            return e
        return resolved  # type: ignore[return-value]

    _validate_sort_exprs(resolved_spec)

    from dax_engine.compiler import compile_table_expr  # local import avoids cycles

    plan_ctx = ctx or Context()

    # Build SUMMARIZECOLUMNS IR.
    summarize_args: list[Expr] = []

    # 1) dimensions (group-by)
    for dim in resolved_spec.dimensions:
        summarize_args.append(dim)

    # 2) filters (must appear before measure name literals for current lowering)
    for f in resolved_spec.filters:
        summarize_args.append(f)

    # 3) measure (name, expr) pairs
    scope_overrides = resolved_spec.measure_scope_overrides or {}
    for measure in resolved_spec.measures:
        if not isinstance(measure, MeasureRef):
            raise ValueError("VisualQuerySpec.measures must be MeasureRef after parameter resolution")
        alias = _default_measure_alias(measure)
        expr = _apply_calc_groups_to_measure_ref(measure)
        expr = _resolve_what_if_in_expr(expr)  # Resolve WHATIFVALUE() calls to literals
        # Apply scope overrides: wrap in CALCULATE if overrides exist for this measure
        measure_overrides = scope_overrides.get(measure.name, ())
        if measure_overrides:
            expr = _wrap_measure_with_scope_overrides(expr, measure_overrides)
        summarize_args.append(Literal(alias))
        summarize_args.append(expr)

    table_ir: Expr = DaxFunction("SUMMARIZECOLUMNS", summarize_args)

    # Sorting / limiting
    if resolved_spec.limit is not None:
        # Use TOPN for limit (optionally with multi-sort).
        n = resolved_spec.limit
        topn_args: list[Expr] = [Literal(n), table_ir]

        if resolved_spec.sort:
            for s in resolved_spec.sort:
                topn_args.append(s.expr)
                topn_args.append(Literal(s.direction))
        else:
            # Limit-only: provide deterministic row selection.
            if resolved_spec.dimensions:
                topn_args.append(resolved_spec.dimensions[0])
                topn_args.append(Literal("ASC"))
            else:
                topn_args.append(Literal(1))

        table_ir = DaxFunction("TOPN", topn_args)
    elif resolved_spec.sort:
        # Sort-only: wrap in ORDERBY (no raw SQL emission in planner).
        orderby_args: list[Expr] = [table_ir]
        for s in resolved_spec.sort:
            orderby_args.append(s.expr)
            orderby_args.append(Literal(s.direction))
        table_ir = DaxFunction("ORDERBY", orderby_args)

    sql = compile_table_expr(table_ir, plan_ctx)
    return (table_ir, sql)


def plan_card_query(
    measure: MeasureRef,
    filters: Sequence[Expr],
    model: object | None,
    calc_groups: Mapping[str, str] | None = None,
    param_values: Mapping[str, str] | None = None,
    what_if_values: Mapping[str, float] | None = None,
    ctx: Optional[Context] = None,
) -> tuple[Expr, str]:
    """Plan a single-value card visual as a 1x1 table.

    The planner composes IR only and delegates to the existing compiler.
    """

    _preflight_registry_for_table_fns()

    # Optional validation against a loaded project model.
    if model is not None and hasattr(model, "measures"):
        measures = getattr(model, "measures")
        names = {getattr(m, "name").upper() for m in measures if hasattr(m, "name")}
        if names and measure.name.upper() not in names:
            raise ValueError(f"Unknown measure for card: {measure.name!r}")

    from dax_engine.compiler import compile_table_expr  # local import avoids cycles

    plan_ctx = ctx or Context()

    resolved_measure: Expr = measure
    resolved_filters: list[Expr] = list(filters)
    if model is not None:
        # Step 1: Resolve facade ColumnRefs for virtual tables
        resolved_measure = resolve_facade_column_refs(measure, model, param_values)
        resolved_filters = [resolve_facade_column_refs(f, model, param_values) for f in filters]
        # Step 2: Resolve ParamRefs
        resolved_measure = resolve_params(resolved_measure, model, param_values)
        resolved_filters = [resolve_params(f, model, param_values) for f in resolved_filters]

    assert_no_paramref(resolved_measure)
    for f in resolved_filters:
        assert_no_paramref(f)

    if not isinstance(resolved_measure, MeasureRef):
        raise ValueError("Card measure must resolve to MeasureRef")

    value_expr: Expr = resolved_measure
    if model is not None and calc_groups:
        value_expr = _expand_measure_ref_with_calc_groups(m=resolved_measure, model=model, calc_groups=calc_groups)

    # Resolve What-If parameters to literals.
    if model is not None:
        value_expr = resolve_what_if_params(value_expr, model, what_if_values)

    args: list[Expr] = []
    for f in resolved_filters:
        args.append(f)
    args.append(Literal("Value"))
    args.append(value_expr)

    table_ir: Expr = DaxFunction("SUMMARIZECOLUMNS", args)
    sql = compile_table_expr(table_ir, plan_ctx)
    return (table_ir, sql)
