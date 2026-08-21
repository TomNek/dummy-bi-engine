"""Auto-extracted route module from dax_ui.server._runtime_routes."""

import copy
import datetime
import json
import logging
import os
import re
import time
import uuid
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Optional

from fastapi.responses import FileResponse
from starlette.requests import Request

import dax_compiler
from dax_engine.ir import MeasureRef, ir_to_dict
from dax_engine.planner import VisualQuerySpec, plan_card_query, plan_visual_query
from dax_engine.planner.visual_planner import resolve_facade_column_refs, resolve_params
from dax_project import get_measure, list_measures, load_project
from dax_project.expr_json import parse_expr
from dax_project.introspection import list_columns, list_tables
from dax_project.security import apply_ols, get_role, resolve_role_name
from dax_project.errors import NotFoundError
from dax_project.save import (
    delete_column_yaml,
    delete_measure_yaml,
    delete_table_yaml,
    update_measure_yaml,
    upsert_column_yaml,
    upsert_table_yaml,
    load_report_filters,
    load_calc_group_selections,
    load_calculation_groups_yaml,
    load_field_parameters_yaml,
    load_slicer_defs,
    load_slicer_instances,
    load_slicers,
    save_report_filters,
    save_calc_group_selections,
    save_calculation_groups_yaml,
    save_field_parameters_yaml,
    save_slicer_defs,
    save_slicer_instances,
    save_slicers,
    save_security_yaml,
    flatten_calc_group_selections,
    resolve_effective_calc_group_selections,
    load_field_parameter_selections,
    save_field_parameter_selections,
    flatten_field_parameter_selections,
    resolve_effective_field_parameter_selections,
    load_what_if_selections,
    save_what_if_selections,
    flatten_what_if_selections,
    resolve_effective_what_if_selections,
    save_pages,
    load_bookmarks,
    save_bookmarks,
)
from dax_project.visual_types import load_visual_type_registry

from dax_ui.server._runtime_helpers import *  # noqa: F403
from dax_ui.server._ir_walkers import (
    _collect_expr_refs_from_json,
    _ols_hidden_refs_for_visual,
    _is_booleanish_security_filter,
)
from dax_ui.server._security import (
    _security_roles_to_json,
    _collect_param_refs,
    _collect_column_refs,
    _collect_measure_refs,
    _validate_single_role_payload,
    _role_from_request,
    _resolve_security_for_request,
    _compile_rls_security_predicates,
    _validate_columnref_in_model,
    _validate_measureref_in_model,
    _resolve_role_and_scope_model,
    _RuntimeSecurityState,
    _build_runtime_security_state,
    _case_insensitive_dict_get,
    _validate_ir_objects_against_model_scoped,
)
from dax_ui.server._filters import (
    _resolve_hierarchy_level_to_column_ref_dict,
    _parse_scoped_filters_payload,
    _parse_interaction_filters_payload,
    _resolve_payload_param_values,
    _resolve_payload_calc_groups,
    _resolve_payload_what_if_values,
)
from dax_ui.server._duckdb import (
    _duckdb_table_exists,
    _sql_string_literal,
    _resolve_source_path,
    _is_remote_path,
    _ensure_duckdb_extension,
    _csv_options_from_source,
    _read_by_format_sql,
    _ensure_duckdb_sources_loaded,
    _connect_duckdb_for_project,
    _REL_CARDINALITY_SYNONYMS,
    _normalize_relationship_cardinality,
    _pretty_relationship_cardinality,
    _detect_relationship_cardinality,
    _resolve_and_validate_relationship_cardinality,
    _serialize_stat_value,
)
from dax_ui.server._engine import (
    ValidateResult,
    _ensure_mapping_loaded,
    PreparedEngineState,
    _ENGINE_LOCK,
    _ENGINE_CACHE,
    _ACTIVE_ENGINE,
    _norm_project_key,
    _project_signature,
    get_prepared_engine,
    _get_engine_table_sources,
    _compile_table_sources_for_model,
    _resolve_project_path,
    _resolve_duckdb_path,
    _deep_merge,
)
from dax_ui.server._plotly import (
    _PLOTLY_COLOR_SEQUENCES,
    _FORMAT_SCHEMA,
    _LEGEND_POSITION_MAP,
    _DEFAULT_VISUAL_INTERACTIONS,
    _format_options_to_plotly_patch,
    _apply_format_patch_to_figure,
    _normalize_visual_interactions,
)
from dax_ui.server._visual_io import (
    _load_visual_json,
    _save_visual_json,
    _delete_visual_json,
    _next_visual_id,
    _slot_value_present,
    _expr_output_name,
    _build_spec_from_encodings,
)
from dax_ui.server._validation import (
    _validate_measure,
    _analyze_ir_complexity,
    _generate_dax_suggestions,
)

logger = logging.getLogger(__name__)


# Module-level helpers from __init__
from dax_ui.server import (
    _validate_safe_name,
    _json_safe,
    _json_safe_with_path,
)





def _calc_groups_meta_from_model(model: Any) -> list[dict[str, Any]]:
    groups_map = getattr(model, "calculation_groups", {}) or {}
    if not isinstance(groups_map, Mapping):
        raise ValueError("model.calculation_groups must be a mapping")

    out: list[dict[str, Any]] = []
    for g_name, g in groups_map.items():
        name = str(getattr(g, "name", g_name) or "").strip()
        if not name:
            continue
        prec = getattr(g, "precedence", 0)
        if prec is None:
            prec = 0
        if not isinstance(prec, int):
            raise ValueError(f"calculation_groups[{name!r}].precedence must be an int")

        items_out: list[dict[str, Any]] = []
        items = getattr(g, "items", []) or []
        for it in items:
            it_name = str(getattr(it, "name", getattr(it, "key", "")) or "").strip()
            if not it_name:
                continue
            row: dict[str, Any] = {"name": it_name}
            fmt = getattr(it, "format_string", None)
            if isinstance(fmt, str) and fmt.strip():
                row["format_string"] = fmt.strip()
            items_out.append(row)
        items_out.sort(key=lambda d: str(d.get("name", "")).upper())
        out.append({"name": name, "precedence": int(prec), "items": items_out})

    out.sort(key=lambda d: (int(d.get("precedence", 0)), str(d.get("name", "")).upper()))
    return out

def _validate_calc_group_selections_against_model(model: Any, flat: list[Mapping[str, Any]]) -> None:
    groups_map = getattr(model, "calculation_groups", {}) or {}
    if not isinstance(groups_map, Mapping):
        raise ValueError("model.calculation_groups must be a mapping")

    norm_to_group: dict[str, Any] = {}
    for k, v in groups_map.items():
        if isinstance(k, str) and k.strip():
            norm_to_group[k.strip().upper()] = v
        nm = getattr(v, "name", None)
        if isinstance(nm, str) and nm.strip():
            norm_to_group[nm.strip().upper()] = v

    for i, it in enumerate(flat):
        group = str(it.get("group") or "").strip()
        item = str(it.get("item") or "").strip()
        if not group or not item:
            raise ValueError(f"calc_group_selections[{i}] must include group and item")
        g = norm_to_group.get(group.upper())
        if g is None:
            raise ValueError(f"calc_group_selections[{i}]: unknown calculation group: {group!r}")

        items = getattr(g, "items", []) or []
        valid = [str(getattr(x, "key", getattr(x, "name", "")) or "") for x in items]
        ok = any(str(getattr(x, "key", getattr(x, "name", "")) or "").upper() == item.upper() for x in items)
        if not ok:
            raise ValueError(
                f"calc_group_selections[{i}]: unknown item for {group!r}: {item!r}; valid: {valid}"
            )

def _hierarchies_meta_from_model(model: Any) -> dict[str, Any]:
    """Return hierarchy definitions from the model (OLS-filtered).

    Returns a dict mapping hierarchy name ΓåÆ {table, levels: [{column, name}]}.
    """
    h_map = getattr(model, "hierarchies", None) or {}
    if not isinstance(h_map, Mapping):
        return {}

    out: dict[str, Any] = {}
    for h_name, h in h_map.items():
        table = getattr(h, "table", "")
        levels = getattr(h, "levels", []) or []
        out[h_name] = {
            "table": table,
            "levels": [
                {"column": getattr(lvl, "column", ""), "name": getattr(lvl, "name", "")}
                for lvl in levels
            ],
        }
    return out

def _field_parameters_meta_from_model(model: Any) -> list[dict[str, Any]]:
    """Return field parameters metadata (Power BI parity schema).

    Uses simplified schema: items with name/ref, no kind/allow_multi.
    """
    fps_map = getattr(model, "field_parameters", {}) or {}
    if not isinstance(fps_map, Mapping):
        raise ValueError("model.field_parameters must be a mapping")

    out: list[dict[str, Any]] = []
    for fp_name, fp in fps_map.items():
        name = str(getattr(fp, "name", fp_name) or "").strip()
        if not name:
            continue

        default_item = str(getattr(fp, "default_item", "") or "").strip()
        items_raw = list(getattr(fp, "items", []) or [])

        items_out: list[dict[str, Any]] = []
        for item in items_raw:
            item_name = str(getattr(item, "name", "") or "").strip()
            if not item_name:
                continue
            ref = getattr(item, "ref", None)
            sort_raw = getattr(item, "sort", None)
            row: dict[str, Any] = {"name": item_name}
            if ref is not None:
                row["ref_type"] = type(ref).__name__
            if isinstance(sort_raw, int):
                row["sort"] = int(sort_raw)
            items_out.append(row)

        def _item_sort_key(d: Mapping[str, Any]) -> tuple:
            s = d.get("sort")
            sort_key = int(s) if isinstance(s, int) else 1_000_000_000
            return (sort_key, str(d.get("name", "")).upper())

        items_out.sort(key=_item_sort_key)

        row_fp: dict[str, Any] = {
            "name": name,
            "default_item": default_item or (items_out[0]["name"] if items_out else ""),
            "items": items_out,
        }
        out.append(row_fp)

    out.sort(key=lambda d: str(d.get("name", "")).upper())
    return out

def _validate_field_parameter_selections_against_model(model: Any, flat: list[Mapping[str, Any]]) -> None:
    """Validate field parameter selections against model (Power BI parity - single-select only)."""
    fps_map = getattr(model, "field_parameters", {}) or {}
    if not isinstance(fps_map, Mapping):
        raise ValueError("model.field_parameters must be a mapping")

    norm_to_fp: dict[str, Any] = {}
    for k, fp in fps_map.items():
        if isinstance(k, str) and k.strip():
            norm_to_fp[k.strip().upper()] = fp
        nm = getattr(fp, "name", None)
        if isinstance(nm, str) and nm.strip():
            norm_to_fp[nm.strip().upper()] = fp

    for i, it in enumerate(flat):
        param = str(it.get("param") or "").strip()
        if not param:
            raise ValueError(f"field_parameter_selections[{i}] must include param")

        values_raw = it.get("values")
        if values_raw is None:
            values_raw = [it.get("value")]
        if not isinstance(values_raw, list):
            values_raw = [values_raw]
        values: list[str] = [str(x).strip() for x in values_raw if isinstance(x, str) and str(x).strip()]
        if not values:
            raise ValueError(f"field_parameter_selections[{i}] must include value(s)")

        # Power BI parity: single-select only.
        if len(values) > 1:
            raise ValueError(
                f"field_parameter_selections[{i}]: field parameter {param!r} only supports single-select"
            )

        fp = norm_to_fp.get(param.upper())
        if fp is None:
            raise ValueError(f"field_parameter_selections[{i}]: unknown field parameter: {param!r}")

        items = list(getattr(fp, "items", []) or [])
        valid = [str(getattr(item, "name", "") or "") for item in items]
        for value in values:
            item_found = next((item for item in items if str(getattr(item, "name", "") or "").upper() == value.upper()), None)
            if item_found is None:
                raise ValueError(
                    f"field_parameter_selections[{i}]: unknown item for {param!r}: {value!r}; valid: {valid}"
                )

def _build_virtual_tables(model: Any) -> list[dict[str, Any]]:
    """Build virtual tables for field parameters, calc groups, and what-if parameters.

    Power BI parity: these appear as tables in the Fields pane and can be
    used in slicers and visuals via ColumnRef.
    """
    virtual_tables: list[dict[str, Any]] = []

    # 1) Field Parameters -> FieldParams_<ParamName> tables
    fps_map = getattr(model, "field_parameters", {}) or {}
    if isinstance(fps_map, Mapping):
        for fp_name, fp in fps_map.items():
            name = str(getattr(fp, "name", fp_name) or "").strip()
            if not name:
                continue
            table_name = f"FieldParams_{name}"
            dax_text = getattr(fp, "dax", None)
            columns: list[str]
            if isinstance(dax_text, str) and dax_text.strip():
                try:
                    from dax_project.save import infer_field_parameter_dax_columns

                    columns = list(infer_field_parameter_dax_columns(dax_text))
                except Exception as exc:  # noqa: BLE001
                    # If something invalid slipped through, do not crash bootstrap.
                    # The authoritative validation happens on PUT /runtime/field_parameters.
                    logger.warning("Failed to infer field parameter columns for %r: %s", name, exc)
                    columns = [name, f"{name} Label", f"{name} Sort"]
            else:
                # Legacy Power BI-style columns: <Name>, <Name> Label, <Name> Sort
                columns = [name, f"{name} Label", f"{name} Sort"]
            virtual_tables.append({
                "name": table_name,
                "columns": columns,
                "virtual": True,
                "semantic_type": "field_parameter",
                "param_name": name,
            })
            # Also register under the unprefixed name so that visuals referencing
            # just "Parameter Columns" (without the FieldParams_ prefix) resolve correctly.
            if table_name != name:
                virtual_tables.append({
                    "name": name,
                    "columns": columns,
                    "virtual": True,
                    "semantic_type": "field_parameter",
                    "param_name": name,
                    "_alias_of": table_name,
                })

    # 2) Calculation Groups -> CalcGroup_<GroupName> tables
    cgs_map = getattr(model, "calculation_groups", {}) or {}
    if isinstance(cgs_map, Mapping):
        for cg_name, cg in cgs_map.items():
            name = str(getattr(cg, "name", cg_name) or "").strip()
            if not name:
                continue
            table_name = f"CalcGroup_{name}"
            # Single column with group name (contains item names as values)
            columns = [name]
            virtual_tables.append({
                "name": table_name,
                "columns": columns,
                "virtual": True,
                "semantic_type": "calculation_group",
                "group_name": name,
            })

    # 3) What-If Parameters -> WhatIf_<ParamName> tables
    wips_map = getattr(model, "what_if_parameters", {}) or {}
    if isinstance(wips_map, Mapping):
        for wip_name, wip in wips_map.items():
            name = str(getattr(wip, "name", wip_name) or "").strip()
            if not name:
                continue
            table_name = f"WhatIf_{name}"
            # Columns: Value (primary), optional Label and Sort
            columns = ["Value", "Label", "Sort"]
            virtual_tables.append({
                "name": table_name,
                "columns": columns,
                "virtual": True,
                "semantic_type": "what_if_parameter",
                "param_name": name,
            })

    return virtual_tables

def _get_virtual_table_distinct_values(
    model: Any,
    table_name: str,
    column_name: str,
) -> list[Any]:
    """Get distinct values for a virtual table column.

    Used by slicers and value pickers for semantic tables.
    """
    # Field Parameters
    if table_name.startswith("FieldParams_"):
        param_name = table_name[len("FieldParams_"):]
        fps_map = getattr(model, "field_parameters", {}) or {}
        fp = None
        for k, v in fps_map.items():
            if str(getattr(v, "name", k) or "").strip().upper() == param_name.upper():
                fp = v
                break
        if fp is None:
            return []

        items = list(getattr(fp, "items", []) or [])
        # Return based on column requested
        if column_name.upper() == param_name.upper():
            # Primary column - return item names
            return [str(getattr(item, "name", "") or "") for item in items if getattr(item, "name", "")]
        elif column_name.upper() == f"{param_name} LABEL".upper():
            # Label column - same as name for now
            return [str(getattr(item, "name", "") or "") for item in items if getattr(item, "name", "")]
        elif column_name.upper() == f"{param_name} SORT".upper():
            # Sort column - return indices
            return list(range(len(items)))
        elif column_name.upper() == "HIERARCHY":
            # Hierarchy/locale column - return distinct locale groupings
            # Locale is stored in custom_props on FieldParameterItem
            seen: set[str] = set()
            result: list[str] = []
            for item in items:
                cp = getattr(item, "custom_props", None)
                locale = ""
                if isinstance(cp, dict):
                    loc = cp.get("locale", "")
                    if isinstance(loc, str) and loc.strip():
                        locale = loc.strip()
                if locale and locale not in seen:
                    seen.add(locale)
                    result.append(locale)
            return result
        return []

    # Field Parameters (unprefixed Power BI name)
    fps_map_check = getattr(model, "field_parameters", {}) or {}
    _fp_match = None
    _fp_match_name = ""
    for k, v in fps_map_check.items():
        nm = str(getattr(v, "name", k) or "").strip()
        if nm.upper() == table_name.upper():
            _fp_match = v
            _fp_match_name = nm
            break
    if _fp_match is not None:
        # Delegate to the prefixed handler
        return _get_virtual_column_values(
            model=model,
            table_name=f"FieldParams_{_fp_match_name}",
            column_name=column_name,
        )

    # Calculation Groups
    if table_name.startswith("CalcGroup_"):
        group_name = table_name[len("CalcGroup_"):]
        cgs_map = getattr(model, "calculation_groups", {}) or {}
        cg = None
        for k, v in cgs_map.items():
            if str(getattr(v, "name", k) or "").strip().upper() == group_name.upper():
                cg = v
                break
        if cg is None:
            return []
        items = list(getattr(cg, "items", []) or [])
        # Return item names
        return [str(getattr(item, "name", getattr(item, "key", "")) or "") for item in items]

    # What-If Parameters
    if table_name.startswith("WhatIf_"):
        param_name = table_name[len("WhatIf_"):]
        wips_map = getattr(model, "what_if_parameters", {}) or {}
        wip = None
        for k, v in wips_map.items():
            if str(getattr(v, "name", k) or "").strip().upper() == param_name.upper():
                wip = v
                break
        if wip is None:
            return []
        min_val = float(getattr(wip, "min_value", 0))
        max_val = float(getattr(wip, "max_value", 1))
        step = float(getattr(wip, "step", 0.1))
        if step <= 0:
            step = 0.1
        # Generate values
        values = []
        v = min_val
        while v <= max_val + step / 2:
            values.append(round(v, 10))
            v += step
        if column_name.upper() == "VALUE":
            return values
        elif column_name.upper() == "LABEL":
            return [str(x) for x in values]
        elif column_name.upper() == "SORT":
            return list(range(len(values)))
        return []

    return []

def _what_if_parameters_meta_from_model(model: Any) -> list[dict[str, Any]]:
    """Return What-If parameters metadata."""
    wips_map = getattr(model, "what_if_parameters", {}) or {}
    if not isinstance(wips_map, Mapping):
        raise ValueError("model.what_if_parameters must be a mapping")

    out: list[dict[str, Any]] = []
    for wip_name, wip in wips_map.items():
        name = str(getattr(wip, "name", wip_name) or "").strip()
        if not name:
            continue

        row: dict[str, Any] = {
            "name": name,
            "min": float(getattr(wip, "min_value", 0)),
            "max": float(getattr(wip, "max_value", 1)),
            "step": float(getattr(wip, "step", 0.1)),
            "default": float(getattr(wip, "default_value", 0)),
        }
        fmt = getattr(wip, "format", None)
        if isinstance(fmt, str) and fmt.strip():
            row["format"] = fmt.strip()
        out.append(row)

    out.sort(key=lambda d: str(d.get("name", "")).upper())
    return out


def _resolve_field_parameter_hierarchy_values(
    model: Any,
    table_name: str,
    column_name: str,
) -> Optional[list[str]]:
    """Resolve distinct values for a field-parameter hierarchy/lookup table.

    Some models define a shared dimension table (e.g. "Parameter Measure Hierarchy")
    that has no backing data source.  Its values are determined by the ``locale``
    attribute on items in the field-parameter tables that reference it via
    relationships.

    Returns a sorted list of distinct values if the table is recognised as a
    field-parameter hierarchy table, otherwise ``None``.
    """
    rels = getattr(model, "relationships", None)
    if not rels:
        return None
    fps_map = getattr(model, "field_parameters", {}) or {}
    if not isinstance(fps_map, Mapping) or not fps_map:
        return None

    # Build a lookup of field-parameter names (case-insensitive).
    fp_by_name: dict[str, Any] = {}
    for k, v in fps_map.items():
        name = str(getattr(v, "name", k) or "").strip()
        if name:
            fp_by_name[name.upper()] = v

    # Walk relationships: find those where to_table matches the requested table
    # and from_table is a known field parameter.
    connected: list[tuple[str, str]] = []  # (fp_name_upper, from_column)
    for rel in rels:
        to_table = str(getattr(rel, "to_table", "") or "").strip()
        to_column = str(getattr(rel, "to_column", "") or "").strip()
        from_table = str(getattr(rel, "from_table", "") or "").strip()
        from_column = str(getattr(rel, "from_column", "") or "").strip()
        if (
            to_table.upper() == table_name.upper()
            and to_column.upper() == column_name.upper()
            and from_table.upper() in fp_by_name
        ):
            connected.append((from_table.upper(), from_column))

    if not connected:
        return None

    # Collect distinct locale values from connected field-parameter items.
    values_set: set[str] = set()
    for fp_key, _from_col in connected:
        fp = fp_by_name.get(fp_key)
        if fp is None:
            continue
        for item in getattr(fp, "items", []) or []:
            # locale may be a direct attribute or stored in custom_props
            locale = getattr(item, "locale", None)
            if locale is None:
                props = getattr(item, "custom_props", None)
                if isinstance(props, Mapping):
                    locale = props.get("locale")
            locale_str = str(locale or "").strip()
            if locale_str:
                values_set.add(locale_str)

    if not values_set:
        return None

    return sorted(values_set)


def _validate_what_if_selections_against_model(model: Any, flat: list[Mapping[str, Any]]) -> None:
    """Validate What-If selections against model."""
    wips_map = getattr(model, "what_if_parameters", {}) or {}
    if not isinstance(wips_map, Mapping):
        raise ValueError("model.what_if_parameters must be a mapping")

    norm_to_wip: dict[str, Any] = {}
    for k, wip in wips_map.items():
        if isinstance(k, str) and k.strip():
            norm_to_wip[k.strip().upper()] = wip
        nm = getattr(wip, "name", None)
        if isinstance(nm, str) and nm.strip():
            norm_to_wip[nm.strip().upper()] = wip

    for i, it in enumerate(flat):
        param = str(it.get("param") or "").strip()
        if not param:
            raise ValueError(f"what_if_selections[{i}] must include param")

        value = it.get("value")
        if not isinstance(value, (int, float)):
            raise ValueError(f"what_if_selections[{i}] must include numeric value")

        wip = norm_to_wip.get(param.upper())
        if wip is None:
            raise ValueError(f"what_if_selections[{i}]: unknown What-If parameter: {param!r}")

        min_val = float(getattr(wip, "min_value", 0))
        max_val = float(getattr(wip, "max_value", 1))
        if value < min_val or value > max_val:
            raise ValueError(
                f"what_if_selections[{i}]: value {value} for {param!r} is out of range [{min_val}, {max_val}]"
            )

def _normalize_slicer_defs_payload(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {"defs": []}
    if isinstance(obj, list):
        return {"defs": obj}
    if isinstance(obj, Mapping):
        defs = obj.get("defs")
        if defs is None:
            defs = []
        if not isinstance(defs, list):
            raise ValueError("slicer_defs.defs must be a list")
        return {"defs": defs}
    raise ValueError("slicer_defs must be an object or a list")

def _evaluate_measure_ref_scalar(
    *,
    project_path: str,
    model: Any,
    sec_state: _RuntimeSecurityState,
    measure_ref: MeasureRef,
    duckdb_path: Optional[str],
    filters: list[dax_compiler.ScopedFilter],
    page_id: Optional[str],
    visual_id: Optional[str],
) -> Any:
    with _ENGINE_LOCK:
        get_prepared_engine(project_path, model)
        from dax_engine.filters_ir import apply_scoped_filters_to_context

        ctx, _applied = apply_scoped_filters_to_context(
            sec_state.ctx,
            list(filters),
            page_id=str(page_id) if page_id else None,
            visual_id=str(visual_id) if visual_id else None,
        )
        _table_ir, sql = plan_card_query(
            measure_ref,
            filters=[],
            model=sec_state.model_scoped,
            ctx=ctx,
        )

    con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
    try:
        rows = con.execute(dax_compiler.normalize_sql(f"SELECT * FROM {sql}")).fetchall()
    finally:
        try:
            con.close()
        except Exception:
            pass
    val = rows[0][0] if rows and rows[0] else None
    if isinstance(val, (dict, list, tuple, set)):
        raise ValueError(f"Slicer default measure must return a scalar; got {type(val).__name__}")
    return val

def _evaluate_measure_set_values(
    *,
    project_path: str,
    model: Any,
    sec_state: _RuntimeSecurityState,
    measure_ref: MeasureRef,
    duckdb_path: Optional[str],
    filters: list[dax_compiler.ScopedFilter],
    page_id: Optional[str],
    visual_id: Optional[str],
) -> list[Any]:
    """Evaluate a table-returning measure (defaults.mode == "measure_set").

    Flow:
    - resolve measure name -> DAX text from the model
    - parse DAX -> table IR
    - compile via compile_table_expr
    - execute rowset and validate 1-column shape
    - dedupe values deterministically
    """
    with _ENGINE_LOCK:
        get_prepared_engine(project_path, model)
        from dax_engine.filters_ir import apply_scoped_filters_to_context
        from dax_engine.compiler import compile_table_expr
        from dax_parser.parser import parse_expression
        from dax_parser.ir_mapper import ast_to_ir

        ctx, _applied = apply_scoped_filters_to_context(
            sec_state.ctx,
            list(filters),
            page_id=str(page_id) if page_id else None,
            visual_id=str(visual_id) if visual_id else None,
        )

        # Find the measure definition in the model
        measure_def = None
        for m in getattr(sec_state.model_scoped, "measures", []):
            if str(getattr(m, "name", "")).strip().upper() == measure_ref.name.upper():
                measure_def = m
                break
        if measure_def is None:
            raise ValueError(f"Measure not found: {measure_ref.name}")

        # Parse and compile the measure's DAX expression
        dax_text = str(getattr(measure_def, "dax", "")).strip()
        if not dax_text:
            raise ValueError(f"Measure {measure_ref.name} has no DAX expression")

        ast = parse_expression(dax_text)
        table_ir = ast_to_ir(ast)
        sql = compile_table_expr(table_ir, ctx)

    con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
    try:
        cur = con.execute(dax_compiler.normalize_sql(f"SELECT * FROM ({sql}) t"))
        col_count = len(cur.description or [])
        rows = cur.fetchall()
    finally:
        try:
            con.close()
        except Exception:
            pass

    # Validate 1-column shape even when the table is empty.
    if col_count != 1:
        raise ValueError(f"Slicer default measure_set must return a 1-column table; got {col_count} columns")

    if not rows:
        return []

    # Extract, dedupe, preserve order.
    import json

    seen: set[str] = set()
    out: list[Any] = []
    for row in rows:
        v = row[0] if row else None
        # Use JSON-safe key for deduplication.
        try:
            k = json.dumps(_json_safe(v), sort_keys=True, separators=(",", ":"))
        except Exception:
            k = str(v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out

def _evaluate_measure_ref_set(
    *,
    project_path: str,
    model: Any,
    sec_state: _RuntimeSecurityState,
    measure_ref: MeasureRef,
    duckdb_path: Optional[str],
    filters: list[dax_compiler.ScopedFilter],
    page_id: Optional[str],
    visual_id: Optional[str],
) -> list[Any]:
    # Back-compat alias for early `measure_set` implementation work.
    return _evaluate_measure_set_values(
        project_path=project_path,
        model=model,
        sec_state=sec_state,
        measure_ref=measure_ref,
        duckdb_path=duckdb_path,
        filters=filters,
        page_id=page_id,
        visual_id=visual_id,
    )

def _materialize_slicer_defs_to_filter_payload_items(
    defs_obj: Mapping[str, Any],
    *,
    exclude_def_id: Optional[str] = None,
    project_path: Optional[str] = None,
    model: Any = None,
    sec_state: Optional[_RuntimeSecurityState] = None,
    duckdb_path: Optional[str] = None,
    runtime_filters: Optional[list[dax_compiler.ScopedFilter]] = None,
    page_id: Optional[str] = None,
    visual_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    ex = str(exclude_def_id or "").strip().upper() if exclude_def_id else ""
    out_static: list[dict[str, Any]] = []
    default_candidates: list[tuple[str, str, Optional[str], Mapping[str, Any], Mapping[str, Any]]] = []

    def _targets_for_slicer(d: Mapping[str, Any], scope: str, target: Optional[str]) -> list[Optional[str]]:
        if scope != "page":
            return [None]
        sync_pages = d.get("sync_pages")
        targets: list[Optional[str]] = []
        if isinstance(sync_pages, Mapping):
            for pid_raw, cfg in sync_pages.items():
                pid = str(pid_raw).strip()
                if not pid:
                    continue
                sync = True
                if isinstance(cfg, Mapping):
                    sync = bool(cfg.get("sync", True))
                if sync:
                    targets.append(pid)
        if not targets and target:
            targets.append(target)
        seen: set[str] = set()
        out: list[Optional[str]] = []
        for item in targets:
            key = str(item or "").upper()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _add_months(d: datetime.date, months: int) -> datetime.date:
        month_index = d.month - 1 + months
        year = d.year + month_index // 12
        month = month_index % 12 + 1
        if month == 12:
            next_month = datetime.date(year + 1, 1, 1)
        else:
            next_month = datetime.date(year, month + 1, 1)
        last_day = (next_month - datetime.timedelta(days=1)).day
        return datetime.date(year, month, min(d.day, last_day))

    def _add_relative_units(d: datetime.date, unit: str, count: int) -> datetime.date:
        if unit == "day":
            return d + datetime.timedelta(days=count)
        if unit == "week":
            return d + datetime.timedelta(days=7 * count)
        if unit == "month":
            return _add_months(d, count)
        if unit == "quarter":
            return _add_months(d, count * 3)
        if unit == "year":
            return _add_months(d, count * 12)
        raise ValueError(f"unsupported relative_date unit: {unit}")

    def _start_of_relative_unit(d: datetime.date, unit: str) -> datetime.date:
        if unit == "day":
            return d
        if unit == "week":
            return d - datetime.timedelta(days=d.weekday())
        if unit == "month":
            return datetime.date(d.year, d.month, 1)
        if unit == "quarter":
            month = ((d.month - 1) // 3) * 3 + 1
            return datetime.date(d.year, month, 1)
        if unit == "year":
            return datetime.date(d.year, 1, 1)
        raise ValueError(f"unsupported relative_date unit: {unit}")

    def _end_of_relative_unit(d: datetime.date, unit: str) -> datetime.date:
        return _add_relative_units(_start_of_relative_unit(d, unit), unit, 1) - datetime.timedelta(days=1)

    def _boolish(value: Any, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _parse_relative_anchor(value: Any, *, index: int) -> datetime.date:
        if value is None or str(value).strip() == "":
            return datetime.datetime.utcnow().date()
        raw = str(value).strip()[:10]
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"slicer_defs.defs[{index}].selection.anchor must be YYYY-MM-DD") from exc

    def _parse_relative_time_anchor(value: Any, *, index: int) -> datetime.datetime:
        if value is None or str(value).strip() == "":
            return datetime.datetime.utcnow().replace(microsecond=0)
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"slicer_defs.defs[{index}].selection.anchor must be an ISO datetime") from exc
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0)

    def _relative_time_delta(unit: str, count: int) -> datetime.timedelta:
        if unit == "minute":
            return datetime.timedelta(minutes=count)
        if unit == "hour":
            return datetime.timedelta(hours=count)
        raise ValueError(f"unsupported relative_time unit: {unit}")

    def _start_of_relative_time_unit(value: datetime.datetime, unit: str) -> datetime.datetime:
        if unit == "minute":
            return value.replace(second=0, microsecond=0)
        if unit == "hour":
            return value.replace(minute=0, second=0, microsecond=0)
        raise ValueError(f"unsupported relative_time unit: {unit}")

    def _format_relative_time(value: datetime.datetime) -> str:
        return value.replace(microsecond=0).isoformat(timespec="seconds")

    def _resolve_relative_time_range(sel: Mapping[str, Any], *, index: int) -> tuple[str, str]:
        direction_raw = str(sel.get("direction") or sel.get("period") or "last").strip().lower()
        direction = {
            "previous": "last",
            "prev": "last",
            "past": "last",
            "future": "next",
            "current": "this",
        }.get(direction_raw, direction_raw)
        if direction not in {"last", "next", "this"}:
            raise ValueError(f"slicer_defs.defs[{index}].selection.direction must be 'last', 'next', or 'this'")

        unit_raw = str(sel.get("unit") or "minute").strip().lower().replace("_", " ").replace("-", " ")
        unit = {
            "minute": "minute",
            "minutes": "minute",
            "min": "minute",
            "mins": "minute",
            "hour": "hour",
            "hours": "hour",
            "hr": "hour",
            "hrs": "hour",
        }.get(unit_raw)
        if unit is None:
            raise ValueError(f"slicer_defs.defs[{index}].selection.unit must be minute or hour")

        try:
            count = int(sel.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"slicer_defs.defs[{index}].selection.count must be a positive integer") from exc
        if count < 1:
            raise ValueError(f"slicer_defs.defs[{index}].selection.count must be a positive integer")

        anchor = _parse_relative_time_anchor(sel.get("anchor"), index=index)
        include_current = _boolish(sel.get("include_current", sel.get("include_today")), default=True)
        unit_delta = _relative_time_delta(unit, 1)

        if direction == "this":
            start = _start_of_relative_time_unit(anchor, unit)
            end = start + unit_delta - datetime.timedelta(seconds=1)
            return _format_relative_time(start), _format_relative_time(end)

        if direction == "last":
            end = anchor if include_current else _start_of_relative_time_unit(anchor, unit) - datetime.timedelta(seconds=1)
            start = end - _relative_time_delta(unit, count)
        else:
            start = anchor if include_current else _start_of_relative_time_unit(anchor, unit) + unit_delta
            end = start + _relative_time_delta(unit, count)
        return _format_relative_time(start), _format_relative_time(end)

    def _resolve_relative_date_range(sel: Mapping[str, Any], *, index: int) -> tuple[str, str]:
        direction_raw = str(sel.get("direction") or sel.get("period") or "last").strip().lower()
        direction = {
            "previous": "last",
            "prev": "last",
            "past": "last",
            "future": "next",
            "current": "this",
        }.get(direction_raw, direction_raw)
        if direction not in {"last", "next", "this"}:
            raise ValueError(f"slicer_defs.defs[{index}].selection.direction must be 'last', 'next', or 'this'")

        unit_raw = str(sel.get("unit") or "day").strip().lower().replace("_", " ").replace("-", " ")
        unit = {
            "day": "day",
            "days": "day",
            "week": "week",
            "weeks": "week",
            "month": "month",
            "months": "month",
            "quarter": "quarter",
            "quarters": "quarter",
            "year": "year",
            "years": "year",
        }.get(unit_raw)
        if unit is None:
            raise ValueError(
                f"slicer_defs.defs[{index}].selection.unit must be day, week, month, quarter, or year"
            )

        try:
            count = int(sel.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"slicer_defs.defs[{index}].selection.count must be a positive integer") from exc
        if count < 1:
            raise ValueError(f"slicer_defs.defs[{index}].selection.count must be a positive integer")

        anchor = _parse_relative_anchor(sel.get("anchor"), index=index)
        include_today = _boolish(sel.get("include_today"), default=True)
        window_raw = sel.get("window")
        if window_raw is None and "calendar" in sel:
            window_raw = "calendar" if _boolish(sel.get("calendar"), default=False) else "rolling"
        window = str(window_raw or "rolling").strip().lower()
        if window not in {"rolling", "calendar"}:
            raise ValueError(f"slicer_defs.defs[{index}].selection.window must be 'rolling' or 'calendar'")

        if direction == "this":
            start = _start_of_relative_unit(anchor, unit)
            end = _end_of_relative_unit(anchor, unit)
            return start.isoformat(), end.isoformat()

        if window == "calendar":
            anchor_start = _start_of_relative_unit(anchor, unit)
            if direction == "last":
                end_unit = anchor_start if include_today else _add_relative_units(anchor_start, unit, -1)
                start_unit = _add_relative_units(end_unit, unit, -(count - 1))
                start = _start_of_relative_unit(start_unit, unit)
                end = _end_of_relative_unit(end_unit, unit)
            else:
                start_unit = anchor_start if include_today else _add_relative_units(anchor_start, unit, 1)
                end_unit = _add_relative_units(start_unit, unit, count - 1)
                start = _start_of_relative_unit(start_unit, unit)
                end = _end_of_relative_unit(end_unit, unit)
            return start.isoformat(), end.isoformat()

        if direction == "last":
            if include_today:
                end = anchor
                start = _add_relative_units(anchor, unit, -count) + datetime.timedelta(days=1)
            else:
                end = anchor - datetime.timedelta(days=1)
                start = _add_relative_units(anchor, unit, -count)
        else:
            start = anchor if include_today else anchor + datetime.timedelta(days=1)
            end = _add_relative_units(start, unit, count) - datetime.timedelta(days=1)
        return start.isoformat(), end.isoformat()

    for i, d in enumerate(defs_obj.get("defs") or []):
        if not isinstance(d, Mapping):
            raise ValueError(f"slicer_defs.defs[{i}] must be an object")
        did = str(d.get("id") or "").strip()
        if not did:
            raise ValueError(f"slicer_defs.defs[{i}].id is required")
        if ex and did.strip().upper() == ex:
            continue

        ui_for_mode = d.get("ui") if isinstance(d.get("ui"), Mapping) else {}
        if (
            str(d.get("type") or "list").strip().lower() == "input"
            and isinstance(ui_for_mode, Mapping)
            and str(ui_for_mode.get("input_mode") or "filter").strip().lower() == "input"
        ):
            continue
        col = d.get("column")
        if not isinstance(col, Mapping):
            raise ValueError(f"slicer_defs.defs[{i}].column must be an object")
        scope = str(d.get("scope") or "report").strip().lower()
        if scope not in {"report", "page"}:
            raise ValueError(f"slicer_defs.defs[{i}].scope must be 'report' or 'page'")
        target_raw = d.get("target")
        target = str(target_raw).strip() if isinstance(target_raw, str) and target_raw.strip() else None
        if scope == "report":
            target = None
        if scope == "page" and not target:
            raise ValueError(f"slicer_defs.defs[{i}].target is required when scope=='page'")
        filter_targets = _targets_for_slicer(d, scope, target)

        s_type = str(d.get("type") or "list").strip().lower()

        sel = d.get("selection")
        if s_type in {"date_range", "relative_date", "relative_time"}:
            if sel is None:
                mode = "all"
                start = None
                end = None
            else:
                if not isinstance(sel, Mapping):
                    raise ValueError(f"slicer_defs.defs[{i}].selection must be an object")
                mode = str(sel.get("mode") or "all").strip().lower()
                if mode == "relative" and s_type not in {"relative_date", "relative_time"}:
                    raise ValueError(f"slicer_defs.defs[{i}].selection.mode must be 'all' or 'range'")
                if mode not in {"all", "range", "relative"}:
                    raise ValueError(f"slicer_defs.defs[{i}].selection.mode must be 'all', 'range', or 'relative'")
                if mode == "relative":
                    if s_type == "relative_time":
                        start, end = _resolve_relative_time_range(sel, index=i)
                    else:
                        start, end = _resolve_relative_date_range(sel, index=i)
                else:
                    start_raw = sel.get("start")
                    end_raw = sel.get("end")
                    start = str(start_raw).strip() if isinstance(start_raw, str) and str(start_raw).strip() else None
                    end = str(end_raw).strip() if isinstance(end_raw, str) and str(end_raw).strip() else None
                    if start is not None and end is not None and start > end:
                        raise ValueError("date_range slicer selection.start must be <= selection.end")

            # Empty range behaves like ALL (emit no filter).
            if mode in {"range", "relative"} and not (start is None and end is None):
                if start is not None:
                    for filter_target in filter_targets:
                        out_static.append(
                            {
                                "scope": scope,
                                "target": filter_target,
                                "keep": True,
                                "source": "slicer",
                                "slicer_id": did,
                                "column": {
                                    "type": "ColumnRef",
                                    "table": str(col.get("table") or ""),
                                    "column": str(col.get("column") or ""),
                                },
                                "operator": ">=",
                                "values": [start],
                            }
                        )
                if end is not None:
                    for filter_target in filter_targets:
                        out_static.append(
                            {
                                "scope": scope,
                                "target": filter_target,
                                "keep": True,
                                "source": "slicer",
                                "slicer_id": did,
                                "column": {
                                    "type": "ColumnRef",
                                    "table": str(col.get("table") or ""),
                                    "column": str(col.get("column") or ""),
                                },
                                "operator": "<=",
                                "values": [end],
                            }
                        )

            # Candidate for defaults only when selection is ALL (no range).
            if mode == "all" or (mode == "range" and start is None and end is None):
                defaults_raw = d.get("defaults")
                if isinstance(defaults_raw, Mapping):
                    for filter_target in filter_targets:
                        default_candidates.append((did, scope, filter_target, col, defaults_raw))
            continue

        if sel is None:
            mode = "all"
            values = []
        else:
            if not isinstance(sel, Mapping):
                raise ValueError(f"slicer_defs.defs[{i}].selection must be an object")
            mode = str(sel.get("mode") or "all").strip().lower()
            if mode == "selected":
                # Back-compat: older builds used 'selected'. Canonicalize to 'values'.
                mode = "values"
            if mode not in {"all", "values"}:
                raise ValueError(f"slicer_defs.defs[{i}].selection.mode must be 'all' or 'values'")
            vals_raw = sel.get("values")
            if vals_raw is None:
                values = []
            elif isinstance(vals_raw, list):
                values = list(vals_raw)
            else:
                values = [vals_raw]

        # Normalize None -> __BLANK__ for IR lowering.
        values = ["__BLANK__" if v is None else v for v in (values or [])]

        # Normalization: empty values selection behaves like 'all' (emit no filter).
        if mode == "values" and not values:
            mode = "all"

        if mode != "values":
            defaults_raw = d.get("defaults")
            if isinstance(defaults_raw, Mapping):
                for filter_target in filter_targets:
                    default_candidates.append((did, scope, filter_target, col, defaults_raw))
            continue

        ui_raw = d.get("ui") if isinstance(d.get("ui"), Mapping) else {}
        filter_operator = str(
            d.get("filter_operator")
            or (ui_raw.get("filter_operator") if isinstance(ui_raw, Mapping) else None)
            or ("contains" if s_type == "input" else "in")
        ).strip().lower()

        for filter_target in filter_targets:
            out_static.append(
                {
                    "scope": scope,
                    "target": filter_target,
                    "keep": True,
                    "source": "slicer",
                    "slicer_id": did,
                    "column": {"type": "ColumnRef", "table": str(col.get("table") or ""), "column": str(col.get("column") or "")},
                    "operator": filter_operator,
                    "values": values,
                }
            )

    # Apply dynamic defaults (measure-driven) only when selection.mode == 'all'.
    # This requires runtime filter context + security scope.
    if default_candidates and project_path and sec_state and isinstance(model, object) and runtime_filters is not None:
        try:
            slicer_filters_static = _parse_scoped_filters_payload(out_static)
        except Exception as exc:
            raise ValueError(f"Slicer default failed: could not parse base slicer filters: {exc}") from exc

        def _meas_ref(raw: Any, *, path: str) -> MeasureRef:
            if not isinstance(raw, Mapping):
                raise ValueError(f"Slicer default failed: {path} must be a MeasureRef")
            m = parse_expr(dict(raw))
            if not isinstance(m, MeasureRef):
                raise ValueError(f"Slicer default failed: {path} must be a MeasureRef")
            return m

        def _ensure_visible_measure(mref: MeasureRef, *, path: str) -> None:
            role = getattr(sec_state, "role", None)
            ols = getattr(role, "ols", None) if role is not None else None
            hidden = {str(x).strip().upper() for x in (getattr(ols, "measures", None) or []) if str(x).strip()}
            if hidden and str(mref.name or "").strip().upper() in hidden:
                raise ValueError(f"Slicer default failed: {path} is hidden by the active role")

        def _iso_date10(v: Any) -> Optional[str]:
            if v is None:
                return None
            if isinstance(v, datetime.datetime):
                return v.date().isoformat()
            if isinstance(v, datetime.date):
                return v.isoformat()
            if not isinstance(v, str):
                raise ValueError("Slicer default failed: date_range default must be a date-like string")
            txt = v.strip()
            if txt == "":
                return None
            if len(txt) >= 10:
                txt = txt[:10]
            if len(txt) != 10 or txt[4] != "-" or txt[7] != "-":
                raise ValueError("Slicer default failed: date_range default must be YYYY-MM-DD")
            y, m, d = txt[:4], txt[5:7], txt[8:10]
            if not (y.isdigit() and m.isdigit() and d.isdigit()):
                raise ValueError("Slicer default failed: date_range default must be YYYY-MM-DD")
            return txt

        out_dynamic: list[dict[str, Any]] = []
        for did, scope, target, col, defaults_raw in default_candidates:
            defaults_mode = str(defaults_raw.get("mode") or "none").strip().lower()
            if defaults_mode not in {"measure", "measure_set"}:
                continue
            if defaults_raw.get("apply_on_load") is not True:
                continue

            # Effective filters for default evaluation exclude this slicer.
            eff_slicer_filters = [
                f for f in slicer_filters_static if str(getattr(f, "slicer_id", "") or "").strip().upper() != did.upper()
            ]
            effective = list(runtime_filters) + list(eff_slicer_filters)

            try:
                if str(defaults_raw.get("date_range") or "") and str(col.get("column") or ""):
                    # date_range shape uses defaults.date_range
                    dr = defaults_raw.get("date_range")
                    if dr is None:
                        dr = {}
                    if not isinstance(dr, Mapping):
                        raise ValueError("Slicer default failed: defaults.date_range must be an object")
                    sm_raw = dr.get("start_measure")
                    em_raw = dr.get("end_measure")

                    if sm_raw is not None:
                        sm = _meas_ref(sm_raw, path="defaults.date_range.start_measure")
                        _ensure_visible_measure(sm, path="defaults.date_range.start_measure")
                        v = _evaluate_measure_ref_scalar(
                            project_path=project_path,
                            model=model,
                            sec_state=sec_state,
                            measure_ref=sm,
                            duckdb_path=duckdb_path,
                            filters=effective,
                            page_id=page_id,
                            visual_id=visual_id,
                        )
                        ds = _iso_date10(v)
                        if ds is not None:
                            out_dynamic.append(
                                {
                                    "scope": scope,
                                    "target": target,
                                    "keep": True,
                                    "source": "slicer",
                                    "slicer_id": did,
                                    "column": {
                                        "type": "ColumnRef",
                                        "table": str(col.get("table") or ""),
                                        "column": str(col.get("column") or ""),
                                    },
                                    "operator": ">=",
                                    "values": [ds],
                                }
                            )

                    if em_raw is not None:
                        em = _meas_ref(em_raw, path="defaults.date_range.end_measure")
                        _ensure_visible_measure(em, path="defaults.date_range.end_measure")
                        v = _evaluate_measure_ref_scalar(
                            project_path=project_path,
                            model=model,
                            sec_state=sec_state,
                            measure_ref=em,
                            duckdb_path=duckdb_path,
                            filters=effective,
                            page_id=page_id,
                            visual_id=visual_id,
                        )
                        ds = _iso_date10(v)
                        if ds is not None:
                            out_dynamic.append(
                                {
                                    "scope": scope,
                                    "target": target,
                                    "keep": True,
                                    "source": "slicer",
                                    "slicer_id": did,
                                    "column": {
                                        "type": "ColumnRef",
                                        "table": str(col.get("table") or ""),
                                        "column": str(col.get("column") or ""),
                                    },
                                    "operator": "<=",
                                    "values": [ds],
                                }
                            )
                    continue

                m_raw = defaults_raw.get("measure")
                if m_raw is None:
                    raise ValueError("Slicer default failed: defaults.measure is required")
                m = _meas_ref(m_raw, path="defaults.measure")
                _ensure_visible_measure(m, path="defaults.measure")
                _validate_measureref_in_model(sec_state.model_scoped, m.name)

                if defaults_mode == "measure":
                    # Scalar measure default
                    v = _evaluate_measure_ref_scalar(
                        project_path=project_path,
                        model=model,
                        sec_state=sec_state,
                        measure_ref=m,
                        duckdb_path=duckdb_path,
                        filters=effective,
                        page_id=page_id,
                        visual_id=visual_id,
                    )
                    if v is None:
                        v = "__BLANK__"
                    elif isinstance(v, datetime.datetime):
                        v = v.isoformat()
                    elif isinstance(v, datetime.date):
                        v = v.isoformat()
                    out_dynamic.append(
                        {
                            "scope": scope,
                            "target": target,
                            "keep": True,
                            "source": "slicer",
                            "slicer_id": did,
                            "column": {
                                "type": "ColumnRef",
                                "table": str(col.get("table") or ""),
                                "column": str(col.get("column") or ""),
                            },
                            "operator": "in",
                            "values": [v],
                        }
                    )
                elif defaults_mode == "measure_set":
                    # Table-returning measure default
                    vals = _evaluate_measure_ref_set(
                        project_path=project_path,
                        model=model,
                        sec_state=sec_state,
                        measure_ref=m,
                        duckdb_path=duckdb_path,
                        filters=effective,
                        page_id=page_id,
                        visual_id=visual_id,
                    )
                    # Empty set => emit no filter
                    if not vals:
                        continue
                    # Normalize values
                    norm_vals = []
                    for v in vals:
                        if v is None:
                            norm_vals.append("__BLANK__")
                        elif isinstance(v, datetime.datetime):
                            norm_vals.append(v.isoformat())
                        elif isinstance(v, datetime.date):
                            norm_vals.append(v.isoformat())
                        else:
                            norm_vals.append(v)
                    out_dynamic.append(
                        {
                            "scope": scope,
                            "target": target,
                            "keep": True,
                            "source": "slicer",
                            "slicer_id": did,
                            "column": {
                                "type": "ColumnRef",
                                "table": str(col.get("table") or ""),
                                "column": str(col.get("column") or ""),
                            },
                            "operator": "in",
                            "values": norm_vals,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"Slicer default failed: {exc}") from exc

        return list(out_static) + list(out_dynamic)

    return list(out_static)


def register_core_routes(app):
    from fastapi import Body, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    @app.get("/runtime/measures")
    def runtime_list_measures(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload={})
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measures = [_measure_to_json(m) for m in getattr(model_scoped, "measures", []) or []]
        measures.sort(key=lambda d: str(d.get("name", "")).upper())
        return _ok({"measures": measures})

    @app.get("/runtime/measures/{name}")
    def runtime_get_measure(name: str, request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload={})
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        m = next(
            (m for m in getattr(model_scoped, "measures", []) or [] if str(getattr(m, "name", "")).upper() == name.upper()),
            None,
        )
        if m is None:
            return _err(404, f"Measure not found: {name!r}")
        return _ok({"measure": _measure_to_json(m)})

    @app.post("/runtime/measures")
    def runtime_create_measure(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        name = str(payload.get("name") or "").strip()
        dax = str(payload.get("dax") or "").strip()
        description = payload.get("description")
        folder = payload.get("folder")
        fmt = payload.get("format")

        if not name:
            return _err(400, "name is required")
        try:
            _validate_safe_name(name, label="measure name")
        except ValueError as e:
            return _err(400, str(e))
        if not dax:
            return _err(400, "dax is required")

        try:
            model, _pages, _visuals = load_project(project_path)
            exists = any(str(getattr(m, "name", "")).upper() == name.upper() for m in getattr(model, "measures", []) or [])
            if exists:
                return _err(409, f"Measure already exists: {name!r}")

            update_measure_yaml(
                project_path,
                name=name,
                dax=dax,
                description=str(description) if isinstance(description, str) else None,
                folder=str(folder) if isinstance(folder, str) else None,
                format=str(fmt) if isinstance(fmt, str) else None,
            )
            _invalidate_engine_cache_for_project(project_path)
            model2, _pages2, _visuals2 = load_project(project_path)
            m2 = next((m for m in getattr(model2, "measures", []) or [] if str(getattr(m, "name", "")).upper() == name.upper()), None)
            if m2 is None:
                return _err(500, "Measure save failed: not found after reload")
            return _ok({"measure": _measure_to_json(m2)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/measures/{name}")
    def runtime_update_measure(name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        dax = payload.get("dax")
        description = payload.get("description")
        folder = payload.get("folder")
        fmt = payload.get("format")

        try:
            model, _pages, _visuals = load_project(project_path)
            current = next((m for m in getattr(model, "measures", []) or [] if str(getattr(m, "name", "")).upper() == name.upper()), None)
            if current is None:
                return _err(404, f"Measure not found: {name!r}")

            dax_out = str(dax) if isinstance(dax, str) else str(getattr(current, "dax", ""))
            if not dax_out.strip():
                return _err(400, "dax is required")

            update_measure_yaml(
                project_path,
                name=str(getattr(current, "name", name)),
                dax=dax_out,
                description=(str(description) if isinstance(description, str) else getattr(current, "description", None)),
                folder=(str(folder) if isinstance(folder, str) else getattr(current, "folder", None)),
                format=(str(fmt) if isinstance(fmt, str) else getattr(current, "format", None)),
            )
            _invalidate_engine_cache_for_project(project_path)
            model2, _pages2, _visuals2 = load_project(project_path)
            m2 = next((m for m in getattr(model2, "measures", []) or [] if str(getattr(m, "name", "")).upper() == name.upper()), None)
            if m2 is None:
                return _err(500, "Measure save failed: not found after reload")
            return _ok({"measure": _measure_to_json(m2)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/measures/{name}")
    def runtime_delete_measure(name: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            removed = delete_measure_yaml(project_path, name=name)
            if not removed:
                return _err(404, f"Measure not found: {name!r}")
            _invalidate_engine_cache_for_project(project_path)
            return _ok({"deleted": name})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.post("/runtime/dax/analyze")
    def runtime_dax_analyze(request: Request, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Analyze DAX measures: parse, compile to SQL, compute complexity, and suggest optimizations."""
        from dax_parser.ir_mapper import ast_to_ir
        from dax_parser.parser import parse_expression

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_names = payload.get("measures") or []
        if not isinstance(measure_names, list) or not measure_names:
            return _err(400, "measures must be a non-empty list of measure names")

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload={})
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        all_measures = {str(getattr(m, "name", "")).upper(): m for m in getattr(model_scoped, "measures", []) or []}
        results = []

        for mname in measure_names:
            mname_str = str(mname).strip()
            m = all_measures.get(mname_str.upper())
            if m is None:
                results.append({
                    "name": mname_str,
                    "dax": "",
                    "compiled_sql": None,
                    "complexity": {
                        "nesting_depth": 0,
                        "filter_contexts": 0,
                        "iterator_count": 0,
                        "measure_refs": [],
                        "tables_referenced": [],
                        "pattern": "unknown",
                    },
                    "sql_plan": None,
                    "suggestions": [],
                    "error": f"Measure not found: {mname_str!r}",
                })
                continue

            dax_text = str(getattr(m, "dax", ""))
            compiled_sql = None
            sql_plan = None
            error_msg = None
            complexity = {
                "nesting_depth": 0,
                "filter_contexts": 0,
                "iterator_count": 0,
                "measure_refs": [],
                "tables_referenced": [],
                "pattern": "simple_aggregation",
            }
            suggestions: list[str] = []

            try:
                # Parse DAX ΓåÆ AST ΓåÆ IR
                ir = ast_to_ir(parse_expression(dax_text))

                # Analyze IR complexity
                complexity = _analyze_ir_complexity(ir, model_scoped)

                # Compile to SQL
                _ensure_mapping_loaded()
                with _ENGINE_LOCK:
                    get_prepared_engine(project_path, model)
                    ctx = dax_compiler.Context()
                    if isinstance(ir, dax_compiler.DaxFunction):
                        spec = dax_compiler.registry.get(ir.fn.upper())
                        if spec is not None and spec.kind == "context":
                            compiled_sql = dax_compiler.compile_context_function(ir, ctx)
                        else:
                            compiled_sql = dax_compiler.compile_measure(ir, ctx)
                    else:
                        compiled_sql = dax_compiler.compile_measure(ir, ctx)

                # Try EXPLAIN
                try:
                    con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=None, model=model)
                    explain_rows = con.execute(f"EXPLAIN {dax_compiler.normalize_sql(compiled_sql)}").fetchall()
                    sql_plan = "\n".join(str(r[1]) if len(r) > 1 else str(r[0]) for r in explain_rows)
                except Exception:  # noqa: BLE001
                    pass  # EXPLAIN is optional

                # Generate suggestions
                suggestions = _generate_dax_suggestions(complexity, dax_text)

            except Exception as exc:  # noqa: BLE001
                error_msg = str(exc)

            results.append({
                "name": mname_str,
                "dax": dax_text,
                "compiled_sql": compiled_sql,
                "complexity": complexity,
                "sql_plan": sql_plan,
                "suggestions": suggestions,
                "error": error_msg,
            })

        return _ok({"measures": results})

    @app.get("/runtime/calculated_tables")
    def runtime_list_calculated_tables(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload={})
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        tables = [t for t in getattr(model_scoped, "tables", []) or [] if bool(getattr(t, "is_calculated", False))]
        out = [_table_to_json(t) for t in tables]
        out.sort(key=lambda d: str(d.get("name", "")).upper())
        return _ok({"tables": out})

    @app.get("/runtime/calculated_tables/{name}")
    def runtime_get_calculated_table(name: str, request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role = _resolve_security_for_request(model=model, request=request, payload={})
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        t = next(
            (
                t
                for t in getattr(model_scoped, "tables", []) or []
                if str(getattr(t, "name", "")).upper() == name.upper()
            ),
            None,
        )
        if t is None:
            return _err(404, f"Table not found: {name!r}")
        if not bool(getattr(t, "is_calculated", False)):
            return _err(409, f"Table is not calculated: {name!r}")
        return _ok({"table": _table_to_json(t)})

    @app.post("/runtime/calculated_tables/preview")
    def runtime_preview_calculated_table(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        expr_text = _coalesce_expr_payload(payload)
        if not isinstance(expr_text, str) or not expr_text.strip():
            return _err(400, "expression is required")

        limit = _coalesce_limit(payload, default=200)

        sql: Optional[str] = None
        try:
            _ensure_mapping_loaded()
            model, _pages, _visuals = load_project(project_path)

            _role_name, role = _resolve_security_for_request(model=model, request=request, payload=payload)
            model_scoped = apply_ols(model, role)

            from dax_parser.ir_mapper import ast_to_ir
            from dax_parser.parser import parse_expression
            from dax_engine.sql_utils import as_from_source

            ir = ast_to_ir(parse_expression(expr_text))

            # Enforce OLS by validating referenced objects against the role-scoped model.
            try:
                _validate_ir_objects_against_model_scoped(ir, model_scoped)
            except ValueError as exc:
                msg = str(exc)
                if "Unresolved field parameter" in msg:
                    raise ValueError(
                        f"Calculated table preview does not support unresolved field parameter: {msg.split(':', 1)[-1].strip()}"
                    ) from exc
                raise

            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=payload)
            with _ENGINE_LOCK:
                table_sql = dax_compiler.compile_table_expr(ir, sec_state.ctx)

            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)

            from_src = as_from_source(table_sql, "t")
            q = dax_compiler.normalize_sql(f"SELECT * FROM {from_src} LIMIT {limit}")
            cols_meta = _describe_columns_from_from_source(con, from_src)
            rows = con.execute(q).fetchall()
            col_names = [c.get("name", "") for c in cols_meta]
            return _ok({"sql": q, "columns": col_names, "rows": [_json_safe(list(r)) for r in rows], "row_count": len(rows)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql, details={"endpoint": "calculated_tables_preview", "project": project_path})

    @app.post("/runtime/calculated_tables")
    def runtime_create_calculated_table(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        name = str(payload.get("name") or "").strip()
        expr_text = _coalesce_expr_payload(payload)
        description = payload.get("description")
        folder = payload.get("folder")
        if not name:
            return _err(400, "name is required")
        try:
            _validate_safe_name(name, label="table name")
        except ValueError as e:
            return _err(400, str(e))
        if not isinstance(expr_text, str) or not expr_text.strip():
            return _err(400, "expression is required")

        sql: Optional[str] = None
        try:
            _ensure_mapping_loaded()
            model, _pages, _visuals = load_project(project_path)
            exists = any(str(getattr(t, "name", "")).upper() == name.upper() for t in getattr(model, "tables", []) or [])
            if exists:
                return _err(409, f"Table already exists: {name!r}")

            from dax_parser.ir_mapper import ast_to_ir
            from dax_parser.parser import parse_expression
            from dax_engine.sql_utils import as_from_source

            ir = ast_to_ir(parse_expression(expr_text))

            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=payload)

            # Enforce OLS by validating referenced objects against the role-scoped model.
            _validate_ir_objects_against_model_scoped(ir, sec_state.model_scoped)

            with _ENGINE_LOCK:
                sql = dax_compiler.compile_table_expr(ir, sec_state.ctx)

            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            from_src = as_from_source(sql, "t")
            cols = _describe_columns_from_from_source(con, from_src)

            upsert_table_yaml(
                project_path,
                name=name,
                columns=cols,
                source=None,
                expression=expr_text,
                is_calculated=True,
                description=str(description) if isinstance(description, str) and description.strip() else None,
                folder=str(folder) if isinstance(folder, str) and folder.strip() else None,
            )

            _invalidate_engine_cache_for_project(project_path)
            model2, _pages2, _visuals2 = load_project(project_path)
            t2 = next(
                (
                    t
                    for t in getattr(model2, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if t2 is None:
                return _err(400, "Table save failed: not found after reload")
            return _ok({"table": _table_to_json(t2), "sql": sql})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql, details={"endpoint": "calculated_tables_create", "project": project_path})

    @app.put("/runtime/calculated_tables/{name}")
    def runtime_update_calculated_table(
        name: str,
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        expr_text = _coalesce_expr_payload(payload)
        description = payload.get("description")
        folder = payload.get("folder")
        if not isinstance(expr_text, str) or not expr_text.strip():
            return _err(400, "expression is required")

        sql: Optional[str] = None
        try:
            _ensure_mapping_loaded()
            model, _pages, _visuals = load_project(project_path)
            current = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if current is None:
                return _err(404, f"Table not found: {name!r}")
            if not bool(getattr(current, "is_calculated", False)):
                return _err(409, f"Table is not calculated: {name!r}")

            from dax_parser.ir_mapper import ast_to_ir
            from dax_parser.parser import parse_expression
            from dax_engine.sql_utils import as_from_source

            ir = ast_to_ir(parse_expression(expr_text))

            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=payload)

            # Enforce OLS by validating referenced objects against the role-scoped model.
            _validate_ir_objects_against_model_scoped(ir, sec_state.model_scoped)

            with _ENGINE_LOCK:
                sql = dax_compiler.compile_table_expr(ir, sec_state.ctx)

            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            from_src = as_from_source(sql, "t")
            cols = _describe_columns_from_from_source(con, from_src)

            upsert_table_yaml(
                project_path,
                name=str(getattr(current, "name", name)),
                columns=cols,
                source=None,
                expression=expr_text,
                is_calculated=True,
                description=str(description) if isinstance(description, str) and description.strip() else None,
                folder=str(folder) if isinstance(folder, str) and folder.strip() else None,
            )
            _invalidate_engine_cache_for_project(project_path)
            model2, _pages2, _visuals2 = load_project(project_path)
            t2 = next(
                (
                    t
                    for t in getattr(model2, "tables", []) or []
                    if str(getattr(t, "name", "")).upper() == name.upper()
                ),
                None,
            )
            if t2 is None:
                return _err(400, "Table save failed: not found after reload")
            return _ok({"table": _table_to_json(t2), "sql": sql})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql, details={"endpoint": "calculated_tables_update", "project": project_path})

    @app.get("/runtime/tables/{table}/columns")

    def runtime_list_table_columns(request: Request, table: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
            _role_name, role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        t = next(
            (
                t
                for t in getattr(model_scoped, "tables", []) or []
                if str(getattr(t, "name", "")).upper() == table.upper()
            ),
            None,
        )
        if t is None:
            return _err(404, f"Table not found: {table!r}")

        cols = []
        for c in getattr(t, "columns", []) or []:
            cols.append(
                {
                    "name": str(getattr(c, "name", "")),
                    "type": str(getattr(c, "type", "")),
                    "expression": getattr(c, "expression", None),
                    "is_calculated": bool(getattr(c, "is_calculated", False)),
                    "description": getattr(c, "description", None),
                    "folder": getattr(c, "folder", None),
                }
            )
        cols.sort(key=lambda d: str(d.get("name", "")).upper())
        return _ok({"table": str(getattr(t, "name", table)), "columns": cols})

    def _validate_filter_items_against_model(model: Any, flat_filters: list[Mapping[str, Any]]) -> None:
        tables = {t.upper() for t in list_tables(model)}
        col_cache: dict[str, set[str]] = {}
        for i, f in enumerate(flat_filters):
            col_raw = f.get("column")
            if not isinstance(col_raw, Mapping):
                raise ValueError(f"filters[{i}].column must be an object")
            # Skip MeasureRef / HierarchyRef filters — they use 'name' not
            # 'column' and cannot be validated against the column model.
            col_type = str(col_raw.get("type") or "").strip()
            if col_type in ("MeasureRef", "HierarchyRef"):
                continue
            table = str(col_raw.get("table") or "").strip()
            column = str(col_raw.get("column") or "").strip()
            if not table or not column:
                raise ValueError(f"filters[{i}].column.table and filters[{i}].column.column are required")
            if table.upper() not in tables:
                raise ValueError(f"filters[{i}]: unknown table: {table!r}")
            if table.upper() not in col_cache:
                col_cache[table.upper()] = {c.upper() for c in list_columns(model, table)}
            if column.upper() not in col_cache[table.upper()]:
                raise ValueError(f"filters[{i}]: unknown column: {table}[{column}]")

    @app.get("/runtime/filters")
    def runtime_get_filters(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            payload = load_report_filters(project_path)

            # Flatten for UI convenience.
            flat: list[dict[str, Any]] = []
            for it in payload.get("report_filters") or []:
                if isinstance(it, Mapping):
                    flat.append(dict(it))
            for page_id, items in (payload.get("page_filters") or {}).items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, Mapping):
                        flat.append(dict(it))
            for vis_id, items in (payload.get("visual_filters") or {}).items():
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, Mapping):
                        flat.append(dict(it))

            _validate_filter_items_against_model(model, flat)
            return _ok({"filters": flat, **payload})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/filters")
    def runtime_put_filters(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)

            # Normalize incoming payload into JSON-safe values.
            safe = _json_safe_with_path(payload, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            # Validate ColumnRefs early (no silent fallbacks).
            flat_filters = safe.get("filters")
            flat_list: list[Mapping[str, Any]] = []
            if isinstance(flat_filters, list):
                for it in flat_filters:
                    if isinstance(it, Mapping):
                        flat_list.append(it)

            if flat_list:
                _validate_filter_items_against_model(model, flat_list)

            out = save_report_filters(project_path, safe)
            # Return with a convenience flat list too.
            flat: list[dict[str, Any]] = []
            for it in out.get("report_filters") or []:
                if isinstance(it, Mapping):
                    flat.append(dict(it))
            for _pid, items in (out.get("page_filters") or {}).items():
                for it in items or []:
                    if isinstance(it, Mapping):
                        flat.append(dict(it))
            for _vid, items in (out.get("visual_filters") or {}).items():
                for it in items or []:
                    if isinstance(it, Mapping):
                        flat.append(dict(it))

            return _ok({"filters": flat, **out})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))



    def _validate_calc_groups_yaml_payload(payload: Mapping[str, Any]) -> None:
        # Validate that each item expression parses as a scalar and includes SELECTEDMEASURE().
        from dax_engine.ir import ScalarExpr, SelectedMeasureRef
        from dax_parser.ir_mapper import ast_to_ir
        from dax_parser.parser import parse_expression

        groups = payload.get("calculation_groups")
        if groups is None:
            groups = {}
        if not isinstance(groups, Mapping):
            raise ValueError("calculation_groups must be a mapping")

        for g_name, g_spec in groups.items():
            if not isinstance(g_name, str) or not g_name.strip():
                raise ValueError("calculation_groups keys must be non-empty strings")
            if not isinstance(g_spec, Mapping):
                raise ValueError(f"calculation_groups[{g_name!r}] must be an object")

            precedence = g_spec.get("precedence", 0)
            if precedence is None:
                precedence = 0
            if not isinstance(precedence, int):
                raise ValueError(f"calculation_groups[{g_name!r}].precedence must be an int")

            items = g_spec.get("items")
            if items is None:
                items = []
            if not isinstance(items, list) or not items:
                raise ValueError(f"calculation_groups[{g_name!r}].items must be a non-empty list")

            seen: set[str] = set()
            for i, it in enumerate(items):
                if not isinstance(it, Mapping):
                    raise ValueError(f"calculation_groups[{g_name!r}].items[{i}] must be an object")
                nm = str(it.get("name") or "").strip()
                expr = str(it.get("expression") or "").strip()
                if not nm:
                    raise ValueError(f"calculation_groups[{g_name!r}].items[{i}].name is required")
                if nm.upper() in seen:
                    raise ValueError(f"calculation_groups[{g_name!r}] has duplicate item name: {nm!r}")
                seen.add(nm.upper())
                if not expr:
                    raise ValueError(f"calculation_groups[{g_name!r}].items[{i}].expression is required")

                ir = ast_to_ir(parse_expression(expr), allow_selected_measure=True)
                if not isinstance(ir, ScalarExpr):
                    raise ValueError(
                        f"calculation_groups[{g_name!r}].items[{i}].expression must be scalar; got {type(ir).__name__}"
                    )

                def _has_selected(e: Any) -> bool:
                    if isinstance(e, SelectedMeasureRef):
                        return True
                    if isinstance(e, Mapping):
                        return any(_has_selected(v) for v in e.values())
                    if isinstance(e, list):
                        return any(_has_selected(v) for v in e)
                    # IR nodes are dataclasses; walk by __dict__ when present.
                    d = getattr(e, "__dict__", None)
                    if isinstance(d, dict):
                        return any(_has_selected(v) for v in d.values())
                    return False

                if not _has_selected(ir):
                    raise ValueError(
                        f"calculation_groups[{g_name!r}].items[{i}] must reference SELECTEDMEASURE()"
                    )

    @app.get("/runtime/calculation_groups")
    def runtime_get_calculation_groups(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            raw = load_calculation_groups_yaml(project_path)
            return _ok({"calculation_groups": raw.get("calculation_groups", {})} if raw else {"calculation_groups": {}})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/calculation_groups")
    def runtime_put_calculation_groups(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            obj = safe.get("calculation_groups") if "calculation_groups" in safe else safe
            if not isinstance(obj, Mapping):
                raise ValueError("calculation_groups must be a mapping")
            canon_in = {"calculation_groups": dict(obj)}
            _validate_calc_groups_yaml_payload(canon_in)

            out = save_calculation_groups_yaml(project_path, canon_in)
            _invalidate_engine_cache_for_project(project_path)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/calc_group_selections")
    def runtime_get_calc_group_selections(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            payload = load_calc_group_selections(project_path)
            flat = flatten_calc_group_selections(payload)
            _validate_calc_group_selections_against_model(model, flat)
            return _ok({**payload, "selections": flat})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/calc_group_selections")
    def runtime_put_calc_group_selections(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            obj = safe.get("calc_group_selections") if "calc_group_selections" in safe else safe
            if not isinstance(obj, Mapping):
                raise ValueError("calc_group_selections must be an object")
            # Validate BEFORE saving (prevent invalid data on disk)
            pre_flat = flatten_calc_group_selections(dict(obj))
            _validate_calc_group_selections_against_model(model, pre_flat)
            out = save_calc_group_selections(project_path, obj)
            flat = flatten_calc_group_selections(out)
            return _ok({**out, "selections": flat})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))


    @app.get("/runtime/hierarchies")
    def runtime_get_hierarchies(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})
            return _ok({"hierarchies": _hierarchies_meta_from_model(model_scoped)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/hierarchies")
    def runtime_put_hierarchies(request: Request, project: Optional[str] = None, payload: Any = Body(default=None)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(
                model=model, request=request, payload=payload if isinstance(payload, Mapping) else {},
            )
            safe = _json_safe_with_path(payload, path="$", strict=True)
            if safe is None:
                safe = {}
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            hierarchies_raw = safe.get("hierarchies")
            if hierarchies_raw is None:
                hierarchies_raw = safe  # Allow flat payload shape too
            canon_in = {"hierarchies": hierarchies_raw}

            # Validate hierarchy names and that all referenced tables and columns exist BEFORE saving.
            h_items = (hierarchies_raw if isinstance(hierarchies_raw, Mapping) else {})
            for h_name, h_spec in (h_items.items() if isinstance(h_items, Mapping) else []):
                _validate_safe_name(h_name, label="hierarchy name")
                if not isinstance(h_spec, Mapping):
                    continue
                h_table = str(h_spec.get("table") or "").strip()
                known_tables = {str(getattr(t, "name", "")).upper() for t in getattr(model, "tables", []) or []}
                if h_table and h_table.upper() not in known_tables:
                    raise ValueError(f"unknown table {h_table!r} in hierarchy {h_name!r}")
                t_obj = next((t for t in getattr(model, "tables", []) or [] if str(getattr(t, "name", "")).upper() == h_table.upper()), None)
                if t_obj is not None:
                    known_cols = {str(getattr(c, "name", "")).upper() for c in getattr(t_obj, "columns", []) or []}
                    for lvl in (h_spec.get("levels") or []):
                        if isinstance(lvl, Mapping):
                            col_name = str(lvl.get("column") or "").strip()
                            if col_name and col_name.upper() not in known_cols:
                                raise ValueError(f"unknown column {col_name!r} in table {h_table!r} for hierarchy {h_name!r}")

            from dax_project.save import save_hierarchies_yaml
            save_hierarchies_yaml(project_path, canon_in)
            _invalidate_engine_cache_for_project(project_path)

            # Reload + re-scope to return OLS-safe result.
            model2, _pages2, _visuals2 = load_project(project_path)
            _role_name2, _role2, model_scoped2 = _resolve_role_and_scope_model(model=model2, request=request, payload={})
            return _ok({"hierarchies": _hierarchies_meta_from_model(model_scoped2)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))


    def _field_parameters_defs_from_model(model: Any) -> dict[str, Any]:
        """Return field parameters definitions (Power BI parity schema).
        
        Uses simplified schema: items with name/ref, no kind/allow_multi.
        """
        fps_map = getattr(model, "field_parameters", {}) or {}
        if not isinstance(fps_map, Mapping):
            raise ValueError("model.field_parameters must be a mapping")

        from dax_engine.ir import ColumnRef as _ColumnRef
        from dax_engine.ir import MeasureRef as _MeasureRef

        out: dict[str, Any] = {}
        for fp_name, fp in fps_map.items():
            name = str(getattr(fp, "name", fp_name) or "").strip()
            if not name:
                continue

            default_item = getattr(fp, "default_item", None)
            items_raw = list(getattr(fp, "items", []) or [])
            dax_text = getattr(fp, "dax", None)

            items_out: list[dict[str, Any]] = []
            for item in items_raw:
                item_name = str(getattr(item, "name", "") or "").strip()
                ref = getattr(item, "ref", None)
                sort_raw = getattr(item, "sort", None)
                custom_props = getattr(item, "custom_props", None)
                if not item_name:
                    continue

                ref_json: dict[str, Any]
                if isinstance(ref, _ColumnRef):
                    ref_json = {"type": "ColumnRef", "table": ref.table, "column": ref.column}
                elif isinstance(ref, _MeasureRef):
                    ref_json = {"type": "MeasureRef", "name": ref.name}
                else:
                    continue

                row: dict[str, Any] = {"name": item_name, "ref": ref_json}
                if isinstance(sort_raw, int):
                    row["sort"] = int(sort_raw)
                # Include custom properties
                if isinstance(custom_props, dict):
                    for k, v in custom_props.items():
                        if isinstance(v, str) and v.strip():
                            row[k] = v
                items_out.append(row)

            spec: dict[str, Any] = {
                "default_item": str(default_item) if isinstance(default_item, str) and str(default_item).strip() else (items_out[0]["name"] if items_out else ""),
                "items": items_out,
            }
            if isinstance(dax_text, str) and dax_text.strip():
                spec["dax"] = dax_text
            out[name] = spec

        return {k: out[k] for k in sorted(out.keys(), key=lambda s: str(s).upper())}

    def _validate_field_parameter_defs_against_model(model: Any, defs_obj: Mapping[str, Any]) -> None:
        """Validate field parameter definitions against model (Power BI parity schema)."""
        tables = {str(t).upper() for t in list_tables(model)}
        cols_by_table: dict[str, set[str]] = {}
        for t in tables:
            try:
                cols_by_table[t] = {str(c).upper() for c in list_columns(model, t)}
            except Exception:
                cols_by_table[t] = set()
        measures = {str(m).upper() for m in list_measures(model)}

        for fp_name, fp_spec in defs_obj.items():
            if not isinstance(fp_name, str) or not fp_name.strip():
                raise ValueError("field_parameters keys must be non-empty strings")
            if not isinstance(fp_spec, Mapping):
                raise ValueError(f"field_parameters[{fp_name!r}] must be an object")

            items = fp_spec.get("items")
            if items is None:
                items = []
            if not isinstance(items, list) or not items:
                raise ValueError(f"field_parameters[{fp_name!r}].items must be a non-empty list")

            seen_names: set[str] = set()

            for i, item in enumerate(items):
                if not isinstance(item, Mapping):
                    raise ValueError(f"field_parameters[{fp_name!r}].items[{i}] must be an object")
                item_name = str(item.get("name") or "").strip()
                if not item_name:
                    raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].name is required")
                if item_name.upper() in seen_names:
                    raise ValueError(f"field_parameters[{fp_name!r}] has duplicate item name: {item_name!r}")
                seen_names.add(item_name.upper())
                ref = item.get("ref")
                if not isinstance(ref, Mapping):
                    raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].ref must be an object")
                t = str(ref.get("type") or "").strip()
                if t == "MeasureRef":
                    nm = str(ref.get("name") or "").strip()
                    if not nm:
                        raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].ref.name is required")
                    if nm.upper() not in measures:
                        raise ValueError(f"Unknown measure in field parameter: {nm!r}")
                elif t == "ColumnRef":
                    tb = str(ref.get("table") or "").strip()
                    col = str(ref.get("column") or "").strip()
                    if not col:
                        raise ValueError(f"field_parameters[{fp_name!r}].items[{i}].ref.column is required")
                    # If table is missing, try to resolve from column name
                    if not tb:
                        matching_tables = [t_name for t_name, cols in cols_by_table.items() if col.upper() in cols]
                        if len(matching_tables) == 1:
                            tb = matching_tables[0]
                            # Inject the resolved table back into the ref for downstream use
                            ref["table"] = tb
                        elif len(matching_tables) > 1:
                            raise ValueError(f"Ambiguous column {col!r} exists in multiple tables: {matching_tables}")
                        else:
                            raise ValueError(f"Unknown column in field parameter: {col!r}")
                    else:
                        if tb.upper() not in tables:
                            raise ValueError(f"Unknown table in field parameter: {tb!r}")
                        if col.upper() not in cols_by_table.get(tb.upper(), set()):
                            raise ValueError(f"Unknown column in field parameter: {tb!r}[{col!r}]")
                else:
                    raise ValueError(
                        f"field_parameters[{fp_name!r}].items[{i}].ref.type must be ColumnRef or MeasureRef"
                    )

            default_item = str(fp_spec.get("default_item") or "").strip()
            if default_item and default_item.upper() not in seen_names:
                raise ValueError(f"field_parameters[{fp_name!r}].default_item {default_item!r} is not a valid item name")

    def _what_if_parameters_defs_from_model(model: Any) -> dict[str, Any]:
        """Return What-If parameters definitions (for saving)."""
        wips_map = getattr(model, "what_if_parameters", {}) or {}
        if not isinstance(wips_map, Mapping):
            raise ValueError("model.what_if_parameters must be a mapping")

        out: dict[str, Any] = {}
        for wip_name, wip in wips_map.items():
            name = str(getattr(wip, "name", wip_name) or "").strip()
            if not name:
                continue

            spec: dict[str, Any] = {
                "min": float(getattr(wip, "min_value", 0)),
                "max": float(getattr(wip, "max_value", 1)),
                "step": float(getattr(wip, "step", 0.1)),
                "default": float(getattr(wip, "default_value", 0)),
            }
            fmt = getattr(wip, "format", None)
            if isinstance(fmt, str) and fmt.strip():
                spec["format"] = fmt.strip()
            out[name] = spec

        return out


    @app.get("/runtime/field_parameters")
    def runtime_get_field_parameters(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})
            meta = _field_parameters_meta_from_model(model_scoped)
            defs = _field_parameters_defs_from_model(model_scoped)
            return _ok({"field_parameters": meta, "field_parameters_defs": defs})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/field_parameters")
    def runtime_put_field_parameters(request: Request, project: Optional[str] = None, payload: Any = Body(default=None)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)

            payload_for_role: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(
                model=model,
                request=request,
                payload=payload_for_role,
            )

            safe = _json_safe_with_path(payload, path="$", strict=True)
            if safe is None:
                safe = {}
            if not isinstance(safe, (Mapping, list)):
                raise ValueError("payload must be an object or list")

            obj: Any = safe
            if isinstance(safe, Mapping):
                obj = (
                    safe.get("field_parameters_defs")
                    if "field_parameters_defs" in safe
                    else safe.get("field_parameters")
                    if "field_parameters" in safe
                    else safe
                )

            defs_map: dict[str, Any] = {}
            if isinstance(obj, Mapping):
                defs_map = dict(obj)
            elif isinstance(obj, list):
                seen: set[str] = set()
                for i, it in enumerate(obj):
                    if not isinstance(it, Mapping):
                        raise ValueError(f"field_parameters[{i}] must be an object")
                    nm = str(it.get("name") or "").strip()
                    if not nm:
                        raise ValueError(f"field_parameters[{i}].name is required")
                    if nm.upper() in seen:
                        raise ValueError(f"Duplicate field parameter name: {nm!r}")
                    seen.add(nm.upper())
                    spec = dict(it)
                    spec.pop("name", None)
                    defs_map[nm] = spec
            else:
                raise ValueError("field_parameters must be an object or list")

            canon_in = {"field_parameters": defs_map}
            _validate_field_parameter_defs_against_model(model_scoped, canon_in["field_parameters"])

            save_field_parameters_yaml(project_path, canon_in)
            _invalidate_engine_cache_for_project(project_path)

            # Reload + re-scope to return OLS-safe defs/meta.
            model2, _pages2, _visuals2 = load_project(project_path)
            _role_name2, _role2, model_scoped2 = _resolve_role_and_scope_model(model=model2, request=request, payload={})
            meta = _field_parameters_meta_from_model(model_scoped2)
            defs = _field_parameters_defs_from_model(model_scoped2)
            return _ok({"field_parameters": meta, "field_parameters_defs": defs})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/field_parameter_selections")
    def runtime_get_field_parameter_selections(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})
            payload = load_field_parameter_selections(project_path)
            flat = flatten_field_parameter_selections(payload)
            _validate_field_parameter_selections_against_model(model_scoped, flat)
            return _ok({**payload, "selections": flat})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/field_parameter_selections")
    def runtime_put_field_parameter_selections(
        request: Request, project: Optional[str] = None, payload: dict = Body(default_factory=dict)
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload=payload)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            obj = safe.get("field_parameter_selections") if "field_parameter_selections" in safe else safe
            if not isinstance(obj, Mapping):
                raise ValueError("field_parameter_selections must be an object")
            # Validate BEFORE saving (prevent invalid data on disk)
            pre_flat = flatten_field_parameter_selections(dict(obj))
            _validate_field_parameter_selections_against_model(model_scoped, pre_flat)
            out = save_field_parameter_selections(project_path, obj)
            flat = flatten_field_parameter_selections(out)
            return _ok({**out, "selections": flat})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/what_if_parameters")
    def runtime_get_what_if_parameters(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})
            meta = _what_if_parameters_meta_from_model(model_scoped)
            defs = _what_if_parameters_defs_from_model(model_scoped)
            return _ok({"what_if_parameters": meta, "what_if_parameters_defs": defs})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/what_if_parameters")
    def runtime_put_what_if_parameters(request: Request, project: Optional[str] = None, payload: Any = Body(default=None)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})

            safe = _json_safe_with_path(payload, path="$", strict=True)
            if safe is None:
                safe = {}
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            obj = safe.get("what_if_parameters_defs") if "what_if_parameters_defs" in safe else safe.get("what_if_parameters") if "what_if_parameters" in safe else safe

            if not isinstance(obj, Mapping):
                raise ValueError("what_if_parameters must be an object")

            from dax_project.save import save_what_if_parameters_yaml
            canon_in = {"what_if_parameters": dict(obj)}
            save_what_if_parameters_yaml(project_path, canon_in)
            _invalidate_engine_cache_for_project(project_path)

            # Reload to return saved defs.
            model2, _pages2, _visuals2 = load_project(project_path)
            _role_name2, _role2, model_scoped2 = _resolve_role_and_scope_model(model=model2, request=request, payload={})
            meta = _what_if_parameters_meta_from_model(model_scoped2)
            defs = _what_if_parameters_defs_from_model(model_scoped2)
            return _ok({"what_if_parameters": meta, "what_if_parameters_defs": defs})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/what_if_selections")
    def runtime_get_what_if_selections(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload={})
            payload = load_what_if_selections(project_path)
            flat = flatten_what_if_selections(payload)
            _validate_what_if_selections_against_model(model_scoped, flat)
            return _ok({**payload, "selections": flat})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/what_if_selections")
    def runtime_put_what_if_selections(
        request: Request, project: Optional[str] = None, payload: dict = Body(default_factory=dict)
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, _pages, _visuals = load_project(project_path)
            _role_name, _role, model_scoped = _resolve_role_and_scope_model(model=model, request=request, payload=payload)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            obj = safe.get("what_if_selections") if "what_if_selections" in safe else safe
            if not isinstance(obj, Mapping):
                raise ValueError("what_if_selections must be an object")
            # Validate BEFORE saving (prevent invalid data on disk)
            pre_flat = flatten_what_if_selections(dict(obj))
            _validate_what_if_selections_against_model(model_scoped, pre_flat)
            out = save_what_if_selections(project_path, obj)
            flat = flatten_what_if_selections(out)
            return _ok({**out, "selections": flat})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))


    def _normalize_slicer_instances_payload(obj: Any) -> dict[str, Any]:
        if obj is None:
            return {"instances": []}
        if isinstance(obj, list):
            inst_list = obj
            out: list[Any] = []
            for it in inst_list:
                if isinstance(it, Mapping):
                    d = dict(it)
                    if not str(d.get("def_id") or "").strip() and str(d.get("slicer_def_id") or "").strip():
                        d["def_id"] = str(d.get("slicer_def_id") or "").strip()
                    out.append(d)
                else:
                    out.append(it)
            return {"instances": out}
        if isinstance(obj, Mapping):
            inst = obj.get("instances")
            if inst is None:
                inst = []
            if not isinstance(inst, list):
                raise ValueError("slicer_instances.instances must be a list")
            out: list[Any] = []
            for it in inst:
                if isinstance(it, Mapping):
                    d = dict(it)
                    if not str(d.get("def_id") or "").strip() and str(d.get("slicer_def_id") or "").strip():
                        d["def_id"] = str(d.get("slicer_def_id") or "").strip()
                    out.append(d)
                else:
                    out.append(it)
            return {"instances": out}
        raise ValueError("slicer_instances must be an object or a list")

    def _validate_slicer_defs_against_model(model: Any, defs_obj: Mapping[str, Any], *, pages: list[Any], lenient: bool = False) -> None:
        """Validate slicer definitions against the semantic model.

        When *lenient* is True (used for read/render paths), slicers that
        reference unknown tables or columns are silently removed from
        ``defs_obj["defs"]`` with a log warning instead of raising.
        All other validation errors still raise.
        """
        defs = defs_obj.get("defs")
        if defs is None:
            return
        if not isinstance(defs, list):
            raise ValueError("slicer_defs.defs must be a list")

        physical_tables = {t.upper() for t in list_tables(model)}
        # Build virtual table lookup
        virtual_tables = _build_virtual_tables(model)
        virtual_table_lookup = {vt["name"].upper(): vt for vt in virtual_tables}
        all_tables = physical_tables | set(virtual_table_lookup.keys())
        col_cache: dict[str, set[str]] = {}
        col_type_cache: dict[tuple[str, str], str] = {}
        page_ids = {str(getattr(p, "id", "")).strip().upper() for p in (pages or []) if str(getattr(p, "id", "")).strip()}

        def _column_type(table: str, column: str) -> str:
            key = (table.upper(), column.upper())
            if key in col_type_cache:
                return col_type_cache[key]
            t_obj = next(
                (
                    t
                    for t in getattr(model, "tables", []) or []
                    if str(getattr(t, "name", "") or "").strip().upper() == table.upper()
                ),
                None,
            )
            if t_obj is None:
                col_type_cache[key] = ""
                return ""
            c_obj = next(
                (
                    c
                    for c in getattr(t_obj, "columns", []) or []
                    if str(getattr(c, "name", "") or "").strip().upper() == column.upper()
                ),
                None,
            )
            ctype = str(getattr(c_obj, "type", "") or "").strip() if c_obj is not None else ""
            col_type_cache[key] = ctype
            return ctype

        def _is_date_like(ctype: str) -> bool:
            t = str(ctype or "").strip().upper()
            return t in {"DATE", "DATETIME", "TIMESTAMP", "TIMESTAMP_TZ", "TIMESTAMPTZ"}

        def _is_iso_date(s: Any) -> bool:
            if s is None:
                return True
            if not isinstance(s, str):
                return False
            txt = s.strip()
            if txt == "":
                return True
            if len(txt) != 10:
                return False
            # YYYY-MM-DD
            if txt[4] != "-" or txt[7] != "-":
                return False
            y, m, d = txt[:4], txt[5:7], txt[8:10]
            return y.isdigit() and m.isdigit() and d.isdigit()

        def _is_iso_datetime(s: Any) -> bool:
            if s is None:
                return True
            if not isinstance(s, str):
                return False
            txt = s.strip()
            if txt == "":
                return True
            try:
                datetime.datetime.fromisoformat(txt.replace("Z", "+00:00"))
            except ValueError:
                return False
            return True

        seen: set[str] = set()
        to_remove: list[int] = []  # indices to remove in lenient mode
        for i, d in enumerate(defs):
            if not isinstance(d, Mapping):
                raise ValueError(f"slicer_defs.defs[{i}] must be an object")

            ui_raw = d.get("ui")
            if ui_raw is not None:
                if not isinstance(ui_raw, Mapping):
                    raise ValueError(f"slicer_defs.defs[{i}].ui must be an object")
                if "multi" in ui_raw and not isinstance(ui_raw.get("multi"), bool):
                    raise ValueError(f"slicer_defs.defs[{i}].ui.multi must be a boolean")
                if "search" in ui_raw and not isinstance(ui_raw.get("search"), bool):
                    raise ValueError(f"slicer_defs.defs[{i}].ui.search must be a boolean")
            # Back-compat: legacy top-level keys.
            if "multi" in d and d.get("multi") is not None and not isinstance(d.get("multi"), bool):
                raise ValueError(f"slicer_defs.defs[{i}].multi must be a boolean")
            if "search" in d and d.get("search") is not None and not isinstance(d.get("search"), bool):
                raise ValueError(f"slicer_defs.defs[{i}].search must be a boolean")
            sid = str(d.get("id") or "").strip()
            if not sid:
                raise ValueError(f"slicer_defs.defs[{i}].id is required")
            if sid.upper() in seen:
                raise ValueError(f"Duplicate slicer_def.id: {sid!r}")
            seen.add(sid.upper())

            name = str(d.get("name") or "").strip()
            if not name:
                raise ValueError(f"slicer_defs.defs[{i}].name is required")

            scope = str(d.get("scope") or "report").strip().lower()
            if scope not in {"report", "page"}:
                raise ValueError(f"slicer_defs.defs[{i}].scope must be 'report' or 'page'")
            target = d.get("target")
            if scope == "page":
                if not isinstance(target, str) or not target.strip():
                    raise ValueError(f"slicer_defs.defs[{i}].target is required when scope=='page'")
                if page_ids and target.strip().upper() not in page_ids:
                    if lenient:
                        logger.warning("slicer_defs[%d] (%s): unknown page_id %r — skipping (lenient)", i, sid, target.strip())
                        to_remove.append(i)
                        continue
                    raise ValueError(f"slicer_defs.defs[{i}]: unknown page_id: {target.strip()!r}")

            s_type = str(d.get("type") or "list").strip().lower()
            if s_type not in {"list", "dropdown", "date_range", "button", "tile", "input", "relative_date", "relative_time"}:
                raise ValueError(
                    f"slicer_defs.defs[{i}].type must be one of: list, dropdown, date_range, button, tile, input, relative_date, relative_time"
                )
            input_mode = "filter"
            if isinstance(ui_raw, Mapping):
                input_mode = str(ui_raw.get("input_mode") or "filter").strip().lower()
            if input_mode not in {"filter", "input"}:
                raise ValueError(f"slicer_defs.defs[{i}].ui.input_mode must be 'filter' or 'input'")
            pure_input = s_type == "input" and input_mode == "input"

            col_raw = d.get("column")
            if col_raw is None and pure_input:
                col_raw = {"type": "InputRef", "table": "", "column": ""}
                d["column"] = col_raw
            if not isinstance(col_raw, Mapping):
                raise ValueError(f"slicer_defs.defs[{i}].column must be an object")
            table = str(col_raw.get("table") or "").strip()
            column = str(col_raw.get("column") or "").strip()
            if not pure_input and (not table or not column):
                raise ValueError(f"slicer_defs.defs[{i}].column.table and slicer_defs.defs[{i}].column.column are required")
            if not pure_input and table.upper() not in all_tables:
                if lenient:
                    logger.warning("slicer_defs[%d] (%s): unknown table %r — skipping (lenient)", i, sid, table)
                    to_remove.append(i)
                    continue
                raise ValueError(f"slicer_defs.defs[{i}]: unknown table: {table!r}")
            # Cache columns for physical vs virtual tables
            if not pure_input and table.upper() not in col_cache:
                if table.upper() in virtual_table_lookup:
                    vt = virtual_table_lookup[table.upper()]
                    col_cache[table.upper()] = {c.upper() for c in vt["columns"]}
                else:
                    col_cache[table.upper()] = {c.upper() for c in list_columns(model, table)}
            if not pure_input and column.upper() not in col_cache[table.upper()]:
                if lenient:
                    logger.warning("slicer_defs[%d] (%s): unknown column %s[%s] — skipping (lenient)", i, sid, table, column)
                    to_remove.append(i)
                    continue
                raise ValueError(f"slicer_defs.defs[{i}]: unknown column: {table}[{column}]")

            s_type = str(d.get("type") or "list").strip().lower()
            if s_type not in {"list", "dropdown", "date_range", "button", "tile", "input", "relative_date", "relative_time"}:
                raise ValueError(
                    f"slicer_defs.defs[{i}].type must be one of: list, dropdown, date_range, button, tile, input, relative_date, relative_time"
                )

            if s_type in {"date_range", "relative_date", "relative_time"}:
                ctype = _column_type(table, column)
                if not _is_date_like(ctype):
                    # Auto-downgrade: column is not a native date type but the
                    # slicer was imported as date_range (common PBI transfer
                    # scenario where dates are stored as VARCHAR).  Silently
                    # treat it as 'list' so it doesn't block all other slicers.
                    logger.warning(
                        "slicer_defs[%d]: date_range slicer on non-date column %s[%s] (type=%r) — auto-downgrading to list",
                        i, table, column, ctype,
                    )
                    d["type"] = "list"
                    s_type = "list"

            sel = d.get("selection")
            if sel is not None:
                if not isinstance(sel, Mapping):
                    raise ValueError(f"slicer_defs.defs[{i}].selection must be an object")
                mode = str(sel.get("mode") or "all").strip().lower()
                if s_type in {"date_range", "relative_date", "relative_time"}:
                    if mode not in {"all", "range", "relative"}:
                        raise ValueError(f"slicer_defs.defs[{i}].selection.mode must be 'all', 'range', or 'relative'")
                    if mode == "relative" and s_type not in {"relative_date", "relative_time"}:
                        raise ValueError(f"slicer_defs.defs[{i}].selection.mode must be 'all' or 'range'")
                    if mode != "relative":
                        start = sel.get("start")
                        end = sel.get("end")
                        valid_start = _is_iso_datetime(start) if s_type == "relative_time" else _is_iso_date(start)
                        valid_end = _is_iso_datetime(end) if s_type == "relative_time" else _is_iso_date(end)
                        if not valid_start or not valid_end:
                            expected = "an ISO datetime or empty" if s_type == "relative_time" else "YYYY-MM-DD or empty"
                            raise ValueError(f"slicer_defs.defs[{i}].selection.start/end must be {expected}")
                        start_s = str(start).strip() if isinstance(start, str) and start.strip() else None
                        end_s = str(end).strip() if isinstance(end, str) and end.strip() else None
                        if start_s is not None and end_s is not None and start_s > end_s:
                            raise ValueError(f"slicer_defs.defs[{i}].selection.start must be <= selection.end")
                else:
                    if mode not in {"all", "values", "selected"}:
                        raise ValueError(f"slicer_defs.defs[{i}].selection.mode must be 'all' or 'values'")

            defaults_raw = d.get("defaults")
            if defaults_raw is not None:
                if not isinstance(defaults_raw, Mapping):
                    raise ValueError(f"slicer_defs.defs[{i}].defaults must be an object")
                defaults_mode = str(defaults_raw.get("mode") or "none").strip().lower()
                if defaults_mode not in {"none", "measure", "measure_set"}:
                    raise ValueError(f"slicer_defs.defs[{i}].defaults.mode must be 'none', 'measure', or 'measure_set'")
                aol = defaults_raw.get("apply_on_load")
                if aol is not None and not isinstance(aol, bool):
                    raise ValueError(f"slicer_defs.defs[{i}].defaults.apply_on_load must be a boolean")

                if defaults_mode == "measure":
                    if s_type in {"date_range", "relative_date", "relative_time"}:
                        dr = defaults_raw.get("date_range")
                        if dr is None:
                            dr = {}
                        if not isinstance(dr, Mapping):
                            raise ValueError(f"slicer_defs.defs[{i}].defaults.date_range must be an object")
                        sm = dr.get("start_measure")
                        em = dr.get("end_measure")
                        if sm is None and em is None:
                            raise ValueError(
                                f"slicer_defs.defs[{i}].defaults.date_range.start_measure or end_measure is required"
                            )

                        def _validate_meas_obj(raw: Any, *, path: str) -> None:
                            if not isinstance(raw, Mapping):
                                raise ValueError(f"{path} must be a MeasureRef")
                            if str(raw.get("type") or "").strip() != "MeasureRef":
                                raise ValueError(f"{path} must be a MeasureRef")
                            nm = str(raw.get("name") or "").strip()
                            if not nm:
                                raise ValueError(f"{path}.name is required")
                            _validate_measureref_in_model(model, nm)

                        if sm is not None:
                            _validate_meas_obj(sm, path=f"slicer_defs.defs[{i}].defaults.date_range.start_measure")
                        if em is not None:
                            _validate_meas_obj(em, path=f"slicer_defs.defs[{i}].defaults.date_range.end_measure")
                    else:
                        m = defaults_raw.get("measure")
                        if not isinstance(m, Mapping):
                            raise ValueError(f"slicer_defs.defs[{i}].defaults.measure must be a MeasureRef")
                        if str(m.get("type") or "").strip() != "MeasureRef":
                            raise ValueError(f"slicer_defs.defs[{i}].defaults.measure must be a MeasureRef")
                        nm = str(m.get("name") or "").strip()
                        if not nm:
                            raise ValueError(f"slicer_defs.defs[{i}].defaults.measure.name is required")
                        _validate_measureref_in_model(model, nm)
                elif defaults_mode == "measure_set":
                    if s_type in {"date_range", "relative_date", "relative_time"}:
                        raise ValueError(f"slicer_defs.defs[{i}].defaults.mode 'measure_set' not supported for date_range slicers")
                    m = defaults_raw.get("measure")
                    if not isinstance(m, Mapping):
                        raise ValueError(f"slicer_defs.defs[{i}].defaults.measure must be a MeasureRef")
                    if str(m.get("type") or "").strip() != "MeasureRef":
                        raise ValueError(f"slicer_defs.defs[{i}].defaults.measure must be a MeasureRef")
                    nm = str(m.get("name") or "").strip()
                    if not nm:
                        raise ValueError(f"slicer_defs.defs[{i}].defaults.measure.name is required")
                    _validate_measureref_in_model(model, nm)

        # Remove invalid slicers in lenient mode (reverse order to preserve indices)
        if lenient and to_remove:
            for idx in reversed(to_remove):
                defs.pop(idx)

    def _validate_slicer_instances_against_defs(inst_obj: Mapping[str, Any], defs_obj: Mapping[str, Any]) -> None:
        inst = inst_obj.get("instances")
        if inst is None:
            return
        if not isinstance(inst, list):
            raise ValueError("slicer_instances.instances must be a list")
        defs = defs_obj.get("defs")
        def_ids = {
            str(d.get("id") or "").strip().upper()
            for d in (defs or [])
            if isinstance(d, Mapping) and str(d.get("id") or "").strip()
        }
        seen: set[str] = set()
        for i, s in enumerate(inst):
            if not isinstance(s, Mapping):
                raise ValueError(f"slicer_instances.instances[{i}] must be an object")
            sid = str(s.get("id") or "").strip()
            if not sid:
                raise ValueError(f"slicer_instances.instances[{i}].id is required")
            if sid.upper() in seen:
                raise ValueError(f"Duplicate slicer_instance.id: {sid!r}")
            seen.add(sid.upper())
            def_id = str(s.get("def_id") or "").strip()
            if not def_id:
                raise ValueError(f"slicer_instances.instances[{i}].def_id is required")
            if def_id.upper() not in def_ids:
                raise ValueError(f"slicer_instances.instances[{i}].def_id not found in defs: {def_id!r}")

            page_id_raw = s.get("page_id")
            if page_id_raw is not None and not (isinstance(page_id_raw, str) and page_id_raw.strip()):
                raise ValueError(f"slicer_instances.instances[{i}].page_id must be a non-empty string")

            container_raw = s.get("container")
            if container_raw is not None:
                container = str(container_raw).strip() if isinstance(container_raw, str) else ""
                if container not in {"canvas"}:
                    raise ValueError(f"slicer_instances.instances[{i}].container must be 'canvas'")

            layout_raw = s.get("layout")
            if layout_raw is not None:
                if not isinstance(layout_raw, Mapping):
                    raise ValueError(f"slicer_instances.instances[{i}].layout must be an object")
                for k in ("x", "y", "w", "h"):
                    v = layout_raw.get(k)
                    if isinstance(v, bool) or v is None or not isinstance(v, (int, float)):
                        raise ValueError(f"slicer_instances.instances[{i}].layout.{k} must be a number")

    @app.get("/runtime/slicers")
    def runtime_get_slicers(project: Optional[str] = None):
        """Return all slicers in unified format (merged def + per-page placement)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            result = load_slicers(project_path)
            return _ok(result)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SAVE_FAILED")

    @app.put("/runtime/slicers")
    def runtime_put_slicers(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Bulk-replace all slicers (unified format)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            slicers_data = safe.get("slicers") if "slicers" in safe else safe.get("defs")
            if slicers_data is None:
                slicers_data = []
            out = save_slicers(project_path, {"slicers": slicers_data if isinstance(slicers_data, list) else []})
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SAVE_FAILED")

    @app.post("/runtime/slicers/create")
    def runtime_create_slicer(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Create a single slicer (unified format)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            item = safe.get("slicer") if isinstance(safe.get("slicer"), Mapping) else safe
            if not isinstance(item, Mapping):
                raise ValueError("slicer must be an object")

            # Validate slicer title/name if provided
            for _label_field in ("title", "name"):
                _val = str(item.get(_label_field) or "").strip()
                if _val:
                    _validate_safe_name(_val, label=f"slicer {_label_field}")

            # Validate table/column reference against model
            col_ref = item.get("column")
            if isinstance(col_ref, Mapping):
                s_table = str(col_ref.get("table") or "").strip()
                s_column = str(col_ref.get("column") or "").strip()
                if s_table or s_column:
                    model, _pages, _visuals = load_project(project_path)
                    known_tables = {str(getattr(t, "name", "")).upper() for t in getattr(model, "tables", []) or []}
                    if s_table and s_table.upper() not in known_tables:
                        raise ValueError(f"unknown table: {s_table!r}")

            current = load_slicers(project_path)
            slicers = list(current.get("slicers") or [])

            d = dict(item)
            if not str(d.get("id") or "").strip():
                d["id"] = f"sd_{uuid.uuid4().hex}"
            slicers.append(d)
            out = save_slicers(project_path, {"slicers": slicers})
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SAVE_FAILED")

    @app.put("/runtime/slicers/{slicer_id}")
    def runtime_update_slicer(slicer_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Update a single slicer (unified format)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            current = load_slicers(project_path)
            slicers = list(current.get("slicers") or [])
            key = str(slicer_id or "").strip().upper()
            if not key:
                raise ValueError("slicer_id is required")
            found = False
            for i, s in enumerate(slicers):
                if not isinstance(s, Mapping):
                    continue
                if str(s.get("id") or "").strip().upper() == key:
                    item = safe.get("slicer") if isinstance(safe.get("slicer"), Mapping) else safe
                    if not isinstance(item, Mapping):
                        raise ValueError("slicer must be an object")
                    merged = dict(s)
                    merged.update(dict(item))
                    merged["id"] = str(slicer_id).strip()
                    slicers[i] = merged
                    found = True
                    break
            if not found:
                return _err(404, f"Slicer not found: {slicer_id!r}")
            out = save_slicers(project_path, {"slicers": slicers})
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SAVE_FAILED")

    @app.delete("/runtime/slicers/{slicer_id}")
    def runtime_delete_slicer(slicer_id: str, project: Optional[str] = None):
        """Delete a single slicer."""
        try:
            project_path = _resolve_project_path_runtime(project)
            current = load_slicers(project_path)
            key = str(slicer_id or "").strip().upper()
            if not key:
                raise ValueError("slicer_id is required")
            slicers = [s for s in (current.get("slicers") or []) if not (isinstance(s, Mapping) and str(s.get("id") or "").strip().upper() == key)]
            out = save_slicers(project_path, {"slicers": slicers})
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SAVE_FAILED")

    @app.get("/runtime/slicers/defs")
    def runtime_get_slicer_defs(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, pages, _visuals = load_project(project_path)
            defs = load_slicer_defs(project_path)
            # Validate but don't fail the entire listing — skip invalid slicers.
            try:
                _validate_slicer_defs_against_model(model, defs, pages=list(pages or []), lenient=True)
            except Exception as val_exc:  # noqa: BLE001
                defs.setdefault("warnings", [])
                defs["warnings"].append(str(val_exc))
            return _ok(defs)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code=_slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED"))

    @app.put("/runtime/slicers/defs")
    def runtime_put_slicer_defs(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, pages, _visuals = load_project(project_path)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            defs_obj = _normalize_slicer_defs_payload(safe.get("slicer_defs") if "slicer_defs" in safe else safe)
            _validate_slicer_defs_against_model(model, defs_obj, pages=list(pages or []))
            out = save_slicer_defs(project_path, defs_obj)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.post("/runtime/slicers/defs")
    def runtime_create_slicer_def(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, pages, _visuals = load_project(project_path)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            current = load_slicer_defs(project_path)
            defs = list(current.get("defs") or [])

            item = safe.get("def") if isinstance(safe.get("def"), Mapping) else safe
            if not isinstance(item, Mapping):
                raise ValueError("def must be an object")
            d = dict(item)
            if not str(d.get("id") or "").strip():
                d["id"] = f"sd_{uuid.uuid4().hex}"
            defs.append(d)
            defs_obj = {"defs": defs}
            _validate_slicer_defs_against_model(model, defs_obj, pages=list(pages or []))
            out = save_slicer_defs(project_path, defs_obj)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.put("/runtime/slicers/defs/{def_id}")
    def runtime_update_slicer_def(def_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, pages, _visuals = load_project(project_path)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            current = load_slicer_defs(project_path)
            defs = list(current.get("defs") or [])
            key = str(def_id or "").strip().upper()
            if not key:
                raise ValueError("def_id is required")
            found = False
            for i, d in enumerate(defs):
                if not isinstance(d, Mapping):
                    continue
                if str(d.get("id") or "").strip().upper() == key:
                    item = safe.get("def") if isinstance(safe.get("def"), Mapping) else safe
                    if not isinstance(item, Mapping):
                        raise ValueError("def must be an object")
                    merged = dict(d)
                    merged.update(dict(item))
                    merged["id"] = str(def_id).strip()
                    defs[i] = merged
                    found = True
                    break
            if not found:
                return _err(404, f"Slicer def not found: {def_id!r}")
            defs_obj = {"defs": defs}
            _validate_slicer_defs_against_model(model, defs_obj, pages=list(pages or []))
            out = save_slicer_defs(project_path, defs_obj)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.delete("/runtime/slicers/defs/{def_id}")
    def runtime_delete_slicer_def(def_id: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            current = load_slicer_defs(project_path)
            inst = load_slicer_instances(project_path)
            key = str(def_id or "").strip().upper()
            if not key:
                raise ValueError("def_id is required")
            for s in inst.get("instances") or []:
                if isinstance(s, Mapping) and str(s.get("def_id") or "").strip().upper() == key:
                    raise ValueError(f"Cannot delete slicer def {def_id!r}: instances still reference it")

            defs = [d for d in (current.get("defs") or []) if not (isinstance(d, Mapping) and str(d.get("id") or "").strip().upper() == key)]
            out = save_slicer_defs(project_path, {"defs": defs})
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.get("/runtime/slicers/instances")
    def runtime_get_slicer_instances(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            defs = load_slicer_defs(project_path)
            inst = load_slicer_instances(project_path)
            _validate_slicer_instances_against_defs(inst, defs)
            return _ok(inst)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code=_slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED"))

    @app.put("/runtime/slicers/instances")
    def runtime_put_slicer_instances(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            defs = load_slicer_defs(project_path)
            inst_obj = _normalize_slicer_instances_payload(safe.get("slicer_instances") if "slicer_instances" in safe else safe)
            _validate_slicer_instances_against_defs(inst_obj, defs)
            out = save_slicer_instances(project_path, inst_obj)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.post("/runtime/slicers/instances")
    def runtime_create_slicer_instance(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            defs = load_slicer_defs(project_path)
            current = load_slicer_instances(project_path)
            inst = list(current.get("instances") or [])

            item = safe.get("instance") if isinstance(safe.get("instance"), Mapping) else safe
            if not isinstance(item, Mapping):
                raise ValueError("instance must be an object")
            d = dict(item)
            if not str(d.get("id") or "").strip():
                d["id"] = f"si_{uuid.uuid4().hex}"
            inst.append(d)
            inst_obj = {"instances": inst}
            _validate_slicer_instances_against_defs(inst_obj, defs)
            out = save_slicer_instances(project_path, inst_obj)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.put("/runtime/slicers/instances/{instance_id}")
    def runtime_update_slicer_instance(instance_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
            defs = load_slicer_defs(project_path)
            current = load_slicer_instances(project_path)
            inst = list(current.get("instances") or [])
            key = str(instance_id or "").strip().upper()
            if not key:
                raise ValueError("instance_id is required")
            found = False
            for i, s in enumerate(inst):
                if not isinstance(s, Mapping):
                    continue
                if str(s.get("id") or "").strip().upper() == key:
                    item = safe.get("instance") if isinstance(safe.get("instance"), Mapping) else safe
                    if not isinstance(item, Mapping):
                        raise ValueError("instance must be an object")
                    merged = dict(s)
                    merged.update(dict(item))
                    merged["id"] = str(instance_id).strip()
                    inst[i] = merged
                    found = True
                    break
            if not found:
                return _err(404, f"Slicer instance not found: {instance_id!r}")
            inst_obj = {"instances": inst}
            _validate_slicer_instances_against_defs(inst_obj, defs)
            out = save_slicer_instances(project_path, inst_obj)
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.delete("/runtime/slicers/instances/{instance_id}")
    def runtime_delete_slicer_instance(instance_id: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            current = load_slicer_instances(project_path)
            key = str(instance_id or "").strip().upper()
            if not key:
                raise ValueError("instance_id is required")
            inst = [s for s in (current.get("instances") or []) if not (isinstance(s, Mapping) and str(s.get("id") or "").strip().upper() == key)]
            out = save_slicer_instances(project_path, {"instances": inst})
            return _ok(out)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_SAVE_FAILED")
            return _err(400, str(exc), error_code=code)

    @app.post("/runtime/slicers/values")
    def runtime_slicer_values(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Return distinct values for a slicer, using current filter context.

        Payload:
          {
            def_id: string,
            exclude_def_id?: string,  # exclude-self semantics
            page_id?: string,
            q?: string,
            limit?: int,
            offset?: int,
            filters?: [...],
            slicer_defs?: {defs:[...] } | [...],  # optional override (unsaved state)
          }
        """

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        def_id = str(safe.get("def_id") or "").strip()
        if not def_id:
            return _err(400, "def_id is required", error_code="E_SLICER_VALIDATION_FAILED")

        exclude_def_id = str(safe.get("exclude_def_id") or "").strip()
        if not exclude_def_id:
            exclude_def_id = str(safe.get("exclude_slicer_id") or "").strip()
        if not exclude_def_id:
            exclude_def_id = def_id
        page_id = safe.get("page_id")
        if page_id is not None:
            if not isinstance(page_id, str) or not page_id.strip():
                return _err(400, "page_id must be a non-empty string if provided")
            page_id = page_id.strip()

        q = safe.get("q")
        qv = str(q).strip() if q is not None and str(q).strip() else None
        try:
            lim = int(safe.get("limit") or 200)
        except Exception:
            lim = 200
        lim = 200 if lim <= 0 else min(lim, 2000)

        try:
            off = int(safe.get("offset") or 0)
        except Exception:
            off = 0
        off = 0 if off < 0 else off

        try:
            model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_VALUES_FAILED")

        # Security scope: values must respect OLS/RLS.
        try:
            sec_state = _build_runtime_security_state(project_path=project_path, model=model, request=request, payload=safe)
            model_scoped = sec_state.model_scoped
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_VALUES_FAILED")

        # Resolve defs: payload override (unsaved) or persisted.
        try:
            defs_obj = _normalize_slicer_defs_payload(safe.get("slicer_defs") if "slicer_defs" in safe else None)
            if not (defs_obj.get("defs") or []):
                defs_obj = load_slicer_defs(project_path)
            _validate_slicer_defs_against_model(model_scoped, defs_obj, pages=list(pages or []), lenient=True)
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_VALUES_FAILED")
            return _err(400, str(exc), error_code=code)

        target_def: Optional[Mapping[str, Any]] = None
        for d in defs_obj.get("defs") or []:
            if isinstance(d, Mapping) and str(d.get("id") or "").strip().upper() == def_id.upper():
                target_def = d
                break
        if target_def is None:
            return _err(404, f"Slicer def not found: {def_id!r}", error_code="E_SLICER_VALIDATION_FAILED")

        col_raw = target_def.get("column")
        if not isinstance(col_raw, Mapping):
            return _err(400, "slicer_def.column must be an object", error_code="E_SLICER_VALIDATION_FAILED")

        table = str(col_raw.get("table") or "").strip()
        column = str(col_raw.get("column") or "").strip()
        target_ui = target_def.get("ui") if isinstance(target_def.get("ui"), Mapping) else {}
        target_is_pure_input = (
            str(target_def.get("type") or "").strip().lower() == "input"
            and isinstance(target_ui, Mapping)
            and str(target_ui.get("input_mode") or "filter").strip().lower() == "input"
        )
        if target_is_pure_input:
            return _ok({"values": [], "limit": lim, "offset": off})
        if not table or not column:
            return _err(400, "slicer_def.column.table and slicer_def.column.column are required", error_code="E_SLICER_INVALID_BINDING")

        # Handle virtual tables (FieldParams_*, CalcGroup_*, WhatIf_*) directly without SQL
        virtual_prefixes = ("FieldParams_", "CalcGroup_", "WhatIf_")
        is_virtual = any(table.startswith(p) or table.upper().startswith(p.upper()) for p in virtual_prefixes)

        if is_virtual:
            try:
                virtual_tables = _build_virtual_tables(model_scoped)
                vt = next((vt for vt in virtual_tables if vt["name"].upper() == table.upper()), None)
                if vt is None:
                    return _err(400, f"Unknown virtual table: {table!r}", error_code="E_SLICER_INVALID_BINDING")
                if column.upper() not in {c.upper() for c in vt["columns"]}:
                    return _err(400, f"Unknown column: {table}[{column}]", error_code="E_SLICER_INVALID_BINDING")
                values = _get_virtual_table_distinct_values(model_scoped, vt["name"], column)
                # Apply search filter if provided
                if qv is not None:
                    values = [v for v in values if qv.lower() in str(v).lower()]
                # Apply limit/offset
                values = values[off:off + lim]
                return _ok({"values": values, "limit": lim, "offset": off})
            except Exception as exc:  # noqa: BLE001
                return _err(400, str(exc), error_code="E_SLICER_VALUES_FAILED")

        # Handle field-parameter hierarchy/lookup tables (no data source, values
        # derived from connected field-parameter items' locale attribute).
        if not is_virtual:
            hierarchy_values = _resolve_field_parameter_hierarchy_values(model_scoped, table, column)
            if hierarchy_values is not None:
                if qv is not None:
                    hierarchy_values = [v for v in hierarchy_values if qv.lower() in str(v).lower()]
                hierarchy_values = hierarchy_values[off:off + lim]
                return _ok({"values": hierarchy_values, "limit": lim, "offset": off})

        # Build effective context: payload filters + slicer materialization (excluding self).
        try:
            runtime_filters = _parse_scoped_filters_payload(
                safe.get("filters"),
                project_path=project_path,
                model=model_scoped,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_VALIDATION_FAILED")

        try:
            slicer_filter_payload = _materialize_slicer_defs_to_filter_payload_items(
                defs_obj,
                exclude_def_id=exclude_def_id,
                project_path=project_path,
                model=model,
                sec_state=sec_state,
                duckdb_path=duckdb_path,
                runtime_filters=list(runtime_filters),
                page_id=str(page_id) if page_id else None,
                visual_id=None,
            )
            slicer_filters = _parse_scoped_filters_payload(
                slicer_filter_payload,
                project_path=project_path,
                model=model_scoped,
            )
        except Exception as exc:  # noqa: BLE001
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_VALIDATION_FAILED")
            return _err(400, str(exc), error_code=code)

        with _ENGINE_LOCK:
            get_prepared_engine(project_path, model)

            ctx = dax_compiler.Context()
            sec = _compile_rls_security_predicates(role=sec_state.role, base_ctx=ctx)
            if sec:
                ctx = ctx.apply_security_predicates(sec)

            from dax_engine.filters_ir import apply_scoped_filters_to_context

            ctx, _applied = apply_scoped_filters_to_context(
                ctx,
                list(runtime_filters) + list(slicer_filters),
                page_id=str(page_id) if page_id else None,
                visual_id=None,
            )

            # Use relationship-aware FROM planning so cross-table filters apply.
            try:
                from dax_engine.ir import ColumnRef
                from dax_engine.relationships import _build_rowset_plan_ctx
                from dax_engine.compiler import compile_expr

                col_ir = ColumnRef(table=table, column=column)
                col_sql = compile_expr(col_ir, ctx)

                required_tables: set[str] = {table}
                for k in ctx.all_filter_keys():
                    if "." in k:
                        required_tables.add(k.split(".", 1)[0])

                from_clause, connected, _ = _build_rowset_plan_ctx(table, sorted(required_tables), ctx)
                where_base = ctx.where_clause_for_tables(sorted(connected))
                clauses: list[str] = []
                if where_base:
                    clauses.append(where_base[len("WHERE ") :])
                params: list[Any] = []
                if qv is not None:
                    clauses.append(f"(CAST({col_sql} AS VARCHAR) ILIKE ('%' || ? || '%'))")
                    params.append(qv)

                where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                sql = (
                    f"SELECT DISTINCT {col_sql} AS v "
                    f"FROM {from_clause} "
                    f"{where_sql} "
                    f"ORDER BY (v IS NULL) ASC, v "
                    f"LIMIT {lim} OFFSET {off}"
                )
            except Exception as exc:
                return _err(400, str(exc), error_code="E_SLICER_VALUES_FAILED")

        con = None
        try:
            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
            rows = con.execute(sql, params).fetchall()
            values = [r[0] for r in rows]
            return _ok({"values": values, "limit": lim, "offset": off})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_VALUES_FAILED")
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

    _REPORT_RESOURCE_EXTENSIONS = {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}

    def _resolve_report_resource(project_path: str, resource: str) -> Path:
        raw = str(resource or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("resource is required")
        if "://" in raw or raw.startswith("//"):
            raise ValueError("remote resource URLs are not served by this endpoint")
        rel = Path(raw.lstrip("/"))
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            raise ValueError("resource must be a relative project path")
        if rel.suffix.lower() not in _REPORT_RESOURCE_EXTENSIONS:
            raise ValueError("resource extension is not an allowed image type")

        project_root = Path(project_path).resolve()
        candidates = [
            project_root / rel,
            project_root / "reports" / rel,
            project_root / "reports" / "resources" / rel,
            project_root / "reports" / "RegisteredResources" / rel.name,
            project_root / "RegisteredResources" / rel.name,
        ]
        for candidate in candidates:
            resolved = candidate.resolve()
            if project_root != resolved and project_root not in resolved.parents:
                continue
            if resolved.exists() and resolved.is_file():
                return resolved
        raise FileNotFoundError(f"Report resource not found: {resource}")

    @app.get("/runtime/report_resource")
    def runtime_report_resource(resource: str, project: Optional[str] = None):
        """Serve imported report image resources from inside the loaded project."""

        try:
            project_path = _resolve_project_path_runtime(project)
            resource_path = _resolve_report_resource(project_path, resource)
            return FileResponse(resource_path)
        except Exception as exc:  # noqa: BLE001
            return _err(404, str(exc), error_code="E_REPORT_RESOURCE_NOT_FOUND")

    _REPORTING_THEME_DEFAULTS: dict = {
        "name": "Default",
        "dataColors": [
            "#DED6FF", "#BCA8F0", "#E0A8E0", "#9478E0",
            "#CC68CC", "#6C50D0", "#A050B0", "#4838A8",
        ],
        "visualCard": {
            "borderRadius": 6,
            "borderWidth": 1,
            "borderColor": "",
            "shadow": "sm",
            "padding": 0,
            "background": "",
        },
        "font": {
            "family": "Inter, system-ui, -apple-system, sans-serif",
            "sizeBody": 11,
            "sizeTitle": 14,
            "colorBody": "",
            "colorTitle": "",
        },
        "chart": {
            "showGridlines": True,
            "gridlineColor": "",
            "axisColor": "",
            "plotBackground": "transparent",
            "legendPosition": "bottom",
        },
        "canvas": {
            "background": "",
        },
        "defaultSize": {
            "width": 400,
            "height": 300,
        },
    }

    def _load_reporting_theme(project_path: str) -> dict:
        theme_path = Path(project_path) / "reports" / "reporting_theme.json"
        if theme_path.exists():
            try:
                with open(theme_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Merge with defaults to fill any missing keys
                    merged = dict(_REPORTING_THEME_DEFAULTS)
                    for section in ("visualCard", "font", "chart", "canvas", "defaultSize"):
                        if section in data and isinstance(data[section], dict):
                            merged[section] = {**_REPORTING_THEME_DEFAULTS.get(section, {}), **data[section]}
                    for key in ("name", "dataColors"):
                        if key in data:
                            merged[key] = data[key]
                    return merged
            except Exception:
                pass
        return dict(_REPORTING_THEME_DEFAULTS)

    def _save_reporting_theme(project_path: str, theme: dict) -> None:
        reports_dir = Path(project_path) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        theme_path = reports_dir / "reporting_theme.json"
        with open(theme_path, "w", encoding="utf-8") as f:
            json.dump(theme, f, indent=2, ensure_ascii=False)

    @app.get("/runtime/reporting_theme")
    def get_reporting_theme(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
            theme = _load_reporting_theme(project_path)
            return _ok(theme)
        except Exception as exc:
            return _err(400, str(exc))

    @app.put("/runtime/reporting_theme")
    def put_reporting_theme(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("reporting theme payload must be an object")
            # Validate structure
            name = safe.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("reporting theme must have a non-empty 'name' string")
            data_colors = safe.get("dataColors")
            if not isinstance(data_colors, list) or len(data_colors) < 2:
                raise ValueError("dataColors must be a list with at least 2 entries")
            for i, c in enumerate(data_colors):
                if not isinstance(c, str):
                    raise ValueError(f"dataColors[{i}] must be a string")
            # Build the cleaned theme dict
            theme: dict = {
                "name": name.strip(),
                "dataColors": [str(c) for c in data_colors],
            }
            for section in ("visualCard", "font", "chart", "canvas", "defaultSize"):
                sec_data = safe.get(section)
                if isinstance(sec_data, Mapping):
                    theme[section] = dict(sec_data)
                else:
                    theme[section] = dict(_REPORTING_THEME_DEFAULTS.get(section, {}))
            _save_reporting_theme(project_path, theme)
            return _ok({"saved": True})
        except Exception as exc:
            return _err(400, str(exc))

    @app.get("/runtime/bookmarks")
    def get_bookmarks(project: Optional[str] = None):
        """List all bookmarks."""
        try:
            project_path = _resolve_project_path_runtime(project)
            data = load_bookmarks(project_path)
            return _ok(data)
        except Exception as exc:
            return _err(400, str(exc))

    @app.put("/runtime/bookmarks")
    def put_bookmarks(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Bulk-replace all bookmarks (used by Save All)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("bookmarks payload must be an object")
            result = save_bookmarks(project_path, safe)
            return _ok(result)
        except Exception as exc:
            return _err(400, str(exc))

    @app.post("/runtime/bookmarks")
    def create_bookmark(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Create a new bookmark (append to list, persist immediately)."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("bookmark payload must be an object")

            bk = safe.get("bookmark")
            if not isinstance(bk, Mapping):
                raise ValueError("bookmark object is required")

            # Validate bookmark name if provided
            bk_name = str(bk.get("name") or "").strip()
            if bk_name:
                _validate_safe_name(bk_name, label="bookmark name")

            # Sanitize all user-facing string fields to prevent stored XSS
            for _field in ("display_name", "description", "caption"):
                _val = bk.get(_field)
                if isinstance(_val, str) and _val.strip():
                    _validate_safe_name(_val.strip(), label=f"bookmark {_field}")

            existing = load_bookmarks(project_path)
            bookmarks = list(existing.get("bookmarks") or [])

            # Ensure no duplicate id.
            new_id = str(bk.get("id") or "").strip()
            if not new_id:
                import uuid
                new_id = str(uuid.uuid4())
                bk = dict(bk, id=new_id)

            for b in bookmarks:
                if str(b.get("id") or "").strip().upper() == new_id.upper():
                    raise ValueError(f"Bookmark with id {new_id!r} already exists")

            bookmarks.append(dict(bk))
            result = save_bookmarks(project_path, {"bookmarks": bookmarks})
            return _ok(result)
        except Exception as exc:
            return _err(400, str(exc))

    @app.put("/runtime/bookmarks/{bookmark_id}")
    def update_bookmark(bookmark_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Update a single bookmark by id."""
        try:
            project_path = _resolve_project_path_runtime(project)
            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("bookmark payload must be an object")

            bk = safe.get("bookmark")
            if not isinstance(bk, Mapping):
                raise ValueError("bookmark object is required")

            # Validate bookmark name if provided
            bk_name = str(bk.get("name") or "").strip()
            if bk_name:
                _validate_safe_name(bk_name, label="bookmark name")

            # Sanitize all user-facing string fields to prevent stored XSS
            for _field in ("display_name", "description", "caption"):
                _val = bk.get(_field)
                if isinstance(_val, str) and _val.strip():
                    _validate_safe_name(_val.strip(), label=f"bookmark {_field}")

            existing = load_bookmarks(project_path)
            bookmarks = list(existing.get("bookmarks") or [])

            target_key = bookmark_id.strip().upper()
            found = False
            for i, b in enumerate(bookmarks):
                if str(b.get("id") or "").strip().upper() == target_key:
                    # Merge: preserve id, update the rest.
                    updated = dict(bk, id=bookmark_id.strip())
                    bookmarks[i] = updated
                    found = True
                    break

            if not found:
                raise ValueError(f"Bookmark {bookmark_id!r} not found")

            result = save_bookmarks(project_path, {"bookmarks": bookmarks})
            return _ok(result)
        except Exception as exc:
            return _err(400, str(exc))

    @app.delete("/runtime/bookmarks/{bookmark_id}")
    def delete_bookmark(bookmark_id: str, project: Optional[str] = None):
        """Delete a bookmark by id."""
        try:
            project_path = _resolve_project_path_runtime(project)
            existing = load_bookmarks(project_path)
            bookmarks = list(existing.get("bookmarks") or [])

            target_key = bookmark_id.strip().upper()
            new_list = [b for b in bookmarks if str(b.get("id") or "").strip().upper() != target_key]

            if len(new_list) == len(bookmarks):
                raise ValueError(f"Bookmark {bookmark_id!r} not found")

            result = save_bookmarks(project_path, {"bookmarks": new_list})
            return _ok({"deleted": bookmark_id.strip(), **result})
        except Exception as exc:
            return _err(400, str(exc))

    @app.post("/runtime/bookmarks/{bookmark_id}/apply")
    def apply_bookmark(bookmark_id: str, project: Optional[str] = None):
        """Return the state captured in a bookmark for the client to restore.

        The client receives filters, slicer_selections, interaction_selections,
        and current_page_id. The client applies these to its in-memory stores
        (no disk write happens here ΓÇö Save-only persistence is respected).
        """
        try:
            project_path = _resolve_project_path_runtime(project)
            existing = load_bookmarks(project_path)
            bookmarks = list(existing.get("bookmarks") or [])

            target_key = bookmark_id.strip().upper()
            target = None
            for b in bookmarks:
                if str(b.get("id") or "").strip().upper() == target_key:
                    target = b
                    break

            if target is None:
                raise ValueError(f"Bookmark {bookmark_id!r} not found")

            # Build response respecting capture flags (Power BI-style).
            # If a capture flag is False, return empty/default for that dimension
            # so the client knows not to overwrite its current state.
            capture_page = target.get("capture_page", True)
            capture_data = target.get("capture_data", True)
            capture_display = target.get("capture_display", True)

            return _ok({
                "bookmark": target,
                "current_page_id": target.get("current_page_id", "") if capture_page else "",
                "filters": target.get("filters", []) if capture_data else [],
                "slicer_selections": target.get("slicer_selections", {}) if capture_data else {},
                "interaction_selections": target.get("interaction_selections", []) if capture_data else [],
                "visual_visibility": target.get("visual_visibility", {}) if capture_display else {},
                "capture_page": capture_page,
                "capture_data": capture_data,
                "capture_display": capture_display,
            })
        except Exception as exc:
            return _err(400, str(exc))

    @app.get("/runtime/slicers/sync")
    def runtime_get_slicer_sync(project: Optional[str] = None):
        """Return per-page sync/visible config for every slicer, from unified model."""
        try:
            project_path = _resolve_project_path_runtime(project)
            _model, pages, _visuals = load_project(project_path)
            unified = load_slicers(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SYNC_FAILED")

        page_list = [{"id": getattr(p, "id", "") or (p.get("id", "") if hasattr(p, "get") else ""), "title": getattr(p, "title", "") or (p.get("title", "") if hasattr(p, "get") else "")} for p in (pages or [])]
        page_ids = [p["id"] for p in page_list]

        sync: dict[str, Any] = {}
        for s in unified.get("slicers") or []:
            if not isinstance(s, Mapping):
                continue
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue

            slicer_pages = s.get("pages") or {}

            # Build per-page config, defaulting unset pages to False
            sp: dict[str, dict[str, bool]] = {}
            for pid in page_ids:
                if pid in slicer_pages:
                    entry = slicer_pages[pid]
                    sp[pid] = {
                        "sync": bool(entry.get("sync", True)) if isinstance(entry, Mapping) else True,
                        "visible": bool(entry.get("visible", True)) if isinstance(entry, Mapping) else True,
                    }
                else:
                    sp[pid] = {"sync": False, "visible": False}

            sync[sid] = {"sync_pages": sp}
            sg = s.get("sync_group")
            if sg:
                sync[sid]["sync_group"] = str(sg)

        return _ok({"sync": sync, "pages": page_list})

    @app.put("/runtime/slicers/sync/{def_id}")
    def runtime_update_slicer_sync(def_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Update sync/visible/layout config for one slicer.

        When a page is toggled to visible=True and has no layout, a default layout
        is auto-assigned so the slicer appears immediately on that page (no need to
        create a separate instance).
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SYNC_FAILED")

        try:
            unified = load_slicers(project_path)
            slicers = list(unified.get("slicers") or [])
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SYNC_FAILED")

        idx = None
        for i, s in enumerate(slicers):
            if isinstance(s, Mapping) and str(s.get("id") or "").strip().upper() == def_id.upper():
                idx = i
                break
        if idx is None:
            return _err(404, f"Slicer not found: {def_id!r}", error_code="E_SLICER_SYNC_FAILED")

        target_slicer = dict(slicers[idx])
        current_pages = dict(target_slicer.get("pages") or {})

        # Apply sync_pages ΓåÆ update pages dict directly
        sp_raw = payload.get("sync_pages")
        if sp_raw is not None:
            if not isinstance(sp_raw, Mapping):
                return _err(400, "sync_pages must be an object", error_code="E_SLICER_SYNC_FAILED")
            for pid, cfg in sp_raw.items():
                pid_s = str(pid).strip()
                if not pid_s:
                    continue
                if not isinstance(cfg, Mapping):
                    return _err(400, f"sync_pages[{pid}] must be an object", error_code="E_SLICER_SYNC_FAILED")
                new_sync = bool(cfg.get("sync", True))
                new_visible = bool(cfg.get("visible", True))
                if pid_s in current_pages:
                    # Update existing entry, preserve layout
                    entry = dict(current_pages[pid_s])
                    entry["sync"] = new_sync
                    entry["visible"] = new_visible
                    current_pages[pid_s] = entry
                elif new_visible or new_sync:
                    # Auto-create page entry with default layout
                    current_pages[pid_s] = {
                        "visible": new_visible,
                        "sync": new_sync,
                        "layout": {"x": 0, "y": 0, "w": 240, "h": 260},
                    }
                # If both false and no existing entry, don't add

        target_slicer["pages"] = current_pages

        # Apply sync_group
        sg_raw = payload.get("sync_group")
        if sg_raw is not None:
            sg_str = str(sg_raw).strip()
            if sg_str:
                target_slicer["sync_group"] = sg_str
            else:
                target_slicer.pop("sync_group", None)
        elif "sync_group" in payload:
            target_slicer.pop("sync_group", None)

        slicers[idx] = target_slicer
        try:
            save_slicers(project_path, {"slicers": slicers})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), error_code="E_SLICER_SYNC_FAILED")

        return _ok({"status": "ok"})

    @app.post("/runtime/save_all")
    def runtime_save_all(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
            model, pages, visuals = load_project(project_path)

            safe = _json_safe_with_path(payload or {}, path="$", strict=True)
            if not isinstance(safe, Mapping):
                raise ValueError("payload must be an object")

            # Optional hardening: Save All can also persist security roles if provided.
            # UI currently persists security via PUT /runtime/security/roles first, then calls Save All.
            # This block exists to keep a single strict entrypoint that can atomically persist roles
            # alongside other report artifacts if the client chooses to send them.
            if "roles" in safe or "default_role" in safe:
                roles_payload = safe.get("roles")
                if roles_payload is None:
                    roles_payload = []
                if not isinstance(roles_payload, list):
                    raise ValueError("roles must be a list")

                default_role = safe.get("default_role")
                if default_role is not None and (not isinstance(default_role, str) or not default_role.strip()):
                    raise ValueError("default_role must be a non-empty string if provided")

                errors: list[str] = []
                seen: set[str] = set()
                for i, rr in enumerate(roles_payload):
                    if not isinstance(rr, Mapping):
                        errors.append(f"roles[{i}] must be an object")
                        continue
                    nm = rr.get("name")
                    if not isinstance(nm, str) or not nm.strip():
                        errors.append(f"roles[{i}].name must be a non-empty string")
                        continue
                    key = nm.strip().upper()
                    if key in seen:
                        errors.append(f"duplicate role name: {nm.strip()!r}")
                    else:
                        seen.add(key)
                    errors.extend(_validate_single_role_payload(project_path=project_path, model=model, role_payload=rr))

                if default_role is not None and isinstance(default_role, str) and default_role.strip():
                    if default_role.strip().upper() not in seen:
                        errors.append(f"default_role not found in roles: {default_role.strip()!r}")

                if errors:
                    msg = "Security role validation failed:\n" + "\n".join(f"- {e}" for e in errors)
                    return _err(400, msg)

                save_security_yaml(
                    project_path,
                    roles=[dict(r) for r in roles_payload if isinstance(r, Mapping)],
                    default_role=default_role.strip() if isinstance(default_role, str) and default_role.strip() else None,
                )

            # For MVP: measures/tables/cols already persist on their own endpoints.
            # Save All focuses on report artifacts (filters, slicers).
            if "filters" in safe or "report_filters" in safe or "page_filters" in safe or "visual_filters" in safe:
                # Validate against model before writing.
                flat_filters = safe.get("filters")
                flat_list: list[Mapping[str, Any]] = []
                if isinstance(flat_filters, list):
                    for it in flat_filters:
                        if isinstance(it, Mapping):
                            flat_list.append(it)
                if flat_list:
                    _validate_filter_items_against_model(model, flat_list)

                save_report_filters(project_path, safe)

            # Persist slicers if provided (unified model).
            # Accept both "slicers" (unified) and legacy "slicer_defs"/"slicer_instances".
            # Empty payloads are ignored to prevent accidental data wipe.
            if "slicers" in safe:
                slicers_payload = safe.get("slicers")
                if isinstance(slicers_payload, list) and slicers_payload:
                    save_slicers(project_path, {"slicers": slicers_payload})
            elif "slicer_defs" in safe:
                slicer_defs_data = safe.get("slicer_defs")
                # Only save if it contains real data (not empty)
                if isinstance(slicer_defs_data, Mapping):
                    defs_list = slicer_defs_data.get("defs")
                elif isinstance(slicer_defs_data, list):
                    defs_list = slicer_defs_data
                else:
                    defs_list = None
                if isinstance(defs_list, list) and defs_list:
                    defs_obj = _normalize_slicer_defs_payload(slicer_defs_data)
                    _validate_slicer_defs_against_model(model, defs_obj, pages=list(pages or []))
                    save_slicer_defs(project_path, defs_obj)

            # Persist bookmarks if provided.
            if "bookmarks" in safe:
                bk_payload = safe.get("bookmarks")
                if isinstance(bk_payload, list):
                    save_bookmarks(project_path, {"bookmarks": bk_payload})
                elif isinstance(bk_payload, Mapping):
                    save_bookmarks(project_path, bk_payload)

            # Persist calc-group selections (report/page/visual state) if provided.
            if "calc_group_selections" in safe or "calc_group_selections_payload" in safe:
                obj = safe.get("calc_group_selections") if "calc_group_selections" in safe else safe.get("calc_group_selections_payload")
                if isinstance(obj, Mapping):
                    out_sel = save_calc_group_selections(project_path, obj)
                    flat_sel = flatten_calc_group_selections(out_sel)
                    _validate_calc_group_selections_against_model(model, flat_sel)

            # Persist field-parameter selections (report/page/visual state) if provided.
            if "field_parameter_selections" in safe or "field_parameter_selections_payload" in safe:
                obj = (
                    safe.get("field_parameter_selections")
                    if "field_parameter_selections" in safe
                    else safe.get("field_parameter_selections_payload")
                )
                if isinstance(obj, Mapping):
                    out_fp = save_field_parameter_selections(project_path, obj)
                    flat_fp = flatten_field_parameter_selections(out_fp)
                    _validate_field_parameter_selections_against_model(model, flat_fp)

            # Persist What-If selections (report/page/visual state) if provided.
            if "what_if_selections" in safe or "what_if_selections_payload" in safe:
                obj = (
                    safe.get("what_if_selections")
                    if "what_if_selections" in safe
                    else safe.get("what_if_selections_payload")
                )
                if isinstance(obj, Mapping):
                    out_wip = save_what_if_selections(project_path, obj)
                    flat_wip = flatten_what_if_selections(out_wip)
                    _validate_what_if_selections_against_model(model, flat_wip)

            # Persist visuals if provided (for non-persistent delete support).
            # This atomically syncs the visuals directory to match the client state.
            visuals_saved = 0
            if "visuals" in safe:
                vis_payload = safe.get("visuals")
                if isinstance(vis_payload, list):
                    visuals_dir = Path(project_path) / "reports" / "visuals"
                    visuals_dir.mkdir(parents=True, exist_ok=True)

                    # Get set of visual IDs from client state.
                    client_ids: set[str] = set()
                    for v in vis_payload:
                        if isinstance(v, Mapping):
                            vid = str(v.get("id") or "").strip()
                            if vid:
                                client_ids.add(vid.upper())

                    # Delete visuals not in client state (non-persistent delete).
                    for existing_file in visuals_dir.glob("*.json"):
                        existing_id = existing_file.stem.upper()
                        if existing_id not in client_ids:
                            existing_file.unlink()

                    # Save each visual from client state.
                    for v in vis_payload:
                        if isinstance(v, Mapping):
                            vid = str(v.get("id") or "").strip()
                            if vid:
                                _save_visual_json(project_path, vid, dict(v))
                                visuals_saved += 1

            # Persist pages if provided.
            pages_saved = 0
            if "pages" in safe:
                pages_payload = safe.get("pages")
                if isinstance(pages_payload, list):
                    pages_list = [dict(p) for p in pages_payload if isinstance(p, Mapping)]
                    save_pages(project_path, pages_list)
                    pages_saved = len(pages_list)

            # Persist model view layouts if provided.
            model_layouts_saved = 0
            if "model_layouts" in safe:
                ml_payload = safe.get("model_layouts")
                if isinstance(ml_payload, list):
                    cleaned_layouts: list[dict] = []
                    for item in ml_payload:
                        if isinstance(item, Mapping):
                            lid = str(item.get("id") or "").strip()
                            lname = str(item.get("name") or "").strip()
                            if lid and lname:
                                visible = item.get("visibleTables")
                                if isinstance(visible, list):
                                    visible = [str(v) for v in visible if isinstance(v, str) and v.strip()]
                                else:
                                    visible = None
                                positions = item.get("nodePositions")
                                if not isinstance(positions, Mapping):
                                    positions = {}
                                cleaned_layouts.append({
                                    "id": lid,
                                    "name": lname,
                                    "visibleTables": visible,
                                    "nodePositions": {
                                        str(k): {"x": float(v.get("x", 0)), "y": float(v.get("y", 0))}
                                        for k, v in positions.items()
                                        if isinstance(v, Mapping)
                                    },
                                })
                    from dax_ui.server._routes_model_ext import _save_model_layouts
                    _save_model_layouts(project_path, cleaned_layouts)
                    model_layouts_saved = len(cleaned_layouts)

            # Persist reporting theme if provided.
            reporting_theme_saved = False
            if "reporting_theme" in safe:
                rt_payload = safe.get("reporting_theme")
                if isinstance(rt_payload, Mapping):
                    rt_name = rt_payload.get("name")
                    if isinstance(rt_name, str) and rt_name.strip():
                        _save_reporting_theme(project_path, dict(rt_payload))
                        reporting_theme_saved = True

            return _ok(
                {
                    "saved": {
                        "report": True,
                        "filters": True,
                        "security": bool("roles" in safe or "default_role" in safe),
                        "slicers": bool("slicer_defs" in safe or "slicer_instances" in safe),
                        "bookmarks": bool("bookmarks" in safe),
                        "calc_group_selections": bool("calc_group_selections" in safe or "calc_group_selections_payload" in safe),
                        "field_parameter_selections": bool(
                            "field_parameter_selections" in safe or "field_parameter_selections_payload" in safe
                        ),
                        "what_if_selections": bool(
                            "what_if_selections" in safe or "what_if_selections_payload" in safe
                        ),
                        "visuals": visuals_saved if "visuals" in safe else len(list(visuals or [])),
                        "pages": pages_saved if "pages" in safe else len(list(pages or [])),
                        "model_layouts": model_layouts_saved,
                        "reporting_theme": reporting_theme_saved,
                    },
                    "warnings": [],
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
