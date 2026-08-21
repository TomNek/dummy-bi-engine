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
from typing import Any, Dict, Mapping, Optional

from starlette.requests import Request

import dax_compiler
from dax_engine.ir import MeasureRef, ir_to_dict
from dax_engine.planner import VisualQuerySpec, plan_card_query, plan_visual_query
from dax_engine.visual_calculations import (
    compile_visual_calculations,
    parse_visual_calculations,
    validate_visual_calculation,
    VisualCalculation,
)
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
from dax_ui.server._render_cache import (
    result_cache as _result_cache,
    sql_cache as _sql_cache,
    SQLPlanEntry as _SQLPlanEntry,
    get_cache_stats as _get_cache_stats,
    invalidate_all_caches as _invalidate_all_caches,
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


_CATEGORY_SORT_VISUAL_TYPES = {
    "bar", "column", "combo", "line", "area", "scatter",
    "histogram", "box", "violin", "strip", "ecdf",
    "funnel", "funnel_area", "waterfall",
    "ibcs_bar", "ibcs_column", "ibcs_line",
}


def _with_imported_category_sort(visual: dict[str, Any], visual_type: str) -> dict[str, Any]:
    fmt = dict(visual.get("format") or {})
    if "categorySort" in fmt:
        return fmt
    if visual_type not in _CATEGORY_SORT_VISUAL_TYPES:
        return fmt
    sort_cfg = visual.get("sort")
    if isinstance(sort_cfg, list) and sort_cfg:
        first_sort = sort_cfg[0] if isinstance(sort_cfg[0], dict) else {}
        direction = str(first_sort.get("direction", "descending") or "descending").lower()
        if direction not in ("ascending", "descending"):
            direction = "descending"
        fmt["categorySort"] = f"total {direction}"
    return fmt


# Module-level helpers from __init__ (available at import time since 
# all are defined before app = create_app() in __init__.py)
from dax_ui.server import (
    OlsVisualBlockedError,
    _render_plotly_figure,
    _resolve_encodings_for_output,
    _json_safe,
    _json_safe_with_path,
    _validate_safe_name,
    _require_plotly,
)
from dax_ui.server._routes_core import (
    _validate_calc_group_selections_against_model,
    _validate_field_parameter_selections_against_model,
    _validate_what_if_selections_against_model,
    _normalize_slicer_defs_payload,
    _materialize_slicer_defs_to_filter_payload_items,
)
try:
    from dax_ui.server._explanations import _execute_explanation_bindings
except ImportError:
    def _execute_explanation_bindings(*args, **kwargs):
        return None  # Community edition — explanations not available


def _resolve_value_param_refs(
    spec,
    model,
    param_values: Optional[Mapping[str, str]] = None,
) -> None:
    """Resolve ParamRef entries in matrix values encoding to concrete MeasureRefs.

    When a matrix encodes its values as ``ParamRef("Parameter Measures")``,
    ``matrix_spec_from_visual`` stores the param name in ``spec._value_param_refs``
    because it has no access to the model.  This helper looks up the field
    parameter definition, finds the selected (or default) item, and—if it is a
    MeasureRef—appends it to ``spec.values``.
    """
    from dax_engine.ir import MeasureRef

    fp_map = getattr(model, "field_parameters", None) or {}
    seen = {m.name for m in spec.values}

    for pname in spec._value_param_refs:
        # Case-insensitive lookup of the field parameter
        fp = None
        for k, v in fp_map.items():
            if isinstance(k, str) and k.upper() == pname.upper():
                fp = v
                break
        if fp is None:
            continue

        fp_items = getattr(fp, "items", []) or []
        if not fp_items:
            continue

        # Determine which item is selected
        selected_name: Optional[str] = None
        if param_values:
            selected_name = param_values.get(pname.upper()) or param_values.get(pname)

        chosen = None
        if selected_name:
            for fp_item in fp_items:
                if getattr(fp_item, "name", "") == selected_name:
                    chosen = fp_item
                    break
        if chosen is None:
            # Fall back to first item
            chosen = fp_items[0]

        ref = getattr(chosen, "ref", None)
        if ref is None:
            continue

        # MeasureRef → add to spec.values
        if hasattr(ref, "name") and not hasattr(ref, "column"):
            mname = ref.name
            if mname and mname not in seen:
                spec.values.append(MeasureRef(name=mname))
                seen.add(mname)
        # ColumnRef → not valid for values axis, skip


def register_visual_routes(app):
    from fastapi import Body, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    @app.post("/runtime/visuals")
    def create_visual(project: Optional[str] = None, page: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            current_page = _select_page_id(pages, page)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        registry = load_visual_type_registry(project_path)

        visual_type = str(payload.get("visual_type") or payload.get("type") or "bar")
        if visual_type not in registry:
            return _err(400, f"Unknown visual_type: {visual_type!r}")

        visual_id = str(payload.get("id") or _next_visual_id(project_path))
        title = str(payload.get("title") or visual_id)

        # Validate title against unsafe characters
        try:
            _validate_safe_name(title, label="visual title")
        except ValueError as e:
            return _err(400, str(e))

        page_id = payload.get("page_id")
        if page_id is None:
            page_id = current_page
        if not isinstance(page_id, str) or not page_id.strip():
            return _err(400, "page_id must be a non-empty string if provided")
        valid_page_ids = {getattr(p, "id").upper(): getattr(p, "id") for p in pages}
        if page_id.strip().upper() not in valid_page_ids:
            return _err(400, f"Unknown page_id: {page_id!r}")

        slots = registry[visual_type].slots
        encodings = {}
        for slot_name, slot_spec in slots.items():
            encodings[slot_name] = [] if slot_spec.multi else None

        advanced_patch_raw = payload.get("advanced_plotly_patch")
        advanced_patch_out: dict[str, Any] = {}
        if advanced_patch_raw is not None:
            if not isinstance(advanced_patch_raw, Mapping):
                return _err(400, "advanced_plotly_patch must be an object")
            try:
                advanced_patch_out = _json_safe_with_path(
                    advanced_patch_raw,
                    path="$.advanced_plotly_patch",
                    strict=True,
                )
            except TypeError as exc:
                return _err(400, f"advanced_plotly_patch must be JSON-serializable; {exc}")

        obj = {
            "id": visual_id,
            "title": title,
            "visual_type": visual_type,
            "page_id": valid_page_ids[page_id.strip().upper()],
            "layout": payload.get("layout")
            or {"x": 40, "y": 20, "w": 520, "h": 360},
            "encodings": encodings,
            "format": dict(payload.get("format") or {}),
            "advanced_plotly_patch": advanced_patch_out,
            "interactions": dict(_DEFAULT_VISUAL_INTERACTIONS),
        }

        # Static visuals: set default static_content per type
        is_static = registry[visual_type].static
        if is_static:
            sc_defaults: dict[str, Any] = {}
            if visual_type == "textbox":
                sc_defaults = {"text": "", "fontSize": 14, "fontWeight": "normal", "textAlign": "left", "color": "#000000", "backgroundColor": "transparent"}
            elif visual_type == "button":
                sc_defaults = {"label": "Button", "buttonType": "blank", "style": "default", "backgroundColor": "#0078d4", "color": "#ffffff", "borderRadius": 4, "url": "", "action": {"type": "none", "target": ""}}
            elif visual_type == "shape":
                sc_defaults = {"shapeType": "rectangle", "fill": "#0078d4", "stroke": "#000000", "strokeWidth": 1, "opacity": 1, "borderRadius": 0, "action": {"type": "none", "target": ""}}
            elif visual_type == "image":
                sc_defaults = {"url": "", "alt": "", "fit": "contain"}
            user_sc = payload.get("static_content")
            if isinstance(user_sc, Mapping):
                sc_defaults.update(user_sc)
            obj["static_content"] = sc_defaults

        _save_visual_json(project_path, visual_id, obj)
        return obj

    @app.put("/runtime/visuals/{visual_id}")
    def update_visual(visual_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            current = _load_visual_json(project_path, visual_id)
        except FileNotFoundError as exc:
            return _err(404, f"Visual not found: {visual_id!r}")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        if "page_id" in payload:
            try:
                _model, pages, _visuals = load_project(project_path)
            except Exception as exc:  # noqa: BLE001
                return _err(400, str(exc))
            page_id = payload.get("page_id")
            if page_id is not None:
                if not isinstance(page_id, str) or not page_id.strip():
                    return _err(400, "page_id must be a non-empty string if provided")
                valid_page_ids = {getattr(p, "id").upper(): getattr(p, "id") for p in pages}
                if page_id.strip().upper() not in valid_page_ids:
                    return _err(400, f"Unknown page_id: {page_id!r}")
                current["page_id"] = valid_page_ids[page_id.strip().upper()]

        for k in ("title", "visual_type", "layout", "encodings", "param_values", "calc_groups"):
            if k in payload:
                current[k] = payload[k]

        # Visual calculations (list of {name, expression})
        if "visual_calculations" in payload:
            raw_vcs = payload.get("visual_calculations")
            if raw_vcs is None:
                current.pop("visual_calculations", None)
            else:
                try:
                    vcs = parse_visual_calculations(raw_vcs)
                    current["visual_calculations"] = [
                        {"name": vc.name, "expression": vc.expression} for vc in vcs
                    ]
                except (ValueError, Exception) as exc:
                    return _err(400, f"Invalid visual_calculations: {exc}")

        # Tooltip page assignment (string page ID or null to clear)
        if "tooltip_page_id" in payload:
            tp_id = payload.get("tooltip_page_id")
            if tp_id is None:
                current.pop("tooltip_page_id", None)
            elif isinstance(tp_id, str) and tp_id.strip():
                current["tooltip_page_id"] = tp_id.strip()
            else:
                return _err(400, "tooltip_page_id must be a non-empty string or null")

        if "format" in payload:
            fmt_raw = payload.get("format")
            if fmt_raw is None:
                current["format"] = {}
            elif isinstance(fmt_raw, Mapping):
                current["format"] = dict(fmt_raw)
            else:
                return _err(400, "format must be an object")

        if "interactions" in payload:
            current["interactions"] = _normalize_visual_interactions(payload.get("interactions"))

        if "advanced_plotly_patch" in payload:
            advanced_patch_raw = payload.get("advanced_plotly_patch")
            if advanced_patch_raw is None:
                current["advanced_plotly_patch"] = {}
            else:
                if not isinstance(advanced_patch_raw, Mapping):
                    return _err(400, "advanced_plotly_patch must be an object")
                try:
                    current["advanced_plotly_patch"] = _json_safe_with_path(
                        advanced_patch_raw,
                        path="$.advanced_plotly_patch",
                        strict=True,
                    )
                except TypeError as exc:
                    return _err(400, f"advanced_plotly_patch must be JSON-serializable; {exc}")

        if "static_content" in payload:
            sc_raw = payload.get("static_content")
            if sc_raw is None:
                current["static_content"] = {}
            elif isinstance(sc_raw, Mapping):
                existing_sc = current.get("static_content") or {}
                if isinstance(existing_sc, Mapping):
                    merged = dict(existing_sc)
                    merged.update(sc_raw)
                    current["static_content"] = merged
                else:
                    current["static_content"] = dict(sc_raw)
            else:
                return _err(400, "static_content must be an object")

        _save_visual_json(project_path, visual_id, current)
        return current

    @app.delete("/runtime/visuals/{visual_id}")
    def delete_visual(visual_id: str, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        if not isinstance(visual_id, str) or not visual_id.strip():
            return _err(400, "visual_id must be a non-empty string")

        try:
            _delete_visual_json(project_path, visual_id)
        except FileNotFoundError:
            return _err(404, f"Visual not found: {visual_id!r}")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        return _ok({"id": visual_id})

    # ── Visual Calculations Endpoints ──────────────────────────────

    @app.get("/runtime/visuals/{visual_id}/visual-calculations")
    def get_visual_calculations(visual_id: str, project: Optional[str] = None):
        """Return visual calculations defined on a visual."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        try:
            visual = _load_visual_json(project_path, visual_id)
        except FileNotFoundError:
            return _err(404, f"Visual not found: {visual_id!r}")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        raw = visual.get("visual_calculations") or []
        try:
            vcs = parse_visual_calculations(raw)
        except ValueError as exc:
            return _err(400, str(exc))
        return _ok({"visual_calculations": [{"name": vc.name, "expression": vc.expression} for vc in vcs]})

    @app.put("/runtime/visuals/{visual_id}/visual-calculations")
    def put_visual_calculations(
        visual_id: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Replace the full list of visual calculations on a visual."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        try:
            visual = _load_visual_json(project_path, visual_id)
        except FileNotFoundError:
            return _err(404, f"Visual not found: {visual_id!r}")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        raw = payload.get("visual_calculations")
        if raw is None:
            raw = []
        try:
            vcs = parse_visual_calculations(raw)
        except ValueError as exc:
            return _err(400, str(exc))
        visual["visual_calculations"] = [{"name": vc.name, "expression": vc.expression} for vc in vcs]
        _save_visual_json(project_path, visual_id, visual)
        return _ok({"visual_calculations": visual["visual_calculations"]})

    @app.post("/runtime/visuals/{visual_id}/visual-calculations/validate")
    def validate_visual_calc_endpoint(
        visual_id: str,
        project: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Validate a visual calculation expression without persisting it."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        try:
            visual = _load_visual_json(project_path, visual_id)
        except FileNotFoundError:
            return _err(404, f"Visual not found: {visual_id!r}")
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        name = payload.get("name")
        expression = payload.get("expression")
        if not isinstance(name, str) or not name.strip():
            return _err(400, "name must be a non-empty string")
        if not isinstance(expression, str) or not expression.strip():
            return _err(400, "expression must be a non-empty string")

        # Get dimension/measure info from the visual's encodings
        encodings = visual.get("encodings") or {}
        registry = load_visual_type_registry(project_path)
        visual_type = str(visual.get("visual_type") or visual.get("type") or "").strip()
        vt = registry.get(visual_type)

        dim_cols: list[str] = []
        meas_names: list[str] = []
        if vt:
            for slot_name, slot_spec in vt.slots.items():
                val = encodings.get(slot_name)
                if not val:
                    continue
                if slot_spec.kind == "dimension":
                    if isinstance(val, str):
                        # Extract column name from "Table[Column]" or "[Column]"
                        if "[" in val and "]" in val:
                            dim_cols.append(val.split("[")[1].rstrip("]"))
                        else:
                            dim_cols.append(val)
                    elif isinstance(val, dict):
                        column_name = val.get("column") or val.get("name")
                        if isinstance(column_name, str) and column_name.strip():
                            dim_cols.append(column_name.strip())
                elif slot_spec.kind == "measure":
                    vals = val if isinstance(val, list) else [val]
                    for v in vals:
                        if isinstance(v, str):
                            meas_names.append(v.strip("[]"))
                        elif isinstance(v, dict):
                            measure_name = v.get("name") or v.get("measure")
                            if isinstance(measure_name, str) and measure_name.strip():
                                meas_names.append(measure_name.strip())

        vc = VisualCalculation(name=name.strip(), expression=expression.strip())
        error = validate_visual_calculation(vc, dim_cols, meas_names)
        if error:
            return _err(400, error)
        return _ok({"valid": True, "name": vc.name, "expression": vc.expression})

    @app.get("/runtime/format_schema")
    def get_format_schema(visual_type: Optional[str] = None):
        """Return the format option schema, optionally filtered by visual type."""
        if visual_type:
            schema = {
                k: v for k, v in _FORMAT_SCHEMA.items()
                if visual_type in v.get("applies_to", [])
            }
        else:
            schema = dict(_FORMAT_SCHEMA)
        return _ok({"schema": schema, "color_sequences": list(_PLOTLY_COLOR_SEQUENCES.keys())})

    @app.get("/runtime/visual_types/{type_name}/format_options")
    def get_visual_type_format_options(type_name: str):
        """Return format options available for a specific visual type.

        Returns a structured list of options with key, label, type, values/range,
        and default ΓÇö ready for the React UI to render dynamic controls.
        """
        type_lower = type_name.strip().lower()
        options: list[dict[str, Any]] = []
        for key, schema_entry in _FORMAT_SCHEMA.items():
            applies_to = schema_entry.get("applies_to", [])
            if type_lower not in applies_to:
                continue
            opt: dict[str, Any] = {
                "key": key,
                "label": schema_entry.get("label", key),
                "type": schema_entry.get("type", "string"),
                "default": schema_entry.get("default"),
                "category": schema_entry.get("category", ""),
            }
            if "options" in schema_entry:
                opt["values"] = schema_entry["options"]
            if "min" in schema_entry:
                opt["min"] = schema_entry["min"]
            if "max" in schema_entry:
                opt["max"] = schema_entry["max"]
            options.append(opt)
        return _ok({"type": type_lower, "options": options})

    @app.post("/runtime/pages")
    def create_page(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Create a new page.  Assigns a unique page ID and persists to pages.yaml."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        title = str(payload.get("title") or "").strip()
        if not title:
            title = f"Page {len(pages) + 1}"

        # Validate page title
        try:
            _validate_safe_name(title, label="page title")
        except ValueError as e:
            return _err(400, str(e))
        existing_ids = {getattr(p, "id", "").upper() for p in pages}
        page_id = str(payload.get("id") or "").strip()
        if not page_id:
            for n in range(1, 10_000):
                cand = f"page{n}"
                if cand.upper() not in existing_ids:
                    page_id = cand
                    break
            else:
                import uuid as _uuid
                page_id = "page_" + _uuid.uuid4().hex[:8]
        elif page_id.upper() in existing_ids:
            return _err(400, f"Page id already exists: {page_id!r}")

        # Compute order: max existing order + 1.
        max_order = max((getattr(p, "order", 0) or 0 for p in pages), default=0)
        order = max_order + 1

        new_page = {"id": page_id, "title": title, "order": order}
        new_page_type = str(payload.get("page_type") or "").strip()
        if new_page_type:
            new_page["page_type"] = new_page_type
        all_pages = []
        for p in pages:
            entry = {"id": getattr(p, "id", ""), "title": getattr(p, "title", ""), "order": getattr(p, "order", None)}
            if getattr(p, "hidden", False):
                entry["hidden"] = True
            pt = getattr(p, "page_type", None)
            if pt:
                entry["page_type"] = pt
            all_pages.append(entry)
        all_pages.append(new_page)

        try:
            save_pages(project_path, all_pages)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        return _ok(new_page)

    @app.put("/runtime/pages/reorder")
    def reorder_pages(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Reorder pages.  Expects ``{page_ids: ["page2", "page1", ...]}``."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        page_ids = payload.get("page_ids")
        if not isinstance(page_ids, list) or not page_ids:
            return _err(400, "page_ids must be a non-empty list")

        # Build lookup from loaded pages.
        lookup: dict[str, dict[str, Any]] = {}
        for p in pages:
            pid = getattr(p, "id", "")
            entry: dict[str, Any] = {"id": pid, "title": getattr(p, "title", "")}
            if getattr(p, "hidden", False):
                entry["hidden"] = True
            pt = getattr(p, "page_type", None)
            if pt:
                entry["page_type"] = pt
            lookup[pid.upper()] = entry

        # Validate all IDs are present and no duplicates/missing.
        seen: set[str] = set()
        reordered: list[dict[str, Any]] = []
        for i, pid in enumerate(page_ids):
            if not isinstance(pid, str) or not pid.strip():
                return _err(400, f"page_ids[{i}] must be a non-empty string")
            key = pid.strip().upper()
            if key in seen:
                return _err(400, f"Duplicate page id in reorder: {pid!r}")
            seen.add(key)
            if key not in lookup:
                return _err(400, f"Unknown page id: {pid!r}")
            entry = dict(lookup[key])
            entry["order"] = i + 1
            reordered.append(entry)

        if len(reordered) != len(pages):
            return _err(400, "page_ids must contain all existing page ids")

        try:
            save_pages(project_path, reordered)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        return _ok({"pages": reordered})

    @app.put("/runtime/pages/{page_id}")
    def update_page(page_id: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Rename a page (update title and/or order)."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        page_id_norm = page_id.strip().upper()
        found = False
        all_pages: list[dict[str, Any]] = []
        for p in pages:
            entry = {"id": getattr(p, "id", ""), "title": getattr(p, "title", ""), "order": getattr(p, "order", None)}
            if getattr(p, "hidden", False):
                entry["hidden"] = True
            pt = getattr(p, "page_type", None)
            if pt:
                entry["page_type"] = pt
            if getattr(p, "id", "").upper() == page_id_norm:
                found = True
                new_title = payload.get("title")
                if new_title is not None:
                    if not isinstance(new_title, str) or not new_title.strip():
                        return _err(400, "title must be a non-empty string")
                    entry["title"] = new_title.strip()
                new_order = payload.get("order")
                if new_order is not None:
                    if not isinstance(new_order, int):
                        return _err(400, "order must be an integer")
                    entry["order"] = new_order
                new_hidden = payload.get("hidden")
                if new_hidden is not None:
                    entry["hidden"] = bool(new_hidden)
                new_page_type = payload.get("page_type")
                if new_page_type is not None:
                    if new_page_type:
                        entry["page_type"] = str(new_page_type).strip()
                    else:
                        entry.pop("page_type", None)
            all_pages.append(entry)

        if not found:
            return _err(404, f"Page not found: {page_id!r}")

        try:
            save_pages(project_path, all_pages)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        updated = next(p for p in all_pages if p["id"].upper() == page_id_norm)
        return _ok(updated)

    @app.delete("/runtime/pages/{page_id}")
    def delete_page(page_id: str, project: Optional[str] = None):
        """Delete a page.  Refuses if it is the only page."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        if len(pages) <= 1:
            return _err(400, "Cannot delete the last page")

        page_id_norm = page_id.strip().upper()
        remaining = []
        for p in pages:
            if getattr(p, "id", "").upper() == page_id_norm:
                continue
            entry: dict[str, Any] = {"id": getattr(p, "id", ""), "title": getattr(p, "title", ""), "order": getattr(p, "order", None)}
            if getattr(p, "hidden", False):
                entry["hidden"] = True
            pt = getattr(p, "page_type", None)
            if pt:
                entry["page_type"] = pt
            remaining.append(entry)
        if len(remaining) == len(pages):
            return _err(404, f"Page not found: {page_id!r}")

        try:
            save_pages(project_path, remaining)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        return _ok({"id": page_id, "remaining": len(remaining)})

    def _get_visual_result_rows(
        *,
        project_path: str,
        visual_id: str,
        duckdb_path: Optional[str],
        runtime_filters: Optional[list[dax_compiler.ScopedFilter]] = None,
        requested_role: Optional[str] = None,
        visual_override: Optional[dict[str, Any]] = None,
        drill_level: int | None = None,
        drill_filters: list[dict[str, Any]] | None = None,
        expand_levels: int = 1,
    ) -> tuple[
        str,
        dict[str, Any],
        Mapping[str, Any],
        Mapping[str, Any],
        list[str],
        list[tuple[Any, ...]],
        str,
        float,
        float,
        list[dict[str, Any]],
        Any,
    ]:
        """Plan + execute the visual query and return result rows.

        Args:
            visual_override: If provided, use this visual definition instead of
                loading from disk.  This allows rendering unsaved (client-only)
                visuals before the user clicks Save All.

        Returns:
                    (visual_type, visual_json, registry, resolved_encodings, columns, rows, sql, execution_ms, plan_ms, filters_meta, table_ir)
        """

        _ensure_mapping_loaded()

        if visual_override is not None:
            visual = visual_override
        else:
            visual = _load_visual_json(project_path, visual_id)
        visual_type = str(visual.get("visual_type") or visual.get("type") or "").strip()
        if not visual_type:
            raise ValueError("visual.visual_type is required")

        encodings = visual.get("encodings") or {}
        if not isinstance(encodings, Mapping):
            raise ValueError("visual.encodings must be an object")

        registry = load_visual_type_registry(project_path)
        vt = registry.get(visual_type)
        if vt is None:
            raise ValueError(f"Unknown visual_type: {visual_type!r}")

        # Validate required slots.
        for slot_name, slot_spec in vt.slots.items():
            if slot_spec.required and not _slot_value_present(encodings.get(slot_name)):
                raise ValueError(f"Missing required encoding slot: {slot_name}")

        model, _pages, _visuals = load_project(project_path)
        role_name = resolve_role_name(model, requested_role)
        role = get_role(model, role_name)
        model_scoped = apply_ols(model, role)

        hidden_refs = _ols_hidden_refs_for_visual(model_full=model, model_scoped=model_scoped, visual_json=visual)
        if hidden_refs:
            raise OlsVisualBlockedError(
                "Visual is blocked by the active security role (OLS).",
                hidden_refs=hidden_refs,
            )
        param_values = visual.get("param_values")
        if param_values is not None and not isinstance(param_values, Mapping):
            raise ValueError("visual.param_values must be an object if provided")
        legacy_calc_groups = visual.get("calc_groups")
        if legacy_calc_groups is not None and not isinstance(legacy_calc_groups, Mapping):
            raise ValueError("visual.calc_groups must be an object if provided")

        # Phase 2.1: calc-group selections are persisted as report/page/visual state.
        # For back-compat, visual.calc_groups (if present) behaves as a visual-scope override.
        sel_payload = load_calc_group_selections(project_path)
        eff = resolve_effective_calc_group_selections(
            sel_payload,
            page_id=str(visual.get("page_id") or "") or None,
            visual_id=visual_id,
        )
        if legacy_calc_groups:
            for g, it in legacy_calc_groups.items():
                if isinstance(g, str) and g.strip() and isinstance(it, str) and it.strip():
                    eff[g.strip()] = it.strip()

        calc_groups_effective: Optional[Mapping[str, str]] = eff if eff else None
        if calc_groups_effective:
            flat_sel = [{"group": g, "item": it} for g, it in calc_groups_effective.items()]
            _validate_calc_group_selections_against_model(model_scoped, flat_sel)

        # Phase 2.2: field-parameter selections are persisted as report/page/visual state.
        # For back-compat, visual.param_values (if present) behaves as a visual-scope override.
        fp_payload = load_field_parameter_selections(project_path)
        fp_eff = resolve_effective_field_parameter_selections(
            fp_payload,
            page_id=str(visual.get("page_id") or "") or None,
            visual_id=visual_id,
        )
        if param_values:
            for p, v in param_values.items():
                if isinstance(p, str) and p.strip() and isinstance(v, str) and v.strip():
                    fp_eff[p.strip()] = v.strip()

        param_values_effective_any: Optional[Mapping[str, Any]] = fp_eff if fp_eff else None
        if param_values_effective_any:
            flat_fp: list[dict[str, Any]] = []
            for p, v in fp_eff.items():
                if isinstance(p, str) and p.strip():
                    if isinstance(v, list):
                        flat_fp.append({"scope": "visual", "target": visual_id, "param": p, "values": list(v)})
                    else:
                        flat_fp.append({"scope": "visual", "target": visual_id, "param": p, "value": v})
            _validate_field_parameter_selections_against_model(model_scoped, flat_fp)

        # Planner currently expects single-select param values. Since we resolve ParamRefs in
        # spec-building, we only pass the first selection (if multi) for back-compat.
        param_values_effective_single: Optional[Mapping[str, str]] = None
        if param_values_effective_any:
            single: dict[str, str] = {}
            for p, v in param_values_effective_any.items():
                if not isinstance(p, str) or not p.strip():
                    continue
                if isinstance(v, list):
                    first = next((x for x in v if isinstance(x, str) and x.strip()), None)
                    if first:
                        single[p.strip()] = first.strip()
                elif isinstance(v, str) and v.strip():
                    single[p.strip()] = v.strip()
            param_values_effective_single = single if single else None

        # Phase 2.3: What-If parameter selections are persisted as report/page/visual state.
        wip_payload = load_what_if_selections(project_path)
        wip_eff = resolve_effective_what_if_selections(
            wip_payload,
            page_id=str(visual.get("page_id") or "") or None,
            visual_id=visual_id,
        )
        what_if_values_effective: Optional[Mapping[str, float]] = wip_eff if wip_eff else None
        if what_if_values_effective:
            flat_wip = [
                {"scope": "visual", "target": visual_id, "param": p, "value": v}
                for p, v in what_if_values_effective.items()
            ]
            _validate_what_if_selections_against_model(model_scoped, flat_wip)

        resolved_encodings = _resolve_encodings_for_output(
            model=model_scoped,
            encodings=encodings,
            param_values=param_values_effective_any,
            drill_level=drill_level,
        )

        applied_filters_meta: list[dict[str, Any]] = []

        # ── Tier 4: SQL plan cache — skip _ENGINE_LOCK on cache hit ──
        _sql_cache_sig = _project_signature(project_path)
        _sql_cache_key = _sql_cache.build_key(
            visual_id=visual_id,
            project_path=project_path,
            role=role_name,
            runtime_filters=runtime_filters or [],
            visual_json=visual,
            engine_sig=_sql_cache_sig,
            drill_level=drill_level,
            drill_filters=drill_filters,
        )
        _cached_plan = _sql_cache.get(_sql_cache_key)

        if _cached_plan is not None:
            # Cache hit — skip _ENGINE_LOCK entirely
            sql = _cached_plan.sql
            table_ir = _cached_plan.table_ir
            applied_filters_meta = _cached_plan.applied_filters_meta
            plan_ms = 0.0  # plan was cached
        else:
            _plan_t0 = time.perf_counter()
            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

                # Build What-If values for context (compiler will resolve WhatIfRef from context).
                wip_for_compile: dict[str, float] = {}
                if what_if_values_effective:
                    for k, v in what_if_values_effective.items():
                        if isinstance(k, str) and k.strip():
                            wip_for_compile[k.strip().upper()] = float(v) if isinstance(v, (int, float)) else 0.0
                # Also add defaults from model for any params not in selections.
                wip_defs = getattr(model_scoped, "what_if_parameters", {}) or {}
                for wip_name, wip_obj in wip_defs.items():
                    norm_name = str(wip_name).strip().upper()
                    if norm_name and norm_name not in wip_for_compile:
                        default_val = getattr(wip_obj, "default_value", None)
                        if default_val is None:
                            default_val = getattr(wip_obj, "default", 0)
                        wip_for_compile[norm_name] = float(default_val) if isinstance(default_val, (int, float)) else 0.0

                # Create context with What-If values (no global mutation).
                ctx = dax_compiler.Context(what_if_values=wip_for_compile)
                sec = _compile_rls_security_predicates(role=role, base_ctx=ctx)
                if sec:
                    ctx = ctx.apply_security_predicates(sec)
                if runtime_filters:
                    from dax_engine.filters_ir import apply_scoped_filters_to_context

                    interactions = visual.get("interactions")
                    is_affected = True
                    if isinstance(interactions, Mapping):
                        is_affected = bool(interactions.get("is_affected", True))

                    effective_filters = list(runtime_filters)
                    if not is_affected:
                        effective_filters = [
                            f for f in effective_filters if str(getattr(f, "scope", "")).strip().lower() != "interaction"
                        ]

                    # Apply hierarchy drill filters as visual-scoped runtime filters
                    if drill_filters:
                        from dax_engine.ir import ColumnRef as _ColRef
                        from dax_engine.ir import FilterCondition as _FC
                        from dax_engine.ir import Literal as _Lit
                        from dax_engine.ir import ScopedFilter as _SF

                        for df in drill_filters:
                            tbl = str(df.get("table") or "").strip()
                            col = str(df.get("column") or "").strip()
                            val = df.get("value")
                            if tbl and col and val is not None:
                                effective_filters.append(
                                    _SF(
                                        scope="visual",
                                        condition=_FC(
                                            column=_ColRef(table=tbl, column=col),
                                            operator="eq",
                                            values=[_Lit(val)],
                                        ),
                                        target=visual_id,
                                        source="drill",
                                    )
                                )

                    ctx, applied_filters_meta = apply_scoped_filters_to_context(
                        ctx,
                        effective_filters,
                        page_id=str(visual.get("page_id") or "") or None,
                        visual_id=visual_id,
                    )

                if visual_type == "card":
                    value_expr = encodings.get("value")
                    if value_expr is None:
                        raise ValueError("card requires encodings.value")
                    measure_expr = parse_expr(value_expr)
                    from dax_engine.ir import ParamRef as _ParamRef

                    if isinstance(measure_expr, _ParamRef):
                        fps = getattr(model_scoped, "field_parameters", {}) or {}
                        fp = fps.get(measure_expr.name)
                        if fp is None:
                            fp = next(
                                (x for k, x in fps.items() if str(getattr(x, "name", k) or "").strip().upper() == measure_expr.name.upper()),
                                None,
                            )
                        if fp is None:
                            raise ValueError(f"Unknown field parameter: {measure_expr.name!r}")

                        sel_key: Optional[str] = None
                        if param_values_effective_any is not None:
                            raw = param_values_effective_any.get(measure_expr.name)
                            if isinstance(raw, list):
                                sel_key = next((x for x in raw if isinstance(x, str) and x.strip()), None)
                            elif isinstance(raw, str) and raw.strip():
                                sel_key = raw

                        if not sel_key:
                            # Try new attribute name first, then legacy
                            default_key = str(getattr(fp, "default_item", "") or getattr(fp, "default", "") or "").strip()
                            if default_key:
                                sel_key = default_key
                            else:
                                default_items = getattr(fp, "default_items", None)
                                if isinstance(default_items, list):
                                    sel_key = next((x for x in default_items if isinstance(x, str) and x.strip()), None)

                        if not sel_key:
                            raise ValueError(f"Missing selection for field parameter: {measure_expr.name!r}")

                        # Try new model shape (items with name) first, then legacy (options with key)
                        fp_items = list(getattr(fp, "items", []) or getattr(fp, "options", []) or [])
                        opt = next(
                            (o for o in fp_items if str(getattr(o, "name", "") or getattr(o, "key", "") or "").strip().upper() == sel_key.upper()),
                            None,
                        )
                        if opt is None:
                            raise ValueError(f"Unknown selection for field parameter {measure_expr.name!r}: {sel_key!r}")
                        measure_expr = getattr(opt, "ref", None) or getattr(opt, "expr", None)
                        if not isinstance(measure_expr, MeasureRef):
                            raise ValueError(
                                f"card encodings.value must resolve to a measure; got {type(measure_expr).__name__}"
                            )
                    if not isinstance(measure_expr, MeasureRef):
                        # Allow ParamRef but planner will resolve.
                        pass
                    table_ir, sql = plan_card_query(
                        measure_expr,  # type: ignore[arg-type]
                        filters=[],
                        model=model_scoped,
                        calc_groups=calc_groups_effective,  # type: ignore[arg-type]
                        param_values=param_values_effective_single,
                        what_if_values=what_if_values_effective,
                        ctx=ctx,
                    )
                else:
                    spec = _build_spec_from_encodings(
                        model=model_scoped,
                        registry=registry,
                        visual_type=visual_type,
                        encodings=encodings,
                        param_values=param_values_effective_any,
                        drill_level=drill_level,
                        drill_filters=drill_filters,
                        expand_levels=expand_levels,
                        sort_entries=visual.get("sort"),
                        query_options=visual.get("query_options"),
                    )
                    table_ir, sql = plan_visual_query(
                        spec,
                        ctx=ctx,
                        model=model_scoped,
                        param_values=param_values_effective_single,
                        calc_groups=calc_groups_effective,  # type: ignore[arg-type]
                        what_if_values=what_if_values_effective,
                    )

                    # Visual calculations: wrap base SQL with window functions
                    raw_vcs = visual.get("visual_calculations")
                    if raw_vcs:
                        vcs = parse_visual_calculations(raw_vcs)
                        if vcs:
                            dim_cols = [d.column for d in spec.dimensions]
                            meas_names = [m.name for m in spec.measures]
                            sql = compile_visual_calculations(sql, vcs, dim_cols, meas_names)

            plan_ms = (time.perf_counter() - _plan_t0) * 1000.0

            # Tier 4: cache the SQL plan for future requests
            _sql_cache.put(_sql_cache_key, _SQLPlanEntry(
                sql=sql,
                table_ir=table_ir,
                applied_filters_meta=applied_filters_meta,
                plan_ms=plan_ms,
            ))

        con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model)
        q = dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
        t0 = time.perf_counter()
        cur = con.execute(q)
        cols = [d[0] for d in (cur.description or [])]
        rows = cur.fetchall()
        exec_ms = (time.perf_counter() - t0) * 1000.0
        return (visual_type, visual, registry, resolved_encodings, cols, rows, sql, exec_ms, plan_ms, applied_filters_meta, table_ir)

    @app.post("/runtime/visuals/{visual_id}/render")
    def render_visual(
        visual_id: str,
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        debug_payload = (
            str(request.query_params.get("debug") or "").strip() == "1"
            or str(os.environ.get("DAX_RUNTIME_DEBUG_PAYLOAD") or "").strip() == "1"
        )

        if debug_payload:
            try:
                logger.info(
                    "[debug] render payload: keys=%s render_mode=%s has_interaction_filters=%s has_interactionFilters=%s",
                    sorted(list(payload.keys())) if isinstance(payload, dict) else [],
                    payload.get("render_mode") if isinstance(payload, dict) else None,
                    bool(payload.get("interaction_filters")) if isinstance(payload, dict) else False,
                    bool(payload.get("interactionFilters")) if isinstance(payload, dict) else False,
                )
            except Exception:
                pass

        # Accept inline visual definition from the client for unsaved visuals
        # (created client-side but not yet persisted via Save All).
        visual_definition: Optional[dict[str, Any]] = None
        if isinstance(payload, dict):
            vd = payload.get("visual_definition")
            if isinstance(vd, dict):
                visual_definition = vd

        # Early check: if this is a matrix visual, delegate to render_matrix
        # Also: static visuals (button, shape, textbox, image, group) have no
        # data encodings — return an empty render response immediately.
        _STATIC_RENDER_TYPES = {"button", "shape", "textbox", "image", "group", "actionbutton", "slicer"}
        try:
            visual_json = _load_visual_json(project_path, visual_id)
            vtype = str(visual_json.get("visual_type") or visual_json.get("type") or "").strip().lower()
            if vtype in _STATIC_RENDER_TYPES:
                return {
                    "visual_id": visual_id,
                    "visual_type": vtype,
                    "columns": [],
                    "rows": [],
                    "query": {"sql": "", "row_count": 0, "execution_ms": 0, "plan_ms": 0, "filters": []},
                    "static": True,
                }
            if vtype == "matrix":
                return render_matrix(
                    visual_id=visual_id,
                    request=request,
                    project=project,
                    duckdb_path=duckdb_path,
                    payload=payload,
                )
        except FileNotFoundError:
            if visual_definition is not None:
                visual_json = visual_definition
                vtype = str(visual_json.get("visual_type") or visual_json.get("type") or "").strip().lower()
                if vtype in _STATIC_RENDER_TYPES:
                    return {
                        "visual_id": visual_id,
                        "visual_type": vtype,
                        "columns": [],
                        "rows": [],
                        "query": {"sql": "", "row_count": 0, "execution_ms": 0, "plan_ms": 0, "filters": []},
                        "static": True,
                    }
                if vtype == "matrix":
                    return render_matrix(
                        visual_id=visual_id,
                        request=request,
                        project=project,
                        duckdb_path=duckdb_path,
                        payload=payload,
                    )
            else:
                return _err(404, f"Visual not found: {visual_id!r}")
        except Exception:
            # If we can't load the visual, let the normal flow handle the error
            pass

        def _section(*, cols: list[str], rows: list[Any], sql: str, exec_ms: float, plan_ms: float = 0.0, filters_meta: list[dict[str, Any]], ir_node: Any = None):
            cols_out = list(cols)
            rows_out = [dict(zip(cols_out, r)) for r in rows[:50]]
            query: dict[str, Any] = {
                "sql": sql,
                "row_count": len(rows),
                "execution_ms": exec_ms,
                "plan_ms": plan_ms,
                "filters": filters_meta,
            }
            if ir_node is not None:
                try:
                    query["ir"] = ir_to_dict(ir_node)
                except Exception:
                    query["ir"] = repr(ir_node)
            return cols_out, rows_out, query

        render_mode = str(payload.get("render_mode") or "normal").strip().lower()
        requested_role = _role_from_request(request=request, payload=payload)

        sql: Optional[str] = None
        applied_filters_meta: list[dict[str, Any]] = []

        # Normal mode (default): current behavior.
        if render_mode != "highlight":
            try:
                runtime_filters = _parse_scoped_filters_payload(
                    payload.get("filters"),
                    project_path=project_path,
                )

                # Build scoped security state once for slicer-default evaluation. (The visual render path
                # will also validate OLS and apply RLS separately when planning/executing the visual.)
                model_for_slicers, _pages_for_slicers, _visuals_for_slicers = load_project(project_path)
                sec_state_for_slicers = _build_runtime_security_state(
                    project_path=project_path,
                    model=model_for_slicers,
                    request=request,
                    payload=payload,
                )

                # Slicers are persistent filter state. If the client sends slicer_defs (unsaved state),
                # use it; otherwise fall back to persisted slicer defs.
                try:
                    defs_obj = _normalize_slicer_defs_payload(payload.get("slicer_defs") if isinstance(payload, Mapping) else None)
                    if not (defs_obj.get("defs") or []):
                        defs_obj = load_slicer_defs(project_path)
                    slicer_filter_payload = _materialize_slicer_defs_to_filter_payload_items(
                        defs_obj,
                        project_path=project_path,
                        model=model_for_slicers,
                        sec_state=sec_state_for_slicers,
                        duckdb_path=duckdb_path,
                        runtime_filters=list(runtime_filters),
                        page_id=None,
                        visual_id=str(visual_id),
                    )
                    slicer_filters = _parse_scoped_filters_payload(
                        slicer_filter_payload,
                        project_path=project_path,
                    )
                    runtime_filters = list(runtime_filters) + list(slicer_filters)
                except Exception as exc:
                    code = _slicer_error_code_from_exc(exc, default="E_SLICER_VALUES_FAILED")
                    return _err(400, str(exc), error_code=code, details={"visual_id": visual_id})

                # Chart drill state from payload
                chart_drill_level: int | None = None
                chart_drill_filters: list[dict[str, Any]] | None = None
                chart_expand_levels: int = 1
                if isinstance(payload, dict):
                    raw_dl = payload.get("drill_level")
                    if raw_dl is not None:
                        try:
                            chart_drill_level = int(raw_dl)
                        except (TypeError, ValueError):
                            pass
                    raw_df = payload.get("drill_filters")
                    if isinstance(raw_df, list):
                        chart_drill_filters = raw_df
                    raw_el = payload.get("expand_levels")
                    if raw_el is not None:
                        try:
                            chart_expand_levels = max(1, int(raw_el))
                        except (TypeError, ValueError):
                            pass

                visual_type, visual, registry, resolved_encodings, cols, rows, sql, exec_ms, plan_ms, applied_filters_meta, table_ir = _get_visual_result_rows(
                    project_path=project_path,
                    visual_id=visual_id,
                    duckdb_path=duckdb_path,
                    runtime_filters=runtime_filters,
                    requested_role=requested_role,
                    # Performance: pass the already-loaded visual JSON to avoid
                    # a redundant disk read inside _get_visual_result_rows.
                    # Prefer client-sent inline definition; fall back to the
                    # visual_json we loaded earlier for the type check.
                    visual_override=visual_definition if visual_definition is not None else visual_json,
                    drill_level=chart_drill_level,
                    drill_filters=chart_drill_filters,
                    expand_levels=chart_expand_levels,
                )
            except FileNotFoundError:
                return _err(404, f"Visual not found: {visual_id!r}")
            except OlsVisualBlockedError as exc:
                details: dict[str, Any] = {"visual_id": visual_id, "role": requested_role}
                if debug_payload:
                    details["hidden_refs"] = list(exc.hidden_refs)
                return _err(400, str(exc), code="OLS_BLOCKED", details=details)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Visual render failed: id=%s project=%s error=%s",
                    visual_id,
                    project_path,
                    str(exc),
                )
                return _err(400, str(exc), sql=sql, details={"visual_id": visual_id})

            cols_out, rows_out, query = _section(
                cols=list(cols),
                rows=list(rows),
                sql=str(sql or ""),
                exec_ms=float(exec_ms),
                plan_ms=float(plan_ms),
                filters_meta=applied_filters_meta,
                ir_node=table_ir,
            )

            graphic_cols_out: list[str] | None = None
            graphic_rows_out: list[dict[str, Any]] | None = None
            graphic_query: dict[str, Any] | None = None
            decision_overlays_out: list[Any] | None = None
            pack_summary_out: dict[str, Any] | None = None
            overlay_meta_out: dict[str, Any] | None = None
            if str(visual_type).strip().lower() == "ibcs_card":
                try:
                    vd_has_decision_overlays = isinstance(visual_definition, Mapping) and "decision_overlays" in visual_definition
                    vd_has_pack_summary = isinstance(visual_definition, Mapping) and "pack_summary" in visual_definition
                    vd_has_overlay_meta = isinstance(visual_definition, Mapping) and "overlay_meta" in visual_definition

                    if isinstance(visual, Mapping):
                        _decision_overlays = visual.get("decision_overlays")
                        if isinstance(_decision_overlays, list):
                            decision_overlays_out = list(_decision_overlays)

                        _pack_summary = visual.get("pack_summary")
                        if isinstance(_pack_summary, Mapping):
                            pack_summary_out = dict(_pack_summary)

                        _overlay_meta = visual.get("overlay_meta")
                        if isinstance(_overlay_meta, Mapping):
                            overlay_meta_out = dict(_overlay_meta)

                    # When inline visual_definition is sent from the client, it may omit
                    # additive overlay envelope fields. In that case, recover them from the
                    # persisted visual JSON to keep overlay rendering stable for saved visuals.
                    if (
                        (decision_overlays_out is None and not vd_has_decision_overlays)
                        or (pack_summary_out is None and not vd_has_pack_summary)
                        or (overlay_meta_out is None and not vd_has_overlay_meta)
                    ):
                        try:
                            persisted_visual = _load_visual_json(project_path, visual_id)
                            if isinstance(persisted_visual, Mapping):
                                if decision_overlays_out is None and not vd_has_decision_overlays:
                                    persisted_decision_overlays = persisted_visual.get("decision_overlays")
                                    if isinstance(persisted_decision_overlays, list):
                                        decision_overlays_out = list(persisted_decision_overlays)

                                if pack_summary_out is None and not vd_has_pack_summary:
                                    persisted_pack_summary = persisted_visual.get("pack_summary")
                                    if isinstance(persisted_pack_summary, Mapping):
                                        pack_summary_out = dict(persisted_pack_summary)

                                if overlay_meta_out is None and not vd_has_overlay_meta:
                                    persisted_overlay_meta = persisted_visual.get("overlay_meta")
                                    if isinstance(persisted_overlay_meta, Mapping):
                                        overlay_meta_out = dict(persisted_overlay_meta)
                        except Exception:
                            pass

                    if isinstance(decision_overlays_out, list):
                        def _signal_token(value: Any) -> str:
                            return "".join(ch for ch in str(value).lower() if ch.isalnum())

                        def _severity_order(value: Any) -> int:
                            token = _signal_token(value)
                            if token == "high":
                                return 3
                            if token == "medium":
                                return 2
                            if token == "low":
                                return 1
                            return 0

                        def _first_string(*values: Any) -> str:
                            for raw in values:
                                if isinstance(raw, str):
                                    val = raw.strip()
                                    if val:
                                        return val
                            return ""

                        def _canonical_data_sufficiency(value: Any) -> str:
                            token = _signal_token(value)
                            if token == "ok":
                                return "OK"
                            if token in {"unknown"}:
                                return "Unknown"
                            if token in {"shorthistory", "historyshort"}:
                                return "Short History"
                            if token in {"missingartifact", "artifactmissing"}:
                                return "Missing Artifact"
                            if token in {"rolerestricted", "restrictedbyrole"}:
                                return "Role Restricted"
                            return _first_string(value)

                        def _canonical_impact_level(value: Any) -> str:
                            token = _signal_token(value)
                            if token == "critical":
                                return "Critical"
                            if token in {"significant", "high"}:
                                return "Significant"
                            if token in {"moderate", "medium"}:
                                return "Moderate"
                            if token == "low":
                                return "Low"
                            return _first_string(value)

                        def _canonical_stability_badge(value: Any) -> str:
                            token = _signal_token(value)
                            if token == "stable":
                                return "Stable"
                            if token == "watch":
                                return "Watch"
                            if token in {"volatile", "unstable"}:
                                return "Volatile"
                            return _first_string(value)

                        sanitized_overlays: list[Any] = []
                        for overlay_item in decision_overlays_out:
                            if not isinstance(overlay_item, Mapping):
                                sanitized_overlays.append(overlay_item)
                                continue

                            overlay_copy = dict(overlay_item)
                            raw_signals = overlay_item.get("signals")
                            normalized_signals: list[dict[str, Any]] = []
                            if isinstance(raw_signals, list):
                                signal_by_token: dict[str, dict[str, Any]] = {}
                                for raw_signal in raw_signals:
                                    if not isinstance(raw_signal, Mapping):
                                        continue
                                    signal_id = _first_string(raw_signal.get("signal_id"), raw_signal.get("signalId"))
                                    if not signal_id:
                                        continue
                                    token = _signal_token(signal_id)
                                    if not token:
                                        continue
                                    normalized_signal = {
                                        "signal_id": signal_id,
                                        "severity": _first_string(raw_signal.get("severity")),
                                    }
                                    existing = signal_by_token.get(token)
                                    if existing is None:
                                        signal_by_token[token] = normalized_signal
                                        continue

                                    existing_score = _severity_order(existing.get("severity"))
                                    candidate_score = _severity_order(normalized_signal.get("severity"))
                                    if candidate_score > existing_score:
                                        signal_by_token[token] = normalized_signal
                                        continue
                                    if candidate_score == existing_score and str(normalized_signal["signal_id"]).lower() < str(existing.get("signal_id") or "").lower():
                                        signal_by_token[token] = normalized_signal

                                deduped_signals = list(signal_by_token.values())
                                has_structural_deterioration = any(
                                    _signal_token(signal.get("signal_id") or "") == "structuraldeterioration"
                                    for signal in deduped_signals
                                )
                                if has_structural_deterioration:
                                    deduped_signals = [
                                        signal
                                        for signal in deduped_signals
                                        if _signal_token(signal.get("signal_id") or "") != "highconfidencegrowth"
                                    ]

                                deduped_signals.sort(
                                    key=lambda signal: (
                                        -_severity_order(signal.get("severity")),
                                        str(signal.get("signal_id") or "").lower(),
                                    )
                                )
                                normalized_signals = deduped_signals[:3]

                            overlay_copy["signals"] = normalized_signals

                            impact_level = _canonical_impact_level(
                                overlay_item.get("impact_level") if isinstance(overlay_item, Mapping) else None
                            )
                            if not impact_level:
                                impact_level = _canonical_impact_level(overlay_item.get("impactLevel") if isinstance(overlay_item, Mapping) else None)

                            data_sufficiency = _canonical_data_sufficiency(
                                overlay_item.get("data_sufficiency") if isinstance(overlay_item, Mapping) else None
                            )
                            if not data_sufficiency:
                                data_sufficiency = _canonical_data_sufficiency(
                                    overlay_item.get("dataSufficiency") if isinstance(overlay_item, Mapping) else None
                                )

                            if data_sufficiency:
                                overlay_copy["data_sufficiency"] = data_sufficiency

                            if data_sufficiency and data_sufficiency != "OK":
                                overlay_copy["impact_level"] = "Low"
                            elif impact_level:
                                overlay_copy["impact_level"] = impact_level

                            stability_badge = _canonical_stability_badge(
                                overlay_item.get("stability_badge") if isinstance(overlay_item, Mapping) else None
                            )
                            if not stability_badge:
                                stability_badge = _canonical_stability_badge(
                                    overlay_item.get("stabilityBadge") if isinstance(overlay_item, Mapping) else None
                                )
                            if stability_badge:
                                overlay_copy["stability_badge"] = stability_badge

                            episode_obj = overlay_item.get("episode") if isinstance(overlay_item.get("episode"), Mapping) else {}
                            evidence_obj = overlay_item.get("evidence") if isinstance(overlay_item.get("evidence"), Mapping) else {}
                            provenance_obj = overlay_item.get("provenance") if isinstance(overlay_item.get("provenance"), Mapping) else {}

                            episode_state = _first_string(
                                overlay_item.get("episode_state"),
                                overlay_item.get("episodeState"),
                                episode_obj.get("episode_state") if isinstance(episode_obj, Mapping) else None,
                                episode_obj.get("state") if isinstance(episode_obj, Mapping) else None,
                            )
                            if episode_state:
                                overlay_copy["episode_state"] = episode_state

                            episode_id = _first_string(
                                overlay_item.get("episode_id"),
                                overlay_item.get("episodeId"),
                                episode_obj.get("episode_id") if isinstance(episode_obj, Mapping) else None,
                                episode_obj.get("id") if isinstance(episode_obj, Mapping) else None,
                            )
                            if episode_id:
                                overlay_copy["episode_id"] = episode_id

                            continuity_key = _first_string(
                                overlay_item.get("continuity_key"),
                                overlay_item.get("continuityKey"),
                                episode_obj.get("continuity_key") if isinstance(episode_obj, Mapping) else None,
                                episode_obj.get("continuityKey") if isinstance(episode_obj, Mapping) else None,
                            )
                            if continuity_key:
                                overlay_copy["continuity_key"] = continuity_key

                            trajectory = _first_string(
                                overlay_item.get("trajectory"),
                                overlay_item.get("episode_trajectory"),
                                overlay_item.get("episodeTrajectory"),
                                episode_obj.get("trajectory") if isinstance(episode_obj, Mapping) else None,
                            )
                            if trajectory:
                                overlay_copy["trajectory"] = trajectory

                            duration_periods = overlay_item.get("duration_periods")
                            if duration_periods is None:
                                duration_periods = overlay_item.get("durationPeriods")
                            if duration_periods is None and isinstance(episode_obj, Mapping):
                                duration_periods = episode_obj.get("duration_periods")
                            if isinstance(duration_periods, (int, float)):
                                overlay_copy["duration_periods"] = int(duration_periods)

                            evidence_bundle_id = _first_string(
                                overlay_item.get("evidence_bundle_id"),
                                overlay_item.get("evidenceBundleId"),
                                evidence_obj.get("bundle_id") if isinstance(evidence_obj, Mapping) else None,
                                evidence_obj.get("evidence_bundle_id") if isinstance(evidence_obj, Mapping) else None,
                            )
                            if evidence_bundle_id:
                                overlay_copy["evidence_bundle_id"] = evidence_bundle_id

                            comparator_snapshot_id = _first_string(
                                overlay_item.get("comparator_snapshot_id"),
                                overlay_item.get("comparatorSnapshotId"),
                                evidence_obj.get("comparator_snapshot_id") if isinstance(evidence_obj, Mapping) else None,
                                evidence_obj.get("snapshot_id") if isinstance(evidence_obj, Mapping) else None,
                            )
                            if comparator_snapshot_id:
                                overlay_copy["comparator_snapshot_id"] = comparator_snapshot_id

                            provenance_id = _first_string(
                                overlay_item.get("provenance_id"),
                                overlay_item.get("provenanceId"),
                                provenance_obj.get("id") if isinstance(provenance_obj, Mapping) else None,
                                evidence_obj.get("provenance_id") if isinstance(evidence_obj, Mapping) else None,
                            )
                            if provenance_id:
                                overlay_copy["provenance_id"] = provenance_id

                            sanitized_overlays.append(overlay_copy)

                        decision_overlays_out = sanitized_overlays

                    fmt = visual.get("format") if isinstance(visual, Mapping) else None
                    fmt_obj = fmt if isinstance(fmt, Mapping) else {}
                    show_graphic = bool(fmt_obj.get("ibcsCardShowGraphic") is True)
                    source_type = str(fmt_obj.get("ibcsCardGraphicSourceType") or "custom").strip().lower()
                    if show_graphic and source_type == "generated":
                        base_enc = visual.get("encodings") if isinstance(visual, Mapping) else None
                        base_enc_obj = base_enc if isinstance(base_enc, Mapping) else {}
                        emb_key_map = {
                            "category": "ibcsCardGraphicEncodingCategory",
                            "ac": "ibcsCardGraphicEncodingAC",
                            "py": "ibcsCardGraphicEncodingPY",
                            "pl": "ibcsCardGraphicEncodingPL",
                            "fc": "ibcsCardGraphicEncodingFC",
                        }
                        # Also support shorthand: format.graphic_encodings.{slot}
                        _ge_shorthand = fmt_obj.get("graphic_encodings")
                        _ge_obj = _ge_shorthand if isinstance(_ge_shorthand, Mapping) else {}
                        graphic_encodings: dict[str, Any] = {}
                        for slot_name, fmt_key in emb_key_map.items():
                            slot_value = fmt_obj.get(fmt_key)
                            if isinstance(slot_value, Mapping):
                                graphic_encodings[slot_name] = dict(slot_value)
                            elif isinstance(_ge_obj.get(slot_name), Mapping):
                                graphic_encodings[slot_name] = dict(_ge_obj.get(slot_name))
                            elif isinstance(base_enc_obj.get(slot_name), Mapping):
                                graphic_encodings[slot_name] = dict(base_enc_obj.get(slot_name))

                        if graphic_encodings:
                            visual_for_graphic = dict(visual)
                            visual_for_graphic["encodings"] = graphic_encodings
                            _g_visual_type, _g_visual, _g_registry, _g_resolved_encodings, g_cols, g_rows, g_sql, g_exec_ms, g_plan_ms, g_filters_meta, g_ir = _get_visual_result_rows(
                                project_path=project_path,
                                visual_id=visual_id,
                                duckdb_path=duckdb_path,
                                runtime_filters=runtime_filters,
                                requested_role=requested_role,
                                visual_override=visual_for_graphic,
                            )
                            graphic_cols_out, graphic_rows_out, graphic_query = _section(
                                cols=list(g_cols),
                                rows=list(g_rows),
                                sql=str(g_sql or ""),
                                exec_ms=float(g_exec_ms),
                                plan_ms=float(g_plan_ms),
                                filters_meta=g_filters_meta,
                                ir_node=g_ir,
                            )
                except Exception as exc:
                    logger.debug(
                        "Embedded card graphic render fallback: id=%s project=%s error=%s",
                        visual_id,
                        project_path,
                        str(exc),
                    )

            # Execute explanation playbooks if ExplanationRef bindings are present
            explanation_result: dict[str, Any] | None = None
            try:
                # Use already-loaded visual (from disk or inline override) instead of
                # re-reading from disk ΓÇö this supports unsaved visuals.
                visual_json_for_expl = visual
                enc_for_expl = visual_json_for_expl.get("encodings") or {}
                expl_refs: list[dict[str, Any]] = []
                for _sn, rv in enc_for_expl.items():
                    vals = rv if isinstance(rv, list) else [rv]
                    for vv in vals:
                        if isinstance(vv, dict) and vv.get("type") == "ExplanationRef":
                            expl_refs.append(vv)
                if expl_refs:
                    # Extract narrative_depth: payload override > ExplanationRef > default
                    _narr_depth = "children"
                    payload_nd = payload.get("narrative_depth") if isinstance(payload, dict) else None
                    if payload_nd in ("children", "leaf", "all"):
                        _narr_depth = payload_nd
                    else:
                        for _er in expl_refs:
                            nd = _er.get("narrative_depth")
                            if nd in ("children", "leaf", "all"):
                                _narr_depth = nd
                                break
                    # Load model for supplementary metric resolution
                    expl_model, _, _ = load_project(project_path)
                    explanation_result = _execute_explanation_bindings(
                        project_path=project_path,
                        expl_refs=expl_refs,
                        query_rows=rows,
                        query_cols=cols,
                        model=expl_model,
                        visual_encodings=enc_for_expl,
                        narrative_depth=_narr_depth,
                        runtime_filters=runtime_filters,
                    )
            except Exception as exc:
                logger.debug("Explanation execution skipped: %s", exc)

            try:
                import pandas as pd

                # SVG-rendered visuals (IBCS) ΓÇö return raw columns+rows, no Plotly figure
                _vt_spec = registry.get(visual_type)
                _vt_renderer = getattr(_vt_spec, "renderer", "") if _vt_spec else ""
                if _vt_renderer == "svg":
                    # ΓöÇΓöÇ Build edu_summary from explanation result ΓöÇΓöÇ
                    edu_summary_out: list[dict[str, Any]] | None = None
                    if explanation_result and isinstance(explanation_result, dict):
                        try:
                            _expl_list = explanation_result.get("explanations", [])
                            _comparator_lbl = explanation_result.get("comparator_label", "budget")
                            _comparator_code_map = {
                                "budget": "BUD", "prior year": "PY",
                                "forecast": "FC", "baseline": "BL",
                            }
                            _comp_code = _comparator_code_map.get(_comparator_lbl, _comparator_lbl.upper())

                            def _collect_drivers(node: dict[str, Any], depth: int = 0) -> list[dict[str, Any]]:
                                """Recursively collect drivers with non-null abs_delta."""
                                result: list[dict[str, Any]] = []
                                children = node.get("children", [])
                                for child in children:
                                    if not isinstance(child, dict):
                                        continue
                                    _label = child.get("metric") or child.get("edu_id") or ""
                                    _delta = child.get("abs_delta")
                                    _rel = child.get("rel_delta")
                                    if _delta is not None:
                                        _drv: dict[str, Any] = {"label": str(_label), "delta": float(_delta)}
                                        if _rel is not None:
                                            _drv["relDelta"] = float(_rel)
                                        result.append(_drv)
                                    elif depth < 2:
                                        # Recurse into grandchildren if child has null delta
                                        result.extend(_collect_drivers(child, depth + 1))
                                return result

                            for _expl_item in _expl_list:
                                if not isinstance(_expl_item, dict):
                                    continue
                                per_row = _expl_item.get("per_row", [])
                                if not per_row:
                                    continue
                                _node = per_row[0] if per_row else None
                                if not isinstance(_node, dict):
                                    continue
                                _drivers = _collect_drivers(_node)

                                # Fallback: if no child drivers found, use root node itself
                                if not _drivers:
                                    _root_delta = _node.get("abs_delta")
                                    _root_rel = _node.get("rel_delta")
                                    _root_label = _node.get("metric") or _node.get("edu_id") or ""
                                    if _root_delta is not None:
                                        _drv_root: dict[str, Any] = {"label": str(_root_label), "delta": float(_root_delta)}
                                        if _root_rel is not None:
                                            _drv_root["relDelta"] = float(_root_rel)
                                        _drivers = [_drv_root]

                                # Collect per-driver narratives from explanation children
                                _child_narratives: dict[str, str] = {}
                                for _child in _node.get("children", []):
                                    if isinstance(_child, dict):
                                        _cn = _child.get("narrative")
                                        _cl = _child.get("metric") or _child.get("edu_id") or ""
                                        if _cn and _cl:
                                            _child_narratives[str(_cl)] = str(_cn)
                                # Attach narrative to each driver
                                for _drv in _drivers:
                                    _dn = _child_narratives.get(_drv.get("label", ""))
                                    if _dn:
                                        _drv["narrative"] = _dn

                                # Sort by |delta| descending, take top 3
                                _drivers.sort(key=lambda d: abs(d.get("delta", 0)), reverse=True)
                                _drivers = _drivers[:3]
                                if _drivers:
                                    if edu_summary_out is None:
                                        edu_summary_out = []
                                    # Root narrative from the top-level node
                                    _root_narrative = _node.get("narrative") or ""
                                    _edu_entry: dict[str, Any] = {
                                        "comparator": _comp_code,
                                        "drivers": _drivers,
                                    }
                                    if _root_narrative:
                                        _edu_entry["narrative"] = str(_root_narrative)
                                    edu_summary_out.append(_edu_entry)
                        except Exception as _edu_exc:
                            logger.debug("edu_summary extraction failed: %s", _edu_exc)

                    return {
                        "ok": True,
                        "sql": sql,
                        "query": query,
                        "columns": cols_out,
                        "rows": rows_out,
                        **({"graphic_columns": graphic_cols_out, "graphic_rows": graphic_rows_out, "graphic_query": graphic_query} if graphic_cols_out is not None and graphic_rows_out is not None else {}),
                        **({"decision_overlays": decision_overlays_out} if decision_overlays_out is not None else {}),
                        **({"pack_summary": pack_summary_out} if pack_summary_out is not None else {}),
                        **({"overlay_meta": overlay_meta_out} if overlay_meta_out is not None else {}),
                        **({"explanation": explanation_result} if explanation_result else {}),
                        **({"edu_summary": edu_summary_out} if edu_summary_out else {}),
                    }

                advanced_patch_raw = visual.get("advanced_plotly_patch")
                advanced_patch: Optional[Mapping[str, Any]] = None
                if advanced_patch_raw is not None:
                    if not isinstance(advanced_patch_raw, Mapping):
                        return _err(400, "advanced_plotly_patch must be an object")
                    try:
                        advanced_patch = _json_safe_with_path(
                            advanced_patch_raw,
                            path="$.advanced_plotly_patch",
                            strict=True,
                        )
                    except TypeError as exc:
                        return _err(
                            400,
                            f"advanced_plotly_patch must be JSON-serializable; {exc}",
                        )

                df = pd.DataFrame.from_records(rows, columns=cols_out)

                # ── Multi-level label concatenation for "Expand All Down One Level" ──
                # When expand_levels > 1, multiple hierarchy columns appear as dims.
                # Concatenate them into a single column for the Plotly x-axis.
                if chart_expand_levels > 1:
                    _enc_raw = visual.get("encodings") or {}
                    _h_cols: list[str] = []
                    for _slot_val in _enc_raw.values():
                        _vals = _slot_val if isinstance(_slot_val, list) else [_slot_val]
                        for _vv in _vals:
                            if isinstance(_vv, dict) and str(_vv.get("type", "")).strip() == "HierarchyRef":
                                _h_name = str(_vv.get("name", "")).strip()
                                if _h_name:
                                    _model_h = getattr(model_for_slicers, "hierarchies", {}) or {}
                                    _h_lower = {k.lower(): v for k, v in _model_h.items()}
                                    _hobj = _h_lower.get(_h_name.lower())
                                    if _hobj:
                                        base_idx = min(chart_drill_level or 0, len(_hobj.levels) - 1)
                                        for offset in range(chart_expand_levels):
                                            idx = base_idx + offset
                                            if idx >= len(_hobj.levels):
                                                break
                                            _h_cols.append(_hobj.levels[idx].column)
                    if len(_h_cols) > 1:
                        # All hierarchy columns must exist in the DataFrame
                        _existing_h_cols = [c for c in _h_cols if c in df.columns]
                        if len(_existing_h_cols) > 1:
                            first_col = _existing_h_cols[0]
                            extra_cols = _existing_h_cols[1:]
                            # Concatenate: "Year Quarter" → "2023 Q1"
                            df[first_col] = df[_existing_h_cols].astype(str).agg(' '.join, axis=1)
                            # Drop the extra columns so the chart only sees the concatenated one
                            df = df.drop(columns=extra_cols)
                            # Also update cols_out
                            cols_out = [c for c in cols_out if c not in extra_cols]

                # Load reporting theme colors + font (if available)
                _theme_colors: list[str] | None = None
                _theme_font: str | None = None
                try:
                    _theme_path = Path(project_path) / "reports" / "reporting_theme.json"
                    if _theme_path.exists():
                        import json as _json_theme
                        with open(_theme_path, "r", encoding="utf-8") as _tf:
                            _theme_data = _json_theme.load(_tf)
                        _dc = _theme_data.get("dataColors")
                        if isinstance(_dc, list) and _dc:
                            _theme_colors = _dc
                        _ff = _theme_data.get("font", {}).get("family")
                        if isinstance(_ff, str) and _ff:
                            _theme_font = _ff
                except Exception:
                    pass  # theme loading is best-effort

                _fmt_for_render = _with_imported_category_sort(visual, visual_type)

                fig = _render_plotly_figure(
                    visual_type=visual_type,
                    registry=registry,
                    df=df,
                    resolved_encodings=resolved_encodings,
                    advanced_patch=advanced_patch,
                    format_options=_fmt_for_render,
                    theme_colors=_theme_colors,
                    theme_font=_theme_font,
                )

                # Build hierarchy drill metadata for the frontend
                drill_meta: dict[str, Any] | None = None
                try:
                    _enc_raw = visual.get("encodings") or {}
                    _h_map_names: list[str] = []
                    for _slot_val in _enc_raw.values():
                        _vals = _slot_val if isinstance(_slot_val, list) else [_slot_val]
                        for _vv in _vals:
                            if isinstance(_vv, dict) and str(_vv.get("type", "")).strip() == "HierarchyRef":
                                _h_name = str(_vv.get("name", "")).strip()
                                if _h_name:
                                    _h_map_names.append(_h_name)
                    if _h_map_names:
                        _model_h = getattr(model_for_slicers, "hierarchies", {}) or {}
                        _h_lower = {k.lower(): v for k, v in _model_h.items()}
                        _levels_info: list[dict[str, Any]] = []
                        for _hn in _h_map_names:
                            _hobj = _h_lower.get(_hn.lower())
                            if _hobj:
                                _levels_info = [
                                    {"column": lvl.column, "name": getattr(lvl, "name", lvl.column)}
                                    for lvl in _hobj.levels
                                ]
                                _cur_level = chart_drill_level or 0
                                _exp_count = chart_expand_levels or 1
                                drill_meta = {
                                    "hierarchy_name": _hobj.name,
                                    "table": _hobj.table,
                                    "levels": _levels_info,
                                    "current_level": _cur_level,
                                    "max_level": len(_hobj.levels) - 1,
                                    "can_drill_down": _cur_level < len(_hobj.levels) - 1,
                                    "can_drill_up": _cur_level > 0,
                                    "expand_levels": _exp_count,
                                    "can_expand": _cur_level + _exp_count <= len(_hobj.levels) - 1,
                                }
                                break  # Use the first hierarchy found
                except Exception:
                    pass  # Non-critical — degrade gracefully

                resp: dict[str, Any] = {
                    "ok": True,
                    "sql": sql,
                    "query": query,
                    "columns": cols_out,
                    "rows": rows_out,
                    "figure": fig,
                }
                if explanation_result:
                    resp["explanation"] = explanation_result
                if drill_meta:
                    resp["drill"] = drill_meta
                return resp
            except ImportError:
                return {
                    "ok": True,
                    "sql": sql,
                    "query": query,
                    "columns": cols_out,
                    "rows": rows_out,
                    "plotly_not_installed": True,
                    **({"explanation": explanation_result} if explanation_result else {}),
                }

        # Highlight mode: dual-query overlay (baseline + selected).
        baseline_sql: Optional[str] = None
        highlight_sql: Optional[str] = None

        try:
            baseline_filters = _parse_scoped_filters_payload(
                payload.get("filters"),
                project_path=project_path,
            )

            model_for_slicers, _pages_for_slicers, _visuals_for_slicers = load_project(project_path)
            sec_state_for_slicers = _build_runtime_security_state(
                project_path=project_path,
                model=model_for_slicers,
                request=request,
                payload=payload,
            )

            # Apply slicers to baseline filters (they remain active in highlight mode).
            try:
                defs_obj = _normalize_slicer_defs_payload(payload.get("slicer_defs") if isinstance(payload, Mapping) else None)
                if not (defs_obj.get("defs") or []):
                    defs_obj = load_slicer_defs(project_path)
                slicer_filter_payload = _materialize_slicer_defs_to_filter_payload_items(
                    defs_obj,
                    project_path=project_path,
                    model=model_for_slicers,
                    sec_state=sec_state_for_slicers,
                    duckdb_path=duckdb_path,
                    runtime_filters=list(baseline_filters),
                    page_id=None,
                    visual_id=str(visual_id),
                )
                slicer_filters = _parse_scoped_filters_payload(
                    slicer_filter_payload,
                    project_path=project_path,
                )
                baseline_filters = list(baseline_filters) + list(slicer_filters)
            except Exception as exc:
                code = _slicer_error_code_from_exc(exc, default="E_SLICER_VALUES_FAILED")
                return _err(400, str(exc), error_code=code, details={"visual_id": visual_id, "render_mode": "highlight"})

            visual_type, visual, registry, resolved_encodings, base_cols, base_rows, baseline_sql, base_exec_ms, _base_plan_ms, base_filters_meta, _base_ir = _get_visual_result_rows(
                project_path=project_path,
                visual_id=visual_id,
                duckdb_path=duckdb_path,
                runtime_filters=baseline_filters,
                requested_role=requested_role,
                visual_override=visual_definition,
            )
        except FileNotFoundError:
            return _err(404, f"Visual not found: {visual_id!r}")
        except OlsVisualBlockedError as exc:
            details: dict[str, Any] = {"visual_id": visual_id, "role": requested_role, "render_mode": "highlight"}
            if debug_payload:
                details["hidden_refs"] = list(exc.hidden_refs)
            return _err(400, str(exc), code="OLS_BLOCKED", details=details)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Visual render failed (baseline): id=%s project=%s error=%s",
                visual_id,
                project_path,
                str(exc),
            )
            return _err(400, str(exc), sql=baseline_sql, details={"visual_id": visual_id, "render_mode": "highlight"})

        base_cols_out, base_rows_out, base_query = _section(
            cols=list(base_cols),
            rows=list(base_rows),
            sql=str(baseline_sql or ""),
            exec_ms=float(base_exec_ms),
            plan_ms=float(_base_plan_ms),
            filters_meta=base_filters_meta,
        )

        interactions = visual.get("interactions")
        is_affected = True
        if isinstance(interactions, Mapping):
            is_affected = bool(interactions.get("is_affected", True))

        # Parse interaction_filters separately.
        try:
            interaction_filters = _parse_interaction_filters_payload(payload.get("interaction_filters"))
        except (ValueError, TypeError) as exc:
            return _err(400, f"Invalid interaction_filters: {exc}", details={"visual_id": visual_id, "render_mode": "highlight"})

        highlight_ok = True
        highlight_error: Optional[str] = None
        highlight_cols_out: list[str] = base_cols_out
        highlight_rows_out: list[dict[str, Any]] = base_rows_out
        highlight_query: dict[str, Any] = dict(base_query)
        highlight_cols_full: list[str] = list(base_cols)
        highlight_rows_full: list[Any] = list(base_rows)
        highlight_fig: Optional[dict[str, Any]] = None
        highlight_plotly_not_installed: bool = False

        # If the target visual opted out, server must ignore interaction filters.
        # Return highlight == baseline to keep response shape stable.
        if is_affected and interaction_filters:
            try:
                combined_filters = list(baseline_filters) + list(interaction_filters)
                _vt2, _v2, _reg2, _enc2, h_cols, h_rows, highlight_sql, h_exec_ms, _h_plan_ms, h_filters_meta, _h_ir = _get_visual_result_rows(
                    project_path=project_path,
                    visual_id=visual_id,
                    duckdb_path=duckdb_path,
                    runtime_filters=combined_filters,
                    requested_role=requested_role,
                    visual_override=visual_definition,
                )
                highlight_cols_out, highlight_rows_out, highlight_query = _section(
                    cols=list(h_cols),
                    rows=list(h_rows),
                    sql=str(highlight_sql or ""),
                    exec_ms=float(h_exec_ms),
                    plan_ms=float(_h_plan_ms),
                    filters_meta=h_filters_meta,
                )
                highlight_cols_full = list(h_cols)
                highlight_rows_full = list(h_rows)
            except Exception as exc:  # noqa: BLE001
                highlight_ok = False
                highlight_error = str(exc)
                highlight_query = {
                    "sql": str(highlight_sql or ""),
                    "row_count": 0,
                    "execution_ms": 0.0,
                    "filters": [],
                }

        # Build plotly figures (best-effort). If unavailable, keep rows/columns.
        # SVG-rendered visuals (IBCS) ΓÇö skip Plotly, return raw data only
        _vt_spec_hl = registry.get(visual_type)
        _vt_renderer_hl = getattr(_vt_spec_hl, "renderer", "") if _vt_spec_hl else ""
        if _vt_renderer_hl == "svg":
            baseline_section_svg: dict[str, Any] = {
                "ok": True,
                "sql": baseline_sql,
                "query": base_query,
                "columns": base_cols_out,
                "rows": base_rows_out,
            }
            highlight_section_svg: dict[str, Any] = {
                "ok": bool(highlight_ok),
                "sql": highlight_query.get("sql") if highlight_ok else (highlight_sql or ""),
                "query": highlight_query,
                "columns": highlight_cols_out,
                "rows": highlight_rows_out,
            }
            if not highlight_ok:
                highlight_section_svg["error"] = highlight_error or "Highlight query failed"
            return {
                "ok": True,
                "render_mode": "highlight",
                "baseline": baseline_section_svg,
                "highlight": highlight_section_svg,
            }

        try:
            import pandas as pd

            advanced_patch_raw = visual.get("advanced_plotly_patch")
            advanced_patch: Optional[Mapping[str, Any]] = None
            if advanced_patch_raw is not None:
                if not isinstance(advanced_patch_raw, Mapping):
                    return _err(400, "advanced_plotly_patch must be an object")
                try:
                    advanced_patch = _json_safe_with_path(
                        advanced_patch_raw,
                        path="$.advanced_plotly_patch",
                        strict=True,
                    )
                except TypeError as exc:
                    return _err(400, f"advanced_plotly_patch must be JSON-serializable; {exc}")

            _fmt_hl = _with_imported_category_sort(visual, visual_type)

            base_df = pd.DataFrame.from_records(list(base_rows), columns=base_cols_out)
            base_fig = _render_plotly_figure(
                visual_type=visual_type,
                registry=registry,
                df=base_df,
                resolved_encodings=resolved_encodings,
                advanced_patch=advanced_patch,
                format_options=_fmt_hl,
            )

            if highlight_ok:
                h_df = pd.DataFrame.from_records(highlight_rows_full, columns=highlight_cols_out)
                highlight_fig = _render_plotly_figure(
                    visual_type=visual_type,
                    registry=registry,
                    df=h_df,
                    resolved_encodings=resolved_encodings,
                    advanced_patch=advanced_patch,
                    format_options=_fmt_hl,
                )
        except ImportError:
            base_fig = None
            highlight_fig = None
            highlight_plotly_not_installed = True

        baseline_section: dict[str, Any] = {
            "ok": True,
            "sql": baseline_sql,
            "query": base_query,
            "columns": base_cols_out,
            "rows": base_rows_out,
        }
        if base_fig is not None:
            baseline_section["figure"] = base_fig
        else:
            baseline_section["plotly_not_installed"] = True

        highlight_section: dict[str, Any] = {
            "ok": bool(highlight_ok),
            "sql": highlight_query.get("sql") if highlight_ok else (highlight_sql or ""),
            "query": highlight_query,
            "columns": highlight_cols_out,
            "rows": highlight_rows_out,
        }
        if not highlight_ok:
            highlight_section["error"] = highlight_error or "Highlight query failed"

        if highlight_fig is not None and highlight_ok:
            highlight_section["figure"] = highlight_fig
        elif highlight_plotly_not_installed:
            highlight_section["plotly_not_installed"] = True

        return {
            "ok": True,
            "visual_id": visual_id,
            "baseline": baseline_section,
            "highlight": highlight_section,
            "query": {"baseline": base_query, "highlight": highlight_query},
        }

    # ---------------------------------------------------------------
    # Batch render — render multiple visuals in a single HTTP request.
    # Eliminates N-1 HTTP round-trips for page loads and crossfilter.
    # ---------------------------------------------------------------
    _BATCH_STATIC_TYPES = {"button", "shape", "textbox", "image", "group", "actionbutton", "slicer"}

    # Persistent thread pool for batch rendering.  Re-using warm threads
    # avoids the ~50-100ms overhead of creating a new pool per request.
    import concurrent.futures as _cf
    _BATCH_POOL = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="batch")

    def _render_one_for_batch(
        *,
        visual_id: str,
        project_path: str,
        duckdb_path: Optional[str],
        runtime_filters: list,
        requested_role: Optional[str],
        visual_json: dict[str, Any],
    ) -> dict[str, Any]:
        """Render a single visual for the batch endpoint.  Returns the result dict
        (same shape as the normal render_visual response) or an error dict."""
        vtype = str(visual_json.get("visual_type") or visual_json.get("type") or "").strip().lower()

        # Static visuals — no data (no caching needed)
        if vtype in _BATCH_STATIC_TYPES:
            return {
                "visual_id": visual_id,
                "visual_type": vtype,
                "columns": [],
                "rows": [],
                "query": {"sql": "", "row_count": 0, "execution_ms": 0, "plan_ms": 0, "filters": []},
                "static": True,
            }

        # Matrix visuals are excluded from batch for now (they have their own
        # complex renderer).  The frontend falls back to individual requests.
        if vtype == "matrix":
            return {"visual_id": visual_id, "skip": True, "reason": "matrix"}

        # ── Tier 2: Result cache check ──────────────────────────────
        _rc_engine_sig = _project_signature(project_path)
        _rc_key = _result_cache.build_key(
            visual_id=visual_id,
            project_path=project_path,
            role=requested_role,
            runtime_filters=runtime_filters,
            visual_json=visual_json,
            engine_sig=_rc_engine_sig,
        )
        cached_result = _result_cache.get(_rc_key)
        if cached_result is not None:
            return cached_result

        try:
            visual_type, visual, registry, resolved_encodings, cols, rows, sql, exec_ms, plan_ms, applied_filters_meta, table_ir = _get_visual_result_rows(
                project_path=project_path,
                visual_id=visual_id,
                duckdb_path=duckdb_path,
                runtime_filters=runtime_filters,
                requested_role=requested_role,
                visual_override=visual_json,
            )
        except OlsVisualBlockedError as exc:
            return {
                "visual_id": visual_id,
                "ok": False,
                "blocked": True,
                "hidden_refs": list(exc.hidden_refs),
                "error": str(exc),
            }
        except Exception as exc:
            return {
                "visual_id": visual_id,
                "ok": False,
                "error": str(exc),
            }

        cols_out = list(cols)
        rows_out = [dict(zip(cols_out, r)) for r in rows[:50]]
        query_out: dict[str, Any] = {
            "sql": str(sql or ""),
            "row_count": len(rows),
            "execution_ms": exec_ms,
            "plan_ms": plan_ms,
            "filters": applied_filters_meta,
        }

        result: dict[str, Any] = {
            "ok": True,
            "visual_id": visual_id,
            "visual_type": visual_type,
            "sql": sql,
            "query": query_out,
            "columns": cols_out,
            "rows": rows_out,
        }

        # Build Plotly figure (best-effort — degrade gracefully)
        try:
            import pandas as pd

            _vt_spec = registry.get(visual_type)
            _vt_renderer = getattr(_vt_spec, "renderer", "") if _vt_spec else ""
            if _vt_renderer == "svg":
                # SVG-rendered visuals (IBCS) return raw data, no Plotly
                pass
            else:
                df = pd.DataFrame.from_records(rows, columns=cols_out)

                # Load theme colors (best-effort)
                _theme_colors: list[str] | None = None
                _theme_font: str | None = None
                try:
                    _theme_path = Path(project_path) / "reports" / "reporting_theme.json"
                    if _theme_path.exists():
                        with open(_theme_path, "r", encoding="utf-8") as _tf:
                            _theme_data = json.load(_tf)
                        _dc = _theme_data.get("dataColors")
                        if isinstance(_dc, list) and _dc:
                            _theme_colors = _dc
                        _ff = _theme_data.get("font", {}).get("family")
                        if isinstance(_ff, str) and _ff:
                            _theme_font = _ff
                except Exception:
                    pass

                _fmt_for_render = _with_imported_category_sort(visual, visual_type)
                advanced_patch_raw = visual.get("advanced_plotly_patch")
                advanced_patch: Optional[Mapping[str, Any]] = None
                if isinstance(advanced_patch_raw, Mapping):
                    try:
                        advanced_patch = _json_safe_with_path(
                            advanced_patch_raw,
                            path="$.advanced_plotly_patch",
                            strict=True,
                        )
                    except TypeError:
                        pass

                fig = _render_plotly_figure(
                    visual_type=visual_type,
                    registry=registry,
                    df=df,
                    resolved_encodings=resolved_encodings,
                    advanced_patch=advanced_patch,
                    format_options=_fmt_for_render,
                    theme_colors=_theme_colors,
                    theme_font=_theme_font,
                )
                result["figure"] = fig
        except ImportError:
            result["plotly_not_installed"] = True
        except Exception as fig_exc:
            logger.debug("Batch figure generation failed for %s: %s", visual_id, fig_exc)

        # ── Tier 2: Cache the result for identical future requests ──
        _result_cache.put(_rc_key, result)

        return result

    @app.post("/runtime/render-batch")
    async def render_batch(
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Render multiple visuals in a single request.

        Payload:
            visual_ids: list[str]   — visual IDs to render
            filters: list[dict]     — shared filters (same format as single render)
            slicer_defs: dict       — optional slicer definitions

        Returns:
            {"ok": true, "results": {"vid1": {...}, "vid2": {...}}, "total_ms": ...}

        Uses asyncio.run_in_executor to run each visual render in uvicorn's
        thread pool — gives the same parallelism as individual HTTP requests
        (threads interleave at GIL release points like DuckDB queries and I/O)
        but eliminates N-1 HTTP round-trips.
        """
        import asyncio
        from functools import partial

        batch_t0 = time.perf_counter()
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        if not isinstance(payload, dict):
            return _err(400, "Payload must be a JSON object")

        visual_ids = payload.get("visual_ids") or []
        if not isinstance(visual_ids, list) or not visual_ids:
            return _err(400, "visual_ids must be a non-empty list")

        # Cap batch size to prevent abuse
        if len(visual_ids) > 50:
            return _err(400, "Batch size limited to 50 visuals")

        requested_role = _role_from_request(request=request, payload=payload)

        # Parse shared filters (once for all visuals)
        try:
            runtime_filters = list(_parse_scoped_filters_payload(
                payload.get("filters"),
                project_path=project_path,
            ))
        except Exception as exc:
            return _err(400, f"Invalid filters: {exc}")

        # Apply slicer filters (once for all visuals)
        try:
            model_for_slicers, _pages_for_slicers, _visuals_for_slicers = load_project(project_path)
            sec_state_for_slicers = _build_runtime_security_state(
                project_path=project_path,
                model=model_for_slicers,
                request=request,
                payload=payload,
            )
            defs_obj = _normalize_slicer_defs_payload(payload.get("slicer_defs") if isinstance(payload, Mapping) else None)
            if not (defs_obj.get("defs") or []):
                defs_obj = load_slicer_defs(project_path)
            slicer_filter_payload = _materialize_slicer_defs_to_filter_payload_items(
                defs_obj,
                project_path=project_path,
                model=model_for_slicers,
                sec_state=sec_state_for_slicers,
                duckdb_path=duckdb_path,
                runtime_filters=runtime_filters,
                page_id=None,
                visual_id=None,
            )
            slicer_filters = _parse_scoped_filters_payload(
                slicer_filter_payload,
                project_path=project_path,
            )
            runtime_filters = list(runtime_filters) + list(slicer_filters)
        except Exception as exc:
            code = _slicer_error_code_from_exc(exc, default="E_SLICER_VALUES_FAILED")
            return _err(400, str(exc), error_code=code)

        # Also parse interaction filters if present
        interaction_filters_raw = payload.get("interaction_filters") or payload.get("interactionFilters")
        if isinstance(interaction_filters_raw, list) and interaction_filters_raw:
            try:
                interaction_scoped = _parse_interaction_filters_payload(
                    interaction_filters_raw,
                )
                runtime_filters = runtime_filters + list(interaction_scoped)
            except Exception:
                pass  # Best-effort for interaction filters

        # Load all visual JSONs
        visual_jsons: dict[str, dict[str, Any]] = {}
        for vid in visual_ids:
            try:
                visual_jsons[vid] = _load_visual_json(project_path, vid)
            except FileNotFoundError:
                visual_jsons[vid] = {}  # Will be caught during render

        duckdb_path_resolved = _resolve_duckdb_path(duckdb_path)

        # Pre-filter: resolve static and matrix visuals synchronously
        # to avoid thread pool overhead for instant-return cases.
        results: dict[str, dict[str, Any]] = {}
        data_visual_ids: list[str] = []
        for vid in visual_ids:
            vj = visual_jsons.get(vid, {})
            vtype = str(vj.get("visual_type") or vj.get("type") or "").strip().lower()
            if vtype in _BATCH_STATIC_TYPES:
                results[vid] = {
                    "visual_id": vid,
                    "visual_type": vtype,
                    "columns": [],
                    "rows": [],
                    "query": {"sql": "", "row_count": 0, "execution_ms": 0, "plan_ms": 0, "filters": []},
                    "static": True,
                }
            elif vtype == "matrix":
                results[vid] = {"visual_id": vid, "skip": True, "reason": "matrix"}
            else:
                data_visual_ids.append(vid)

        # Render data visuals in parallel using the persistent batch pool.
        # The pool has 4 workers — enough to overlap DuckDB I/O (which
        # releases GIL) while keeping Python CPU contention manageable.
        if data_visual_ids:
            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(
                    _BATCH_POOL,
                    partial(
                        _render_one_for_batch,
                        visual_id=vid,
                        project_path=project_path,
                        duckdb_path=duckdb_path_resolved,
                        runtime_filters=runtime_filters,
                        requested_role=requested_role,
                        visual_json=visual_jsons.get(vid, {}),
                    ),
                )
                for vid in data_visual_ids
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            for vid, result in zip(data_visual_ids, raw_results):
                if isinstance(result, Exception):
                    results[vid] = {"visual_id": vid, "ok": False, "error": str(result)}
                else:
                    results[vid] = result

        total_ms = (time.perf_counter() - batch_t0) * 1000.0
        return {
            "ok": True,
            "results": results,
            "total_ms": round(total_ms, 2),
            "visual_count": len(visual_ids),
        }

    # ---------------------------------------------------------------
    # Cache stats — diagnostic endpoint for render caches
    # ---------------------------------------------------------------
    @app.get("/runtime/cache/stats")
    def cache_stats():
        """Return render cache hit/miss statistics."""
        return _get_cache_stats()

    @app.post("/runtime/cache/invalidate")
    def cache_invalidate():
        """Manually clear all render caches."""
        _invalidate_all_caches()
        return {"ok": True, "message": "All render caches cleared"}

    # ---------------------------------------------------------------
    # Tooltip page render — renders all visuals on a tooltip page
    # with additional filter context from the hovered data point.
    # ---------------------------------------------------------------
    @app.post("/runtime/tooltip-page/{page_id}/render")
    def render_tooltip_page(
        page_id: str,
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Render all visuals on a tooltip page with hover filter context.

        Payload:
            filter_context: dict[str, Any]  — category values from the hovered data point
                e.g. {"Category": "Bikes", "Year": 2024}
            filters: list[dict]             — optional additional scoped filters from the source visual
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        # Validate page exists and is a tooltip page
        try:
            _model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        target_page = None
        for pg in pages:
            if str(getattr(pg, "id", "")).strip() == str(page_id).strip():
                target_page = pg
                break
        if target_page is None:
            return _err(404, f"Page not found: {page_id!r}")

        page_type = str(getattr(target_page, "page_type", "") or "").strip().lower()
        if page_type != "tooltip":
            return _err(400, f"Page {page_id!r} is not a tooltip page (page_type={page_type!r})")

        # Parse filter context from the hover data point
        filter_context: dict[str, Any] = {}
        if isinstance(payload, dict):
            fc = payload.get("filter_context")
            if isinstance(fc, dict):
                filter_context = fc

        # Build scoped filters from the hover context
        # Each key=column_name, value=filter_value becomes an equality filter
        tooltip_filters: list[Any] = []
        if filter_context:
            from dax_engine.ir import ColumnRef as _ColRef
            from dax_engine.ir import FilterCondition as _FC
            from dax_engine.ir import Literal as _Lit
            from dax_engine.ir import ScopedFilter as _SF

            for col_key, col_val in filter_context.items():
                if col_val is None:
                    continue
                # Column key may be "Table.Column" or just "Column"
                parts = str(col_key).split(".", 1)
                if len(parts) == 2:
                    tbl, col = parts[0].strip(), parts[1].strip()
                else:
                    # Try to infer table from model
                    col = parts[0].strip()
                    tbl = ""
                    for t in _model.tables:
                        for c in t.columns:
                            if c.name.upper() == col.upper():
                                tbl = t.name
                                break
                        if tbl:
                            break
                if not tbl or not col:
                    continue
                tooltip_filters.append(
                    _SF(
                        scope="visual",
                        condition=_FC(
                            column=_ColRef(table=tbl, column=col),
                            operator="eq",
                            values=[_Lit(col_val)],
                        ),
                        target=None,
                        source="tooltip",
                    )
                )

        # Also parse any additional scoped filters from the payload
        runtime_filters: list[Any] = []
        if isinstance(payload, dict):
            raw_filters = payload.get("filters")
            if raw_filters:
                try:
                    runtime_filters = list(
                        _parse_scoped_filters_payload(raw_filters, project_path=project_path)
                    )
                except Exception:
                    pass  # Best-effort

        combined_filters = list(runtime_filters) + list(tooltip_filters)

        # Find all visuals on this page
        visuals_dir = Path(project_path) / "reports" / "visuals"
        page_visual_ids: list[str] = []
        if visuals_dir.exists() and visuals_dir.is_dir():
            for p in sorted(visuals_dir.glob("*.json")):
                try:
                    v = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(v, dict):
                        vid = str(v.get("page_id") or "").strip()
                        if vid == str(page_id).strip():
                            visual_id_val = p.stem
                            page_visual_ids.append(visual_id_val)
                except Exception:
                    continue

        if not page_visual_ids:
            return {
                "ok": True,
                "page_id": page_id,
                "page_title": getattr(target_page, "title", page_id),
                "visuals": [],
            }

        # Render each visual with the tooltip filter context
        requested_role = _role_from_request(request=request, payload=payload)
        rendered_visuals: list[dict[str, Any]] = []

        for vid in page_visual_ids:
            result: dict[str, Any] = {"visual_id": vid}
            try:
                visual_type, visual, registry, resolved_encodings, cols, rows, sql, exec_ms, plan_ms, applied_filters_meta, table_ir = _get_visual_result_rows(
                    project_path=project_path,
                    visual_id=vid,
                    duckdb_path=duckdb_path,
                    runtime_filters=combined_filters,
                    requested_role=requested_role,
                )

                cols_out = list(cols)
                rows_out = [dict(zip(cols_out, r)) for r in rows[:50]]
                result["type"] = visual_type
                result["title"] = str(visual.get("title") or vid)
                result["columns"] = cols_out
                result["rows"] = rows_out
                result["query"] = {
                    "sql": str(sql or ""),
                    "row_count": len(rows),
                    "execution_ms": exec_ms,
                    "plan_ms": plan_ms,
                }
                result["layout"] = visual.get("layout")

                # Build Plotly figure if possible
                try:
                    import pandas as _pd

                    df = _pd.DataFrame(rows, columns=cols_out)
                    advanced_patch = visual.get("format", {}).get("advanced_patch")
                    _fmt_batch = _with_imported_category_sort(visual, visual_type)

                    fig = _render_plotly_figure(
                        visual_type=visual_type,
                        registry=registry,
                        df=df,
                        resolved_encodings=resolved_encodings,
                        advanced_patch=advanced_patch,
                        format_options=_fmt_batch,
                    )
                    result["figure"] = fig
                except ImportError:
                    result["plotly_not_installed"] = True
                except Exception as fig_exc:
                    result["figure_error"] = str(fig_exc)

            except Exception as exc:  # noqa: BLE001
                result["error"] = str(exc)

            rendered_visuals.append(result)

        return {
            "ok": True,
            "page_id": page_id,
            "page_title": getattr(target_page, "title", page_id),
            "visuals": rendered_visuals,
        }

    @app.post("/runtime/visuals/{visual_id}/matrix")
    def render_matrix(
        visual_id: str,
        request: Request,
        project: Optional[str] = None,
        duckdb_path: Optional[str] = None,
        payload: dict = Body(default_factory=dict),
    ):
        """Render a matrix visual with SSRS/tablix-style row hierarchies and column bands.
        
        This endpoint is specialized for matrix visuals and returns:
        - rowTree: Hierarchical row structure with expand/collapse state
        - colHeaderBands: Multi-row column headers with spans
        - values: Measure columns with cell data
        
        Unlike the generic /render endpoint, this returns structured matrix data
        instead of a Plotly figure or flat table rows.
        """
        from dax_engine.context import Context
        from dax_engine.ir import ColumnRef
        from dax_engine.planner.matrix_planner import (
            AxisItem,
            CellValue,
            MatrixSpec,
            MeasureColumn,
            execute_matrix_query,
            matrix_spec_from_visual,
            plan_matrix_query,
            _resolve_axis_items_to_columns,
            _apply_drill_to_axis,
        )

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        requested_role = _role_from_request(request=request, payload=payload)
        debug_mode = str(request.query_params.get("debug") or "").strip() == "1"
        debug_rows_target: Optional[int] = None

        # Deterministic row inflation for Playwright tests (strictly gated)
        debug_rows_raw = str(request.query_params.get("debug_rows") or "").strip()
        if debug_rows_raw:
            if not debug_mode:
                return _err(400, "debug_rows requires debug=1")
            try:
                n = int(debug_rows_raw)
            except Exception:
                return _err(400, f"Invalid debug_rows: {debug_rows_raw!r}")
            if n <= 0:
                return _err(400, f"debug_rows must be > 0 (got {n})")
            # Only enable for the sample project
            try:
                if Path(str(project_path)).name == "sample_project":
                    debug_rows_target = n
                else:
                    return _err(400, "debug_rows is only allowed for sample_project")
            except Exception:
                return _err(400, "debug_rows gating failed")
        include_bars = bool(payload.get("include_bars", False))

        render_mode = str(payload.get("render_mode") or "normal").strip().lower()

        sql: Optional[str] = None

        try:
            # Load project and visual
            model_full, pages, all_visuals = load_project(project_path)
            
            # Find visual
            visuals_dir = Path(project_path) / "reports" / "visuals"
            visual: Optional[dict[str, Any]] = None
            for p in visuals_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        vj = json.load(f)
                    if str(vj.get("id") or "").strip() == str(visual_id).strip():
                        visual = vj
                        break
                except Exception:
                    continue
            
            # Fall back to inline visual_definition for unsaved visuals
            if visual is None:
                vd = payload.get("visual_definition") if isinstance(payload, dict) else None
                if isinstance(vd, dict):
                    visual = vd

            if visual is None:
                return _err(404, f"Visual not found: {visual_id!r}")
            
            # Apply OLS scoping
            sec_state = _build_runtime_security_state(
                project_path=project_path,
                model=model_full,
                request=request,
                payload=payload,
            )
            model_scoped = apply_ols(model_full, sec_state.role) if sec_state.role else model_full
            
            # Check for hidden refs
            hidden_refs = _ols_hidden_refs_for_visual(
                model_full=model_full,
                model_scoped=model_scoped,
                visual_json=visual,
            )
            if hidden_refs:
                raise OlsVisualBlockedError(
                    f"Visual references hidden objects: {hidden_refs}",
                    hidden_refs=hidden_refs,
                )
            
            # Build MatrixSpec from visual or payload overrides
            spec = matrix_spec_from_visual(visual)
            
            # Apply options from payload (showRowSubtotals, showColSubtotals, etc.)
            options = payload.get("options")
            if isinstance(options, Mapping):
                if "showRowSubtotals" in options:
                    spec.show_row_subtotals = bool(options.get("showRowSubtotals", True))
                if "showColSubtotals" in options:
                    spec.show_col_subtotals = bool(options.get("showColSubtotals", True))
                if "showRowGrandTotal" in options:
                    spec.show_row_grand_total = bool(options.get("showRowGrandTotal", True))
                if "showColGrandTotal" in options:
                    spec.show_col_grand_total = bool(options.get("showColGrandTotal", True))
            
            # ΓöÇΓöÇ Matrix Performance Safety Caps ΓöÇΓöÇ
            # Read caps from payload.matrix_caps > visual.options.matrix_caps > defaults.
            # Defaults: max_rows=5000, max_cols=100, max_cells=500000.
            _DEFAULT_MAX_ROWS = 5000
            _DEFAULT_MAX_COLS = 100
            _DEFAULT_MAX_CELLS = 500000
            
            caps_src = None
            if isinstance(payload.get("matrix_caps"), Mapping):
                caps_src = payload["matrix_caps"]
            elif isinstance(options, Mapping) and isinstance(options.get("matrix_caps"), Mapping):
                caps_src = options["matrix_caps"]
            else:
                visual_opts = visual.get("options") or {}
                if isinstance(visual_opts, Mapping) and isinstance(visual_opts.get("matrix_caps"), Mapping):
                    caps_src = visual_opts["matrix_caps"]
            
            _cap_max_rows = _DEFAULT_MAX_ROWS
            _cap_max_cols = _DEFAULT_MAX_COLS
            _cap_max_cells = _DEFAULT_MAX_CELLS
            if caps_src:
                try:
                    mr = int(caps_src.get("max_rows", _DEFAULT_MAX_ROWS))
                    _cap_max_rows = max(100, min(mr, 50000))
                except (TypeError, ValueError):
                    pass
                try:
                    mc = int(caps_src.get("max_cols", _DEFAULT_MAX_COLS))
                    _cap_max_cols = max(10, min(mc, 1000))
                except (TypeError, ValueError):
                    pass
                try:
                    mcc = int(caps_src.get("max_cells", _DEFAULT_MAX_CELLS))
                    _cap_max_cells = max(10000, min(mcc, 5000000))
                except (TypeError, ValueError):
                    pass
            
            spec.max_rows = _cap_max_rows
            spec.max_cols = _cap_max_cols
            # Attach max_cells as a private attr for execute_matrix_query to use
            spec._max_cells = _cap_max_cells  # type: ignore[attr-defined]
            
            # Bridge payload tablixProperties.showSubtotals ΓåÆ spec subtotals
            # This ensures the tablix-level toggle is respected even when the
            # frontend sends it in tablixProperties instead of options.
            payload_tablix_st = None
            _ptab = payload.get("tablixProperties") or payload.get("tablix_properties")
            if isinstance(_ptab, Mapping):
                _st = _ptab.get("showSubtotals")
                if _st is None:
                    _st = _ptab.get("show_subtotals")
                if _st is not None:
                    payload_tablix_st = bool(_st)
            if payload_tablix_st is not None:
                # Only override if payload.options didn't already set these
                if not (isinstance(options, Mapping) and "showRowSubtotals" in options):
                    spec.show_row_subtotals = payload_tablix_st
            # Bridge column subtotals separately
            payload_tablix_cst = None
            if isinstance(_ptab, Mapping):
                _cst = _ptab.get("showColSubtotals")
                if _cst is None:
                    _cst = _ptab.get("show_col_subtotals")
                if _cst is not None:
                    payload_tablix_cst = bool(_cst)
            if payload_tablix_cst is not None:
                if not (isinstance(options, Mapping) and "showColSubtotals" in options):
                    spec.show_col_subtotals = payload_tablix_cst
            
            # Apply tablix_properties for subtotal placement
            tablix_props = payload.get("tablix_properties")
            if isinstance(tablix_props, Mapping):
                placement = tablix_props.get("subtotal_placement")
                if placement in ("before_children", "after_children"):
                    spec.subtotal_placement = placement
            
            # Override spec from payload if provided
            if payload.get("rows"):
                spec.rows = [
                    AxisItem(
                        type=item.get("type", "column"),
                        table=item.get("table"),
                        column=item.get("column"),
                        field_param_name=item.get("name") if item.get("type") == "ParamRef" else None,
                    )
                    for item in payload.get("rows", [])
                ]
            if payload.get("cols"):
                spec.cols = [
                    AxisItem(
                        type=item.get("type", "column"),
                        table=item.get("table"),
                        column=item.get("column"),
                        field_param_name=item.get("name") if item.get("type") == "ParamRef" else None,
                    )
                    for item in payload.get("cols", [])
                ]
            if payload.get("values"):
                spec.values = [
                    MeasureRef(name=item.get("name", ""))
                    for item in payload.get("values", [])
                ]

            # Expansion state (rows/cols)
            # Preferred contract: expanded_rows / expanded_cols as list[str] where each entry
            # is a rowKey/colKey using the matrix key joiner ('__').
            from dax_engine.planner.matrix_planner import ExpandedPath

            spec.expanded_paths = []
            expanded_rows = payload.get("expanded_rows")
            expanded_cols = payload.get("expanded_cols")
            if isinstance(expanded_rows, list):
                for item in expanded_rows:
                    if isinstance(item, list):
                        path_parts = tuple(str(x) for x in item)
                    else:
                        path_parts = tuple(str(item).split("__"))
                    if path_parts and any(p.strip() for p in path_parts):
                        spec.expanded_paths.append(ExpandedPath(axis="rows", path=path_parts))

            if "expanded_cols" in payload:
                setattr(spec, "_expanded_cols_provided", True)
            if isinstance(expanded_cols, list):
                for item in expanded_cols:
                    if isinstance(item, list):
                        path_parts = tuple(str(x) for x in item)
                    else:
                        path_parts = tuple(str(item).split("__"))
                    if path_parts and any(p.strip() for p in path_parts):
                        spec.expanded_paths.append(ExpandedPath(axis="cols", path=path_parts))

            # Back-compat: older clients send expanded_paths as [{axis, path:[...]}]
            if not spec.expanded_paths and isinstance(payload.get("expanded_paths"), list):
                for ep in payload.get("expanded_paths", []):
                    if not isinstance(ep, dict):
                        continue
                    axis = str(ep.get("axis") or "").strip().lower()
                    if axis not in ("rows", "cols"):
                        continue
                    path = ep.get("path")
                    if isinstance(path, list) and path:
                        spec.expanded_paths.append(ExpandedPath(axis=axis, path=tuple(str(x) for x in path)))
            
            # Drill state (Power BI style drill down/up/flat navigation)
            drill_row_level = payload.get("drill_row_level")
            if isinstance(drill_row_level, int) and drill_row_level >= 0:
                spec.drill_row_level = drill_row_level
            drill_col_level = payload.get("drill_col_level")
            if isinstance(drill_col_level, int) and drill_col_level >= 0:
                spec.drill_col_level = drill_col_level
            drill_row_mode = str(payload.get("drill_row_mode") or "expand").strip().lower()
            if drill_row_mode in ("expand", "drill", "flat"):
                spec.drill_row_mode = drill_row_mode
            drill_col_mode = str(payload.get("drill_col_mode") or "expand").strip().lower()
            if drill_col_mode in ("expand", "drill", "flat"):
                spec.drill_col_mode = drill_col_mode
            
            # Drill filters (from "Drill Down" action - filters to specific parent value)
            drill_row_filters = payload.get("drill_row_filters")
            if isinstance(drill_row_filters, list):
                for drf in drill_row_filters:
                    if isinstance(drf, dict) and "column" in drf and "value" in drf:
                        spec.drill_row_filters.append({
                            "column": str(drf["column"]),
                            "value": drf["value"],
                            "level": int(drf.get("level", 0)),
                        })
            drill_col_filters = payload.get("drill_col_filters")
            if isinstance(drill_col_filters, list):
                for dcf in drill_col_filters:
                    if isinstance(dcf, dict) and "column" in dcf and "value" in dcf:
                        spec.drill_col_filters.append({
                            "column": str(dcf["column"]),
                            "value": dcf["value"],
                            "level": int(dcf.get("level", 0)),
                        })
            
            # Expand all flags (for "Expand All" menu action)
            if payload.get("expand_all_rows"):
                spec.expand_all_rows = True
            if payload.get("expand_all_cols"):
                spec.expand_all_cols = True
            if payload.get("expand_all_cmb"):
                spec.expand_all_cmb = True
            if payload.get("expand_all_rmb"):
                spec.expand_all_rmb = True
            
            # CMB/RMB incremental expansion depth (for "Expand to Next Level")
            # -1 = not set (fall back to expand_all_* boolean)
            # 0+ = expand to that depth level
            cmb_depth = payload.get("cmb_expand_depth")
            if isinstance(cmb_depth, int) and cmb_depth >= 0:
                spec.cmb_expand_depth = cmb_depth
            rmb_depth = payload.get("rmb_expand_depth")
            if isinstance(rmb_depth, int) and rmb_depth >= 0:
                spec.rmb_expand_depth = rmb_depth
            
            # Resolve parameters
            param_values = _resolve_payload_param_values(payload, model_scoped)
            calc_groups = _resolve_payload_calc_groups(payload, project_path)

            # Resolve What-If values from payload + persisted state (match /render behavior)
            # Phase 2.3: What-If parameter selections are persisted as report/page/visual state.
            wip_payload = load_what_if_selections(project_path)
            wip_eff = resolve_effective_what_if_selections(
                wip_payload,
                page_id=str(visual.get("page_id") or "") or None,
                visual_id=visual_id,
            )
            what_if_values_effective: Optional[Mapping[str, float]] = wip_eff if wip_eff else None
            if what_if_values_effective:
                flat_wip = [
                    {"scope": "visual", "target": visual_id, "param": p, "value": v}
                    for p, v in what_if_values_effective.items()
                ]
                _validate_what_if_selections_against_model(model_scoped, flat_wip)

            # Parse filters (shared scoped filter IR)
            runtime_filters = _parse_scoped_filters_payload(
                payload.get("filters"),
                project_path=project_path,
                model=model_scoped,
            )

            # Highlight mode: interaction filters may be sent separately.
            if render_mode == "highlight":
                runtime_filters = list(runtime_filters) + list(
                    _parse_interaction_filters_payload(payload.get("interaction_filters"))
                )

            # Materialize slicers into scoped filters (shared pipeline)
            try:
                defs_obj = _normalize_slicer_defs_payload(payload.get("slicer_defs") if isinstance(payload, Mapping) else None)
                if not (defs_obj.get("defs") or []):
                    defs_obj = load_slicer_defs(project_path)
                slicer_filter_payload = _materialize_slicer_defs_to_filter_payload_items(
                    defs_obj,
                    project_path=project_path,
                    model=model_full,
                    sec_state=sec_state,
                    duckdb_path=duckdb_path,
                    runtime_filters=list(runtime_filters),
                    page_id=str(visual.get("page_id") or "") or None,
                    visual_id=str(visual_id),
                )
                slicer_filters = _parse_scoped_filters_payload(
                    slicer_filter_payload,
                    project_path=project_path,
                    model=model_scoped,
                )
                runtime_filters = list(runtime_filters) + list(slicer_filters)
            except Exception as exc:
                code = _slicer_error_code_from_exc(exc, default="E_SLICER_VALUES_FAILED")
                return _err(400, str(exc), error_code=code, details={"visual_id": visual_id})

            # Build What-If values for context (compiler will resolve WhatIfRef from context).
            wip_for_compile: dict[str, float] = {}
            if what_if_values_effective:
                for k, v in what_if_values_effective.items():
                    if isinstance(k, str) and k.strip():
                        wip_for_compile[k.strip().upper()] = float(v) if isinstance(v, (int, float)) else 0.0
            # Also add defaults from model for any params not in selections.
            wip_defs = getattr(model_scoped, "what_if_parameters", {}) or {}
            for wip_name, wip_obj in wip_defs.items():
                norm_name = str(wip_name).strip().upper()
                if norm_name and norm_name not in wip_for_compile:
                    default_val = getattr(wip_obj, "default_value", None)
                    if default_val is None:
                        default_val = getattr(wip_obj, "default", 0)
                    wip_for_compile[norm_name] = float(default_val) if isinstance(default_val, (int, float)) else 0.0

            # Create context with What-If values (no global mutation)
            ctx = Context(what_if_values=wip_for_compile)
            sec = _compile_rls_security_predicates(role=sec_state.role, base_ctx=ctx)
            if sec:
                ctx = ctx.apply_security_predicates(sec)

            applied_filters_meta: list[dict[str, Any]] = []
            if runtime_filters:
                from dax_engine.filters_ir import apply_scoped_filters_to_context

                interactions = visual.get("interactions")
                is_affected = True
                if isinstance(interactions, Mapping):
                    is_affected = bool(interactions.get("is_affected", True))

                effective_filters = list(runtime_filters)
                if not is_affected:
                    effective_filters = [
                        f
                        for f in effective_filters
                        if str(getattr(f, "scope", "")).strip().lower() != "interaction"
                    ]

                ctx, applied_filters_meta = apply_scoped_filters_to_context(
                    ctx,
                    effective_filters,
                    page_id=str(visual.get("page_id") or "") or None,
                    visual_id=visual_id,
                )
            
            # Resolve row and column columns (full hierarchy)
            row_columns_full = _resolve_axis_items_to_columns(spec.rows, model_scoped, param_values)
            col_columns_full = _resolve_axis_items_to_columns(spec.cols, model_scoped, param_values)
            
            # Apply drill state to filter axes (Power BI "Go to Next Level" / drill behavior)
            # drill_mode='expand' shows all levels (default)
            # drill_mode='drill' shows only the single level at drill_level (hides parents)
            row_columns = _apply_drill_to_axis(row_columns_full, spec.drill_row_level, spec.drill_row_mode)
            col_columns = _apply_drill_to_axis(col_columns_full, spec.drill_col_level, spec.drill_col_mode)
            
            # When drill filters are present, skip the levels that have been drilled through.
            # E.g., if we have a filter at level 0, we should show levels 1+ (the children).
            # The drill filter acts as a WHERE clause AND skips parent groupings.
            if spec.drill_row_filters:
                max_filter_level = max(df.get("level", 0) for df in spec.drill_row_filters)
                start_level = max_filter_level + 1
                if start_level < len(row_columns):
                    row_columns = row_columns[start_level:]
                else:
                    row_columns = []
            
            if spec.drill_col_filters:
                max_filter_level = max(df.get("level", 0) for df in spec.drill_col_filters)
                start_level = max_filter_level + 1
                if start_level < len(col_columns):
                    col_columns = col_columns[start_level:]
                else:
                    col_columns = []
            
            # Build and execute query using existing SUMMARIZECOLUMNS pattern
            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=duckdb_path, model=model_scoped)
            
            # ── Resolve ParamRef in values (field-parameter measures) ──
            if spec._value_param_refs:
                _resolve_value_param_refs(spec, model_scoped, param_values)
            
            # Build a simple grouped query using the visual planner pattern
            all_dims = row_columns + col_columns
            measures = spec.values
            
            if not all_dims and not measures:
                return _err(400, "Matrix requires at least one row/column dimension or measure")
            
            # Convert drill filters to IR filter expressions (DaxBinaryOp)
            # These will be included in SUMMARIZECOLUMNS which puts them in the WHERE clause
            # INSIDE the query (not outside as a wrapper).
            from dax_engine.ir import DaxBinaryOp, Literal
            drill_filter_exprs: list = []
            
            def _parse_drill_filter(df: dict[str, Any], columns_full: list[ColumnRef]) -> Optional[DaxBinaryOp]:
                """Convert a drill filter dict to a DaxBinaryOp IR expression."""
                col_name = df.get("column", "")
                value = df.get("value")
                if not col_name or value is None:
                    return None
                
                # Parse column name (could be "Table[Column]" or just "Column")
                if "[" in col_name and "]" in col_name:
                    table_part = col_name.split("[")[0]
                    col_part = col_name.split("[")[1].rstrip("]")
                else:
                    col_part = col_name
                    # Find table from columns_full at this level
                    level = df.get("level", 0)
                    table_part = columns_full[level].table if level < len(columns_full) else ""
                
                if not table_part or not col_part:
                    return None
                
                # Create DaxBinaryOp: ColumnRef = Literal
                col_ref = ColumnRef(table=table_part, column=col_part)
                value_literal = Literal(value)
                return DaxBinaryOp(operator="=", left=col_ref, right=value_literal)
            
            for df in spec.drill_row_filters:
                filter_expr = _parse_drill_filter(df, row_columns_full)
                if filter_expr is not None:
                    drill_filter_exprs.append(filter_expr)
            
            for df in spec.drill_col_filters:
                filter_expr = _parse_drill_filter(df, col_columns_full)
                if filter_expr is not None:
                    drill_filter_exprs.append(filter_expr)
            
            # Use visual planner to build SQL - must be inside ENGINE_LOCK
            # to ensure relationships and measures are correctly loaded
            from dax_engine.planner import VisualQuerySpec, plan_visual_query
            
            _matrix_plan_t0 = time.perf_counter()
            with _ENGINE_LOCK:
                _ensure_mapping_loaded()
                get_prepared_engine(project_path, model_scoped)
                
                vspec = VisualQuerySpec(
                    dimensions=list(all_dims),
                    measures=list(measures),
                    filters=drill_filter_exprs,  # Drill filters are now part of the query
                )
                
                # Plan and execute
                _table_ir, sql = plan_visual_query(
                    vspec,
                    ctx=ctx,
                    model=model_scoped,
                    param_values=param_values,
                    calc_groups=calc_groups,
                    what_if_values=what_if_values_effective,
                )
            
            matrix_plan_ms = (time.perf_counter() - _matrix_plan_t0) * 1000.0
            # No need to wrap with WHERE - drill filters are now inside the query
            q = dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
            t0 = time.perf_counter()
            
            # Conditional formatting rules from visual JSON
            cond_fmt_rules = (visual.get("format") or {}).get("conditional_formatting") or []

            # Execute matrix query
            result = execute_matrix_query(
                spec=spec,
                sql=q,
                connection=con,
                model=model_scoped,
                row_columns=row_columns,
                col_columns=col_columns,
                ctx=ctx,
                param_values=param_values,
                calc_groups=calc_groups,
                what_if_values=what_if_values_effective,
                include_bars=include_bars,
                debug_rows_target=debug_rows_target,
                conditional_formatting_rules=cond_fmt_rules if cond_fmt_rules else None,
            )
            exec_ms = (time.perf_counter() - t0) * 1000.0

            # ── Visual Calculations (post-processing) ──────────────
            native_calcs = visual.get("native_calcs") or []
            if native_calcs and result.values:
                from dax_ui.server._visual_calcs import (
                    parse_visual_calcs,
                    evaluate_visual_calcs,
                )
                parsed_calcs = parse_visual_calcs(native_calcs)
                # Deduplicate (same name can appear twice in PBIR)
                seen_names: set[str] = set()
                unique_calcs = []
                for pc in parsed_calcs:
                    if pc.name not in seen_names:
                        seen_names.add(pc.name)
                        unique_calcs.append(pc)

                # Build display_name → actual_name mapping from visual encodings
                # Visual calcs reference measures by display_name (e.g. [Value])
                # but MatrixResult uses actual measure names (e.g. "Sales Sum")
                display_to_actual: Dict[str, str] = {}
                enc_all = visual.get("encodings") or {}
                vals_enc = enc_all.get("Values") or enc_all.get("values") or enc_all.get("y")
                if isinstance(vals_enc, dict):
                    if vals_enc.get("type") == "ParamRef":
                        # ParamRef encoding: [Value] maps to the first resolved measure
                        if result.values:
                            first_m = result.values[0].measure.get("name", "") if isinstance(result.values[0].measure, dict) else getattr(result.values[0].measure, "name", "")
                            if first_m:
                                display_to_actual["Value"] = first_m
                    else:
                        dn = vals_enc.get("display_name") or vals_enc.get("name", "")
                        an = vals_enc.get("name", "")
                        if dn and an:
                            display_to_actual[dn] = an
                elif isinstance(vals_enc, list):
                    for ve in vals_enc:
                        if isinstance(ve, dict):
                            dn = ve.get("display_name") or ve.get("name", "")
                            an = ve.get("name", "")
                            if dn and an:
                                display_to_actual[dn] = an
                # Remap ref_measure in parsed calcs from display name to actual name
                for pc in unique_calcs:
                    if pc.ref_measure and pc.ref_measure in display_to_actual:
                        pc.ref_measure = display_to_actual[pc.ref_measure]

                # Evaluate over the result set
                values_dicts = [mc.to_dict() for mc in result.values]
                new_cols = evaluate_visual_calcs(
                    unique_calcs,
                    values_dicts,
                    row_order=result.row_order,
                    col_leaf_keys=result.col_leaf_keys,
                    display_to_actual=display_to_actual,
                )
                # Append computed columns as MeasureColumn objects
                for nc_dict in new_cols:
                    mc_cells: Dict[str, Dict[str, CellValue]] = {}
                    for rk, col_cells in nc_dict.get("cells", {}).items():
                        mc_cells[rk] = {}
                        for ck, cv in col_cells.items():
                            if isinstance(cv, dict):
                                mc_cells[rk][ck] = CellValue(
                                    value=cv.get("value"),
                                    formatted=cv.get("formatted", ""),
                                )
                            else:
                                mc_cells[rk][ck] = CellValue(value=cv, formatted=str(cv))
                    result.values.append(MeasureColumn(
                        measure=nc_dict.get("measure", {}),
                        cells=mc_cells,
                    ))

            matrix_dict = result.to_dict()
            # Provide IR-level axis metadata for clickΓåÆinteraction mapping (no SQL parsing).
            matrix_dict["_interaction"] = {
                "row_columns": [
                    {"type": "ColumnRef", "table": c.table, "column": c.column}
                    for c in row_columns
                ],
                "col_columns": [
                    {"type": "ColumnRef", "table": c.table, "column": c.column}
                    for c in col_columns
                ],
                "key_joiner": "__",
                "subtotal_suffix": "__subtotal",
                "row_grand_total_key": "__grand_total__",
                "col_grand_total_key": "__col_grand_total__",
                "all_key": "__all__",
            }
            
            # Compile MatrixResult to TablixPlan (SSRS-style layout)
            from dax_engine.planner.tablix_compiler import compile_matrix_to_tablix
            from dax_engine.planner.tablix import (
                ColumnMeasureBlock,
                TablixProperties,
                resolve_unified_measures,
                measures_for_column_block,
                measures_for_row_block,
            )
            
            # Extract tablix properties from payload (save-only persistence) or visual encodings
            # Payload takes precedence so in-memory UI changes render before Save
            # Accept both camelCase and snake_case keys for compatibility
            tablix_props_dict = payload.get("tablixProperties") or payload.get("tablix_properties")
            if tablix_props_dict is None:
                encodings = visual.get("encodings") or {}
                tablix_props_dict = encodings.get("tablix") if isinstance(encodings, Mapping) else None
            payload_tablix_props = copy.deepcopy(tablix_props_dict) if isinstance(tablix_props_dict, Mapping) else None
            
            # Execute sub-queries for grouped blocks (blocks with column_fields)
            # These blocks need their own mini-matrix queries
            block_results: dict[str, dict[str, Any]] = {}
            
            # Unified measure resolution registry for cross-block interoperability
            resolved_measures: list = []

            # Preserve row field ordering from the visual definition when payload
            # rowFields are a permutation of the visual rowFields. This avoids
            # accidental axis flips from UI state drift.
            if isinstance(tablix_props_dict, Mapping) and isinstance(visual, Mapping):
                payload_blocks = tablix_props_dict.get("rowMeasureBlocks")
                visual_blocks = ((visual.get("encodings") or {}).get("tablix") or {}).get("rowMeasureBlocks")
                if isinstance(payload_blocks, list) and isinstance(visual_blocks, list):
                    for idx, payload_block in enumerate(payload_blocks):
                        if not isinstance(payload_block, dict):
                            continue
                        if idx >= len(visual_blocks):
                            continue
                        visual_block = visual_blocks[idx]
                        if not isinstance(visual_block, dict):
                            continue
                        payload_fields = payload_block.get("rowFields")
                        visual_fields = visual_block.get("rowFields")
                        if not isinstance(payload_fields, list) or not isinstance(visual_fields, list):
                            continue
                        payload_pairs = [
                            (f.get("table"), f.get("column"))
                            for f in payload_fields
                            if isinstance(f, dict)
                        ]
                        visual_pairs = [
                            (f.get("table"), f.get("column"))
                            for f in visual_fields
                            if isinstance(f, dict)
                        ]
                        if not payload_pairs or not visual_pairs:
                            continue
                        if len(payload_pairs) != len(visual_pairs):
                            continue
                        if set(payload_pairs) != set(visual_pairs):
                            continue
                        order_index = {pair: i for i, pair in enumerate(visual_pairs)}
                        payload_fields_sorted = sorted(
                            payload_fields,
                            key=lambda f: order_index.get((f.get("table"), f.get("column")), 0),
                        )
                        payload_block["rowFields"] = payload_fields_sorted

            # Parse TablixProperties once via from_dict() - this assigns stable IDs
            # to any blocks that are missing them. Server MUST NOT generate UUIDs;
            # all ID assignment happens in ColumnMeasureBlock.from_dict() / RowMeasureBlock.from_dict().
            tablix_props = TablixProperties.from_dict(tablix_props_dict) if tablix_props_dict else None

            # Default: expand grouped column measure blocks only on first render.
            # If any block has explicit expand state (expand_all or expanded_paths),
            # do NOT force auto-expand.
            if tablix_props and not spec.expand_all_cmb and getattr(spec, "cmb_expand_depth", -1) < 0:
                col_blocks = tablix_props.column_measure_blocks or []
                has_grouped = any(getattr(b, "column_fields", None) for b in col_blocks)
                any_explicit_state = any(
                    getattr(b, "expand_all", None) is not None or bool(getattr(b, "expanded_paths", None))
                    for b in col_blocks
                )
                if has_grouped and not any_explicit_state:
                    spec.expand_all_cmb = True
            
            # Default: expand grouped row measure blocks only on first render.
            # If any block has explicit expand state (expand_all or expanded_paths),
            # do NOT force auto-expand.
            if tablix_props and not spec.expand_all_rmb and getattr(spec, "rmb_expand_depth", -1) < 0:
                row_blocks_check = tablix_props.row_measure_blocks or []
                has_grouped_rmb = any(getattr(b, "row_fields", None) for b in row_blocks_check)
                any_explicit_state_rmb = any(
                    getattr(b, "expand_all", None) is not None or bool(getattr(b, "expanded_paths", None))
                    for b in row_blocks_check
                )
                if has_grouped_rmb and not any_explicit_state_rmb:
                    spec.expand_all_rmb = True
            
            if tablix_props:
                # Use parsed block objects (IDs guaranteed non-empty from from_dict())
                col_blocks = tablix_props.column_measure_blocks or []
                row_blocks = tablix_props.row_measure_blocks or []
                
                # Collect main values measure names
                main_value_names: list[str] = []
                for mv in (spec.values or []):
                    if hasattr(mv, "name") and mv.name:
                        main_value_names.append(mv.name)
                
                # Collect column block measures (block_id, measure_name)
                col_block_measures: list[tuple[str, str]] = []
                for block_idx, block in enumerate(col_blocks):
                    if block.measure_id:
                        col_block_measures.append((f"col_block_{block_idx}", block.measure_id))
                
                # Collect row block measures (block_id, measure_name)
                row_block_measures: list[tuple[str, str]] = []
                for block_idx, block in enumerate(row_blocks):
                    if block.measure_id:
                        row_block_measures.append((f"row_block_{block_idx}", block.measure_id))
                
                # Build unified measure registry
                resolved_measures = resolve_unified_measures(
                    main_measures=main_value_names,
                    column_block_measures=col_block_measures,
                    row_block_measures=row_block_measures,
                )
                
                # Convert to set for quick lookup
                main_value_names_set: set[str] = set(main_value_names)
                
                # =========================================================================
                # Domain expansion for 2D tablix composition
                # Collect ALL row block row_fields and ALL column block column_fields
                # so block queries can span the full tablix grid (not just main matrix).
                # =========================================================================
                
                # Collect all column block column_fields (for row block query expansion)
                # Also collect per-block column lists for pairwise overlap queries
                # Block IDs are already assigned by from_dict() - no UUID generation here
                all_col_block_col_columns: list[ColumnRef] = []
                all_col_block_axis_items: list[AxisItem] = []
                # Store: block_id -> (col_columns, axis_items, expanded_paths, block)
                # This includes BOTH grouped blocks (with column_fields) AND simple blocks (no column_fields)
                # Simple blocks are needed for overlap queries to get row block row cells
                # Block is included to access measure_mode and calc_group_item for base_calc mode
                col_block_columns_by_id: dict[str, tuple[list[ColumnRef], list[AxisItem], list[ExpandedPath], Any]] = {}
                
                # Get CMB depth limit (-1 = no limit, 0+ = limit to that depth)
                cmb_depth_limit = spec.cmb_expand_depth
                
                for block in col_blocks:
                    # block.id is guaranteed non-empty from from_dict()
                    column_fields = block.column_fields or []
                    block_col_refs: list[ColumnRef] = []
                    block_axis_items: list[AxisItem] = []
                    for cf in column_fields:
                        if isinstance(cf, dict) and cf.get("table") and cf.get("column"):
                            col_ref = ColumnRef(table=cf["table"], column=cf["column"])
                            axis_item = AxisItem(type='column', table=cf["table"], column=cf["column"])
                            block_col_refs.append(col_ref)
                            block_axis_items.append(axis_item)
                            # Also add to merged list (avoiding duplicates)
                            if col_ref not in all_col_block_col_columns:
                                all_col_block_col_columns.append(col_ref)
                                all_col_block_axis_items.append(axis_item)
                    
                    # Apply CMB depth limiting (for "Expand to Next Level" incremental expansion)
                    if cmb_depth_limit >= 0 and len(block_col_refs) > 0:
                        block_col_refs = block_col_refs[:cmb_depth_limit]
                        block_axis_items = block_axis_items[:cmb_depth_limit]
                    
                    # Parse column block's expanded_paths for overlap queries
                    cb_expanded_paths: list[ExpandedPath] = []
                    cb_exp_raw = block.expanded_paths or []
                    if isinstance(cb_exp_raw, list):
                        for ep in cb_exp_raw:
                            if not isinstance(ep, dict):
                                continue
                            axis = str(ep.get("axis") or "").strip().lower()
                            if axis != "cols":
                                continue
                            path = ep.get("path")
                            if isinstance(path, list) and path:
                                cb_expanded_paths.append(
                                    ExpandedPath(axis="cols", path=tuple(str(x) for x in path))
                                )
                    # Include ALL column blocks (grouped and simple) for overlap queries
                    # Simple blocks have empty col_columns/axis_items
                    # Include block object for access to measure_mode and calc_group_item
                    col_block_columns_by_id[block.id] = (block_col_refs, block_axis_items, cb_expanded_paths, block)
                
                # Collect all row block row_fields (for column block query expansion)
                all_row_block_row_columns: list[ColumnRef] = []
                all_row_block_axis_items: list[AxisItem] = []
                
                # Get RMB depth limit (-1 = no limit, 0+ = limit to that depth)
                rmb_depth_limit = spec.rmb_expand_depth
                
                for block in row_blocks:
                    row_fields = block.row_fields or []
                    block_row_refs: list[ColumnRef] = []
                    block_row_axis_items: list[AxisItem] = []
                    for rf in row_fields:
                        if isinstance(rf, dict) and rf.get("table") and rf.get("column"):
                            row_ref = ColumnRef(table=rf["table"], column=rf["column"])
                            axis_item = AxisItem(type='column', table=rf["table"], column=rf["column"])
                            block_row_refs.append(row_ref)
                            block_row_axis_items.append(axis_item)
                    
                    # Apply RMB depth limiting (for "Expand to Next Level" incremental expansion)
                    if rmb_depth_limit >= 0 and len(block_row_refs) > 0:
                        block_row_refs = block_row_refs[:rmb_depth_limit]
                        block_row_axis_items = block_row_axis_items[:rmb_depth_limit]
                    
                    # Add to merged list (avoiding duplicates)
                    for row_ref, axis_item in zip(block_row_refs, block_row_axis_items):
                        if row_ref not in all_row_block_row_columns:
                            all_row_block_row_columns.append(row_ref)
                            all_row_block_axis_items.append(axis_item)
                
                for block_idx, block in enumerate(col_blocks):
                    # Check if this is a grouped block (has column_fields)
                    column_fields = block.column_fields or []
                    
                    # Get the block's effective measure(s) based on measure_mode
                    # - "explicit": use block.measure_id
                    # - "base" or "base_calc": use matrix's main values measures
                    # - "blank": skip subquery entirely (emit blank column)
                    block_measure_mode = getattr(block, "measure_mode", "explicit") or "explicit"
                    
                    # Skip subquery for blank mode blocks (they emit blank columns)
                    if block_measure_mode == "blank":
                        continue
                    
                    if block_measure_mode in ("base", "base_calc") and main_value_names:
                        # Base mode: use all matrix values measures
                        effective_measure_ids = main_value_names
                    else:
                        # Explicit mode: use block's explicit measure_id
                        measure_id = block.measure_id
                        if not measure_id:
                            continue
                        effective_measure_ids = [measure_id]

                    # Expanded paths for this column block (column axis only)
                    block_expanded_paths: list[ExpandedPath] = []
                    expanded_paths_raw = block.expanded_paths or []
                    if isinstance(expanded_paths_raw, list):
                        for ep in expanded_paths_raw:
                            if not isinstance(ep, dict):
                                continue
                            axis = str(ep.get("axis") or "").strip().lower()
                            if axis != "cols":
                                continue
                            path = ep.get("path")
                            if isinstance(path, list) and path:
                                block_expanded_paths.append(
                                    ExpandedPath(axis="cols", path=tuple(str(x) for x in path))
                                )
                    
                    # Determine if we need a sub-query:
                    # - Grouped blocks (with column_fields) always need sub-query
                    # - Simple blocks (no column_fields) need sub-query if ANY measure is NOT in main values
                    # - base_calc mode blocks always need sub-query to apply calc group transformation
                    is_grouped = bool(column_fields)
                    # For base mode, check if base measures need sub-query
                    any_measure_not_in_main = any(m not in main_value_names_set for m in effective_measure_ids)
                    # base_calc mode requires subquery even for simple blocks to apply calc group
                    needs_calc_group = block_measure_mode == "base_calc" and block.calc_group_item
                    needs_subquery = is_grouped or any_measure_not_in_main or needs_calc_group
                    
                    if not needs_subquery:
                        continue  # Simple block with all measures in main values - no sub-query needed
                    
                    # Build a sub-query for this block
                    # Rows = main matrix rows + all row block rows (2D tablix composition)
                    # Cols = block's column_fields (empty for simple blocks)
                    # Values = block's effective measures + cross-block measures
                    block_col_columns: list[ColumnRef] = []
                    for cf in column_fields:
                        if isinstance(cf, dict) and cf.get("table") and cf.get("column"):
                            block_col_columns.append(ColumnRef(table=cf["table"], column=cf["column"]))
                    
                    # Apply CMB depth limiting (for "Expand to Next Level" incremental expansion)
                    # cmb_expand_depth >= 0 limits the column hierarchy depth
                    # -1 means no depth limit (expand_all_cmb controls full expansion)
                    cmb_depth = spec.cmb_expand_depth
                    if cmb_depth >= 0 and len(block_col_columns) > 0:
                        # Slice to depth: 0 = collapsed (empty), 1 = first level only, etc.
                        block_col_columns = block_col_columns[:cmb_depth]
                    
                    try:
                        # Build and execute block sub-query
                        from dax_project import get_measure
                        
                        # Get all measures visible to this column block (unified resolution)
                        # For base mode, use all effective measures; for explicit, use block's measure
                        primary_measure = effective_measure_ids[0] if effective_measure_ids else None
                        if primary_measure:
                            block_measure_names = measures_for_column_block(resolved_measures, primary_measure)
                            # Include all effective measures (for base mode with multiple matrix values)
                            for m in effective_measure_ids:
                                if m not in block_measure_names:
                                    block_measure_names.append(m)
                        else:
                            block_measure_names = list(effective_measure_ids)
                        block_measure_refs = [MeasureRef(name=m) for m in block_measure_names]
                        
                        # Keep column-block subqueries aligned with main matrix row keys.
                        # Overlap regions (row blocks ├ù column blocks) are handled by dedicated overlap queries.
                        expanded_rows = list(spec.rows or [])
                        expanded_row_columns = list(row_columns)
                        
                        # For simple blocks (no column_fields), use row-only query
                        # For grouped blocks, include block's column axis
                        block_spec = MatrixSpec(
                            visual_id=f"{visual_id}_col_block_{block_idx}",
                            page_id=spec.page_id,
                            rows=expanded_rows,  # Main matrix rows + row block rows
                            cols=[AxisItem(type='column', table=c.table, column=c.column) for c in block_col_columns] if block_col_columns else [],
                            values=block_measure_refs,  # All cross-block visible measures
                            show_row_subtotals=spec.show_row_subtotals,
                            show_row_grand_total=spec.show_row_grand_total,
                            # Grouped blocks inherit column subtotal setting from main matrix
                            show_col_subtotals=spec.show_col_subtotals if block_col_columns else False,
                            show_col_grand_total=True if block_col_columns else False,  # Only include col grand total for grouped blocks
                            expanded_paths=[
                                *[ep for ep in (spec.expanded_paths or []) if ep.axis == "rows"],
                                *block_expanded_paths,
                            ],
                            # Inherit expand-all flags: rows from main spec, cols from CMB flag
                            expand_all_rows=spec.expand_all_rows,
                            expand_all_cols=spec.expand_all_cmb,
                        )
                        
                        # Build sub-query using same pattern as main query
                        block_measures = block_spec.values
                        
                        # Dimensions: expanded row columns + block column columns (if any)
                        block_dims = list(expanded_row_columns) + list(block_col_columns)
                        
                        # For base_calc mode, apply the block's calc_group_item
                        # This overrides/merges with the visual's calc_groups
                        block_calc_groups = dict(calc_groups) if calc_groups else {}
                        if block_measure_mode == "base_calc" and block.calc_group_item:
                            # Parse calc_group_item format: "GroupName|ItemName"
                            cg_parts = block.calc_group_item.split("|", 1)
                            if len(cg_parts) == 2:
                                cg_name, cg_item = cg_parts
                                block_calc_groups[cg_name.strip()] = cg_item.strip()
                        
                        with _ENGINE_LOCK:
                            block_vspec = VisualQuerySpec(
                                dimensions=block_dims,
                                measures=list(block_measures),
                            )
                            _block_table_ir, block_sql = plan_visual_query(
                                block_vspec,
                                ctx=ctx,
                                model=model_scoped,
                                param_values=param_values,
                                calc_groups=block_calc_groups if block_calc_groups else None,
                                what_if_values=what_if_values_effective,
                            )
                        
                        block_q = dax_compiler.normalize_sql(f"SELECT * FROM {block_sql}")
                        
                        # Execute block query
                        block_matrix_result = execute_matrix_query(
                            spec=block_spec,
                            sql=block_q,
                            connection=con,
                            model=model_scoped,
                            row_columns=expanded_row_columns,
                            col_columns=block_col_columns,
                            ctx=ctx,
                            param_values=param_values,
                            calc_groups=block_calc_groups if block_calc_groups else None,
                            what_if_values=what_if_values_effective,
                        )
                        
                        block_results[f"col_block_{block_idx}"] = block_matrix_result.to_dict()
                        
                    except Exception as block_exc:
                        logger.warning(
                            "Block sub-query failed: block=%d measure=%s error=%s",
                            block_idx, measure_id, str(block_exc)
                        )
                        # Continue without block results - will render as simple block
                
                # Process row measure blocks (similar pattern to column blocks)
                # Block IDs are already assigned by from_dict() - no UUID generation here
                
                for block_idx, block in enumerate(row_blocks):
                    # block.id is guaranteed non-empty from from_dict()
                    row_block_id = block.id
                    row_fields = block.row_fields or []
                    
                    # Get the block's effective measure(s) based on measure_mode
                    # - "explicit": use block.measure_id
                    # - "base" or "base_calc": use matrix's main values measures
                    # - "blank": skip subquery entirely (emit blank row)
                    block_measure_mode = getattr(block, "measure_mode", "explicit") or "explicit"
                    
                    # Skip subquery for blank mode blocks (they emit blank rows)
                    if block_measure_mode == "blank":
                        continue
                    
                    if block_measure_mode in ("base", "base_calc") and main_value_names:
                        # Base mode: use all matrix values measures
                        effective_measure_ids = main_value_names
                    else:
                        # Explicit mode: use block's explicit measure_id
                        measure_id = block.measure_id
                        if not measure_id:
                            continue
                        effective_measure_ids = [measure_id]

                    show_sub = block.show_sub
                    show_gt = block.show_gt

                    # Expanded paths for this row block:
                    # 1. Row axis: from block's own expanded_paths
                    # 2. Column axis: from main matrix's expanded_paths (since block uses spec.cols)
                    block_expanded_paths: list[ExpandedPath] = []
                    
                    # Include main matrix's column expanded paths (since row blocks share the column axis)
                    for ep in (spec.expanded_paths or []):
                        if ep.axis == "cols":
                            block_expanded_paths.append(ep)
                    
                    # Include block's own row expanded paths
                    expanded_paths_raw = block.expanded_paths or []
                    if isinstance(expanded_paths_raw, list):
                        for ep in expanded_paths_raw:
                            if not isinstance(ep, dict):
                                continue
                            axis = str(ep.get("axis") or "").strip().lower()
                            if axis != "rows":
                                continue
                            path = ep.get("path")
                            if isinstance(path, list) and path:
                                block_expanded_paths.append(
                                    ExpandedPath(axis="rows", path=tuple(str(x) for x in path))
                                )
                    
                    # Determine if we need a sub-query:
                    # - Grouped blocks (with row_fields) always need sub-query
                    # - Simple blocks (no row_fields) need sub-query if ANY measure is NOT in main values
                    # - base_calc mode with calc_group_item needs sub-query for transformed values
                    is_grouped = bool(row_fields)
                    any_measure_not_in_main = any(m not in main_value_names_set for m in effective_measure_ids)
                    needs_calc_group = block_measure_mode == "base_calc" and block.calc_group_item
                    needs_subquery = is_grouped or any_measure_not_in_main or needs_calc_group
                    
                    # Build row columns for this block (empty for simple blocks)
                    # Rows = block's row_fields (if grouped) or empty for simple blocks
                    # Cols = main matrix cols ONLY (not expanded - overlap handled separately)
                    # Values = block's effective measures + cross-block measures
                    block_row_columns: list[ColumnRef] = []
                    for rf in row_fields:
                        if isinstance(rf, dict) and rf.get("table") and rf.get("column"):
                            block_row_columns.append(ColumnRef(table=rf["table"], column=rf["column"]))
                    
                    # Get all measures visible to this row block (unified resolution)
                    # For base mode, use all effective measures; for explicit, use block's measure
                    primary_measure = effective_measure_ids[0] if effective_measure_ids else None
                    if primary_measure:
                        block_measure_names = measures_for_row_block(resolved_measures, primary_measure)
                        # Include all effective measures (for base mode with multiple matrix values)
                        for m in effective_measure_ids:
                            if m not in block_measure_names:
                                block_measure_names.append(m)
                    else:
                        block_measure_names = list(effective_measure_ids)
                    block_measure_refs = [MeasureRef(name=m) for m in block_measure_names]
                    
                    if not needs_subquery:
                        # Simple block with all measures in main values - no block sub-query needed
                        # BUT we still need overlap queries for RMB ├ù CMB intersections
                        pass  # Fall through to overlap query section below
                    else:
                        # Build and execute block sub-query for grouped or external-measure blocks
                        try:
                            block_spec = MatrixSpec(
                                visual_id=f"{visual_id}_row_block_{block_idx}",
                                page_id=spec.page_id,
                                rows=[AxisItem(type='column', table=r.table, column=r.column) for r in block_row_columns] if block_row_columns else [],
                                cols=spec.cols,  # Main matrix cols only - do NOT expand
                                values=block_measure_refs,  # All cross-block visible measures
                                show_row_subtotals=bool(show_sub),
                                show_row_grand_total=bool(show_gt),
                                show_col_subtotals=spec.show_col_subtotals,
                                show_col_grand_total=spec.show_col_grand_total,
                                expanded_paths=block_expanded_paths,
                                # Inherit expand-all flags: rows from RMB flag, cols from main spec
                                expand_all_rows=spec.expand_all_rmb,
                                expand_all_cols=spec.expand_all_cols,
                            )
                            
                            # Dimensions: block row columns + main matrix col columns
                            block_dims = list(block_row_columns) + list(col_columns)
                            
                            # For base_calc mode, apply the block's calc_group_item
                            # This overrides/merges with the visual's calc_groups
                            row_block_calc_groups = dict(calc_groups) if calc_groups else {}
                            if block_measure_mode == "base_calc" and block.calc_group_item:
                                # Parse calc_group_item format: "GroupName|ItemName"
                                cg_parts = block.calc_group_item.split("|", 1)
                                if len(cg_parts) == 2:
                                    cg_name, cg_item = cg_parts
                                    row_block_calc_groups[cg_name.strip()] = cg_item.strip()
                            
                            with _ENGINE_LOCK:
                                block_vspec = VisualQuerySpec(
                                    dimensions=block_dims,
                                    measures=list(block_measure_refs),
                                )
                                _block_table_ir, block_sql = plan_visual_query(
                                    block_vspec,
                                    ctx=ctx,
                                    model=model_scoped,
                                    param_values=param_values,
                                    calc_groups=row_block_calc_groups if row_block_calc_groups else None,
                                    what_if_values=what_if_values_effective,
                                )
                            
                            block_q = dax_compiler.normalize_sql(f"SELECT * FROM {block_sql}")
                            
                            # Execute block query
                            block_matrix_result = execute_matrix_query(
                                spec=block_spec,
                                sql=block_q,
                                connection=con,
                                model=model_scoped,
                                row_columns=block_row_columns,
                                col_columns=col_columns,  # Main matrix cols only
                                ctx=ctx,
                                param_values=param_values,
                                calc_groups=row_block_calc_groups if row_block_calc_groups else None,
                                what_if_values=what_if_values_effective,
                            )
                            
                            block_results[f"row_block_{block_idx}"] = block_matrix_result.to_dict()
                            
                        except Exception as block_exc:
                            logger.warning(
                                "Row block sub-query failed: block=%d measure=%s error=%s",
                                block_idx, measure_id, str(block_exc)
                            )
                            # Continue without block results - will render as simple block
                    
                    # =========================================================
                    # Pairwise overlap queries: row block rows ├ù EACH column block columns
                    # Execute one overlap query per column block to keep keyspaces separate
                    # Use stable block IDs (not indices) for overlap result keys
                    # NOTE: Run for ALL row blocks (including simple base mode blocks without sub-queries)
                    # =========================================================
                    try:
                        for col_block_id, (cb_col_columns, cb_axis_items, cb_expanded_paths, col_block) in col_block_columns_by_id.items():
                            # Skip overlap query if EITHER block is in blank mode
                            # (blank mode emits blank cells, no data needed)
                            cb_measure_mode = getattr(col_block, "measure_mode", "explicit") or "explicit"
                            if block_measure_mode == "blank" or cb_measure_mode == "blank":
                                # Either block is blank mode - intersection is blanked, skip query
                                continue
                            # Skip overlap query if BOTH blocks are base/base_calc mode
                            # (intersection will be blanked by compiler anyway - redundant query)
                            if block_measure_mode in ("base", "base_calc") and cb_measure_mode in ("base", "base_calc"):
                                # Both blocks use base mode - intersection is blanked, skip query
                                continue
                            
                            # Merge row block's row expanded paths + column block's col expanded paths
                            overlap_expanded_paths: list[ExpandedPath] = []
                            # Include row block's row expanded paths
                            for ep in block_expanded_paths:
                                if ep.axis == "rows":
                                    overlap_expanded_paths.append(ep)
                            # Include column block's col expanded paths
                            for ep in cb_expanded_paths:
                                overlap_expanded_paths.append(ep)
                            
                            # Determine overlap measures: use COLUMN BLOCK's measure for the intersection
                            # This ensures the overlap cells show the CMB values, not the RMB values
                            if cb_measure_mode in ("base", "base_calc"):
                                # Column block uses main matrix measures
                                overlap_measure_refs = [MeasureRef(name=m) for m in main_value_names]
                            else:
                                # Column block uses explicit measure
                                cb_measure_id = getattr(col_block, "measure_id", None)
                                if cb_measure_id:
                                    overlap_measure_refs = [MeasureRef(name=cb_measure_id)]
                                else:
                                    # Fallback to main matrix measures
                                    overlap_measure_refs = [MeasureRef(name=m) for m in main_value_names]
                            
                            overlap_spec = MatrixSpec(
                                visual_id=f"{visual_id}_row_block_{row_block_id}_col_block_{col_block_id}_overlap",
                                page_id=spec.page_id,
                                rows=[AxisItem(type='column', table=r.table, column=r.column) for r in block_row_columns] if block_row_columns else [],
                                cols=cb_axis_items,  # THIS column block's columns only
                                values=overlap_measure_refs,  # Use COLUMN BLOCK's measures
                                show_row_subtotals=bool(show_sub),
                                show_row_grand_total=bool(show_gt),
                                show_col_subtotals=False,
                                show_col_grand_total=True,
                                expanded_paths=overlap_expanded_paths,
                                # Inherit expand-all flags: rows from RMB flag, cols from CMB flag
                                expand_all_rows=spec.expand_all_rmb,
                                expand_all_cols=spec.expand_all_cmb,
                            )
                            
                            overlap_dims = list(block_row_columns) + list(cb_col_columns)
                            
                            # For base_calc mode blocks, apply calc_group_item from either/both blocks
                            # Row block's calc_group_item first, then column block's (column wins on conflict)
                            overlap_calc_groups = dict(calc_groups) if calc_groups else {}
                            # Apply row block's calc_group_item if in base_calc mode
                            if block_measure_mode == "base_calc" and block.calc_group_item:
                                cg_parts = block.calc_group_item.split("|", 1)
                                if len(cg_parts) == 2:
                                    cg_name, cg_item = cg_parts
                                    overlap_calc_groups[cg_name.strip()] = cg_item.strip()
                            # Apply column block's calc_group_item if in base_calc mode (overwrites if same group)
                            if cb_measure_mode == "base_calc" and col_block.calc_group_item:
                                # Parse calc_group_item format: "GroupName|ItemName"
                                cg_parts = col_block.calc_group_item.split("|", 1)
                                if len(cg_parts) == 2:
                                    cg_name, cg_item = cg_parts
                                    overlap_calc_groups[cg_name.strip()] = cg_item.strip()
                            
                            with _ENGINE_LOCK:
                                overlap_vspec = VisualQuerySpec(
                                    dimensions=overlap_dims,
                                    measures=list(overlap_measure_refs),  # Use column block's measures
                                )
                                _overlap_table_ir, overlap_sql = plan_visual_query(
                                    overlap_vspec,
                                    ctx=ctx,
                                    model=model_scoped,
                                    param_values=param_values,
                                    calc_groups=overlap_calc_groups if overlap_calc_groups else None,
                                    what_if_values=what_if_values_effective,
                                )
                            
                            overlap_q = dax_compiler.normalize_sql(f"SELECT * FROM {overlap_sql}")
                            
                            overlap_matrix_result = execute_matrix_query(
                                spec=overlap_spec,
                                sql=overlap_q,
                                connection=con,
                                model=model_scoped,
                                row_columns=block_row_columns,
                                col_columns=cb_col_columns,
                                ctx=ctx,
                                param_values=param_values,
                                calc_groups=overlap_calc_groups if overlap_calc_groups else None,
                                what_if_values=what_if_values_effective,
                            )
                            
                            # Store with pairwise key using stable IDs: row_block_{id}_col_block_{id}_overlap
                            block_results[f"row_block_{row_block_id}_col_block_{col_block_id}_overlap"] = overlap_matrix_result.to_dict()
                    
                    except Exception as overlap_exc:
                        logger.warning(
                            "Overlap query failed: row_block=%d col_blocks=%s error=%s",
                            block_idx, list(col_block_columns_by_id.keys()), str(overlap_exc)
                        )
                        # Continue without overlap results
            
            # CRITICAL: Pass the SERIALIZED parsed props (with assigned IDs) to compiler.
            # If we pass the original tablix_props_dict, the compiler will re-parse
            # and generate NEW UUIDs, causing overlap key mismatch.
            tablix_props_with_ids = tablix_props.to_dict() if tablix_props else tablix_props_dict
            
            tablix_plan = compile_matrix_to_tablix(
                matrix_dict,
                tablix_properties=tablix_props_with_ids,
                block_results=block_results,
                debug=debug_mode,
            )
            tablix_dict = tablix_plan.to_dict()
            if isinstance(tablix_props_with_ids, Mapping):
                props_out = tablix_dict.get("properties") if isinstance(tablix_dict.get("properties"), dict) else None
                if props_out is None:
                    props_out = {}
                    tablix_dict["properties"] = props_out
                row_blocks = tablix_props_with_ids.get("rowMeasureBlocks")
                if row_blocks is None:
                    row_blocks = tablix_props_with_ids.get("row_measure_blocks")
                if row_blocks is not None:
                    payload_blocks = None
                    if isinstance(payload_tablix_props, Mapping):
                        payload_blocks = payload_tablix_props.get("rowMeasureBlocks") or payload_tablix_props.get("row_measure_blocks")

                    if isinstance(row_blocks, list) and isinstance(payload_blocks, list):
                        merged_blocks: list[dict[str, Any]] = []
                        for idx, rb in enumerate(row_blocks):
                            if not isinstance(rb, Mapping):
                                merged_blocks.append(rb)  # type: ignore[list-item]
                                continue
                            src = payload_blocks[idx] if idx < len(payload_blocks) and isinstance(payload_blocks[idx], Mapping) else {}
                            def _pick_flag(camel: str, snake: str, default: Any) -> Any:
                                if camel in src:
                                    return bool(src.get(camel))
                                if snake in src:
                                    return bool(src.get(snake))
                                return default

                            out_block = dict(rb)
                            out_block["showLeaf"] = _pick_flag("showLeaf", "show_leaf", rb.get("showLeaf", True))
                            out_block["showGrp"] = _pick_flag("showGrp", "show_grp", rb.get("showGrp", False))
                            out_block["showSub"] = _pick_flag("showSub", "show_sub", rb.get("showSub", True))
                            out_block["showGT"] = _pick_flag("showGT", "show_gt", rb.get("showGT", True))
                            merged_blocks.append(out_block)
                        props_out["rowMeasureBlocks"] = merged_blocks
                    else:
                        props_out["rowMeasureBlocks"] = row_blocks
            
            # ΓöÇΓöÇ Explanation column: execute ExplanationRef bindings if present ΓöÇΓöÇ
            explanation_result: dict[str, Any] | None = None
            try:
                enc_for_expl = visual.get("encodings") or {}
                expl_refs: list[dict[str, Any]] = []
                for _sn, rv in enc_for_expl.items():
                    vals = rv if isinstance(rv, list) else [rv]
                    for vv in vals:
                        if isinstance(vv, dict) and vv.get("type") == "ExplanationRef":
                            expl_refs.append(vv)

                if expl_refs:
                    # Build flat rows from matrix result for explanation binding
                    _expl_cols: list[str] = []
                    _expl_rows: list[tuple[Any, ...]] = []
                    try:
                        # Extract flat row data from the matrix result's rowTree + values
                        for rc in row_columns:
                            _expl_cols.append(rc.column)
                        for mv in result.values:
                            _expl_cols.append(mv.measure.get("name", ""))
                        # Determine the "all" column key for non-pivoted matrices
                        _all_col_key = "__all__"
                        if result.col_leaf_keys:
                            _all_col_key = result.col_leaf_keys[0]
                        for rk in result.row_order:
                            if rk == "__grand_total__":
                                continue  # Skip grand total rows
                            row_vals: list[Any] = []
                            # Row key parts (dimension values)
                            parts = rk.split("__") if rk else []
                            for ci, _rc in enumerate(row_columns):
                                row_vals.append(parts[ci] if ci < len(parts) else None)
                            # Measure values for this row (cells is rowKey -> colLeafKey -> CellValue)
                            for mv in result.values:
                                cell_dict = mv.cells.get(rk, {})
                                cell_val = cell_dict.get(_all_col_key)
                                if cell_val is not None:
                                    row_vals.append(getattr(cell_val, "value", cell_val))
                                else:
                                    row_vals.append(None)
                            _expl_rows.append(tuple(row_vals))
                    except Exception:
                        _expl_cols = []
                        _expl_rows = []

                    if _expl_cols and _expl_rows:
                        _narr_depth = "children"
                        payload_nd = payload.get("narrative_depth") if isinstance(payload, dict) else None
                        if payload_nd in ("children", "leaf", "all"):
                            _narr_depth = payload_nd
                        else:
                            for _er in expl_refs:
                                nd = _er.get("narrative_depth")
                                if nd in ("children", "leaf", "all"):
                                    _narr_depth = nd
                                    break
                        explanation_result = _execute_explanation_bindings(
                            project_path=project_path,
                            expl_refs=expl_refs,
                            query_rows=_expl_rows,
                            query_cols=_expl_cols,
                            model=model_scoped,
                            visual_encodings=enc_for_expl,
                            narrative_depth=_narr_depth,
                            runtime_filters=runtime_filters,
                        )
            except Exception as exc:
                logger.debug("Matrix explanation execution skipped: %s", exc)

            response = {
                "ok": True,
                "visual_id": visual_id,
                "matrix": matrix_dict,
                "tablix": tablix_dict,
                "query": {
                    "sql": sql,
                    "execution_ms": exec_ms,
                    "plan_ms": matrix_plan_ms,
                    "filters": applied_filters_meta,
                    **({
                        "ir": ir_to_dict(_table_ir)
                    } if _table_ir is not None else {}),
                    # Include truncation info when safety caps were applied
                    **({"truncated": matrix_dict["truncated"]} if "truncated" in matrix_dict else {}),
                },
                **({"explanation": explanation_result} if explanation_result else {}),
            }
            
            if debug_mode:
                response["debug"] = {
                    "spec": {
                        "rows": [{"type": r.type, "table": r.table, "column": r.column} for r in spec.rows],
                        "cols": [{"type": c.type, "table": c.table, "column": c.column} for c in spec.cols],
                        "values": [{"name": m.name} for m in spec.values],
                    },
                    "row_columns": [{"table": c.table, "column": c.column} for c in row_columns],
                    "col_columns": [{"table": c.table, "column": c.column} for c in col_columns],
                    "render_mode": render_mode,
                    "block_results_keys": list(block_results.keys()) if block_results else [],
                }
            
            return response
            
        except FileNotFoundError:
            return _err(404, f"Visual not found: {visual_id!r}")
        except OlsVisualBlockedError as exc:
            details: dict[str, Any] = {"visual_id": visual_id, "role": requested_role}
            if debug_mode:
                details["hidden_refs"] = list(exc.hidden_refs)
            return _err(400, str(exc), code="OLS_BLOCKED", details=details)
        except Exception as exc:
            logger.warning(
                "Matrix render failed: id=%s project=%s error=%s",
                visual_id,
                project_path,
                str(exc),
            )
            return _err(400, str(exc), sql=sql, details={"visual_id": visual_id})

    @app.get("/runtime/visuals/{visual_id}/matrix/export.xlsx")
    def export_matrix_excel(
        visual_id: str,
        request: Request,
        project: Optional[str] = None,
    ):
        """Export a matrix visual to Excel with formatting.
        
        Creates a workbook with:
        - Merged multi-row column headers
        - Indented row hierarchy labels
        - Formatted numeric values
        - Frozen header row/columns
        """
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise HTTPException(status_code=400, detail="Install requirements-ui.txt") from exc

        from io import BytesIO

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        # Re-use the matrix endpoint logic to get the data
        from dax_engine.context import Context
        from dax_engine.planner.matrix_planner import (
            execute_matrix_query,
            matrix_spec_from_visual,
            _resolve_axis_items_to_columns,
        )

        try:
            model_full, pages, all_visuals = load_project(project_path)
            
            # Find visual
            visuals_dir = Path(project_path) / "reports" / "visuals"
            visual: Optional[dict[str, Any]] = None
            for p in visuals_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        vj = json.load(f)
                    if str(vj.get("id") or "").strip() == str(visual_id).strip():
                        visual = vj
                        break
                except Exception:
                    continue
            
            if visual is None:
                return _err(404, f"Visual not found: {visual_id!r}")
            
            # Apply OLS
            sec_state = _build_runtime_security_state(
                project_path=project_path,
                model=model_full,
                request=request,
                payload={},
            )
            model_scoped = apply_ols(model_full, sec_state.role) if sec_state.role else model_full
            
            # Build spec and execute
            spec = matrix_spec_from_visual(visual)
            
            row_columns = _resolve_axis_items_to_columns(spec.rows, model_scoped, None)
            col_columns = _resolve_axis_items_to_columns(spec.cols, model_scoped, None)
            
            con = _connect_duckdb_for_project(project_path=project_path, duckdb_path=None, model=model_scoped)
            ctx = Context()
            
            # Build simple query
            all_dims = row_columns + col_columns
            
            from dax_engine.planner import VisualQuerySpec, plan_visual_query
            
            vspec = VisualQuerySpec(
                dimensions=list(all_dims),
                measures=list(spec.values),
                filters=[],
            )
            
            _table_ir, sql = plan_visual_query(vspec, ctx=ctx, model=model_scoped)
            q = dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
            
            result = execute_matrix_query(
                spec=spec,
                sql=q,
                connection=con,
                model=model_scoped,
                row_columns=row_columns,
                col_columns=col_columns,
                ctx=ctx,
            )
            
            # Build Excel workbook
            wb = Workbook()
            ws = wb.active
            
            title = str(visual.get("title") or visual.get("id") or visual_id)
            sheet_name = title
            for ch in (":", "\\", "/", "?", "*", "[", "]"):
                sheet_name = sheet_name.replace(ch, " ")
            sheet_name = (sheet_name.strip() or str(visual_id))[:31]
            ws.title = sheet_name
            
            # Styles
            header_font = Font(bold=True)
            header_fill = PatternFill(start_color="E0E0E0", end_color="E0E0E0", fill_type="solid")
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin'),
            )
            
            num_row_cols = len(row_columns)
            num_header_rows = len(result.col_header_bands) if result.col_header_bands else 1
            
            # Write column header bands
            current_row = 1
            
            if result.col_header_bands:
                for band_idx, band in enumerate(result.col_header_bands):
                    col_offset = num_row_cols + 1
                    
                    for cell_data in band:
                        c = ws.cell(row=current_row, column=col_offset)
                        c.value = cell_data.label
                        c.font = header_font
                        c.fill = header_fill
                        c.border = thin_border
                        c.alignment = Alignment(horizontal='center', vertical='center')
                        
                        # Merge cells if needed
                        if cell_data.col_span > 1 or cell_data.row_span > 1:
                            ws.merge_cells(
                                start_row=current_row,
                                start_column=col_offset,
                                end_row=current_row + cell_data.row_span - 1,
                                end_column=col_offset + cell_data.col_span - 1,
                            )
                        
                        col_offset += cell_data.col_span
                    
                    current_row += 1
            else:
                # Single header row with measure names
                col_offset = num_row_cols + 1
                for m in spec.values:
                    c = ws.cell(row=current_row, column=col_offset)
                    c.value = m.name
                    c.font = header_font
                    c.fill = header_fill
                    c.border = thin_border
                    col_offset += 1
                current_row += 1
            
            # Write row dimension headers
            for i, col in enumerate(row_columns):
                c = ws.cell(row=1, column=i + 1)
                c.value = col.column
                c.font = header_font
                c.fill = header_fill
                c.border = thin_border
            
            # Build row key to node map
            node_map = {n.key: n for n in result.row_tree}
            
            # Write data rows
            data_start_row = current_row
            for row_key in result.row_order:
                node = node_map.get(row_key)
                if not node:
                    continue
                
                # Write row labels with indentation
                if num_row_cols > 0:
                    # For hierarchical rows, put label in appropriate column
                    level_col = min(node.level, num_row_cols - 1) + 1
                    
                    # Write indented label
                    c = ws.cell(row=current_row, column=1)
                    indent_str = "  " * node.indent
                    label = node.label
                    if node.is_grand_total:
                        label = "Grand Total"
                    elif node.is_subtotal:
                        label = f"Total"
                    c.value = indent_str + label
                    c.border = thin_border
                    
                    if node.is_grand_total or node.is_subtotal:
                        c.font = header_font
                
                # Write measure values
                col_offset = num_row_cols + 1
                
                for measure_col in result.values:
                    row_cells = measure_col.cells.get(row_key, {})
                    
                    for col_key in result.col_leaf_keys:
                        cell_val = row_cells.get(col_key)
                        c = ws.cell(row=current_row, column=col_offset)
                        
                        if cell_val:
                            c.value = cell_val.value
                            c.number_format = '#,##0.00'
                        
                        c.border = thin_border
                        c.alignment = Alignment(horizontal='right')
                        
                        if node.is_grand_total or node.is_subtotal:
                            c.font = header_font
                        
                        col_offset += 1
                
                current_row += 1
            
            # Freeze panes
            freeze_cell = ws.cell(row=data_start_row, column=num_row_cols + 1)
            ws.freeze_panes = freeze_cell
            
            # Auto-fit column widths
            for col_idx in range(1, ws.max_column + 1):
                max_width = 8
                for row_idx in range(1, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    if cell.value:
                        max_width = max(max_width, len(str(cell.value)) + 2)
                ws.column_dimensions[get_column_letter(col_idx)].width = min(50, max_width)
            
            # Save to buffer
            buf = BytesIO()
            wb.save(buf)
            buf.seek(0)
            
            filename = f"{visual_id}_matrix.xlsx"
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers=headers,
            )
            
        except Exception as exc:
            logger.warning("Matrix Excel export failed: %s", str(exc))
            return _err(400, str(exc))

    @app.get("/runtime/pages/{page_id}/export.xlsx")
    def export_page_excel(page_id: str, request: Request, project: Optional[str] = None, duckdb_path: Optional[str] = None):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment
            from openpyxl.styles import Font
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise HTTPException(status_code=400, detail="Install requirements-ui.txt") from exc

        from io import BytesIO

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            _model, pages, _visuals = load_project(project_path)
            current_page = _select_page_id(pages, page_id)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        visuals_dir = Path(project_path) / "reports" / "visuals"
        visuals: list[dict[str, Any]] = []
        if visuals_dir.exists() and visuals_dir.is_dir():
            for p in sorted(visuals_dir.glob("*.json")):
                try:
                    v = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(v, dict):
                        if str(v.get("page_id") or "").strip() == current_page:
                            visuals.append(v)
                except Exception:
                    continue

        wb = Workbook()
        # Remove default sheet; we'll create one per visual.
        if wb.active is not None:
            wb.remove(wb.active)

        def _unique_sheet_name(desired: str) -> str:
            name = desired[:31]
            if name not in wb.sheetnames:
                return name
            # First deterministic retry.
            if name.startswith("_") and not name.startswith("__"):
                name = ("_" + name)[:31]
                if name not in wb.sheetnames:
                    return name
            # Final: suffix.
            for i in range(2, 10_000):
                cand = (f"{desired[:28]}_{i}")[:31]
                if cand not in wb.sheetnames:
                    return cand
            return (desired[:28] + "_X")[:31]

        def _sanitize_sheet_name(name: str) -> str:
            s = str(name or "Sheet")
            for ch in (":", "\\", "/", "?", "*", "[", "]"):
                s = s.replace(ch, " ")
            s = s.strip() or "Sheet"
            return s[:31]

        max_width = 60
        min_width = 8

        query_rows: list[dict[str, Any]] = []
        requested_role = _role_from_request(request=request, payload={})

        for idx, v in enumerate(visuals, start=1):
            visual_id = str(v.get("id") or f"v{idx}")
            title = str(v.get("title") or visual_id)
            sheet_name = _sanitize_sheet_name(title)
            if sheet_name in wb.sheetnames:
                # Ensure uniqueness.
                suffix = f" ({idx})"
                sheet_name = _sanitize_sheet_name(sheet_name + suffix)

            ws = wb.create_sheet(sheet_name)

            sql: Optional[str] = None
            try:
                visual_type, _visual, _registry, _resolved_encodings, cols, rows, sql, exec_ms, _plan_ms, _applied_filters, _ir = _get_visual_result_rows(
                    project_path=project_path,
                    visual_id=visual_id,
                    duckdb_path=duckdb_path,
                    requested_role=requested_role,
                )
            except Exception as exc:  # noqa: BLE001
                ws.append(["Error"])
                ws.append([str(exc)])
                query_rows.append(
                    {
                        "visual_id": visual_id,
                        "title": title,
                        "visual_type": str(v.get("visual_type") or v.get("type") or ""),
                        "execution_ms": None,
                        "row_count": None,
                        "sql": sql or "",
                    }
                )
                continue

            query_rows.append(
                {
                    "visual_id": visual_id,
                    "title": title,
                    "visual_type": visual_type,
                    "execution_ms": exec_ms,
                    "row_count": len(rows),
                    "sql": sql or "",
                }
            )

            ws.append(list(cols))
            for cell in ws[1]:
                cell.font = Font(bold=True)
            ws.freeze_panes = "A2"
            for r in rows:
                ws.append(list(r))

            widths = [len(str(c)) for c in cols]
            scan_rows = rows[:1000]
            for r in scan_rows:
                for i, val in enumerate(r):
                    if i >= len(widths):
                        break
                    if val is None:
                        continue
                    widths[i] = max(widths[i], len(str(val)))
            for i, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(i)].width = max(min_width, min(max_width, w + 2))

        # Add metadata sheet with SQL per visual.
        wsq = wb.create_sheet(_unique_sheet_name("_Queries"))
        headers = ["visual_id", "title", "visual_type", "execution_ms", "row_count", "sql"]
        wsq.append(headers)
        for cell in wsq[1]:
            cell.font = Font(bold=True)
        for row in query_rows:
            wsq.append(
                [
                    row.get("visual_id"),
                    row.get("title"),
                    row.get("visual_type"),
                    row.get("execution_ms"),
                    row.get("row_count"),
                    row.get("sql"),
                ]
            )
        # Wrap SQL column.
        for r in range(2, wsq.max_row + 1):
            wsq.cell(row=r, column=6).alignment = Alignment(wrap_text=True, vertical="top")
        wsq.column_dimensions[get_column_letter(6)].width = 80

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f"{current_page}.xlsx"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    @app.get("/runtime/data/tables")
    def data_view_list_tables(
        request: Request,
        project: Optional[str] = None,
    ):
        """List all tables with metadata for the Data View."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            sec_state = _build_runtime_security_state(
                project_path=project_path, model=model, request=request, payload=None,
            )
            model_scoped = sec_state.model_scoped
        except Exception as exc:
            return _err(400, str(exc))

        con = None
        try:
            duckdb_path = os.environ.get("DAX_DUCKDB_PATH", "").strip() or None
            con = _connect_duckdb_for_project(
                project_path=project_path, duckdb_path=duckdb_path, model=model,
            )
            result = []
            for t in sorted(getattr(model_scoped, "tables", []) or [], key=lambda x: str(getattr(x, "name", "")).upper()):
                tname = str(getattr(t, "name", "")).strip()
                if not tname:
                    continue
                cols = [
                    {
                        "name": str(getattr(c, "name", "")),
                        "type": str(getattr(c, "type", "UNKNOWN")),
                        "is_calculated": bool(getattr(c, "is_calculated", False)),
                        "expression": getattr(c, "expression", None),
                        "description": getattr(c, "description", None),
                        "sort_by_column": getattr(c, "sort_by_column", None),
                    }
                    for c in sorted(getattr(t, "columns", []) or [], key=lambda x: str(getattr(x, "name", "")).upper())
                ]
                is_calc = bool(getattr(t, "is_calculated", False))
                row_count = 0
                try:
                    from dax_engine.sql_utils import quote_ident
                    if _duckdb_table_exists(con, tname):
                        r = con.execute(f"SELECT COUNT(*) FROM {quote_ident(tname)}").fetchone()
                        row_count = int(r[0]) if r else 0
                except Exception:
                    pass
                result.append({
                    "name": tname,
                    "columns": cols,
                    "column_count": len(cols),
                    "row_count": row_count,
                    "is_calculated": is_calc,
                    "description": getattr(t, "description", None),
                })
            
            # Add field parameters as virtual tables (prefixed with FieldParams_)
            fps_map = getattr(model_scoped, "field_parameters", {}) or {}
            for fp_name, fp in fps_map.items():
                fp_table_name = f"FieldParams_{fp_name}"
                fp_items = list(getattr(fp, "items", []) or [])
                
                # Determine columns: Name, Sort, plus any custom properties
                custom_cols: set[str] = set()
                for item in fp_items:
                    props = getattr(item, "custom_props", None)
                    if isinstance(props, dict):
                        custom_cols.update(props.keys())
                
                fp_cols = [
                    {"name": "Name", "type": "VARCHAR", "is_calculated": False, "expression": None, "description": "Item name"},
                    {"name": "Sort", "type": "INTEGER", "is_calculated": False, "expression": None, "description": "Sort order"},
                    {"name": "Ref", "type": "VARCHAR", "is_calculated": False, "expression": None, "description": "Referenced column or measure"},
                ]
                for cc in sorted(custom_cols):
                    fp_cols.append({"name": cc, "type": "VARCHAR", "is_calculated": False, "expression": None, "description": f"Custom property: {cc}"})
                
                result.append({
                    "name": fp_table_name,
                    "columns": fp_cols,
                    "column_count": len(fp_cols),
                    "row_count": len(fp_items),
                    "is_calculated": False,
                    "is_field_parameter": True,
                    "description": f"Field Parameter: {fp_name}",
                })
            
            return _ok({"tables": result})
        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/data/table/{table_name}/rows")
    def data_view_table_rows(
        table_name: str,
        request: Request,
        project: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
        sort_column: Optional[str] = None,
        sort_dir: Optional[str] = None,
        filters: Optional[str] = None,
    ):
        """Return paginated rows for a table in the Data View.

        Query params:
          page: 1-based page number
          page_size: rows per page (max 500)
          sort_column: column name to sort by
          sort_dir: 'asc' or 'desc'
          filters: JSON-encoded dict of {column_name: {op, value}} or {column_name: [values]}
        """
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            sec_state = _build_runtime_security_state(
                project_path=project_path, model=model, request=request, payload=None,
            )
            model_scoped = sec_state.model_scoped
        except Exception as exc:
            return _err(400, str(exc))

        # Handle field parameter virtual tables (FieldParams_<name>)
        if table_name.strip().upper().startswith("FIELDPARAMS_"):
            fp_name = table_name.strip()[len("FieldParams_"):]
            fps_map = getattr(model_scoped, "field_parameters", {}) or {}
            matched_fp = None
            for name, fp in fps_map.items():
                if name.upper() == fp_name.upper():
                    matched_fp = fp
                    break
            if matched_fp is None:
                return _err(400, f"Unknown field parameter: {fp_name!r}")
            
            # Build rows from field parameter items
            from dax_engine.ir import ColumnRef as _ColumnRef, MeasureRef as _MeasureRef
            fp_items = list(getattr(matched_fp, "items", []) or [])
            all_rows = []
            custom_cols: set[str] = set()
            for item in fp_items:
                props = getattr(item, "custom_props", None)
                if isinstance(props, dict):
                    custom_cols.update(props.keys())
            
            for item in fp_items:
                ref = getattr(item, "ref", None)
                ref_str = ""
                if isinstance(ref, _ColumnRef):
                    ref_str = f"{ref.table}[{ref.column}]" if ref.table else f"[{ref.column}]"
                elif isinstance(ref, _MeasureRef):
                    ref_str = f"[{ref.name}]"
                row: dict[str, Any] = {
                    "Name": str(getattr(item, "name", "")),
                    "Sort": getattr(item, "sort", None),
                    "Ref": ref_str,
                }
                props = getattr(item, "custom_props", None)
                for cc in sorted(custom_cols):
                    row[cc] = (props or {}).get(cc, "")
                all_rows.append(row)
            
            # Sort if requested
            if sort_column:
                sort_key = sort_column.strip()
                reverse = (sort_dir or "").lower() == "desc"
                try:
                    all_rows.sort(key=lambda r: (r.get(sort_key) is None, r.get(sort_key, "")), reverse=reverse)
                except Exception:
                    pass
            
            # Paginate
            page_size = max(1, min(500, int(page_size or 100)))
            page_num = max(1, int(page or 1))
            total_rows = len(all_rows)
            total_pages = (total_rows + page_size - 1) // page_size if total_rows else 1
            offset = (page_num - 1) * page_size
            page_rows = all_rows[offset:offset + page_size]
            columns_list = ["Name", "Sort", "Ref"] + sorted(custom_cols)
            
            return _ok({
                "table": f"FieldParams_{fp_name}",
                "columns": columns_list,
                "rows": page_rows,
                "page": page_num,
                "page_size": page_size,
                "total_rows": total_rows,
                "total_pages": total_pages,
            })

        # Validate table exists in scoped model
        tables_list = list_tables(model_scoped)
        tname_upper = table_name.strip().upper()
        matched_table = None
        for t in tables_list:
            if t.upper() == tname_upper:
                matched_table = t
                break
        if matched_table is None:
            return _err(400, f"Unknown table: {table_name!r}")

        # Validate columns
        valid_cols = list_columns(model_scoped, matched_table)
        valid_cols_upper = {c.upper() for c in valid_cols}

        from dax_engine.sql_utils import quote_ident

        # Clamp page_size
        page_size = max(1, min(500, int(page_size or 100)))
        page_num = max(1, int(page or 1))
        offset = (page_num - 1) * page_size

        # Build SQL
        rls_sql: Optional[str] = None
        try:
            rls_sql = _case_insensitive_dict_get(sec_state.sec_predicates or {}, f"{matched_table}.__RLS__")
        except Exception:
            pass

        # Build the FROM source ΓÇö use compiled table_sources (which include
        # calculated-column expressions) so that calc cols appear as real
        # columns in the result set.
        table_src_map = _get_engine_table_sources(project_path, model)

        from_source_sql = table_src_map.get(matched_table)
        # If the table has a compiled source (e.g. with calc columns), wrap it.
        # Otherwise, just use the quoted table name.
        has_compiled_source = bool(from_source_sql and from_source_sql.strip().upper() != quote_ident(matched_table).upper())
        if has_compiled_source:
            from_clause = f"({from_source_sql}) AS _dv"
        else:
            from_clause = quote_ident(matched_table)

        con = None
        try:
            duckdb_path = os.environ.get("DAX_DUCKDB_PATH", "").strip() or None
            con = _connect_duckdb_for_project(
                project_path=project_path, duckdb_path=duckdb_path, model=model,
            )

            # Skip the physical-table check when we have a compiled source
            # (e.g. calculated tables like Sales2 that exist only as DAX).
            if not has_compiled_source and not _duckdb_table_exists(con, matched_table):
                return _err(400, f"Table {matched_table!r} not found in database")

            # Build WHERE clause
            where_parts: list[str] = []
            if rls_sql:
                where_parts.append(f"({rls_sql})")

            # Parse filter JSON
            if filters:
                try:
                    filter_dict = json.loads(filters)
                except (json.JSONDecodeError, TypeError):
                    return _err(400, "Invalid filters JSON")
                for col_name, filter_spec in filter_dict.items():
                    if col_name.upper() not in valid_cols_upper:
                        continue  # skip unknown columns
                    # Always double-quote to avoid reserved word clashes
                    qi_col = f'"{col_name}"'
                    if isinstance(filter_spec, list):
                        # Value list filter: column IN (...)
                        if filter_spec:
                            placeholders = ", ".join(["?" for _ in filter_spec])
                            where_parts.append(f"{qi_col} IN ({placeholders})")
                    elif isinstance(filter_spec, dict):
                        op = str(filter_spec.get("op", "")).strip().lower()
                        val = filter_spec.get("value")
                        if op == "contains" and val is not None:
                            where_parts.append(f"CAST({qi_col} AS VARCHAR) ILIKE ?")
                        elif op == "eq" and val is not None:
                            where_parts.append(f"{qi_col} = ?")
                        elif op == "neq" and val is not None:
                            where_parts.append(f"{qi_col} != ?")
                        elif op == "gt" and val is not None:
                            where_parts.append(f"{qi_col} > ?")
                        elif op == "lt" and val is not None:
                            where_parts.append(f"{qi_col} < ?")
                        elif op == "gte" and val is not None:
                            where_parts.append(f"{qi_col} >= ?")
                        elif op == "lte" and val is not None:
                            where_parts.append(f"{qi_col} <= ?")
                        elif op == "is_null":
                            where_parts.append(f"{qi_col} IS NULL")
                        elif op == "is_not_null":
                            where_parts.append(f"{qi_col} IS NOT NULL")

            where_clause = ""
            params: list[Any] = []
            if where_parts:
                where_clause = " WHERE " + " AND ".join(where_parts)
                # Build params for IN and operator filters
                if filters:
                    try:
                        filter_dict = json.loads(filters)
                    except Exception:
                        filter_dict = {}
                    for col_name, filter_spec in filter_dict.items():
                        if col_name.upper() not in valid_cols_upper:
                            continue
                        if isinstance(filter_spec, list) and filter_spec:
                            params.extend(filter_spec)
                        elif isinstance(filter_spec, dict):
                            op = str(filter_spec.get("op", "")).strip().lower()
                            val = filter_spec.get("value")
                            if op == "contains" and val is not None:
                                params.append(f"%{val}%")
                            elif op in ("eq", "neq", "gt", "lt", "gte", "lte") and val is not None:
                                params.append(val)

            # Count total
            count_sql = f"SELECT COUNT(*) FROM {from_clause}{where_clause}"
            total_count = int(con.execute(count_sql, params).fetchone()[0])

            # Sort
            order_clause = ""
            if sort_column and sort_column.upper() in valid_cols_upper:
                direction = "DESC" if str(sort_dir or "").strip().lower() == "desc" else "ASC"
                order_clause = f' ORDER BY "{sort_column}" {direction}'

            # Fetch rows ΓÇö quote every column name to avoid clashes with
            # DuckDB reserved words (Month, Year, etc.)
            select_cols = ", ".join(f'"{c}"' for c in valid_cols)
            data_sql = f"SELECT {select_cols} FROM {from_clause}{where_clause}{order_clause} LIMIT {page_size} OFFSET {offset}"
            result = con.execute(data_sql, params)
            rows_raw = result.fetchall()

            # Convert to list of dicts
            rows = []
            for row in rows_raw:
                row_dict: dict[str, Any] = {}
                for i, col in enumerate(valid_cols):
                    val = row[i]
                    # Serialize date/datetime objects
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif val is not None and not isinstance(val, (int, float, str, bool)):
                        val = str(val)
                    row_dict[col] = val
                rows.append(row_dict)

            total_pages = max(1, (total_count + page_size - 1) // page_size)

            return _ok({
                "table": matched_table,
                "columns": valid_cols,
                "rows": rows,
                "page": page_num,
                "page_size": page_size,
                "total_rows": total_count,
                "total_pages": total_pages,
            })
        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/data/table/{table_name}/profile")
    def data_view_column_profile(
        table_name: str,
        request: Request,
        project: Optional[str] = None,
    ):
        """Return column-level statistics for all columns in a table."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            sec_state = _build_runtime_security_state(
                project_path=project_path, model=model, request=request, payload=None,
            )
            model_scoped = sec_state.model_scoped
        except Exception as exc:
            return _err(400, str(exc))

        # Validate table
        tables_list = list_tables(model_scoped)
        tname_upper = table_name.strip().upper()
        matched_table = None
        for t in tables_list:
            if t.upper() == tname_upper:
                matched_table = t
                break
        if matched_table is None:
            return _err(400, f"Unknown table: {table_name!r}")

        valid_cols = list_columns(model_scoped, matched_table)
        from dax_engine.sql_utils import quote_ident

        # Get column type info from model
        col_types: dict[str, str] = {}
        col_is_calc: dict[str, bool] = {}
        for t in getattr(model_scoped, "tables", []) or []:
            if str(getattr(t, "name", "")).upper() == tname_upper:
                for c in getattr(t, "columns", []) or []:
                    cname = str(getattr(c, "name", ""))
                    col_types[cname.upper()] = str(getattr(c, "type", "UNKNOWN")).upper()
                    col_is_calc[cname.upper()] = bool(getattr(c, "is_calculated", False))
                break

        # Build compiled FROM source (includes calc columns)
        table_src_map = _get_engine_table_sources(project_path, model)

        from_source_sql = table_src_map.get(matched_table)
        has_compiled_source = bool(from_source_sql and from_source_sql.strip().upper() != quote_ident(matched_table).upper())
        if has_compiled_source:
            from_clause = f"({from_source_sql}) AS _dv"
        else:
            from_clause = quote_ident(matched_table)

        rls_sql: Optional[str] = None
        try:
            rls_sql = _case_insensitive_dict_get(sec_state.sec_predicates or {}, f"{matched_table}.__RLS__")
        except Exception:
            pass

        con = None
        try:
            duckdb_path = os.environ.get("DAX_DUCKDB_PATH", "").strip() or None
            con = _connect_duckdb_for_project(
                project_path=project_path, duckdb_path=duckdb_path, model=model,
            )

            # Skip the physical-table check when we have a compiled source
            # (e.g. calculated tables like Sales2 that exist only as DAX).
            if not has_compiled_source and not _duckdb_table_exists(con, matched_table):
                return _err(400, f"Table {matched_table!r} not found in database")

            where_clause = f" WHERE ({rls_sql})" if rls_sql else ""
            qi_table = from_clause

            # Get total row count
            total_count = int(con.execute(f"SELECT COUNT(*) FROM {qi_table}{where_clause}").fetchone()[0])

            profiles: list[dict[str, Any]] = []
            for col_name in valid_cols:
                # Always double-quote column names to avoid clashing with
                # DuckDB reserved words / functions (e.g. Month, Year).
                qi_col = f'"{col_name}"'
                col_type = col_types.get(col_name.upper(), "UNKNOWN")
                is_calc = col_is_calc.get(col_name.upper(), False)

                profile: dict[str, Any] = {
                    "name": col_name,
                    "type": col_type,
                    "is_calculated": is_calc,
                    "total_count": total_count,
                }

                try:
                    # Common stats for all types
                    stats_sql = f"""
                        SELECT
                            COUNT(*) AS total,
                            COUNT({qi_col}) AS non_null,
                            COUNT(*) - COUNT({qi_col}) AS null_count,
                            COUNT(DISTINCT {qi_col}) AS distinct_count
                        FROM {qi_table}{where_clause}
                    """
                    stats = con.execute(stats_sql).fetchone()
                    profile["non_null_count"] = int(stats[1])
                    profile["null_count"] = int(stats[2])
                    profile["distinct_count"] = int(stats[3])
                    profile["completeness"] = round(int(stats[1]) / max(1, int(stats[0])) * 100, 1)

                    # Type-specific stats
                    is_numeric = col_type.upper() in ("INTEGER", "DOUBLE", "FLOAT", "DECIMAL", "BIGINT", "INT",
                                                       "SMALLINT", "TINYINT", "NUMERIC", "REAL", "NUMBER", "CURRENCY")
                    is_date = col_type.upper() in ("DATE", "DATETIME", "TIMESTAMP", "TIME")
                    is_boolean = col_type.upper() in ("BOOLEAN", "BOOL")

                    if is_numeric:
                        num_sql = f"""
                            SELECT
                                MIN({qi_col}) AS min_val,
                                MAX({qi_col}) AS max_val,
                                AVG({qi_col}) AS mean_val,
                                MEDIAN({qi_col}) AS median_val,
                                STDDEV({qi_col}) AS stddev_val,
                                SUM({qi_col}) AS sum_val,
                                QUANTILE_CONT({qi_col}, 0.25) AS p25,
                                QUANTILE_CONT({qi_col}, 0.75) AS p75
                            FROM {qi_table}{where_clause}
                        """
                        num_stats = con.execute(num_sql).fetchone()
                        profile["min"] = _serialize_stat_value(num_stats[0])
                        profile["max"] = _serialize_stat_value(num_stats[1])
                        profile["mean"] = _serialize_stat_value(num_stats[2])
                        profile["median"] = _serialize_stat_value(num_stats[3])
                        profile["stddev"] = _serialize_stat_value(num_stats[4])
                        profile["sum"] = _serialize_stat_value(num_stats[5])
                        profile["p25"] = _serialize_stat_value(num_stats[6])
                        profile["p75"] = _serialize_stat_value(num_stats[7])

                    elif is_date:
                        date_sql = f"""
                            SELECT
                                MIN({qi_col}) AS min_date,
                                MAX({qi_col}) AS max_date
                            FROM {qi_table}{where_clause}
                        """
                        date_stats = con.execute(date_sql).fetchone()
                        min_d = date_stats[0]
                        max_d = date_stats[1]
                        profile["min"] = min_d.isoformat() if hasattr(min_d, "isoformat") else str(min_d) if min_d is not None else None
                        profile["max"] = max_d.isoformat() if hasattr(max_d, "isoformat") else str(max_d) if max_d is not None else None
                        if min_d is not None and max_d is not None:
                            try:
                                profile["date_range_days"] = (max_d - min_d).days
                            except Exception:
                                profile["date_range_days"] = None
                        else:
                            profile["date_range_days"] = None

                    elif is_boolean:
                        bool_sql = f"""
                            SELECT
                                COUNT(CASE WHEN {qi_col} = TRUE THEN 1 END) AS true_count,
                                COUNT(CASE WHEN {qi_col} = FALSE THEN 1 END) AS false_count
                            FROM {qi_table}{where_clause}
                        """
                        bool_stats = con.execute(bool_sql).fetchone()
                        profile["true_count"] = int(bool_stats[0])
                        profile["false_count"] = int(bool_stats[1])

                    else:
                        # Text / other
                        text_sql = f"""
                            SELECT
                                MIN(LENGTH(CAST({qi_col} AS VARCHAR))) AS min_len,
                                MAX(LENGTH(CAST({qi_col} AS VARCHAR))) AS max_len,
                                AVG(LENGTH(CAST({qi_col} AS VARCHAR))) AS avg_len
                            FROM {qi_table}{where_clause}
                            WHERE {qi_col} IS NOT NULL
                        """
                        text_stats = con.execute(text_sql).fetchone()
                        profile["min_length"] = int(text_stats[0]) if text_stats[0] is not None else None
                        profile["max_length"] = int(text_stats[1]) if text_stats[1] is not None else None
                        profile["avg_length"] = round(float(text_stats[2]), 1) if text_stats[2] is not None else None

                    # Top-N value distribution (for all types, top 10)
                    top_sql = f"""
                        SELECT CAST({qi_col} AS VARCHAR) AS val, COUNT(*) AS cnt
                        FROM {qi_table}{where_clause}
                        WHERE {qi_col} IS NOT NULL
                        GROUP BY {qi_col}
                        ORDER BY cnt DESC, val ASC
                        LIMIT 10
                    """
                    top_rows = con.execute(top_sql).fetchall()
                    profile["top_values"] = [
                        {"value": str(r[0]), "count": int(r[1])}
                        for r in top_rows
                    ]

                except Exception as col_exc:
                    profile["error"] = str(col_exc)

                profiles.append(profile)

            return _ok({
                "table": matched_table,
                "row_count": total_count,
                "profiles": profiles,
            })
        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/data/table/{table_name}/column/{column_name}/values")
    def data_view_column_values(
        table_name: str,
        column_name: str,
        request: Request,
        project: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
    ):
        """Return distinct values for a column (used by column filter popover)."""
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            sec_state = _build_runtime_security_state(
                project_path=project_path, model=model, request=request, payload=None,
            )
            model_scoped = sec_state.model_scoped
        except Exception as exc:
            return _err(400, str(exc))

        # Validate table
        tables_list = list_tables(model_scoped)
        tname_upper = table_name.strip().upper()
        matched_table = None
        for t in tables_list:
            if t.upper() == tname_upper:
                matched_table = t
                break
        if matched_table is None:
            return _err(400, f"Unknown table: {table_name!r}")

        valid_cols = list_columns(model_scoped, matched_table)
        if column_name.upper() not in {c.upper() for c in valid_cols}:
            return _err(400, f"Unknown column: {table_name}[{column_name}]")

        from dax_engine.sql_utils import quote_ident

        lim = max(1, min(500, int(limit or 50)))

        # Build compiled FROM source (includes calc columns)
        table_src_map = _get_engine_table_sources(project_path, model)

        from_source_sql = table_src_map.get(matched_table)
        has_compiled_source = bool(from_source_sql and from_source_sql.strip().upper() != quote_ident(matched_table).upper())
        if has_compiled_source:
            from_clause = f"({from_source_sql}) AS _dv"
        else:
            from_clause = quote_ident(matched_table)

        rls_sql: Optional[str] = None
        try:
            rls_sql = _case_insensitive_dict_get(sec_state.sec_predicates or {}, f"{matched_table}.__RLS__")
        except Exception:
            pass

        con = None
        try:
            duckdb_path = os.environ.get("DAX_DUCKDB_PATH", "").strip() or None
            con = _connect_duckdb_for_project(
                project_path=project_path, duckdb_path=duckdb_path, model=model,
            )

            # Skip the physical-table check when we have a compiled source
            # (e.g. calculated tables like Sales2 that exist only as DAX).
            if not has_compiled_source and not _duckdb_table_exists(con, matched_table):
                return _err(400, f"Table {matched_table!r} not found in database")

            qi_table = from_clause
            # Always double-quote to avoid reserved word issues
            qi_col = f'"{column_name}"'

            where_parts: list[str] = []
            params: list[Any] = []
            if rls_sql:
                where_parts.append(f"({rls_sql})")
            where_parts.append(f"{qi_col} IS NOT NULL")

            if q is not None and str(q).strip():
                where_parts.append(f"CAST({qi_col} AS VARCHAR) ILIKE ?")
                params.append(f"%{str(q).strip()}%")

            where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""

            sql = f"""
                SELECT DISTINCT CAST({qi_col} AS VARCHAR) AS val
                FROM {qi_table}{where_clause}
                ORDER BY val ASC
                LIMIT {lim}
            """
            rows = con.execute(sql, params).fetchall()
            values = [str(r[0]) for r in rows]

            return _ok({"values": values})
        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/visuals/{visual_id}/export.xlsx")
    def export_visual_excel(visual_id: str, request: Request, project: Optional[str] = None, page: Optional[str] = None):
        # NOTE: `page` is accepted for lookup convenience; visual id is authoritative.
        _ = page

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment
            from openpyxl.styles import Font
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise HTTPException(status_code=400, detail="Install requirements-ui.txt") from exc

        from io import BytesIO

        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        sql: Optional[str] = None
        try:
            visual_type, visual, _registry, _resolved_encodings, cols, rows, sql, exec_ms, _plan_ms, _applied_filters, _ir = _get_visual_result_rows(
                project_path=project_path,
                visual_id=visual_id,
                duckdb_path=None,
                requested_role=_role_from_request(request=request, payload={}),
            )
        except FileNotFoundError as exc:
            return _err(404, f"Visual not found: {visual_id!r}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc), sql=sql)

        # Build workbook.
        title = str(visual.get("title") or visual.get("id") or visual_id)
        sheet_name = title
        for ch in (":", "\\", "/", "?", "*", "[", "]"):
            sheet_name = sheet_name.replace(ch, " ")
        sheet_name = sheet_name.strip() or str(visual_id)
        sheet_name = sheet_name[:31]

        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name

        ws.append(list(cols))
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"

        for r in rows:
            ws.append(list(r))

        def _unique_sheet_name(desired: str) -> str:
            name = desired[:31]
            if name not in wb.sheetnames:
                return name
            if name.startswith("_") and not name.startswith("__"):
                name = ("_" + name)[:31]
                if name not in wb.sheetnames:
                    return name
            for i in range(2, 10_000):
                cand = (f"{desired[:28]}_{i}")[:31]
                if cand not in wb.sheetnames:
                    return cand
            return (desired[:28] + "_X")[:31]

        # Add metadata sheet with SQL (keeps data sheet data-only).
        wsq = wb.create_sheet(_unique_sheet_name("_Query"))
        wsq.append(["key", "value"])
        wsq["A1"].font = Font(bold=True)
        wsq["B1"].font = Font(bold=True)
        meta = [
            ("visual_id", visual_id),
            ("title", title),
            ("visual_type", visual_type),
            ("execution_ms", exec_ms),
            ("row_count", len(rows)),
            ("sql", sql or ""),
        ]
        for k, v in meta:
            wsq.append([k, v])
        # Wrap SQL row.
        wsq["B7"].alignment = Alignment(wrap_text=True, vertical="top")
        wsq.column_dimensions["A"].width = 18
        wsq.column_dimensions["B"].width = 100

        # Best-effort autofit (capped).
        max_width = 60
        min_width = 8
        widths = [len(str(c)) for c in cols]
        scan_rows = rows[:1000]
        for r in scan_rows:
            for i, v in enumerate(r):
                if i >= len(widths):
                    break
                if v is None:
                    continue
                widths[i] = max(widths[i], len(str(v)))
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = max(min_width, min(max_width, w + 2))

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = f"{visual_id}.xlsx"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
