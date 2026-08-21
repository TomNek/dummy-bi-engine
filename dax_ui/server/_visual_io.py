"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional

import dax_compiler
from dax_engine import ir as _ir
from dax_engine.planner import VisualQuerySpec
from dax_engine.planner.visual_planner import SortSpec, resolve_facade_column_refs, resolve_params

from dax_project.expr_json import parse_expr

from dax_ui.server._plotly import _normalize_visual_interactions

logger = logging.getLogger(__name__)


def _load_visual_json(project_path: str, visual_id: str) -> dict[str, Any]:
    path = Path(project_path) / "reports" / "visuals" / f"{visual_id}.json"
    if not path.exists():
        raise FileNotFoundError(str(path))
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Visual JSON must be an object")

    # Back-compat: older visuals may not have interactions config.
    raw["interactions"] = _normalize_visual_interactions(raw.get("interactions"))
    return raw

def _save_visual_json(project_path: str, visual_id: str, obj: Mapping[str, Any]) -> None:
    visuals_dir = Path(project_path) / "reports" / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)
    path = visuals_dir / f"{visual_id}.json"
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")

def _delete_visual_json(project_path: str, visual_id: str) -> None:
    path = Path(project_path) / "reports" / "visuals" / f"{visual_id}.json"
    if not path.exists():
        raise FileNotFoundError(str(path))
    path.unlink()

def _next_visual_id(project_path: str) -> str:
    visuals_dir = Path(project_path) / "reports" / "visuals"
    if not visuals_dir.exists():
        return "v1"
    existing = {p.stem.upper() for p in visuals_dir.glob("*.json")}
    for i in range(1, 10_000):
        cand = f"v{i}"
        if cand.upper() not in existing:
            return cand
    return "v_" + uuid.uuid4().hex[:8]

def _slot_value_present(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, list):
        return len(v) > 0
    return True

def _expr_output_name(expr: Any) -> Optional[str]:
    # After ParamRef resolution, we expect ColumnRef/MeasureRef.
    from dax_engine.ir import ColumnRef as _ColumnRef
    from dax_engine.ir import MeasureRef as _MeasureRef

    if isinstance(expr, _ColumnRef):
        return expr.column
    if isinstance(expr, _MeasureRef):
        return expr.name
    return None

def _build_sort_specs_from_visual(
    sort_entries: list[dict[str, Any]] | None,
    model: Any,
) -> list[SortSpec]:
    """Convert visual JSON sort entries to SortSpec list.

    Visual sort format: [{"table": "T", "field": "F", "direction": "ascending"|"descending"}]
    """
    if not sort_entries:
        return []

    from dax_engine.ir import ColumnRef as _ColumnRef
    from dax_engine.ir import MeasureRef as _MeasureRef

    # Build a set of measure names for fast lookup
    measure_names: set[str] = set()
    if model is not None:
        measures = getattr(model, "measures", None) or []
        if isinstance(measures, Mapping):
            for m_name in measures:
                measure_names.add(str(m_name).strip())
        elif isinstance(measures, (list, tuple)):
            for m in measures:
                m_name = getattr(m, "name", None)
                if m_name:
                    measure_names.add(str(m_name).strip())

    specs: list[SortSpec] = []
    for entry in sort_entries:
        if not isinstance(entry, dict):
            continue
        table = str(entry.get("table") or "").strip()
        field = str(entry.get("field") or "").strip()
        raw_dir = str(entry.get("direction") or "ascending").strip().lower()
        direction: str = "DESC" if raw_dir.startswith("desc") else "ASC"

        if not field:
            continue

        # Decide if the sort field is a measure or column
        if field in measure_names:
            specs.append(SortSpec(expr=_MeasureRef(name=field), direction=direction))  # type: ignore[arg-type]
        elif table:
            specs.append(SortSpec(expr=_ColumnRef(table=table, column=field), direction=direction))  # type: ignore[arg-type]
    return specs


def _default_sort_specs_from_model(
    dimensions: list[Any],
    model: Any,
) -> tuple[list[SortSpec], list[Any]]:
    """Generate default SortSpec for dimensions that have sort_by_column in the model.

    This implements Power BI's implicit sorting behavior: if a column has
    sortByColumn defined, the query is implicitly ordered by that sort column.

    Returns (sort_specs, extra_dims) — extra_dims must be added to the VisualQuerySpec
    dimensions so the planner validation passes.
    """
    if model is None or not dimensions:
        return [], []

    from dax_engine.ir import ColumnRef as _ColumnRef

    tables = getattr(model, "tables", None) or []

    # Build a lookup: table_name -> table_obj
    table_map: dict[str, Any] = {}
    if isinstance(tables, Mapping):
        table_map = dict(tables)
    elif isinstance(tables, (list, tuple)):
        for t in tables:
            tname = getattr(t, "name", None)
            if tname:
                table_map[str(tname).strip()] = t

    if not table_map:
        return [], []

    specs: list[SortSpec] = []
    extra_dims: list[Any] = []
    existing_dim_set = {(d.table, d.column) for d in dimensions if isinstance(d, _ColumnRef)}

    for dim in dimensions:
        if not isinstance(dim, _ColumnRef):
            continue
        table_obj = table_map.get(dim.table)
        if table_obj is None:
            continue
        columns = getattr(table_obj, "columns", {}) or {}
        if isinstance(columns, Mapping):
            col_obj = columns.get(dim.column)
        elif isinstance(columns, (list, tuple)):
            col_obj = next((c for c in columns if getattr(c, "name", None) == dim.column), None)
        else:
            continue
        if col_obj is None:
            continue
        sort_by = getattr(col_obj, "sort_by_column", None)
        if sort_by and isinstance(sort_by, str) and sort_by.strip():
            sort_col_ref = _ColumnRef(table=dim.table, column=sort_by.strip())
            # Add the sort column as a hidden dimension if not already present
            if (sort_col_ref.table, sort_col_ref.column) not in existing_dim_set:
                extra_dims.append(sort_col_ref)
                existing_dim_set.add((sort_col_ref.table, sort_col_ref.column))
            specs.append(SortSpec(
                expr=sort_col_ref,
                direction="ASC",  # type: ignore[arg-type]
            ))
    return specs, extra_dims


def _build_spec_from_encodings(
    *,
    model: Any,
    registry: Mapping[str, Any],
    visual_type: str,
    encodings: Mapping[str, Any],
    param_values: Mapping[str, Any] | None,
    drill_level: int | None = None,
    drill_filters: list[dict[str, Any]] | None = None,
    expand_levels: int = 1,
    sort_entries: list[dict[str, Any]] | None = None,
    query_options: Mapping[str, Any] | None = None,
) -> VisualQuerySpec:
    """Build a VisualQuerySpec from visual encodings.

    Supports HierarchyRef in chart visual encodings:
    - Resolves to the ColumnRef for the appropriate hierarchy level based on *drill_level*.
    - If *drill_level* is None, uses the top-level (index 0).
    - *drill_filters* are applied as additional WHERE conditions by the caller.
    - *expand_levels* controls multi-level expansion ("Expand All Down One Level").
      Default 1 = single level.  2+ = show that many consecutive hierarchy levels
      starting from *drill_level*, adding all resolved ColumnRefs as dimensions.
    """
    vt = registry.get(visual_type)
    if vt is None:
        raise ValueError(f"Unknown visual_type: {visual_type!r}")
    slots = getattr(vt, "slots", {})

    from dax_engine.ir import ColumnRef as _ColumnRef
    from dax_engine.ir import HierarchyRef as _HierarchyRef
    from dax_engine.ir import MeasureRef as _MeasureRef
    from dax_engine.ir import ParamRef as _ParamRef

    dims: list[Any] = []
    measures: list[Any] = []
    measure_scope_overrides: dict[str, list[dict[str, Any]]] = {}

    def _fps_map() -> Mapping[str, Any]:
        fps = getattr(model, "field_parameters", {}) or {}
        if not isinstance(fps, Mapping):
            raise ValueError("model.field_parameters must be a mapping")
        return fps

    def _find_fp(fp_name: str) -> Any:
        fps = _fps_map()
        for k, fp in fps.items():
            if isinstance(k, str) and k.strip() and k.strip().upper() == fp_name.strip().upper():
                return fp
            nm = getattr(fp, "name", None)
            if isinstance(nm, str) and nm.strip() and nm.strip().upper() == fp_name.strip().upper():
                return fp
        raise ValueError(f"Unknown field parameter: {fp_name!r}")

    def _lookup_selected_raw(fp: Any, fp_name: str) -> Any:
        values = param_values or {}
        target = str(getattr(fp, "name", fp_name) or fp_name).strip()

        if target in values:
            return values.get(target)
        for k, v in values.items():
            if isinstance(k, str) and k.strip().upper() == target.upper():
                return v
        return None

    def _selected_keys(fp: Any, fp_name: str) -> list[str]:
        raw = _lookup_selected_raw(fp, fp_name)
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        if isinstance(raw, list):
            out: list[str] = []
            seen: set[str] = set()
            for it in raw:
                if not isinstance(it, str) or not it.strip():
                    continue
                key = it.strip()
                ku = key.upper()
                if ku in seen:
                    continue
                seen.add(ku)
                out.append(key)
            if out:
                return out

        # Power BI parity: single-select only, use default_item.
        default_item = getattr(fp, "default_item", None)
        if isinstance(default_item, str) and default_item.strip():
            return [default_item.strip()]
        # Fall back to first item.
        items = list(getattr(fp, "items", []) or [])
        if items:
            first_name = str(getattr(items[0], "name", "")).strip()
            if first_name:
                return [first_name]
        raise ValueError(
            f"Unresolved ParamRef {fp_name!r} reached spec build; ensure selection/default exist."
        )

    def _expr_for_key(fp: Any, fp_name: str, key: str) -> Any:
        items = list(getattr(fp, "items", []) or [])
        item = next(
            (item for item in items if str(getattr(item, "name", "")).strip().upper() == key.strip().upper()),
            None,
        )
        if item is None:
            valid = [str(getattr(item, "name", "")) for item in items]
            raise ValueError(f"Invalid field parameter value for {fp_name!r}: {key!r}; valid names: {valid}")
        return getattr(item, "ref")

    def add_dim(e: Any) -> None:
        dims.append(e)

    def add_meas(e: Any, raw: Any = None) -> None:
        """Append a resolved measure and collect scope_overrides if present."""
        measures.append(e)
        # Collect scope_overrides from the raw encoding dict
        if isinstance(raw, dict) and isinstance(e, _MeasureRef):
            so = raw.get("scope_overrides")
            if isinstance(so, list) and so:
                measure_scope_overrides[e.name] = so

    for slot_name, raw_val in encodings.items():
        # Skip non-expression encodings fields (e.g., tablix layout properties)
        if slot_name == "tablix":
            continue
        # Combo layers: extract y/color/size measures from each layer dict.
        if slot_name == "layers" and isinstance(raw_val, list):
            for lyr in raw_val:
                if not isinstance(lyr, dict):
                    continue
                for lk in ("y", "color", "size"):
                    lv = lyr.get(lk)
                    if lv is None:
                        continue
                    if isinstance(lv, dict) and lv.get("type") == "ExplanationRef":
                        continue
                    if isinstance(lv, dict):
                        expr = parse_expr(lv)
                    elif isinstance(lv, str):
                        # Plain string in a layer slot — treat as measure name
                        expr = _MeasureRef(lv)
                    else:
                        expr = lv
                    if isinstance(expr, _MeasureRef):
                        add_meas(expr, lv)
                    elif isinstance(expr, _ColumnRef):
                        add_dim(expr)
            continue
        slot_spec = slots.get(slot_name)
        kind = getattr(slot_spec, "kind", "any") if slot_spec is not None else "any"
        slot_multi = bool(getattr(slot_spec, "multi", False)) if slot_spec is not None else False
        values = raw_val if isinstance(raw_val, list) else [raw_val]
        for v in values:
            if v is None:
                continue
            # Skip ExplanationRef bindings ΓÇö they are handled separately
            if isinstance(v, dict) and v.get("type") == "ExplanationRef":
                continue
            expr = parse_expr(v) if isinstance(v, dict) else v

            # ── HierarchyRef resolution for chart visuals ──────────────
            if isinstance(expr, _HierarchyRef):
                h_map = getattr(model, "hierarchies", {}) or {}
                h_lower = {k.lower(): v for k, v in h_map.items()}
                hierarchy = h_lower.get(expr.name.lower())
                if hierarchy is None:
                    raise ValueError(f"Unknown hierarchy: {expr.name!r}")
                base_idx = min(drill_level or 0, len(hierarchy.levels) - 1)
                # Multi-level expansion: add consecutive levels as dims
                n_expand = max(1, expand_levels)
                for lvl_offset in range(n_expand):
                    lvl_idx = base_idx + lvl_offset
                    if lvl_idx >= len(hierarchy.levels):
                        break
                    lvl = hierarchy.levels[lvl_idx]
                    col_ref = _ColumnRef(table=hierarchy.table, column=lvl.column)
                    add_dim(col_ref)
                continue

            if kind == "dimension":
                if isinstance(expr, _ParamRef):
                    fp = _find_fp(expr.name)
                    keys = _selected_keys(fp, expr.name)
                    if len(keys) > 1:
                        if not slot_multi:
                            raise ValueError(
                                f"Field parameter {expr.name!r} is multi-select, but slot {slot_name!r} does not support multiple values"
                            )
                        if not bool(getattr(fp, "allow_multi", False)):
                            raise ValueError(f"Field parameter {expr.name!r} does not allow multi-select")
                        resolved = [_expr_for_key(fp, expr.name, k) for k in keys]
                        if not all(isinstance(r, _ColumnRef) for r in resolved):
                            raise ValueError(
                                "Multi-select field parameters are columns-only (measures are not supported in multi-select)."
                            )
                        for r in resolved:
                            add_dim(r)
                        continue
                    resolved_one = _expr_for_key(fp, expr.name, keys[0])
                    if not isinstance(resolved_one, _ColumnRef):
                        raise ValueError("All visual dimensions must resolve to ColumnRef")
                    add_dim(resolved_one)
                    continue

                add_dim(expr)
                continue

            if kind == "measure":
                if isinstance(expr, _ParamRef):
                    fp = _find_fp(expr.name)
                    keys = _selected_keys(fp, expr.name)
                    if len(keys) > 1:
                        raise ValueError(
                            f"Field parameter {expr.name!r} is multi-select, but values slots require single selection"
                        )
                    resolved_one = _expr_for_key(fp, expr.name, keys[0])
                    if isinstance(resolved_one, _ColumnRef):
                        raise ValueError(
                            "Column field parameters are not valid for values slot without explicit aggregation"
                        )
                    if not isinstance(resolved_one, _MeasureRef):
                        raise ValueError("All visual measures must resolve to MeasureRef")
                    add_meas(resolved_one, v)
                    continue

                if isinstance(expr, _ColumnRef):
                    raise ValueError("Column field parameters are not valid for values slot without explicit aggregation")
                add_meas(expr, v)
                continue

            # kind == 'any': classify columns/measures; resolve ParamRef to decide.
            resolved = expr
            if isinstance(expr, _ParamRef):
                fp = _find_fp(expr.name)
                keys = _selected_keys(fp, expr.name)
                resolved = _expr_for_key(fp, expr.name, keys[0])
            else:
                # Resolve facade ColumnRefs for virtual tables first, then resolve ParamRef
                resolved = resolve_facade_column_refs(expr, model, None)
                resolved = resolve_params(resolved, model, None)

            name = _expr_output_name(resolved)
            if name is None:
                continue
            if isinstance(resolved, _ColumnRef):
                add_dim(resolved)
            elif isinstance(resolved, _MeasureRef):
                add_meas(resolved, v)

    # Build sort specs from explicit visual sort configuration and imported query options.
    sort_specs = _build_sort_specs_from_visual(sort_entries, model)
    query_sort_specs, query_limit = _build_query_option_specs(query_options, dims, measures)
    if not sort_specs:
        sort_specs = query_sort_specs

    return VisualQuerySpec(
        dimensions=dims,
        measures=measures,
        sort=sort_specs,
        limit=query_limit,
        measure_scope_overrides=measure_scope_overrides,
    )


def _build_query_option_specs(
    query_options: Mapping[str, Any] | None,
    dimensions: list[Any],
    measures: list[Any],
) -> tuple[list[SortSpec], int | None]:
    if not isinstance(query_options, Mapping):
        return [], None

    sort_specs: list[SortSpec] = []
    limit: int | None = None
    top_n = query_options.get("top_n")
    if isinstance(top_n, Mapping):
        count = _positive_int(top_n.get("count"))
        if count is not None:
            limit = count
        direction = "ASC" if str(top_n.get("direction") or "").strip().lower().startswith("bottom") else "DESC"
        order_expr = _find_query_option_expr(top_n.get("order_field"), dimensions, measures)
        if order_expr is None and measures:
            order_expr = measures[0]
        if order_expr is None and dimensions:
            order_expr = dimensions[0]
        if order_expr is not None:
            sort_specs.append(SortSpec(expr=order_expr, direction=direction))  # type: ignore[arg-type]

    sort_payload = query_options.get("sort")
    if not sort_specs and isinstance(sort_payload, Mapping):
        sort_field = sort_payload.get("column") or sort_payload.get("field") or sort_payload.get("order_field")
        sort_expr = _find_query_option_expr(sort_field, dimensions, measures)
        if sort_expr is not None:
            raw_direction = str(sort_payload.get("direction") or "ascending").strip().lower()
            direction = "DESC" if raw_direction.startswith("desc") else "ASC"
            sort_specs.append(SortSpec(expr=sort_expr, direction=direction))  # type: ignore[arg-type]

    if limit is None:
        data_reduction = query_options.get("data_reduction")
        if isinstance(data_reduction, Mapping):
            for key in ("primary_limit", "max_points", "series_limit"):
                limit = _positive_int(data_reduction.get(key))
                if limit is not None:
                    break
    return sort_specs, limit


def _find_query_option_expr(name: Any, dimensions: list[Any], measures: list[Any]) -> Any:
    needle = str(name or "").strip().lower()
    if not needle:
        return None
    for expr in [*measures, *dimensions]:
        expr_name = _expr_output_name(expr)
        if expr_name and expr_name.strip().lower() == needle:
            return expr
    return None


def _positive_int(value: Any) -> int | None:
    try:
        out = int(float(value))
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None

