"""Community helper module — extracted from dax_ui.server.__init__."""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

import dax_compiler
from dax_engine import ir as _ir

from dax_project import load_project
from dax_project.expr_json import parse_expr

from dax_ui.server._runtime_helpers import _resolve_project_path_runtime

logger = logging.getLogger(__name__)


def _resolve_hierarchy_level_to_column_ref_dict(
    hierarchy_name: str,
    level_name: str,
    *,
    idx: int = 0,
    model: Any = None,
    project_path: Optional[str] = None,
) -> dict[str, str]:
    """Resolve a HierarchyLevel filter target to a ColumnRef dict.

    Looks up the hierarchy in the current model (loaded lazily).
    """
    # This helper is called during filter parsing which may not have a model in scope.
    # Lazily load the model from the current project path when needed.
    if model is None:
        if project_path is None:
            project_path = _resolve_project_path_runtime(None)
        model, _pages, _visuals = load_project(project_path)

    h_map = getattr(model, "hierarchies", None) or {}
    hierarchy = None
    for k, v in h_map.items():
        if isinstance(k, str) and k.upper() == hierarchy_name.upper():
            hierarchy = v
            break
    if hierarchy is None:
        raise ValueError(f"filters[{idx}].column: unknown hierarchy {hierarchy_name!r}")

    for lvl in hierarchy.levels:
        if getattr(lvl, "name", "").upper() == level_name.upper():
            return {"type": "ColumnRef", "table": hierarchy.table, "column": lvl.column}

    raise ValueError(
        f"filters[{idx}].column: unknown level {level_name!r} in hierarchy {hierarchy_name!r}"
    )

def _parse_scoped_filters_payload(
    payload_filters: Any,
    *,
    project_path: Optional[str] = None,
    model: Any = None,
) -> list[dax_compiler.ScopedFilter]:
    """Parse runtime filter payload into ScopedFilter IR.

                Expected per-item shape:
            {
                scope: 'report' | 'page' | 'interaction' | 'visual',
                target?: string,
                keep?: bool,
                column: {type:'ColumnRef', table:'T', column:'C'},
                operator: string,
                values: [<json scalar>, ...],
                source?: 'manual' | 'slicer' | 'interaction',
                slicer_id?: string
            }
    """

    if payload_filters is None:
        return []
    if not isinstance(payload_filters, list):
        raise ValueError("filters must be a list")

    out: list[dax_compiler.ScopedFilter] = []
    for i, raw in enumerate(payload_filters):
        if not isinstance(raw, Mapping):
            raise ValueError(f"filters[{i}] must be an object")

        scope = str(raw.get("scope") or "").strip().lower()
        if scope not in {"report", "page", "interaction", "visual", "drillthrough"}:
            raise ValueError(
                f"filters[{i}].scope must be one of 'report'|'page'|'interaction'|'visual'|'drillthrough'; got {raw.get('scope')!r}"
            )

        target_raw = raw.get("target")
        target = str(target_raw).strip() if isinstance(target_raw, str) and target_raw.strip() else None

        keep = bool(raw.get("keep") or False)

        source_raw = raw.get("source")
        source = str(source_raw).strip().lower() if isinstance(source_raw, str) and str(source_raw).strip() else None
        if source is not None and source not in {"manual", "slicer", "interaction", "drillthrough"}:
            raise ValueError(
                f"filters[{i}].source must be one of 'manual'|'slicer'|'interaction'|'drillthrough'; got {source_raw!r}"
            )

        # Deterministic defaulting:
        # - interaction scope => source='interaction'
        # - otherwise => source='manual'
        if source is None:
            source = "interaction" if scope == "interaction" else "manual"

        # Safety: if declared source=interaction, enforce interaction scope.
        if source == "interaction":
            scope = "interaction"

        slicer_id_raw = raw.get("slicer_id")
        slicer_id = str(slicer_id_raw).strip() if isinstance(slicer_id_raw, str) and slicer_id_raw.strip() else None
        if source == "interaction":
            slicer_id = None

        col_raw = raw.get("column")
        if not isinstance(col_raw, Mapping):
            raise ValueError(f"filters[{i}].column must be an object")

        # Support HierarchyLevel filter targets: resolve to ColumnRef using
        # the hierarchy definition from the model (loaded from _current_model if needed).
        col_type = str(col_raw.get("type") or "").strip()
        if col_type == "HierarchyLevel":
            # Resolve hierarchy level ΓåÆ ColumnRef
            h_name = str(col_raw.get("hierarchy") or "").strip()
            lvl_name = str(col_raw.get("level") or "").strip()
            if not h_name or not lvl_name:
                raise ValueError(f"filters[{i}].column HierarchyLevel requires 'hierarchy' and 'level'")
            # Replace with ColumnRef for downstream processing
            col_raw = _resolve_hierarchy_level_to_column_ref_dict(
                h_name,
                lvl_name,
                idx=i,
                model=model,
                project_path=project_path,
            )

        col_expr = parse_expr(dict(col_raw))
        if not isinstance(col_expr, dax_compiler.ColumnRef):
            # MeasureRef and other non-ColumnRef filter targets (e.g. PBI
            # "exists" measure filters) cannot be lowered to SQL WHERE.
            # Skip silently — these are PBI measure-level filters that would
            # require HAVING semantics we don't support yet.
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "filters[%d]: skipping non-ColumnRef filter (type=%s)",
                i, type(col_expr).__name__,
            )
            continue

        op = str(raw.get("operator") or "").strip()
        if not op:
            raise ValueError(f"filters[{i}].operator is required")

        # Skip operators we cannot lower to SQL WHERE yet.
        _UNSUPPORTED_OPS = {"exists", "topn"}
        if op.lower() in _UNSUPPORTED_OPS:
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "filters[%d]: skipping unsupported operator %r", i, op,
            )
            continue

        vals_raw = raw.get("values")
        if vals_raw is None:
            values = []
        elif isinstance(vals_raw, list):
            values = [dax_compiler.Literal(v) for v in vals_raw]
        else:
            values = [dax_compiler.Literal(vals_raw)]

        cond = dax_compiler.FilterCondition(column=col_expr, operator=op, values=values)
        out.append(
            dax_compiler.ScopedFilter(
                scope=scope,
                condition=cond,
                target=target,
                keep=keep,
                source=source,
                slicer_id=slicer_id,
            )
        )

    return out

def _parse_interaction_filters_payload(payload_interaction_filters: Any) -> list[dax_compiler.ScopedFilter]:
    """Parse interaction_filters payload into ScopedFilter IR.

    Interaction filter items use a flat format:
        {source_visual_id, table, column, values}
    This differs from the *scoped* filter format that _parse_scoped_filters_payload expects.
    This helper normalises them into ScopedFilter with scope='interaction'.
    """
    if payload_interaction_filters is None:
        return []
    if not isinstance(payload_interaction_filters, list):
        raise ValueError("interaction_filters must be a list")

    out: list[dax_compiler.ScopedFilter] = []
    for i, raw in enumerate(payload_interaction_filters):
        if not isinstance(raw, Mapping):
            raise ValueError(f"interaction_filters[{i}] must be an object")

        # Accept both flat (table+column) and nested (column={type,table,column}) forms.
        col_raw = raw.get("column")
        table_raw = raw.get("table")

        if isinstance(col_raw, Mapping):
            # Already a ColumnRef-style object; parse directly.
            col_expr = parse_expr(dict(col_raw))
        elif isinstance(col_raw, str) and isinstance(table_raw, str):
            # Flat form: build a ColumnRef.
            col_expr = dax_compiler.ColumnRef(table=table_raw.strip(), column=col_raw.strip())
        else:
            raise ValueError(
                f"interaction_filters[{i}] must have either a ColumnRef 'column' object "
                f"or both 'table' and 'column' strings"
            )

        if not isinstance(col_expr, dax_compiler.ColumnRef):
            raise ValueError(f"interaction_filters[{i}].column must resolve to ColumnRef")

        op = str(raw.get("operator") or "in").strip()

        vals_raw = raw.get("values")
        if vals_raw is None:
            values: list[dax_compiler.Literal] = []
        elif isinstance(vals_raw, list):
            values = [dax_compiler.Literal(v) for v in vals_raw]
        else:
            values = [dax_compiler.Literal(vals_raw)]

        cond = dax_compiler.FilterCondition(column=col_expr, operator=op, values=values)
        out.append(
            dax_compiler.ScopedFilter(
                scope="interaction",
                condition=cond,
                target=None,
                keep=False,
                source="interaction",
                slicer_id=None,
            )
        )

    return out

def _resolve_payload_param_values(
    payload: Mapping[str, Any],
    model: Any,
) -> Optional[Mapping[str, str]]:
    """Extract and validate field parameter selections from payload.
    
    Returns a mapping of param_name -> selected_value (single selection).
    """
    raw = payload.get("param_values") or payload.get("field_params")
    if not raw or not isinstance(raw, Mapping):
        return None
    
    result: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if isinstance(v, list):
            # Multi-select: take first
            first = next((x for x in v if isinstance(x, str) and x.strip()), None)
            if first:
                result[k.strip()] = first.strip()
        elif isinstance(v, str) and v.strip():
            result[k.strip()] = v.strip()
    
    return result if result else None

def _resolve_payload_calc_groups(
    payload: Mapping[str, Any],
    project_path: str,
) -> Optional[Mapping[str, str]]:
    """Extract and validate calculation group selections from payload.
    
    Returns a mapping of calc_group_name -> selected_item_name.
    """
    raw = payload.get("calc_groups") or payload.get("calculation_groups")
    if not raw or not isinstance(raw, Mapping):
        return None
    
    result: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip():
            result[k.strip()] = v.strip()
    
    return result if result else None

def _resolve_payload_what_if_values(
    payload: Mapping[str, Any],
    project_path: str,
    model: Any,
) -> Optional[Mapping[str, float]]:
    """Extract and validate what-if parameter values from payload.
    
    Returns a mapping of param_name -> numeric_value.
    """
    raw = payload.get("what_if_values") or payload.get("what_if")
    if not raw or not isinstance(raw, Mapping):
        return None
    
    result: dict[str, float] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip():
            continue
        try:
            result[k.strip()] = float(v)
        except (TypeError, ValueError):
            continue
    
    return result if result else None

