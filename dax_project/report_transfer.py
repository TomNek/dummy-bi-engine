"""
PBIR Report Transfer — converts a Power BI PBIR .Report directory
into the project's native report format (pages.yaml, visual JSONs,
filters.yaml, bookmarks.yaml).

Used by:
- Server endpoint (POST /runtime/report-transfer/preview + /execute)
- CLI for batch transfers
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from dax_project.report_crawlers import (
    adapt_pbir_to_legacy,
    crawl_visual_all,
    crawl_report_summary,
    build_alias_table_mapping,
)


# ---------------------------------------------------------------------------
# Locale translation — German → English day/month names
# ---------------------------------------------------------------------------
# PBI reports authored in German locale store day/month names in German
# (e.g. "Montag" instead of "Monday"). DuckDB data typically uses English.
# This mapping is applied to filter values during import so that filters
# actually match the data.

_GERMAN_TO_ENGLISH: dict[str, str] = {
    # Day names
    "Montag": "Monday",
    "Dienstag": "Tuesday",
    "Mittwoch": "Wednesday",
    "Donnerstag": "Thursday",
    "Freitag": "Friday",
    "Samstag": "Saturday",
    "Sonntag": "Sunday",
    # Short day names
    "Mo": "Mon", "Di": "Tue", "Mi": "Wed",
    "Do": "Thu", "Fr": "Fri", "Sa": "Sat", "So": "Sun",
    # Month names
    "Januar": "January", "Februar": "February", "März": "March",
    "April": "April", "Mai": "May", "Juni": "June",
    "Juli": "July", "August": "August", "September": "September",
    "Oktober": "October", "November": "November", "Dezember": "December",
    # Short month names
    "Jan": "Jan", "Feb": "Feb", "Mär": "Mar",
    "Apr": "Apr", "Jun": "Jun", "Jul": "Jul",
    "Aug": "Aug", "Sep": "Sep", "Okt": "Oct",
    "Nov": "Nov", "Dez": "Dec",
}


def _translate_filter_values_locale(filters: list[dict]) -> None:
    """Translate German day/month names to English in filter values (in-place)."""
    for f in filters:
        vals = f.get("values")
        if isinstance(vals, list):
            f["values"] = [_GERMAN_TO_ENGLISH.get(v, v) if isinstance(v, str) else v for v in vals]
        val = f.get("value")
        if isinstance(val, str) and val in _GERMAN_TO_ENGLISH:
            f["value"] = _GERMAN_TO_ENGLISH[val]


# ---------------------------------------------------------------------------
# Visual type mapping — PBI → project
# ---------------------------------------------------------------------------

def _map_visual_type(pbi_type: str) -> str:
    """Map a PBI visual type to the project visual type."""
    return _VISUAL_TYPE_MAP.get(pbi_type, pbi_type)


_VISUAL_TYPE_MAP = {
    "barChart": "bar",
    "clusteredBarChart": "bar",
    "clusteredColumnChart": "bar",
    "stackedBarChart": "bar",
    "stackedColumnChart": "bar",
    "hundredPercentStackedBarChart": "bar",
    "hundredPercentStackedColumnChart": "bar",
    "lineChart": "line",
    "areaChart": "area",
    "stackedAreaChart": "area",
    "lineStackedColumnComboChart": "combo",
    "lineClusteredColumnComboChart": "combo",
    "pieChart": "pie",
    "donutChart": "pie",
    "treemap": "treemap",
    "funnel": "funnel",
    "waterfallChart": "waterfall",
    "scatterChart": "scatter",
    "card": "card",
    "multiRowCard": "card",
    "kpi": "card",
    "tableEx": "table",
    "pivotTable": "matrix",
    "matrix": "matrix",
    "slicer": "slicer",
    "advancedSlicerVisual": "slicer",
    "gauge": "gauge",
    "textbox": "textbox",
    "shape": "shape",
    "image": "image",
    "actionButton": "button",
    "bookmarkNavigator": "button",
    "pageNavigator": "button",
    "map": "map",
    "filledMap": "map",
    "visualGroup": "group",
}


# ---------------------------------------------------------------------------
# Data classes for transfer results
# ---------------------------------------------------------------------------

@dataclass
class TransferResult:
    """Result of a report transfer operation."""
    project_path: str = ""
    pages_created: int = 0
    visuals_created: int = 0
    filters_transferred: int = 0
    bookmarks_transferred: int = 0
    interactions_transferred: int = 0
    warnings: list[str] = field(default_factory=list)
    unsupported_visual_types: list[str] = field(default_factory=list)
    # Crawler-enriched counts
    field_parameters_transferred: int = 0
    sort_configs_transferred: int = 0
    native_calcs_transferred: int = 0
    reference_lines_transferred: int = 0
    column_formatting_transferred: int = 0
    values_formatting_transferred: int = 0
    column_widths_transferred: int = 0
    hierarchy_levels_transferred: int = 0
    slicer_sync_groups_transferred: int = 0
    # Row-count verification
    source_crawler_counts: dict = field(default_factory=dict)
    transferred_crawler_counts: dict = field(default_factory=dict)


@dataclass
class VisualPreview:
    """Preview of a visual before transfer."""
    visual_id: str
    visual_type_pbi: str
    visual_type_project: str
    page: str
    title: str = ""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    field_count: int = 0
    filter_count: int = 0
    is_supported: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _extract_field_ref(field_obj: dict) -> Optional[dict]:
    """Convert a PBI field reference to a project encoding reference."""
    if "Column" in field_obj:
        col = field_obj["Column"]
        entity = col.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
        prop = col.get("Property", "")
        if entity and prop:
            return {"type": "ColumnRef", "table": entity, "column": prop}
    elif "Measure" in field_obj:
        m = field_obj["Measure"]
        entity = m.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
        prop = m.get("Property", "")
        if prop:
            return {"type": "MeasureRef", "table": entity, "name": prop}
    elif "HierarchyLevel" in field_obj:
        h = field_obj["HierarchyLevel"]
        hier_expr = h.get("Expression", {}).get("Hierarchy", {})
        hierarchy = hier_expr.get("Hierarchy", "")
        level = h.get("Level", "")
        if hierarchy:
            ref: dict[str, Any] = {"type": "HierarchyRef", "name": hierarchy}
            # Extract source table from PropertyVariationSource (auto-date hierarchies)
            # or plain SourceRef.  This tells us which real table the hierarchy lives on.
            pvs = hier_expr.get("Expression", {}).get("PropertyVariationSource", {})
            if pvs:
                source_table = pvs.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                if source_table:
                    ref["_source_table"] = source_table
            else:
                source_table = hier_expr.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
                if source_table:
                    ref["_source_table"] = source_table
            if level:
                ref["_level"] = level
            return ref
    return None


def _map_encoding_role(role: str, visual_type: str) -> str:
    """Map a PBI query state role to a project encoding key.

    The mapping is visual-type-aware because different visual types use
    different slot names in our engine (e.g. ``card`` uses ``value``,
    ``slicer`` uses ``columns``, ``pie`` uses ``names``/``values``).
    """
    role_lower = role.lower()
    vtype = _map_visual_type(visual_type).lower()

    # --- Visual-type-specific overrides ---
    _type_role_map: dict[str, dict[str, str]] = {
        "card": {"values": "value", "y": "value"},
        "slicer": {"values": "columns", "y": "columns", "category": "columns"},
        "pie": {"category": "names", "values": "values", "y": "values"},
        "treemap": {"group": "path", "category": "path", "values": "values", "y": "values"},
        "sunburst": {"group": "path", "category": "path", "values": "values", "y": "values"},
        "matrix": {"values": "values", "y": "values"},
        "table": {"values": "columns", "y": "columns", "category": "columns"},
        "funnel_area": {"category": "names", "values": "values", "y": "values"},
        "gauge": {"values": "value", "y": "value"},
    }

    type_map = _type_role_map.get(vtype, {})
    if role_lower in type_map:
        return type_map[role_lower]

    # --- Generic fallback ---
    role_map = {
        "category": "x",
        "values": "y",
        "y": "y",
        "y1": "y",
        "y2": "y2",
        "series": "color",
        "legend": "color",
        "color": "color",
        "size": "size",
        "rows": "rows",
        "columns": "columns",
        "tooltips": "tooltip",
        "details": "detail",
        "gradient": "gradient",
        "x axis": "x",
        "y axis": "y",
    }
    return role_map.get(role_lower, role_lower)


def _extract_encodings(visual_data: dict) -> dict:
    """Extract field encodings from a PBIR visual's query.queryState.

    Handles multi-measure Y axis: when separate PBI roles (Y, Y2) map to the
    same encoding key, their projections are merged into a list.

    When a role has ``fieldParameters``, the corresponding projections are
    replaced with ``ParamRef`` entries so the render pipeline can resolve them
    dynamically via the field parameter table.
    """
    vis = visual_data.get("visual", {})
    query = vis.get("query", {})
    query_state = query.get("queryState", {})
    visual_type = vis.get("visualType", "")

    encodings: dict[str, Any] = {}
    for role, role_data in query_state.items():
        projections = role_data.get("projections", [])
        if not projections:
            continue

        enc_key = _map_encoding_role(role, visual_type)

        # Check for field parameters on this role
        fp_entries = role_data.get("fieldParameters", [])

        # Build refs for this role
        refs = []
        seen_hierarchies: set[str] = set()
        # Track which projection indices are covered by field parameters
        fp_covered: set[int] = set()
        fp_refs: dict[int, dict] = {}  # index → ParamRef
        for fp_entry in fp_entries:
            idx = fp_entry.get("index", -1)
            length = fp_entry.get("length", 1)
            param_expr = fp_entry.get("parameterExpr", {})
            param_ref = _extract_field_ref(param_expr)
            if param_ref and idx >= 0:
                # The param_ref will be a ColumnRef pointing to the FP table;
                # convert it to a ParamRef using the table name as the FP name.
                fp_table = param_ref.get("table", "")
                if fp_table:
                    for j in range(idx, idx + length):
                        fp_covered.add(j)
                    fp_refs[idx] = {"type": "ParamRef", "name": fp_table}

        for i, proj in enumerate(projections):
            # If this projection is covered by a field parameter, emit ParamRef
            if i in fp_covered:
                if i in fp_refs:
                    refs.append(fp_refs[i])
                # Skip projections covered by the same FP (length > 1)
                continue

            ref = _extract_field_ref(proj.get("field", {}))
            if ref:
                if ref.get("type") == "HierarchyRef":
                    h_name = ref.get("name", "")
                    if h_name in seen_hierarchies:
                        continue
                    seen_hierarchies.add(h_name)
                display_name = proj.get("displayName")
                if display_name and display_name != ref.get("column", "") and display_name != ref.get("name", ""):
                    ref["display_name"] = display_name
                refs.append(ref)

        if not refs:
            continue

        # Merge with existing encoding if the same key was already populated
        # (e.g. Y and Y2 both map to "y")
        if enc_key in encodings:
            existing = encodings[enc_key]
            if not isinstance(existing, list):
                existing = [existing]
            existing.extend(refs)
            encodings[enc_key] = existing
        else:
            encodings[enc_key] = refs if len(refs) > 1 else refs[0]

    return encodings


def _ref_display_name(ref: dict) -> str:
    if not isinstance(ref, dict):
        return ""
    rtype = str(ref.get("type", ""))
    if rtype == "MeasureRef":
        return str(ref.get("name", "") or "")
    if rtype == "ColumnRef":
        return str(ref.get("column", "") or "")
    if rtype == "HierarchyRef":
        return str(ref.get("_level", "") or ref.get("name", "") or "")
    if rtype == "ParamRef":
        return str(ref.get("name", "") or "")
    return ""


def _first_ref_label(encodings: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        if k not in encodings:
            continue
        v = encodings.get(k)
        ref = v[0] if isinstance(v, list) and v else v
        label = _ref_display_name(ref if isinstance(ref, dict) else {})
        if label:
            return label
    return ""


def _field_display_name(field_obj: dict) -> str:
    if "Measure" in field_obj:
        return str(field_obj.get("Measure", {}).get("Property", "") or "")
    if "Column" in field_obj:
        return str(field_obj.get("Column", {}).get("Property", "") or "")
    if "HierarchyLevel" in field_obj:
        return str(field_obj.get("HierarchyLevel", {}).get("Level", "") or "")
    return ""


def _derive_auto_title(encodings: dict, vis: dict | None = None) -> str:
    if isinstance(vis, dict):
        query_state = vis.get("query", {}).get("queryState", {})
        value_label = ""
        category_label = ""
        for key in ("Y", "Values", "y", "values"):
            role = query_state.get(key) if isinstance(query_state, dict) else None
            projections = role.get("projections", []) if isinstance(role, dict) else []
            if projections:
                value_label = _field_display_name(projections[0].get("field", {}))
                if value_label:
                    break
        for key in ("Category", "X", "category", "x", "Rows", "Columns"):
            role = query_state.get(key) if isinstance(query_state, dict) else None
            projections = role.get("projections", []) if isinstance(role, dict) else []
            if projections:
                category_label = _field_display_name(projections[0].get("field", {}))
                if category_label:
                    break
        if value_label and category_label and value_label.lower() != category_label.lower():
            return f"{value_label} by {category_label}"
        if value_label or category_label:
            return value_label or category_label

    value_label = _first_ref_label(encodings, ("value", "values", "y", "y2", "x"))
    category_label = _first_ref_label(encodings, ("x", "names", "columns", "rows", "path", "y"))
    if value_label and category_label and value_label.lower() != category_label.lower():
        return f"{value_label} by {category_label}"
    return value_label or category_label or ""


def _extract_sort_config_from_query(vis: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    sort_entries = (
        vis.get("query", {})
        .get("sortDefinition", {})
        .get("sort", [])
    )
    for s in sort_entries:
        ref = _extract_field_ref(s.get("field", {}))
        if not ref:
            continue
        table = ""
        field = ""
        if ref.get("type") == "MeasureRef":
            table = str(ref.get("table", "") or "")
            field = str(ref.get("name", "") or "")
        elif ref.get("type") == "ColumnRef":
            table = str(ref.get("table", "") or "")
            field = str(ref.get("column", "") or "")
        elif ref.get("type") == "HierarchyRef":
            table = str(ref.get("_source_table", "") or "")
            field = str(ref.get("_level", "") or ref.get("name", "") or "")
        if not field:
            continue
        direction_raw = str(s.get("direction", "Descending") or "Descending").lower()
        direction = "ascending" if direction_raw.startswith("asc") else "descending"
        key = (table, field, direction)
        if key in seen:
            continue
        seen.add(key)
        out.append({"table": table, "field": field, "direction": direction})
    return out


def _extract_visual_filters(visual_data: dict) -> list[dict]:
    """Extract filters from a PBIR visual's filterConfig.

    Handles standard filters (Categorical, Advanced) and TopN filters.
    """
    fc = visual_data.get("filterConfig", {})
    filters = fc.get("filters", [])
    result = []
    for f in filters:
        field_ref = _extract_field_ref(f.get("field", {}))
        if not field_ref:
            continue

        filter_type = f.get("type", "")

        # TopN filter — special handling
        if filter_type == "TopN":
            filter_entry: dict[str, Any] = {
                "column": field_ref,
                "operator": "topn",
                "filter_type": "TopN",
            }
            # Extract TopN details from the filter expression
            filt = f.get("filter", {})
            top = filt.get("Top", {})
            if top:
                count = top.get("Count", 5)
                filter_entry["count"] = count
            result.append(filter_entry)
            continue
        
        filter_entry = {
            "column": field_ref,
            "operator": "exists",  # default
        }
        if filter_type:
            filter_entry["filter_type"] = filter_type
        
        # Parse filter conditions
        filt = f.get("filter", {})
        where = filt.get("Where", [])
        if where:
            for cond in where:
                condition = cond.get("Condition", {})
                if "In" in condition:
                    filter_entry["operator"] = "in"
                    vals = condition["In"].get("Values", [])
                    filter_entry["values"] = []
                    for v_list in vals:
                        for v in v_list:
                            lit = v.get("Literal", {}).get("Value", "")
                            if lit:
                                filter_entry["values"].append(lit.strip("'"))
                elif "Comparison" in condition:
                    comp = condition["Comparison"]
                    kind = comp.get("ComparisonKind", 0)
                    kind_map = {0: "eq", 1: "gt", 2: "gte", 3: "lt", 4: "lte", 5: "ne"}
                    filter_entry["operator"] = kind_map.get(kind, "eq")
                    right = comp.get("Right", {})
                    if "Literal" in right:
                        filter_entry["value"] = right["Literal"].get("Value", "").strip("'")
        
        # Skip PBI-internal "exists" scaffolding filters — these are auto-created
        # for every field in visual encodings and are not real user-applied filters.
        if filter_entry.get("operator") == "exists":
            continue
        result.append(filter_entry)
    
    return result


# ---------------------------------------------------------------------------
# Preview (non-destructive analysis)
# ---------------------------------------------------------------------------

def preview_report_transfer(report_dir: str) -> dict:
    """
    Analyze a PBIR .Report directory and return a transfer plan
    without writing anything to disk.
    """
    pages_dir = os.path.join(report_dir, "definition", "pages")
    if not os.path.isdir(pages_dir):
        return {"error": f"Not a valid PBIR .Report directory: {report_dir}"}

    report_name = Path(report_dir).stem

    # Read pages order
    pages_json = os.path.join(pages_dir, "pages.json")
    page_order = []
    if os.path.isfile(pages_json):
        pdata = _read_json(pages_json)
        page_order = pdata.get("pageOrder", [])
    if not page_order:
        page_order = [x for x in os.listdir(pages_dir)
                       if os.path.isdir(os.path.join(pages_dir, x))]

    # Read report-level filters
    report_json_path = os.path.join(report_dir, "definition", "report.json")
    report_data = _read_json(report_json_path)
    report_filters = report_data.get("filterConfig", {}).get("filters", [])

    pages = []
    visuals = []
    all_page_filters = []
    unsupported = set()

    for order, page_id in enumerate(page_order, 1):
        page_dir = os.path.join(pages_dir, page_id)
        pj = _read_json(os.path.join(page_dir, "page.json"))
        page_name = pj.get("displayName", page_id)
        page_hidden = pj.get("visibility", "") == "HiddenInViewMode"
        has_drillthrough = "pageBinding" in pj

        pages.append({
            "page_id": page_id,
            "name": page_name,
            "order": order,
            "width": pj.get("width", 1280),
            "height": pj.get("height", 720),
            "hidden": page_hidden,
            "is_drillthrough": has_drillthrough,
        })

        # Page-level filters
        page_fc = pj.get("filterConfig", {}).get("filters", [])
        for pf in page_fc:
            ref = _extract_field_ref(pf.get("field", {}))
            if ref:
                all_page_filters.append({
                    "page": page_name,
                    "field": ref,
                })

        # Visuals
        visuals_dir = os.path.join(page_dir, "visuals")
        if not os.path.isdir(visuals_dir):
            continue

        for vis_folder in os.listdir(visuals_dir):
            vis_json_path = os.path.join(visuals_dir, vis_folder, "visual.json")
            if not os.path.isfile(vis_json_path):
                continue

            vdata = _read_json(vis_json_path)
            vis = vdata.get("visual", {})
            pos = vdata.get("position", {})
            pbi_type = vis.get("visualType", "unknown")
            
            if "visualGroup" in vdata:
                pbi_type = "visualGroup"

            project_type = _VISUAL_TYPE_MAP.get(pbi_type, "")
            is_supported = bool(project_type)
            if not is_supported:
                unsupported.add(pbi_type)

            # Count fields
            encodings = _extract_encodings(vdata)
            field_count = sum(
                len(v) if isinstance(v, list) else 1
                for v in encodings.values()
            )

            # Count filters
            vis_filters = _extract_visual_filters(vdata)

            # Title
            vco = vis.get("visualContainerObjects", {})
            title = ""
            for t in vco.get("title", []):
                text = t.get("properties", {}).get("text", {})
                lit = text.get("expr", {}).get("Literal", {}).get("Value", "")
                if lit:
                    title = lit.strip("'")

            visuals.append({
                "visual_id": vdata.get("name", vis_folder),
                "visual_type_pbi": pbi_type,
                "visual_type_project": project_type or "(unsupported)",
                "page": page_name,
                "page_id": page_id,
                "title": title,
                "x": pos.get("x", 0),
                "y": pos.get("y", 0),
                "width": pos.get("width", 0),
                "height": pos.get("height", 0),
                "field_count": field_count,
                "filter_count": len(vis_filters),
                "is_supported": is_supported,
            })

    # Read bookmarks
    bookmarks_dir = os.path.join(report_dir, "definition", "bookmarks")
    bookmark_count = 0
    if os.path.isdir(bookmarks_dir):
        for bk_folder in os.listdir(bookmarks_dir):
            bk_json = os.path.join(bookmarks_dir, bk_folder, "bookmark.json")
            if os.path.isfile(bk_json):
                bookmark_count += 1

    return {
        "report_name": report_name,
        "report_dir": report_dir,
        "pages": pages,
        "visuals": visuals,
        "summary": {
            "total_pages": len(pages),
            "total_visuals": len(visuals),
            "supported_visuals": sum(1 for v in visuals if v["is_supported"]),
            "unsupported_visuals": sum(1 for v in visuals if not v["is_supported"]),
            "unsupported_types": sorted(unsupported),
            "total_fields": sum(v["field_count"] for v in visuals),
            "total_visual_filters": sum(v["filter_count"] for v in visuals),
            "report_filters": len(report_filters),
            "page_filters": len(all_page_filters),
            "bookmarks": bookmark_count,
        },
    }


# ---------------------------------------------------------------------------
# Execute Transfer
# ---------------------------------------------------------------------------

def execute_report_transfer(
    report_dir: str,
    output_project_dir: str,
    *,
    skip_unsupported: bool = True,
    merge_existing: bool = False,
) -> TransferResult:
    """
    Transfer a PBIR .Report into the project's native report format.

    Writes:
    - reports/pages.yaml
    - reports/visuals/<id>.json (one per supported visual)
    - reports/filters.yaml (report + page + visual filters)
    - reports/bookmarks.yaml (if bookmarks exist)
    """
    result = TransferResult(project_path=output_project_dir)
    
    pages_dir = os.path.join(report_dir, "definition", "pages")
    if not os.path.isdir(pages_dir):
        result.warnings.append(f"Not a valid PBIR .Report directory: {report_dir}")
        return result

    report_name = Path(report_dir).stem
    reports_out = os.path.join(output_project_dir, "reports")
    visuals_out = os.path.join(reports_out, "visuals")
    os.makedirs(visuals_out, exist_ok=True)

    # Clean stale visual files from a previous transfer
    for _old in os.listdir(visuals_out):
        if _old.endswith(".json"):
            os.remove(os.path.join(visuals_out, _old))

    # --- Pages ---
    pages_json_path = os.path.join(pages_dir, "pages.json")
    page_order = []
    if os.path.isfile(pages_json_path):
        pdata = _read_json(pages_json_path)
        page_order = pdata.get("pageOrder", [])
    if not page_order:
        page_order = [x for x in os.listdir(pages_dir)
                       if os.path.isdir(os.path.join(pages_dir, x))]

    pages_yaml_data = {"pages": []}
    page_id_map = {}  # PBI page_id → project page_id

    for order, page_id in enumerate(page_order, 1):
        page_dir = os.path.join(pages_dir, page_id)
        pj = _read_json(os.path.join(page_dir, "page.json"))
        page_name = pj.get("displayName", page_id)
        page_hidden = pj.get("visibility", "") == "HiddenInViewMode"
        has_drillthrough = "pageBinding" in pj

        # Generate a short project page id
        project_page_id = f"pbi_page{order}"
        page_id_map[page_id] = project_page_id

        page_entry: dict[str, Any] = {
            "id": project_page_id,
            "title": page_name,
            "order": order,
        }
        p_width = pj.get("width", 1280)
        p_height = pj.get("height", 720)
        if p_width != 1280 or p_height != 720:
            page_entry["width"] = p_width
            page_entry["height"] = p_height
        display_opt = pj.get("displayOption")
        if display_opt:
            page_entry["display_option"] = display_opt
        if page_hidden:
            page_entry["hidden"] = True
        if has_drillthrough:
            page_entry["page_type"] = "drillthrough"
            # Drillthrough binding parameters
            pb = pj.get("pageBinding", {})
            if pb:
                page_entry["drillthrough_binding"] = {
                    "type": pb.get("type", "Drillthrough"),
                    "parameters": [
                        {"name": p.get("name", ""), "bound_filter": p.get("boundFilter", "")}
                        for p in pb.get("parameters", [])
                    ],
                }

        pages_yaml_data["pages"].append(page_entry)
        result.pages_created += 1

    # Write pages.yaml
    pages_yaml_path = os.path.join(reports_out, "pages.yaml")
    if merge_existing and os.path.isfile(pages_yaml_path):
        existing = _read_yaml(pages_yaml_path)
        existing_ids = {p["id"] for p in existing.get("pages", [])}
        for p in pages_yaml_data["pages"]:
            if p["id"] not in existing_ids:
                existing.setdefault("pages", []).append(p)
        pages_yaml_data = existing
    
    with open(pages_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(pages_yaml_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- Interactions config ---
    interactions_json_path = os.path.join(
        report_dir, "definition", "interactions.json")
    interactions_data = _read_json(interactions_json_path)

    # --- Visuals ---
    report_json_path = os.path.join(report_dir, "definition", "report.json")
    report_data = _read_json(report_json_path)

    # --- Load theme dataColors for resolving theme:X@Y color tokens ---
    theme_data_colors: list[str] = []
    try:
        _theme = extract_pbi_theme(report_dir)
        theme_data_colors = _theme.get("dataColors", [])
    except Exception:
        pass  # theme loading is best-effort

    report_default_drill = report_data.get("settings", {}).get("defaultDrillFilterOtherVisuals", True)

    # Collect all filters
    all_report_filters = []
    all_page_filters = {}
    all_visual_filters = {}

    # Collect slicer visuals for conversion to native unified slicers
    slicer_visuals_for_conversion: list[dict[str, Any]] = []

    # Mapping from PBI visual name → project visual ID (for interaction target resolution)
    pbi_name_to_project_id: dict[str, str] = {}

    # Collect auto-date hierarchies discovered from visual encodings.
    # Key: hierarchy name, Value: {"table": str, "levels": list[str]}
    discovered_hierarchies: dict[str, dict[str, Any]] = {}

    # Report-level filters
    for rf in report_data.get("filterConfig", {}).get("filters", []):
        ref = _extract_field_ref(rf.get("field", {}))
        if ref:
            filter_entry = {"column": ref, "scope": "report"}
            vis_filters = _extract_visual_filters({"filterConfig": {"filters": [rf]}})
            if vis_filters:
                filter_entry.update(vis_filters[0])
            all_report_filters.append(filter_entry)
            result.filters_transferred += 1

    for page_id in page_order:
        page_dir = os.path.join(pages_dir, page_id)
        pj = _read_json(os.path.join(page_dir, "page.json"))
        project_page_id = page_id_map.get(page_id, page_id)

        # Page-level filters
        page_fc = pj.get("filterConfig", {}).get("filters", [])
        if page_fc:
            page_filter_list = []
            for pf in page_fc:
                vis_filters = _extract_visual_filters({"filterConfig": {"filters": [pf]}})
                for vf in vis_filters:
                    vf["scope"] = "page"
                    vf["target"] = project_page_id
                    page_filter_list.append(vf)
                    result.filters_transferred += 1
            if page_filter_list:
                all_page_filters[project_page_id] = page_filter_list

        # Walk visuals
        visuals_dir = os.path.join(page_dir, "visuals")
        if not os.path.isdir(visuals_dir):
            continue

        # --- Pre-pass: collect group container positions for coordinate resolution ---
        # Child visuals in PBI use coordinates RELATIVE to their parent group.
        # We need to convert to absolute canvas coords by adding the parent's position.
        group_positions: dict[str, dict[str, float]] = {}  # group_name -> {x, y}
        for _gf in os.listdir(visuals_dir):
            _gv_path = os.path.join(visuals_dir, _gf, "visual.json")
            if not os.path.isfile(_gv_path):
                continue
            _gv = _read_json(_gv_path)
            if "visualGroup" in _gv:
                _gname = _gv.get("name", _gf)
                _gpos = _gv.get("position", {})
                group_positions[_gname] = {
                    "x": _gpos.get("x", 0),
                    "y": _gpos.get("y", 0),
                }

        for vis_folder in os.listdir(visuals_dir):
            vis_json_path = os.path.join(visuals_dir, vis_folder, "visual.json")
            if not os.path.isfile(vis_json_path):
                continue

            vdata = _read_json(vis_json_path)
            vis = vdata.get("visual", {})
            pos = vdata.get("position", {})
            pbi_type = vis.get("visualType", "unknown")

            if "visualGroup" in vdata:
                pbi_type = "visualGroup"

            project_type = _VISUAL_TYPE_MAP.get(pbi_type, "")
            if not project_type:
                if skip_unsupported:
                    result.unsupported_visual_types.append(pbi_type)
                    result.warnings.append(
                        f"Skipped unsupported visual type '{pbi_type}' "
                        f"(visual {vdata.get('name', vis_folder)} on page {pj.get('displayName', page_id)})"
                    )
                    continue
                else:
                    project_type = pbi_type  # Keep original type name

            vis_id = vdata.get("name", vis_folder)
            project_vis_id = f"pbi_{vis_id[:12]}"

            # Track PBI visual name → project ID for interaction target resolution
            pbi_name_to_project_id[vis_id] = project_vis_id

            # Build encodings
            encodings = _extract_encodings(vdata)

            # Collect hierarchy info directly from raw queryState (before dedup
            # strips duplicate HierarchyRef projections with different _level values).
            vis_inner = vdata.get("visual", {})
            for _role_data in (vis_inner.get("query", {}).get("queryState", {}) or {}).values():
                for _proj in (_role_data.get("projections", []) or []):
                    _field = _proj.get("field", {})
                    if "HierarchyLevel" in _field:
                        _ref = _extract_field_ref(_field)
                        if _ref and _ref.get("type") == "HierarchyRef":
                            h_name = _ref.get("name", "")
                            src_table = _ref.pop("_source_table", None)
                            level = _ref.pop("_level", None)
                            if h_name and src_table and level:
                                entry = discovered_hierarchies.setdefault(
                                    h_name, {"table": src_table, "levels": []})
                                if level not in entry["levels"]:
                                    entry["levels"].append(level)

            # Strip internal _source_table/_level from encoding refs
            def _strip_internal_fields(enc_val: Any) -> None:
                items = enc_val if isinstance(enc_val, list) else [enc_val]
                for ref in items:
                    if isinstance(ref, dict):
                        ref.pop("_source_table", None)
                        ref.pop("_level", None)
            for _enc_val in encodings.values():
                _strip_internal_fields(_enc_val)

            # --- Run comprehensive crawlers on adapted visual ---
            adapted = copy.deepcopy(vdata)
            adapt_pbir_to_legacy(adapted)
            crawler_results = crawl_visual_all(adapted, visualname="visual")

            # --- Enrich visual data from crawler results ---

            # Sort configuration from order_by crawler + query.sortDefinition fallback
            sort_config = []
            for item in crawler_results.get("order_by", []):
                # 6-tuple: (Table, Field, UsedIn, Direction, JsonPath, OriginalJson)
                table, fld, used_in, direction, *_ = item
                sort_config.append({
                    "table": table or "",
                    "field": fld or "",
                    "direction": "ascending" if direction == 1 else "descending",
                })
            for item in _extract_sort_config_from_query(vis):
                if item not in sort_config:
                    sort_config.append(item)
            if sort_config:
                result.sort_configs_transferred += len(sort_config)

            # Field parameters from field_parameters crawler
            field_params = []
            for item in crawler_results.get("field_parameters", []):
                # 7-tuple: (Table, Field, "FieldParameter", DefaultRef, JsonPath, OriginalJson, Role)
                table, fld, _, default_ref, _, _, role = item
                field_params.append({
                    "table": table or "",
                    "field": fld or "",
                    "default_ref": default_ref or "",
                    "role": role or "",
                })
            if field_params:
                result.field_parameters_transferred += len(field_params)

            # Native visual calculations
            native_calcs = []
            for item in crawler_results.get("native_calcs", []):
                # 7-tuple: (Table, CalcName, Source, Direction, DaxExpr, JsonPath, OriginalJson)
                _, calc_name, source, direction, dax_expr, *_ = item
                native_calcs.append({
                    "name": calc_name or "",
                    "expression": dax_expr or "",
                    "direction": direction,
                })
            if native_calcs:
                result.native_calcs_transferred += len(native_calcs)

            # Column formatting
            col_formatting = []
            for item in crawler_results.get("column_formatting", []):
                # 7-tuple: (Table, Field, Source, Condition, Value, JsonPath, OriginalJson)
                table, fld, _, _, value, *_ = item
                if fld:
                    col_formatting.append({
                        "table": table or "", "field": fld,
                        "format_string": value,
                    })
            if col_formatting:
                result.column_formatting_transferred += len(col_formatting)

            # Values formatting
            val_formatting = []
            for item in crawler_results.get("values_formatting", []):
                table, fld, _, _, value, *_ = item
                if fld:
                    val_formatting.append({
                        "table": table or "", "field": fld,
                        "format_string": value,
                    })
            if val_formatting:
                result.values_formatting_transferred += len(val_formatting)

            # Column widths
            col_widths = []
            for item in crawler_results.get("column_widths", []):
                # 6-tuple: (Table, Field, Source, Value, JsonPath, OriginalJson)
                table, fld, _, value, *_ = item
                if fld:
                    # Clean PBI literal suffix (trailing 'D') and parse to float
                    width_val = value
                    if isinstance(width_val, str):
                        width_val = width_val.rstrip('Dd')
                        try:
                            width_val = float(width_val)
                        except (ValueError, TypeError):
                            width_val = 100  # fallback default
                    col_widths.append({
                        "table": table or "", "field": fld, "width": width_val,
                    })
            if col_widths:
                result.column_widths_transferred += len(col_widths)

            # Hierarchy levels
            hierarchy_items = []
            for item in crawler_results.get("hierarchy_levels", []):
                # 6-tuple: (Table, Level, "Hierarchy", HierarchyName, JsonPath, OriginalJson)
                table, level, _, hier_name, *_ = item
                hierarchy_items.append({
                    "table": table or "", "level": level or "",
                    "hierarchy": hier_name or "",
                })
            if hierarchy_items:
                result.hierarchy_levels_transferred += len(hierarchy_items)

            # Slicer sync group
            sync_group = None
            for item in crawler_results.get("slicer_sync_group", []):
                sync_group = item[1]  # GroupName
                result.slicer_sync_groups_transferred += 1

            # Reference lines
            ref_lines = []
            for item in crawler_results.get("reference_lines", []):
                # 7-tuple: (Table, Field, UsedIn, Cond, Value, JsonPath, OriginalJson)
                table, fld, used_in, *_ = item
                if fld:
                    ref_lines.append({
                        "table": table or "", "field": fld, "axis": used_in,
                    })
            if ref_lines:
                result.reference_lines_transferred += len(ref_lines)

            # Expansion states
            expansion_states = []
            for item in crawler_results.get("expansion_queryrefs", []):
                table, fld, *_ = item
                if fld:
                    expansion_states.append({"table": table or "", "field": fld})

            # Display name overrides from column_properties_labels
            label_overrides = {}
            for item in crawler_results.get("column_properties_labels", []):
                # 6-tuple: (Table, Field, UsedIn, Condition, Value, JsonPath)
                table, fld, _, _, display_name, *_ = item
                if table and fld and display_name:
                    label_overrides[f"{table}.{fld}"] = display_name

            # Scope selectors (conditional formatting)
            scope_selectors = []
            for item in crawler_results.get("scope_selectors", []):
                table, fld, used_in, *_ = item
                if fld:
                    scope_selectors.append({
                        "table": table or "", "field": fld, "section": used_in,
                    })

            # Datapoint selectors
            dp_selectors = []
            for item in crawler_results.get("datapoint_selectors", []):
                table, fld, used_in, _, value, *_ = item
                if fld:
                    dp_selectors.append({
                        "table": table or "", "field": fld, "value": value,
                    })

            # Cached filter names/ids
            cached_filters = []
            for item in crawler_results.get("cached_filter_display_items", []):
                cached_filters.append({"display_name": item[1]})
            for item in crawler_results.get("cached_filter_ids", []):
                table, fld = item[0], item[1]
                cached_filters.append({"table": table, "field": fld})

            # Visual selector objects
            vis_selector_objects = []
            for item in crawler_results.get("visual_selector_objects", []):
                table, fld, _, value, *_ = item
                if fld:
                    vis_selector_objects.append({
                        "table": table or "", "field": fld, "value": value,
                    })

            # Track per-visual crawler counts for verification
            vis_crawler_counts = {}
            for cat, items in crawler_results.items():
                vis_crawler_counts[cat] = len(items)
            result.source_crawler_counts[project_vis_id] = vis_crawler_counts

            # Title / Subtitle
            vco = vis.get("visualContainerObjects", {})
            title = ""
            subtitle = ""
            for t in vco.get("title", []):
                text = t.get("properties", {}).get("text", {})
                lit = text.get("expr", {}).get("Literal", {}).get("Value", "")
                if lit:
                    title = lit.strip("'")
                meas = text.get("expr", {}).get("Measure", {})
                if meas:
                    title = f"[{meas.get('Property', '')}]"
            for s in vco.get("subTitle", []):
                text = s.get("properties", {}).get("text", {})
                lit = text.get("expr", {}).get("Literal", {}).get("Value", "")
                if lit:
                    subtitle = lit.strip("'")

            # Format options (colors, background, border)
            format_opts: dict[str, Any] = {}
            # Background color (only if shown)
            for bg in vco.get("background", []):
                props = bg.get("properties", {})
                show = _pbi_literal(props.get("show", {}), True)
                if show is not False:
                    color = _extract_color_value(props.get("color", {}))
                    if color:
                        format_opts["backgroundColor"] = color
            # Border color (only if shown)
            for bd in vco.get("border", []):
                props = bd.get("properties", {})
                show = _pbi_literal(props.get("show", {}), True)
                if show is not False:
                    color = _extract_color_value(props.get("color", {}))
                    if color:
                        format_opts["borderColor"] = color

            # Data point colors (flat list + value→color map)
            dp_colors = []
            dp_color_map: dict[str, str] = {}  # selector_value → color
            for dp in vis.get("objects", {}).get("dataPoint", []):
                fill = dp.get("properties", {}).get("fill", {})
                color = _extract_color_value(fill)
                if color:
                    # Resolve theme:X@Y to hex if theme colors are available
                    if theme_data_colors and color.startswith("theme:"):
                        color = _resolve_theme_color(color, theme_data_colors)
                    dp_colors.append(color)
                    # Try to extract the selector value for this dataPoint
                    selector = dp.get("selector", {})
                    for sd in selector.get("data", []):
                        scope = sd.get("scopeId", {})
                        comp = scope.get("Comparison", {})
                        if comp.get("ComparisonKind") == 0:  # Equals
                            right = comp.get("Right", {}).get("Literal", {}).get("Value", "")
                            left_col = comp.get("Left", {}).get("Column", {})
                            left_field = left_col.get("Property", "")
                            if right:
                                val = right.strip("'")
                                dp_color_map[val] = color
            if dp_colors:
                format_opts["dataPointColors"] = dp_colors
            if dp_color_map:
                format_opts["colorMap"] = dp_color_map

            # --- VCO: show/hide, border, shadow, padding, preset, divider ---
            vco_props = _extract_vco_properties(vco)
            if vco_props:
                format_opts.update(vco_props)

            # --- PBI defaults for VCO properties not explicitly set ---
            # PBI default: chart types show title by default; non-chart types hide it.
            _CHART_TYPES_WITH_TITLE = {
                "bar", "column", "combo", "line", "area", "scatter",
                "pie", "donut", "treemap", "funnel", "waterfall",
                "histogram", "box", "violin", "matrix", "table",
            }
            if "showTitle" not in format_opts:
                format_opts["showTitle"] = project_type in _CHART_TYPES_WITH_TITLE
            # PBI default: chart types show the visual header (title bar); non-chart types hide it.
            if "showVisualHeader" not in format_opts:
                format_opts["showVisualHeader"] = project_type in _CHART_TYPES_WITH_TITLE
            # PBI default: textbox backgrounds are transparent (no card background)
            if project_type == "textbox" and "background_show" not in format_opts:
                format_opts["background_show"] = False

            # --- Chart-level objects: legend, labels, axes, grid, etc. ---
            chart_objs = _extract_chart_objects(vis)
            if chart_objs:
                format_opts["chart_objects"] = chart_objs

            # --- Resolve all theme:X@Y color tokens to hex ---
            if theme_data_colors:
                _THEME_COLOR_KEYS = (
                    "backgroundColor", "borderColor", "titleFontColor",
                    "titleBackground", "subtitleFontColor", "divider_color",
                    "shape_outline_color",
                )
                for _ck in _THEME_COLOR_KEYS:
                    _cv = format_opts.get(_ck)
                    if isinstance(_cv, str) and _cv.startswith("theme:"):
                        format_opts[_ck] = _resolve_theme_color(_cv, theme_data_colors)
                # Resolve inside nested dicts
                _ds = format_opts.get("drop_shadow")
                if isinstance(_ds, dict):
                    _sc = _ds.get("shadowColor")
                    if isinstance(_sc, str) and _sc.startswith("theme:"):
                        _ds["shadowColor"] = _resolve_theme_color(_sc, theme_data_colors)
                # Resolve inside chart_objects
                if chart_objs:
                    for _axis_key in ("category_axis", "value_axis"):
                        _ax = chart_objs.get(_axis_key, {})
                        _afc = _ax.get("fontColor")
                        if isinstance(_afc, str) and _afc.startswith("theme:"):
                            _ax["fontColor"] = _resolve_theme_color(_afc, theme_data_colors)
                        _agc = _ax.get("gridlineColor")
                        if isinstance(_agc, str) and _agc.startswith("theme:"):
                            _ax["gridlineColor"] = _resolve_theme_color(_agc, theme_data_colors)
                    _leg = chart_objs.get("legend", {})
                    _lfc = _leg.get("fontColor")
                    if isinstance(_lfc, str) and _lfc.startswith("theme:"):
                        _leg["fontColor"] = _resolve_theme_color(_lfc, theme_data_colors)
                    # Column formatting (matrix)
                    for _cf in chart_objs.get("column_formatting", []):
                        _cfc = _cf.get("fontColor")
                        if isinstance(_cfc, str) and _cfc.startswith("theme:"):
                            _cf["fontColor"] = _resolve_theme_color(_cfc, theme_data_colors)
                        _db = _cf.get("dataBars", {})
                        for _dbk in ("positiveColor", "negativeColor", "axisColor"):
                            _dbc = _db.get(_dbk)
                            if isinstance(_dbc, str) and _dbc.startswith("theme:"):
                                _db[_dbk] = _resolve_theme_color(_dbc, theme_data_colors)
                    # Column headers bg
                    _ch = chart_objs.get("column_headers", {})
                    _chbg = _ch.get("back_color")
                    if isinstance(_chbg, str) and _chbg.startswith("theme:"):
                        _ch["back_color"] = _resolve_theme_color(_chbg, theme_data_colors)
                    # Total formatting
                    _tt = chart_objs.get("total", {})
                    for _ttk in ("backColor", "fontColor"):
                        _ttc = _tt.get(_ttk)
                        if isinstance(_ttc, str) and _ttc.startswith("theme:"):
                            _tt[_ttk] = _resolve_theme_color(_ttc, theme_data_colors)

            # --- PBI chart type → orientation & barMode promotion ---
            # PBI "Bar" types are horizontal; "Column" types are vertical.
            # Stacked/100% types get barMode = "stack" / "relative".
            _HORIZONTAL_BAR_TYPES = {
                "barChart", "clusteredBarChart", "stackedBarChart",
                "hundredPercentStackedBarChart",
            }
            _STACKED_TYPES = {"stackedBarChart", "stackedColumnChart"}
            _PERCENT_STACKED_TYPES = {
                "hundredPercentStackedBarChart",
                "hundredPercentStackedColumnChart",
            }
            if pbi_type in _HORIZONTAL_BAR_TYPES:
                format_opts["orientation"] = "h"
            if pbi_type in _STACKED_TYPES:
                format_opts["barMode"] = "stack"
            elif pbi_type in _PERCENT_STACKED_TYPES:
                format_opts["barMode"] = "relative"

            # --- Promote chart_layout properties to flat format keys ---
            # The renderer reads flat keys (barMode, bargap, etc.) but
            # chart_layout is nested under chart_objects.  Promote
            # overlap/gap/seriesOrder props so the renderer can use them.
            if chart_objs:
                cl = chart_objs.get("chart_layout", {})
                if cl.get("clusteredGapOverlaps"):
                    # PBI "clusteredGapOverlaps" means bars overlap in
                    # the same category slot → Plotly barmode "overlay"
                    format_opts["barMode"] = "overlay"
                gap = cl.get("clusteredGapSize")
                if gap is not None:
                    # PBI gap size ≈ percentage → Plotly bargap [0..1]
                    format_opts["bargap"] = max(0.0, min(1.0, gap / 100.0))
                # seriesOrderReversed → reverse trace order in render
                if cl.get("seriesOrderReversed"):
                    format_opts["seriesOrderReversed"] = True
                # clusteredGapOverlapReverse → put earlier series behind
                if cl.get("clusteredGapOverlapReverse"):
                    format_opts["clusteredGapOverlapReverse"] = True

                # --- Promote legend settings to flat format keys ---
                legend = chart_objs.get("legend", {})
                if "show" in legend:
                    format_opts.setdefault("showLegend", legend["show"])
                if "position" in legend:
                    format_opts.setdefault("legendPosition", legend["position"])
                if "show_gradient" in legend:
                    format_opts.setdefault("legendShowGradient", legend["show_gradient"])

                # --- Promote labels (data labels) to flat format keys ---
                # Card visuals use labels.fontSize for the *value* display,
                # not for chart data-labels.  Promote to card-specific keys
                # and skip the generic chart-label promotion for cards.
                if project_type == "card":
                    labels = chart_objs.get("labels", {})
                    if "fontSize" in labels:
                        format_opts.setdefault("cardValueFontSize", labels["fontSize"])

                    # --- Promote card category-label properties ---
                    cat_lbl = chart_objs.get("category_labels", {})
                    if "show" in cat_lbl:
                        format_opts.setdefault("cardCategoryLabelsShow", cat_lbl["show"])
                    if "fontSize" in cat_lbl:
                        format_opts.setdefault("cardCategoryFontSize", cat_lbl["fontSize"])
                    if "color" in cat_lbl:
                        _cc = cat_lbl["color"]
                        if theme_data_colors and isinstance(_cc, str) and _cc.startswith("theme:"):
                            _cc = _resolve_theme_color(_cc, theme_data_colors)
                        format_opts.setdefault("cardCategoryColor", _cc)

                    # --- Promote card accent-bar properties ---
                    card_obj = chart_objs.get("card", {})
                    if "barColor" in card_obj:
                        _bc = card_obj["barColor"]
                        if theme_data_colors and isinstance(_bc, str) and _bc.startswith("theme:"):
                            _bc = _resolve_theme_color(_bc, theme_data_colors)
                        format_opts.setdefault("cardBarColor", _bc)
                    if "barWeight" in card_obj:
                        format_opts.setdefault("cardBarWeight", card_obj["barWeight"])

                    # --- Promote dataLabels properties ---
                    data_lbl = chart_objs.get("data_labels", {})
                    if "fontFamily" in data_lbl:
                        format_opts.setdefault("cardDataLabelsFontFamily", data_lbl["fontFamily"])
                    if "fontSize" in data_lbl:
                        format_opts.setdefault("cardDataLabelsFontSize", data_lbl["fontSize"])
                else:
                    labels = chart_objs.get("labels", {})
                    if "show" in labels:
                        format_opts.setdefault("showDataLabels", labels["show"])
                    if "position" in labels:
                        # Map PBI label positions to Plotly equivalents
                        pos_map = {
                            "Auto": "auto",
                            "OutsideEnd": "outside",
                            "InsideEnd": "inside",
                            "InsideBase": "inside",
                            "InsideCenter": "inside",
                        }
                        pbi_pos = labels["position"]
                        plotly_pos = pos_map.get(pbi_pos, pbi_pos.lower() if isinstance(pbi_pos, str) else "auto")
                        format_opts.setdefault("dataLabelPosition", plotly_pos)
                    if "color" in labels:
                        _lc = labels["color"]
                        if theme_data_colors and isinstance(_lc, str) and _lc.startswith("theme:"):
                            _lc = _resolve_theme_color(_lc, theme_data_colors)
                        format_opts.setdefault("dataLabelColor", _lc)
                    if "fontSize" in labels:
                        format_opts.setdefault("dataLabelFontSize", labels["fontSize"])
                    if "fontFamily" in labels:
                        format_opts.setdefault("dataLabelFontFamily", labels["fontFamily"])
                    if "displayUnits" in labels:
                        format_opts.setdefault("dataLabelDisplayUnits", labels["displayUnits"])
                    if "precision" in labels:
                        format_opts.setdefault("dataLabelPrecision", labels["precision"])
                    if "transparency" in labels:
                        format_opts.setdefault("dataLabelTransparency", labels["transparency"])

                # --- Promote category axis settings ---
                cat_axis = chart_objs.get("category_axis", {})
                if "show" in cat_axis:
                    format_opts.setdefault("showXAxis", cat_axis["show"])
                if "show_title" in cat_axis:
                    format_opts.setdefault("showXAxisTitle", cat_axis["show_title"])
                if "axis_type" in cat_axis:
                    format_opts.setdefault("categoryAxisType", cat_axis["axis_type"])
                if "inner_padding" in cat_axis:
                    format_opts.setdefault("categoryAxisInnerPadding", cat_axis["inner_padding"])

                # --- Promote value axis settings ---
                val_axis = chart_objs.get("value_axis", {})
                if "show" in val_axis:
                    format_opts.setdefault("showYAxis", val_axis["show"])
                if "show_title" in val_axis:
                    format_opts.setdefault("showYAxisTitle", val_axis["show_title"])

                # --- Promote data point properties ---
                data_pt = chart_objs.get("data_point", {})
                if "border_show" in data_pt:
                    format_opts.setdefault("dataPointBorderShow", data_pt["border_show"])

                # --- Promote structured reference lines from chart_objects ---
                co_ref_lines = chart_objs.get("reference_lines", [])
                if co_ref_lines:
                    format_opts.setdefault("chart_reference_lines", co_ref_lines)

                # --- Promote matrix/pivotTable properties ---
                if "general_layout" in chart_objs:
                    format_opts.setdefault("matrixLayout", chart_objs["general_layout"])
                rh = chart_objs.get("row_headers", {})
                if "stepped_indentation" in rh:
                    format_opts.setdefault("matrixSteppedIndentation", rh["stepped_indentation"])
                grid = chart_objs.get("grid", {})
                if "horizontal" in grid:
                    format_opts.setdefault("matrixGridHorizontal", grid["horizontal"])
                ch = chart_objs.get("column_headers", {})
                if "back_color" in ch:
                    format_opts.setdefault("matrixColumnHeaderBg", ch["back_color"])
                if "word_wrap" in ch:
                    format_opts.setdefault("matrixColumnHeaderWordWrap", ch["word_wrap"])
                if "outline_style" in ch:
                    format_opts.setdefault("matrixColumnHeaderOutline", ch["outline_style"])
                if "auto_size_column_width" in ch:
                    format_opts.setdefault("matrixAutoSizeColumns", ch["auto_size_column_width"])
                    format_opts.setdefault(
                        "matrixColumnWidthMode",
                        "grow_to_fit" if ch["auto_size_column_width"] else "fixed",
                    )

                # --- Promote extended category axis settings ---
                if "fontSize" in cat_axis:
                    format_opts.setdefault("categoryAxisFontSize", cat_axis["fontSize"])
                    format_opts.setdefault("xAxisFontSize", cat_axis["fontSize"])
                if "fontFamily" in cat_axis:
                    format_opts.setdefault("categoryAxisFontFamily", cat_axis["fontFamily"])
                    format_opts.setdefault("xAxisFontFamily", cat_axis["fontFamily"])
                if "fontColor" in cat_axis:
                    format_opts.setdefault("categoryAxisFontColor", cat_axis["fontColor"])
                    format_opts.setdefault("xAxisFontColor", cat_axis["fontColor"])
                if "title_text" in cat_axis:
                    format_opts.setdefault("categoryAxisTitleText", cat_axis["title_text"])
                    # Bridge to Plotly-compatible key
                    format_opts.setdefault("xAxisLabel", cat_axis["title_text"])
                if "label_angle" in cat_axis:
                    format_opts.setdefault("categoryAxisLabelAngle", cat_axis["label_angle"])
                    # Bridge to Plotly-compatible key
                    format_opts.setdefault("xAxisTickAngle", cat_axis["label_angle"])

                # --- Promote extended value axis settings ---
                if "fontSize" in val_axis:
                    format_opts.setdefault("valueAxisFontSize", val_axis["fontSize"])
                    format_opts.setdefault("yAxisFontSize", val_axis["fontSize"])
                if "fontFamily" in val_axis:
                    format_opts.setdefault("valueAxisFontFamily", val_axis["fontFamily"])
                    format_opts.setdefault("yAxisFontFamily", val_axis["fontFamily"])
                if "fontColor" in val_axis:
                    format_opts.setdefault("valueAxisFontColor", val_axis["fontColor"])
                    format_opts.setdefault("yAxisFontColor", val_axis["fontColor"])
                if "title_text" in val_axis:
                    format_opts.setdefault("valueAxisTitleText", val_axis["title_text"])
                    # Bridge to Plotly-compatible key
                    format_opts.setdefault("yAxisLabel", val_axis["title_text"])
                if "start" in val_axis:
                    format_opts.setdefault("valueAxisMin", val_axis["start"])
                    # Bridge to Plotly-compatible key
                    format_opts.setdefault("yAxisMin", val_axis["start"])
                if "end" in val_axis:
                    format_opts.setdefault("valueAxisMax", val_axis["end"])
                    # Bridge to Plotly-compatible key
                    format_opts.setdefault("yAxisMax", val_axis["end"])
                if "displayUnits" in val_axis:
                    format_opts.setdefault("valueAxisDisplayUnits", val_axis["displayUnits"])
                if "precision" in val_axis:
                    format_opts.setdefault("valueAxisPrecision", val_axis["precision"])
                if "gridlines" in val_axis:
                    format_opts.setdefault("valueAxisGridlines", val_axis["gridlines"])
                    # Bridge to Plotly-compatible key
                    format_opts.setdefault("showYAxisGridlines", val_axis["gridlines"])
                if "gridlineColor" in val_axis:
                    format_opts.setdefault("valueAxisGridlineColor", val_axis["gridlineColor"])
                    format_opts.setdefault("yAxisGridlineColor", val_axis["gridlineColor"])

                # --- Promote extended legend settings ---
                legend = chart_objs.get("legend", {})
                if "fontSize" in legend:
                    format_opts.setdefault("legendFontSize", legend["fontSize"])
                if "fontFamily" in legend:
                    format_opts.setdefault("legendFontFamily", legend["fontFamily"])
                if "fontColor" in legend:
                    format_opts.setdefault("legendFontColor", legend["fontColor"])
                if "titleText" in legend:
                    format_opts.setdefault("legendTitleText", legend["titleText"])
                if "showTitle" in legend:
                    format_opts.setdefault("legendShowTitle", legend["showTitle"])

                # --- Promote matrix column_formatting (dataBars) ---
                cf_list = chart_objs.get("column_formatting")
                if cf_list:
                    format_opts.setdefault("matrixColumnFormatting", cf_list)

                # --- Promote matrix column widths ---
                cw_dict = chart_objs.get("column_widths")
                if cw_dict:
                    format_opts.setdefault("matrixColumnWidths", cw_dict)

                # --- Promote matrix values formatting (conditional formatting) ---
                vf_list = chart_objs.get("values_formatting")
                if vf_list:
                    format_opts.setdefault("matrixValuesFormatting", vf_list)

                # --- Promote matrix subTotals config ---
                st_cfg = chart_objs.get("sub_totals")
                if st_cfg:
                    format_opts.setdefault("matrixSubTotals", st_cfg)

                # --- Promote matrix total formatting ---
                total_fmt = chart_objs.get("total")
                if total_fmt:
                    format_opts.setdefault("matrixTotalFormatting", total_fmt)

                # --- Promote plotArea transparency ---
                pa_tr = chart_objs.get("plotArea_transparency")
                if pa_tr is not None:
                    format_opts.setdefault("plotAreaTransparency", pa_tr)

            # --- PBI donutChart → explicit pieHole ---
            # PBI distinguishes pieChart (no hole) from donutChart (hole).
            # Set pieHole so the renderer knows whether to cut a hole.
            if pbi_type == "donutChart":
                format_opts["pieHole"] = 0.35

            # --- Visual link (bookmark/back/page navigation) ---
            visual_link = _extract_visual_link(vco)

            # --- Shape properties (type, fill, outline, rotation) ---
            shape_props = _extract_shape_properties(vis) if project_type == "shape" else None

            # Promote shape outline properties into flat format_opts so renderers
            # can access them alongside other format keys (borderColor, etc.).
            if shape_props:
                oc = shape_props.get("outline_color")
                if oc:
                    if theme_data_colors and oc.startswith("theme:"):
                        oc = _resolve_theme_color(oc, theme_data_colors)
                    format_opts["shape_outline_color"] = oc
                ow = shape_props.get("outline_weight")
                if ow is not None:
                    format_opts["shape_outline_weight"] = ow
                if shape_props.get("outline_show") is False:
                    format_opts["shape_outline_show"] = False
                # Shape with transparent fill → card background must also be transparent
                if shape_props.get("fill_show") is False:
                    format_opts["background_show"] = False

            # --- Textbox rich text content ---
            textbox_content = _extract_textbox_content(vis) if project_type == "textbox" else None

            # --- Slicer config ---
            slicer_cfg = _extract_slicer_config(vis) if project_type == "slicer" else None

            # Promote slicer config keys into flat format_opts so the React
            # slicer renderer can consume them directly.
            if slicer_cfg:
                _SLICER_PROMOTE = {
                    # Layout grid
                    "rowCount": "slicerRowCount",
                    "columnCount": "slicerColumnCount",
                    "style": "slicerStyle",
                    "orientation": "slicerOrientation",
                    "customizePadding": "slicerCustomizePadding",
                    # Tile shape
                    "tile_shape": "slicerTileShape",
                    "rounded_curve": "slicerRoundedCurve",
                    "rounded_curve_custom": "slicerRoundedCurveCustom",
                    # Value text
                    "value_alignment": "slicerValueAlignment",
                    "value_fontSize": "slicerValueFontSize",
                    # Overflow
                    "overflow_style": "slicerOverflowStyle",
                    "overflow_direction": "slicerOverflowDirection",
                    # Image
                    "image_imageFit": "slicerImageFit",
                    "image_padding": "slicerImagePadding",
                    "image_setAsBackGround": "slicerImageAsBackground",
                    "image_ignorePadding": "slicerImageIgnorePadding",
                    "image_position": "slicerImagePosition",
                    "image_saturation": "slicerImageSaturation",
                    # Padding
                    "padding_paddingSelection": "slicerPaddingSelection",
                    "padding_topMargin": "slicerPaddingTop",
                    "padding_bottomMargin": "slicerPaddingBottom",
                    # Fill
                    "fill_custom_show": "slicerFillCustomShow",
                }
                for src_key, dst_key in _SLICER_PROMOTE.items():
                    val = slicer_cfg.get(src_key)
                    if val is not None:
                        format_opts[dst_key] = val

            # --- Button icon (for actionButton) ---
            button_icon = None
            if project_type == "button":
                for ic in vis.get("objects", {}).get("icon", []):
                    shape = _pbi_literal(ic.get("properties", {}).get("shapeType", {}))
                    if shape:
                        button_icon = shape

            # --- Visual group parent ---
            parent_group = vdata.get("parentGroupName")
            is_hidden = vdata.get("isHidden", False)

            # --- Visual group container properties ---
            group_props = None
            if "visualGroup" in vdata:
                vg = vdata["visualGroup"]
                group_props = {
                    "display_name": vg.get("displayName", ""),
                    "group_mode": vg.get("groupMode", ""),
                }

            # Build visual JSON
            # Resolve absolute coordinates for child visuals in groups.
            # PBI stores child positions relative to the parent group container.
            raw_x = pos.get("x", 0)
            raw_y = pos.get("y", 0)
            if parent_group and parent_group in group_positions:
                gp = group_positions[parent_group]
                raw_x += gp["x"]
                raw_y += gp["y"]
            layout_data: dict[str, Any] = {
                "x": round(raw_x),
                "y": round(raw_y),
                "w": round(pos.get("width", 300)),
                "h": round(pos.get("height", 200)),
            }
            # Z-order and tab order
            z = pos.get("z")
            if z is not None:
                layout_data["z"] = z
            tab_order = pos.get("tabOrder")
            if tab_order is not None:
                layout_data["tabOrder"] = tab_order

            _drill_filter = vis.get("drillFilterOtherVisuals")
            if isinstance(_drill_filter, bool):
                _affects_others = _drill_filter
            else:
                _affects_others = bool(report_default_drill)

            _interactions: dict[str, Any] = {
                "affects_others": _affects_others,
                "is_affected": True,
                "mode": "highlight",  # PBI default interaction mode
            }

            visual_json: dict[str, Any] = {
                "id": project_vis_id,
                "title": title or f"{pbi_type} visual",
                "visual_type": project_type,
                "page_id": page_id_map.get(page_id, page_id),
                "layout": layout_data,
                "encodings": encodings,
                "format": format_opts,
                "advanced_plotly_patch": {},
                "interactions": _interactions,
                "_pbi_source": {
                    "visual_id": vis_id,
                    "visual_type": pbi_type,
                    "page_id": page_id,
                }
            }

            if not title:
                _auto_title = _derive_auto_title(encodings, vis)
                if _auto_title:
                    visual_json["title"] = _auto_title

            if subtitle:
                visual_json["subtitle"] = subtitle
            if visual_link:
                visual_json["visual_link"] = visual_link
            if shape_props:
                visual_json["shape_properties"] = shape_props
            if textbox_content:
                visual_json["textbox_content"] = textbox_content

            # Build static_content for React UI from textbox/shape transfer data
            static_content = _build_static_content(
                project_type, textbox_content, shape_props, vco_props, visual_link
            )
            if static_content:
                visual_json["static_content"] = static_content
            if slicer_cfg:
                visual_json["slicer_config"] = slicer_cfg
            if button_icon:
                visual_json["button_icon"] = button_icon
            if parent_group:
                visual_json["parent_group"] = parent_group
            if is_hidden:
                visual_json["hidden"] = True
            if group_props:
                visual_json["group_properties"] = group_props

            # --- Enrich visual JSON with crawler data ---
            if sort_config:
                visual_json["sort"] = sort_config
                # Auto-populate categorySort for Plotly rendering pipeline
                _first_sort = sort_config[0]
                _sort_dir = _first_sort.get("direction", "descending")
                if project_type in (
                    "bar", "column", "combo", "line", "area", "scatter",
                    "histogram", "box", "violin", "strip", "ecdf",
                    "funnel", "funnel_area", "waterfall",
                    "ibcs_bar", "ibcs_column", "ibcs_line",
                ):
                    visual_json.setdefault("format", {})["categorySort"] = f"total {_sort_dir}"
            if field_params:
                visual_json["field_parameters"] = field_params
            if native_calcs:
                visual_json["native_calcs"] = native_calcs
            if col_formatting:
                visual_json.setdefault("format", {})["column_formatting"] = col_formatting
            if val_formatting:
                visual_json.setdefault("format", {})["values_formatting"] = val_formatting
            if col_widths:
                visual_json.setdefault("format", {})["column_widths"] = col_widths

            # Structured conditional formatting (dataBars, gradients, icons)
            cond_fmt = crawler_results.get("conditional_formatting", [])
            if cond_fmt:
                visual_json.setdefault("format", {})["conditional_formatting"] = list(cond_fmt)

            if ref_lines:
                visual_json.setdefault("format", {})["reference_lines"] = ref_lines
            if hierarchy_items:
                visual_json["hierarchy_levels"] = hierarchy_items
            if sync_group:
                visual_json["slicer_sync_group"] = sync_group
            if expansion_states:
                visual_json["expansion_states"] = expansion_states
            if label_overrides:
                visual_json["label_overrides"] = label_overrides
            if scope_selectors:
                visual_json.setdefault("format", {})["scope_selectors"] = scope_selectors
            if dp_selectors:
                visual_json.setdefault("format", {})["datapoint_selectors"] = dp_selectors
            if cached_filters:
                visual_json["cached_filters"] = cached_filters
            if vis_selector_objects:
                visual_json.setdefault("format", {})["visual_selector_objects"] = vis_selector_objects

            # Bridge PBI chart_objects to tablix properties for matrix/table visuals
            if project_type in ("matrix", "table"):
                chart_objs = format_opts.get("chart_objects", {})
                if chart_objs:
                    tablix_defaults = visual_json["encodings"].setdefault("tablix", {})
                    # general_layout → density
                    gen_layout = chart_objs.get("general_layout", "")
                    if isinstance(gen_layout, str) and gen_layout.lower() == "compact":
                        tablix_defaults.setdefault("density", "compact")
                    # grid → gridlines
                    grid = chart_objs.get("grid", {})
                    if isinstance(grid, dict):
                        h = grid.get("horizontal")
                        v = grid.get("vertical")
                        if h is False and v is False:
                            tablix_defaults.setdefault("gridlines", "none")
                        elif h is False or v is False:
                            tablix_defaults.setdefault("gridlines", "light")
                    # column_headers back_color → columnHeaderBackColor
                    col_hdrs = chart_objs.get("column_headers", {})
                    if isinstance(col_hdrs, dict):
                        back_color = col_hdrs.get("back_color")
                        if back_color and isinstance(back_color, str):
                            tablix_defaults.setdefault("columnHeaderBackColor", back_color)
                        auto_size = col_hdrs.get("auto_size_column_width")
                        if isinstance(auto_size, bool):
                            tablix_defaults.setdefault("autofitColumns", auto_size)
                            tablix_defaults.setdefault("columnWidthMode", "grow_to_fit" if auto_size else "fixed")
                        more_granular = col_hdrs.get("more_granular_column_widths", col_hdrs.get("moreGranularColumnWidths"))
                        if isinstance(more_granular, bool):
                            tablix_defaults.setdefault("moreGranularColumnWidths", more_granular)
                    # Seed PBI column widths as initial column widths map
                    chart_widths = chart_objs.get("column_widths") if isinstance(chart_objs, dict) else None
                    chart_initial_widths = {}
                    if isinstance(chart_widths, dict):
                        for key, value in chart_widths.items():
                            try:
                                width_value = float(str(value).rstrip("Dd"))
                            except (TypeError, ValueError):
                                continue
                            if width_value > 0:
                                chart_initial_widths[str(key)] = width_value
                    if col_widths:
                        # Build a lookup: "Table.Field" → width (float)
                        initial_widths = dict(chart_initial_widths)
                        for cw in col_widths:
                            key = f"{cw['table']}.{cw['field']}" if cw.get('table') else cw['field']
                            w = cw.get('width')
                            if isinstance(w, (int, float)) and w > 0:
                                initial_widths[key] = w
                        if initial_widths:
                            tablix_defaults.setdefault("initialColumnWidths", initial_widths)
                    elif chart_initial_widths:
                        tablix_defaults.setdefault("initialColumnWidths", chart_initial_widths)

                    mobile_widths = chart_objs.get("mobile_column_widths") if isinstance(chart_objs, dict) else None
                    if mobile_widths is None and isinstance(chart_objs, dict):
                        mobile_widths = chart_objs.get("mobileColumnWidths")
                    if isinstance(mobile_widths, dict):
                        parsed_mobile_widths = {}
                        for key, value in mobile_widths.items():
                            try:
                                width_value = float(str(value).rstrip("Dd"))
                            except (TypeError, ValueError):
                                continue
                            if width_value > 0:
                                parsed_mobile_widths[str(key)] = width_value
                        if parsed_mobile_widths:
                            tablix_defaults.setdefault("mobileColumnWidths", parsed_mobile_widths)

            # Write visual JSON
            vis_out_path = os.path.join(visuals_out, f"{project_vis_id}.json")
            with open(vis_out_path, "w", encoding="utf-8") as f:
                json.dump(visual_json, f, indent=2, ensure_ascii=False)
            result.visuals_created += 1

            # Collect slicer visuals for native slicer conversion
            if project_type == "slicer":
                slicer_visuals_for_conversion.append(visual_json)

            # Visual-level filters
            vis_filters = _extract_visual_filters(vdata)
            if vis_filters:
                for vf in vis_filters:
                    vf["scope"] = "visual"
                    vf["target"] = project_vis_id
                all_visual_filters[project_vis_id] = vis_filters
                result.filters_transferred += len(vis_filters)

    # --- Apply per-visual interaction targets from interactions.json ---
    # PBI PBIR interactions.json stores per-visual-pair overrides with format:
    # { "modifiedInteractions": [ { "source": {"visualName": "..."}, "target": {"visualName": "..."}, "type": "..." } ] }
    # type values: "noFilter"/"noImpact" → "none", "autoFilter" → "filter", "autoHighlight" → "highlight"
    _PBI_INTERACTION_TYPE_MAP: dict[str, str] = {
        "noFilter": "none",
        "noImpact": "none",
        "autoFilter": "filter",
        "autoHighlight": "highlight",
    }
    modified_interactions = interactions_data.get("modifiedInteractions", [])
    if modified_interactions:
        # Build a dict: source_pbi_name → {target_pbi_name: interaction_type}
        source_targets: dict[str, dict[str, str]] = {}
        for mi in modified_interactions:
            src_name = mi.get("source", {}).get("visualName", "")
            tgt_name = mi.get("target", {}).get("visualName", "")
            raw_type = mi.get("type", "")
            if not src_name or not tgt_name:
                continue
            mapped_type = _PBI_INTERACTION_TYPE_MAP.get(raw_type, raw_type)
            source_targets.setdefault(src_name, {})[tgt_name] = mapped_type

        # Update each visual JSON file that has interaction targets
        for pbi_name, targets_by_pbi_name in source_targets.items():
            src_project_id = pbi_name_to_project_id.get(pbi_name)
            if not src_project_id:
                continue
            # Resolve target PBI names → project IDs
            interaction_targets: dict[str, str] = {}
            for tgt_pbi_name, itype in targets_by_pbi_name.items():
                tgt_project_id = pbi_name_to_project_id.get(tgt_pbi_name)
                if tgt_project_id:
                    interaction_targets[tgt_project_id] = itype
            if not interaction_targets:
                continue
            # Re-read the visual JSON, add interaction_targets, re-write
            vis_out_path = os.path.join(visuals_out, f"{src_project_id}.json")
            if os.path.isfile(vis_out_path):
                with open(vis_out_path, "r", encoding="utf-8") as f:
                    vis_json_data = json.load(f)
                vis_json_data.setdefault("interactions", {})["interaction_targets"] = interaction_targets
                with open(vis_out_path, "w", encoding="utf-8") as f:
                    json.dump(vis_json_data, f, indent=2, ensure_ascii=False)
                result.interactions_transferred += len(interaction_targets)

    # --- Translate German locale day/month names → English in filter values ---
    _translate_filter_values_locale(all_report_filters)
    for _pf_list in all_page_filters.values():
        _translate_filter_values_locale(_pf_list)
    for _vf_list in all_visual_filters.values():
        _translate_filter_values_locale(_vf_list)

    # --- Write filters.yaml ---
    filters_data = {
        "report_filters": all_report_filters,
        "page_filters": all_page_filters if all_page_filters else {},
        "visual_filters": all_visual_filters if all_visual_filters else {},
    }
    filters_path = os.path.join(reports_out, "filters.yaml")
    with open(filters_path, "w", encoding="utf-8") as f:
        yaml.dump(filters_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # --- Generate slicers.yaml from PBI slicer visuals ---
    if slicer_visuals_for_conversion:
        generated_slicers = _generate_native_slicers(slicer_visuals_for_conversion)
        if generated_slicers:
            slicers_path = os.path.join(reports_out, "slicers.yaml")
            # Merge with existing slicers (avoid overwriting user-created ones)
            existing_slicers_data: dict[str, Any] = {}
            if merge_existing and os.path.isfile(slicers_path):
                existing_slicers_data = _read_yaml(slicers_path)
            existing_ids = {
                s.get("id") for s in (existing_slicers_data.get("slicers") or [])
            }
            merged_slicers = list(existing_slicers_data.get("slicers") or [])
            for gs in generated_slicers:
                if gs["id"] not in existing_ids:
                    merged_slicers.append(gs)
            slicers_out_data = {"slicers": merged_slicers}
            with open(slicers_path, "w", encoding="utf-8") as f:
                yaml.dump(slicers_out_data, f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)
            result.slicer_sync_groups_transferred += len(generated_slicers)

    # --- Generate field_parameter_selections.yaml from visual-level defaults ---
    # Two sources of default information:
    # 1. Visual JSONs contain field_parameters[].default_ref (e.g. "Measure Table.Sales Sum")
    #    which capture the PBI designer's intended default for each visual.
    # 2. Slicer defaults (from slicers.yaml) for field parameter hierarchy slicers
    #    indicate which locale/category the designer intended.
    #
    # We build report-scoped selections from slicer defaults (using locale matching)
    # and visual-scoped selections from visual-level default_ref overrides.
    fp_yaml_path = os.path.join(output_project_dir, "model", "field_parameters.yaml")
    if os.path.isfile(fp_yaml_path):
        model_fps = _read_yaml(fp_yaml_path).get("field_parameters", {})

        # Build lookups for matching
        # ref_name_lower → (fp_name, item_name)
        _ref_to_fp_item: dict[str, tuple[str, str]] = {}
        # locale_lower → [(fp_name, item_name), ...]
        _locale_to_fp_items: dict[str, list[tuple[str, str]]] = {}
        # item_name_lower → (fp_name, item_name) per FP
        _name_to_fp_item: dict[str, list[tuple[str, str]]] = {}

        for fp_name, fp_data in model_fps.items():
            items = fp_data.get("items", []) if isinstance(fp_data, dict) else []
            for it in items:
                if not isinstance(it, dict):
                    continue
                ref = it.get("ref", {})
                item_name = it.get("name", "")
                locale_val = it.get("locale", "")
                if not item_name:
                    continue
                # Ref lookup (for visual-level default_ref matching)
                rtype = ref.get("type", "")
                if rtype == "MeasureRef":
                    rkey = str(ref.get("name", "")).strip().lower()
                    if rkey:
                        _ref_to_fp_item[rkey] = (fp_name, item_name)
                elif rtype == "ColumnRef":
                    rkey = f"{ref.get('table', '')}.{ref.get('column', '')}".strip().lower()
                    if rkey:
                        _ref_to_fp_item[rkey] = (fp_name, item_name)
                # Locale lookup (for slicer default matching)
                if locale_val:
                    lk = locale_val.strip().lower()
                    _locale_to_fp_items.setdefault(lk, []).append((fp_name, item_name))
                # Name lookup (for direct name matching)
                nk = item_name.strip().lower()
                _name_to_fp_item.setdefault(nk, []).append((fp_name, item_name))

        report_selections: dict[str, str] = {}  # fp_name → item_name

        # --- Pass 1: Slicer defaults → report-scoped selections ---
        # Each slicer default value is matched against FP items by locale or name.
        slicers_path = os.path.join(reports_out, "slicers.yaml")
        if os.path.isfile(slicers_path):
            sl_data = _read_yaml(slicers_path)
            for sl in (sl_data.get("slicers") or []):
                sel = sl.get("selection", {})
                if sel.get("mode") != "values":
                    continue
                vals = sel.get("values", [])
                if not vals:
                    continue
                # Use the FIRST default value for FP selection
                dv = str(vals[0]).strip()
                if not dv:
                    continue
                dv_lower = dv.lower()
                # Try locale match first
                matches = _locale_to_fp_items.get(dv_lower, [])
                if not matches:
                    # Try direct name match
                    matches = _name_to_fp_item.get(dv_lower, [])
                for fp_name, item_name in matches:
                    model_default = model_fps.get(fp_name, {}).get("default_item", "")
                    if item_name != model_default:
                        report_selections[fp_name] = item_name

        # --- Pass 2: Visual-level default_ref → visual-scoped selections ---
        visual_selections: dict[str, dict[str, str]] = {}
        visuals_dir = os.path.join(reports_out, "visuals")
        if os.path.isdir(visuals_dir):
            for vf in os.listdir(visuals_dir):
                if not vf.endswith(".json"):
                    continue
                vf_path = os.path.join(visuals_dir, vf)
                try:
                    with open(vf_path, encoding="utf-8") as f:
                        vj_data = json.load(f)
                except Exception:
                    continue
                vid = vj_data.get("id", "")
                fps_list = vj_data.get("field_parameters", [])
                if not isinstance(fps_list, list) or not fps_list:
                    continue
                for fp_entry in fps_list:
                    dref = fp_entry.get("default_ref", "")
                    if not dref:
                        continue
                    parts = dref.split(".", 1)
                    if len(parts) == 2:
                        measure_key = parts[1].strip().lower()
                        match = _ref_to_fp_item.get(measure_key)
                        if not match:
                            full_key = dref.strip().lower()
                            match = _ref_to_fp_item.get(full_key)
                        if match:
                            fp_name, item_name = match
                            # Only if different from report-level AND model default
                            model_default = model_fps.get(fp_name, {}).get("default_item", "")
                            report_sel = report_selections.get(fp_name, "")
                            effective_default = report_sel or model_default
                            if item_name != effective_default:
                                visual_selections.setdefault(vid, {})[fp_name] = item_name

        # Write field_parameter_selections.yaml if we have any selections
        if report_selections or visual_selections:
            fps_path = os.path.join(reports_out, "field_parameter_selections.yaml")
            fps_data: dict[str, Any] = {
                "report": {
                    fp_name: {"selected_item_name": item_name}
                    for fp_name, item_name in report_selections.items()
                },
                "page": {},
                "visual": {
                    vid: {
                        fp_name: {"selected_item_name": item_name}
                        for fp_name, item_name in sels.items()
                    }
                    for vid, sels in visual_selections.items()
                },
            }
            with open(fps_path, "w", encoding="utf-8") as f:
                yaml.dump(fps_data, f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)

    # --- Write discovered hierarchies to model/hierarchies.yaml ---
    if discovered_hierarchies:
        hier_yaml_path = os.path.join(output_project_dir, "model", "hierarchies.yaml")
        # Read existing hierarchies to avoid overwriting user-defined ones
        existing_hier: dict[str, Any] = {}
        if os.path.isfile(hier_yaml_path):
            with open(hier_yaml_path, encoding="utf-8") as f:
                existing_data = yaml.safe_load(f) or {}
            existing_hier = existing_data.get("hierarchies", {})

        # Common mapping from auto-date level names (German/English) to
        # typical Date table column names.  Falls back to level name itself.
        _AUTO_DATE_LEVEL_MAP: dict[str, list[str]] = {
            # German
            "Jahr": ["Year"],
            "Quartal": ["Quarter", "YearQuarter"],
            "Monat": ["MonthNameLong", "MonthNameShort", "Monthnumber"],
            "Tag": ["Date", "Day"],
            # English
            "Year": ["Year"],
            "Quarter": ["Quarter", "YearQuarter"],
            "Month": ["MonthNameLong", "MonthNameShort", "Monthnumber"],
            "Day": ["Date", "Day"],
        }

        for h_name, h_info in discovered_hierarchies.items():
            # Overwrite if the discovered version has more levels (fixes
            # earlier partial extractions).  Skip only if the existing
            # hierarchy already has >= the number of levels we discovered
            # (likely user-curated).
            if h_name in existing_hier:
                existing_levels = existing_hier[h_name].get("levels", [])
                if len(existing_levels) >= len(h_info["levels"]):
                    continue
            src_table = h_info["table"]
            levels = h_info["levels"]

            # Try to map levels to real columns on the source table
            table_yaml_path = os.path.join(
                output_project_dir, "model", "tables", f"{src_table}.yaml")
            table_columns: set[str] = set()
            if os.path.isfile(table_yaml_path):
                with open(table_yaml_path, encoding="utf-8") as f:
                    tdata = yaml.safe_load(f) or {}
                for col_def in (tdata.get("columns") or []):
                    if isinstance(col_def, dict):
                        table_columns.add(col_def.get("name", ""))
                    elif isinstance(col_def, str):
                        table_columns.add(col_def)

            mapped_levels = []
            for lvl in levels:
                # Try auto-date mapping first, then exact match
                mapped_col = lvl  # fallback
                candidates = _AUTO_DATE_LEVEL_MAP.get(lvl, [])
                for cand in candidates:
                    if cand in table_columns:
                        mapped_col = cand
                        break
                else:
                    # If no auto-date candidate matched, check if the level
                    # name itself is a column
                    if lvl in table_columns:
                        mapped_col = lvl
                mapped_levels.append({"name": lvl, "column": mapped_col})

            existing_hier[h_name] = {
                "table": src_table,
                "levels": mapped_levels,
            }

        hier_out_data = {"hierarchies": existing_hier}
        os.makedirs(os.path.dirname(hier_yaml_path), exist_ok=True)
        with open(hier_yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(hier_out_data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)

    # --- Bookmarks ---
    bookmarks_dir = os.path.join(report_dir, "definition", "bookmarks")
    if os.path.isdir(bookmarks_dir):
        # Read bookmark index if present
        bk_index_path = os.path.join(bookmarks_dir, "bookmarks.json")
        bk_index = _read_json(bk_index_path)
        bk_order = [item.get("name", "") for item in bk_index.get("items", [])]

        # Discover bookmark files — supports two layouts:
        # 1. Flat: <id>.bookmark.json  (PBIR default)
        # 2. Subdirectory: <id>/bookmark.json
        bk_files: dict[str, str] = {}  # id → file path
        for entry in os.listdir(bookmarks_dir):
            full = os.path.join(bookmarks_dir, entry)
            if entry.endswith(".bookmark.json"):
                bk_id = entry.replace(".bookmark.json", "")
                bk_files[bk_id] = full
            elif os.path.isdir(full):
                sub = os.path.join(full, "bookmark.json")
                if os.path.isfile(sub):
                    bk_files[entry] = sub

        # Order: use index if available, else alpha
        if not bk_order:
            bk_order = sorted(bk_files.keys())

        bookmarks_data: dict[str, Any] = {"bookmarks": []}
        for bk_id in bk_order:
            bk_path = bk_files.get(bk_id)
            if not bk_path:
                continue
            bk = _read_json(bk_path)
            exploration = bk.get("explorationState", {})
            options = bk.get("options", {})

            bookmark_entry: dict[str, Any] = {
                "id": bk.get("name", bk_id),
                "name": bk.get("displayName", bk_id),
                "current_page_id": page_id_map.get(
                    exploration.get("activeSection", ""), ""
                ),
            }

            # Options
            if options.get("applyOnlyToTargetVisuals"):
                bookmark_entry["apply_only_to_targets"] = True
                targets = options.get("targetVisualNames", [])
                if targets:
                    bookmark_entry["target_visuals"] = [
                        f"pbi_{t[:12]}" for t in targets
                    ]
            if options.get("suppressActiveSection"):
                bookmark_entry["suppress_page"] = True
            if options.get("suppressDisplay"):
                bookmark_entry["suppress_display"] = True

            # Filters
            bk_filters = []
            filters_by_expr = exploration.get("filters", {})
            if isinstance(filters_by_expr, dict):
                for bf in filters_by_expr.get("byExpr", []):
                    field_ref = _extract_field_ref(bf.get("expression", {}))
                    if field_ref:
                        bk_filters.append({
                            "column": field_ref,
                            "scope": "bookmark",
                        })
            bookmark_entry["filters"] = bk_filters

            # Per-visual states (slicer selections, visual visibility)
            visual_states: dict[str, Any] = {}
            for sec_id, sec_data in exploration.get("sections", {}).items():
                for vc_id, vc_data in sec_data.get("visualContainers", {}).items():
                    pvi = f"pbi_{vc_id[:12]}"
                    state: dict[str, Any] = {}
                    # Slicer / visual object overrides
                    sv = vc_data.get("singleVisual", {})
                    if sv:
                        state["visual_type"] = sv.get("visualType", "")
                    # Per-visual filters
                    vc_filters = vc_data.get("filters", {})
                    if isinstance(vc_filters, dict):
                        for vf in vc_filters.get("byExpr", []):
                            fr = _extract_field_ref(vf.get("expression", {}))
                            if fr:
                                state.setdefault("filters", []).append({
                                    "column": fr, "scope": "bookmark_visual"
                                })
                    if state:
                        visual_states[pvi] = state
            if visual_states:
                bookmark_entry["visual_states"] = visual_states

            bookmarks_data["bookmarks"].append(bookmark_entry)
            result.bookmarks_transferred += 1

        if bookmarks_data["bookmarks"]:
            bk_path = os.path.join(reports_out, "bookmarks.yaml")
            with open(bk_path, "w", encoding="utf-8") as f:
                yaml.dump(bookmarks_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return result


def _extract_color_value(color_obj: dict) -> Optional[str]:
    """Extract a hex color value from a PBI color property."""
    if not isinstance(color_obj, dict):
        return None
    solid = color_obj.get("solid", {}).get("color", {})
    if isinstance(solid, str):
        return solid
    if isinstance(solid, dict):
        expr = solid.get("expr", {})
        lit = expr.get("Literal", {})
        val = lit.get("Value", "")
        if "#" in str(val):
            return val.strip("'")
        theme = expr.get("ThemeDataColor", {})
        if theme:
            return f"theme:{theme.get('ColorId', 0)}@{theme.get('Percent', 0)}"
    return None


def _resolve_theme_color(color_str: str, theme_data_colors: list[str]) -> str:
    """Resolve a ``theme:X@Y`` color token to a hex color.

    ``theme:2@0.6`` means: take ``theme_data_colors[2]``, then tint/shade
    by the percent (positive = lighten towards white, negative = darken
    towards black).  If the string is already a hex color, return as-is.
    """
    if not color_str or not color_str.startswith("theme:"):
        return color_str
    import re as _re
    m = _re.match(r'^theme:(\d+)@(-?[\d.]+)$', color_str)
    if not m:
        return color_str
    color_id = int(m.group(1))
    percent = float(m.group(2))
    if color_id >= len(theme_data_colors) or color_id < 0:
        return color_str  # out of range, return as-is
    base_hex = theme_data_colors[color_id]
    if not base_hex.startswith("#") or len(base_hex) < 7:
        return base_hex
    # Parse hex to RGB
    r = int(base_hex[1:3], 16)
    g = int(base_hex[3:5], 16)
    b = int(base_hex[5:7], 16)
    # Apply tint/shade: positive percent = lighten, negative = darken
    if percent > 0:
        # Lighten: blend with white (255,255,255)
        r = int(r + (255 - r) * percent)
        g = int(g + (255 - g) * percent)
        b = int(b + (255 - b) * percent)
    elif percent < 0:
        # Darken: blend with black (0,0,0)
        factor = 1 + percent  # e.g., -0.25 → 0.75
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def _pbi_literal(prop: dict, default: Any = None) -> Any:
    """Extract a literal value from a PBI property expression.

    Handles the common pattern: ``{"expr": {"Literal": {"Value": "'xxx'"}}}``
    and strips surrounding quotes and type suffixes (e.g. ``"0L"`` → ``0``,
    ``"'line'"`` → ``"line"``).
    """
    if not isinstance(prop, dict):
        return default
    expr = prop.get("expr", prop)  # accept both {expr:{Literal:..}} and {Literal:..}
    lit = expr.get("Literal", {})
    val = lit.get("Value", None)
    if val is None:
        return default
    if isinstance(val, str):
        # Strip surrounding single quotes
        if len(val) >= 2 and val[0] == "'" and val[-1] == "'":
            return val[1:-1]
        # Bool values
        if val == "true":
            return True
        if val == "false":
            return False
        # Numeric with type suffix: "0L", "15M", "0D", "1280D" etc.
        import re as _re
        m = _re.match(r'^(-?\d+(?:\.\d+)?)[LMDI]$', val)
        if m:
            num_str = m.group(1)
            return float(num_str) if '.' in num_str else int(num_str)
    return val


def _extract_color_from_prop(prop: dict) -> Optional[str]:
    """Extract color from a PBI property — handles solid, ThemeDataColor."""
    if not isinstance(prop, dict):
        return None
    # Direct solid color
    color = _extract_color_value(prop)
    if color:
        return color
    # May be nested inside {solid: {color: {expr: ...}}}
    solid = prop.get("solid", {}).get("color", {})
    if solid:
        return _extract_color_value({"solid": {"color": solid}})
    return None


def _build_static_content(
    visual_type: str,
    textbox_content: Optional[list],
    shape_props: Optional[dict],
    vco_props: dict,
    visual_link: Optional[dict],
) -> Optional[dict]:
    """Build a `static_content` dict for the React UI from PBI transfer data.

    Maps the raw extracted fields (textbox_content, shape_properties, VCO props)
    into the StaticContent interface expected by StaticVisualContent.tsx.
    """
    if visual_type == "textbox" and textbox_content:
        # Combine all paragraph text runs into a single text string.
        lines = []
        first_style: dict[str, Any] = {}
        first_alignment: Optional[str] = None
        for para in textbox_content:
            parts = []
            for run in para.get("text_runs", []):
                parts.append(run.get("value", ""))
                if not first_style and run.get("style"):
                    first_style = run["style"]
            lines.append("".join(parts))
            if first_alignment is None and para.get("alignment"):
                first_alignment = para["alignment"]
        sc: dict[str, Any] = {"text": "\n".join(lines)}
        if first_style.get("fontSize"):
            # Convert "16pt" -> px equivalent (1pt = 1.333px, rounded)
            fs = first_style["fontSize"]
            if isinstance(fs, str) and fs.endswith("pt"):
                try:
                    sc["fontSize"] = round(int(fs.replace("pt", "")) * 4 / 3)
                except ValueError:
                    pass
            elif isinstance(fs, (int, float)):
                sc["fontSize"] = round(int(fs) * 4 / 3)
        if first_style.get("fontWeight"):
            sc["fontWeight"] = first_style["fontWeight"]
        if first_style.get("color"):
            sc["color"] = first_style["color"]
        if first_alignment:
            sc["textAlign"] = first_alignment
        sc["backgroundColor"] = "transparent"
        return sc

    if visual_type == "shape":
        sc = {}
        if shape_props:
            sc["shapeType"] = shape_props.get("shape_type", "rectangle")
            if shape_props.get("fill_show") is False:
                sc["fill"] = "transparent"
            elif shape_props.get("fill_color"):
                sc["fill"] = shape_props["fill_color"]
            else:
                # In PBI, shapes default to white fill when no fill is specified
                sc["fill"] = "#FFFFFF"
            if shape_props.get("outline_show") is False:
                sc["stroke"] = "transparent"
                sc["strokeWidth"] = 0
            elif shape_props.get("outline_color"):
                sc["stroke"] = shape_props["outline_color"]
            else:
                sc["stroke"] = "transparent"
                sc["strokeWidth"] = 0
            if shape_props.get("outline_weight") is not None:
                sc["strokeWidth"] = shape_props["outline_weight"]
        else:
            # Default: white fill, no outline (PBI default shape)
            sc["shapeType"] = "rectangle"
            sc["fill"] = "#FFFFFF"
            sc["stroke"] = "transparent"
            sc["strokeWidth"] = 0
        sc["opacity"] = 1.0
        # Attach action from visual link
        if visual_link:
            sc["action"] = {
                "type": visual_link.get("type", "none"),
                "target": visual_link.get("target", ""),
            }
        return sc

    if visual_type == "button":
        sc = {"label": "", "buttonType": "blank"}
        if visual_link:
            sc["action"] = {
                "type": visual_link.get("type", "none"),
                "target": visual_link.get("target", ""),
            }
        return sc

    return None


def _extract_textbox_content(vis: dict) -> Optional[list]:
    """Extract rich text paragraphs from a textbox visual.

    Returns a list of paragraph dicts:
    [{"text_runs": [{"value": "...", "style": {...}}], "alignment": "center"}]
    """
    objects = vis.get("objects", {})
    general = objects.get("general", [])
    if not general:
        return None
    paragraphs_raw = general[0].get("properties", {}).get("paragraphs", [])
    if not paragraphs_raw:
        return None

    paragraphs = []
    for p in paragraphs_raw:
        text_runs = []
        for run in p.get("textRuns", []):
            entry: dict[str, Any] = {"value": run.get("value", "")}
            ts = run.get("textStyle", {})
            if ts:
                style: dict[str, Any] = {}
                for k in ("fontSize", "color", "fontWeight", "fontFamily",
                          "fontStyle", "textDecorationLine"):
                    if k in ts:
                        style[k] = ts[k]
                if style:
                    entry["style"] = style
            text_runs.append(entry)
        para: dict[str, Any] = {"text_runs": text_runs}
        align = p.get("horizontalTextAlignment")
        if align:
            para["alignment"] = align
        paragraphs.append(para)
    return paragraphs or None


def _extract_shape_properties(vis: dict) -> Optional[dict]:
    """Extract shape-specific properties (type, fill, outline, rotation)."""
    objects = vis.get("objects", {})
    if not objects:
        return None

    props: dict[str, Any] = {}

    # Shape type: line or rectangle
    for s in objects.get("shape", []):
        tile = _pbi_literal(s.get("properties", {}).get("tileShape", {}))
        if tile:
            props["shape_type"] = tile

    # Fill
    for f in objects.get("fill", []):
        fp = f.get("properties", {})
        show = _pbi_literal(fp.get("show", {}), True)
        if show is False:
            props["fill_show"] = False
        else:
            color = _extract_color_from_prop(fp.get("fillColor", {}))
            if color:
                props["fill_color"] = color

    # Outline
    for o in objects.get("outline", []):
        op = o.get("properties", {})
        show = _pbi_literal(op.get("show", {}), True)
        if show is False:
            props["outline_show"] = False
        else:
            color = _extract_color_from_prop(op.get("lineColor", {}))
            if color:
                props["outline_color"] = color
            weight = _pbi_literal(op.get("weight", {}))
            if weight is not None:
                props["outline_weight"] = weight

    # Rotation
    for r in objects.get("rotation", []):
        angle = _pbi_literal(r.get("properties", {}).get("shapeAngle", {}))
        if angle is not None and angle != 0:
            props["rotation"] = angle

    return props or None


def _extract_vco_properties(vco: dict) -> dict:
    """Extract visualContainerObjects properties: show/hide, border, shadow, etc.

    Returns a flat dict of properties to merge into format_opts.
    """
    result: dict[str, Any] = {}

    # Title show/hide  (UI reads format.showTitle)
    for t in vco.get("title", []):
        props = t.get("properties", {})
        show = _pbi_literal(props.get("show", {}))
        if show is not None:
            result["showTitle"] = bool(show)
        # Title text formatting
        title_font_size = _pbi_literal(props.get("fontSize", {}))
        if title_font_size is not None:
            result["titleFontSize"] = title_font_size
        title_font_color = _extract_color_from_prop(props.get("fontColor", {}))
        if title_font_color:
            result["titleFontColor"] = title_font_color
        title_alignment = _pbi_literal(props.get("alignment", {}))
        if title_alignment:
            result["titleAlignment"] = title_alignment
        title_font_family = _pbi_literal(props.get("fontFamily", {}))
        if title_font_family:
            result["titleFontFamily"] = title_font_family
        title_bold = _pbi_literal(props.get("bold", {}))
        if title_bold is not None:
            result["titleBold"] = bool(title_bold)
        title_italic = _pbi_literal(props.get("italic", {}))
        if title_italic is not None:
            result["titleItalic"] = bool(title_italic)
        title_underline = _pbi_literal(props.get("underline", {}))
        if title_underline is not None:
            result["titleUnderline"] = bool(title_underline)
        title_bg = _extract_color_from_prop(props.get("background", {}))
        if title_bg:
            result["titleBackground"] = title_bg
        title_heading = _pbi_literal(props.get("heading", {}))
        if title_heading is not None:
            result["titleHeading"] = title_heading
        title_wrap = _pbi_literal(props.get("titleWrap", {}))
        if title_wrap is not None:
            result["titleWrap"] = bool(title_wrap)

    # Background show/hide + transparency
    for bg in vco.get("background", []):
        bgp = bg.get("properties", {})
        show = _pbi_literal(bgp.get("show", {}))
        if show is False:
            result["background_show"] = False
        bg_transparency = _pbi_literal(bgp.get("transparency", {}))
        if bg_transparency is not None:
            result["backgroundTransparency"] = bg_transparency

    # Subtitle show/hide + formatting  (UI reads format.showSubtitle)
    for st in vco.get("subTitle", []):
        stp = st.get("properties", {})
        show = _pbi_literal(stp.get("show", {}))
        if show is False:
            result["showSubtitle"] = False
        elif show is True:
            result["showSubtitle"] = True
        sub_font_size = _pbi_literal(stp.get("fontSize", {}))
        if sub_font_size is not None:
            result["subtitleFontSize"] = sub_font_size
        sub_font_color = _extract_color_from_prop(stp.get("fontColor", {}))
        if sub_font_color:
            result["subtitleFontColor"] = sub_font_color
        sub_font_family = _pbi_literal(stp.get("fontFamily", {}))
        if sub_font_family:
            result["subtitleFontFamily"] = sub_font_family
        sub_alignment = _pbi_literal(stp.get("alignment", {}))
        if sub_alignment:
            result["subtitleAlignment"] = sub_alignment
        sub_bold = _pbi_literal(stp.get("bold", {}))
        if sub_bold is not None:
            result["subtitleBold"] = bool(sub_bold)
        sub_italic = _pbi_literal(stp.get("italic", {}))
        if sub_italic is not None:
            result["subtitleItalic"] = bool(sub_italic)
        sub_underline = _pbi_literal(stp.get("underline", {}))
        if sub_underline is not None:
            result["subtitleUnderline"] = bool(sub_underline)

    # Visual header show/hide  (UI reads format.showVisualHeader)
    for vh in vco.get("visualHeader", []):
        show = _pbi_literal(vh.get("properties", {}).get("show", {}))
        if show is False:
            result["showVisualHeader"] = False

    # Border (extended: radius, width, color)
    for bd in vco.get("border", []):
        bp = bd.get("properties", {})
        show = _pbi_literal(bp.get("show", {}), True)
        if show is False:
            result["border_show"] = False
        else:
            radius = _pbi_literal(bp.get("radius", {}))
            if radius is not None:
                result["border_radius"] = radius
            width = _pbi_literal(bp.get("width", {}))
            if width is not None:
                result["border_width"] = width
            color = _extract_color_from_prop(bp.get("color", {}))
            if color:
                result["borderColor"] = color

    # Drop shadow
    for ds in vco.get("dropShadow", []):
        dp = ds.get("properties", {})
        show = _pbi_literal(dp.get("show", {}))
        if show:
            shadow: dict[str, Any] = {"show": True}
            for k in ("preset", "shadowBlur", "shadowDistance", "shadowSpread",
                      "transparency", "shadowColor", "angle", "position"):
                v = _pbi_literal(dp.get(k, {}))
                if v is not None:
                    shadow[k] = v
            # Color might be a color object
            shadow_color = _extract_color_from_prop(dp.get("shadowColor", {}))
            if shadow_color:
                shadow["shadowColor"] = shadow_color
            result["drop_shadow"] = shadow

    # Padding
    for pd in vco.get("padding", []):
        pp = pd.get("properties", {})
        padding: dict[str, Any] = {}
        for side in ("top", "left", "right", "bottom"):
            v = _pbi_literal(pp.get(side, {}))
            if v is not None:
                padding[side] = v
        if padding:
            result["padding"] = padding

    # Style preset
    for sp in vco.get("stylePreset", []):
        name = _pbi_literal(sp.get("properties", {}).get("name", {}))
        if name:
            result["style_preset"] = name

    # Divider
    for dv in vco.get("divider", []):
        dvp = dv.get("properties", {})
        show = _pbi_literal(dvp.get("show", {}))
        if show:
            result["divider_show"] = True
        dv_color = _extract_color_from_prop(dvp.get("color", {}))
        if dv_color:
            result["divider_color"] = dv_color
        dv_width = _pbi_literal(dvp.get("width", {}))
        if dv_width is not None:
            result["divider_width"] = dv_width
        dv_style = _pbi_literal(dvp.get("style", {}))
        if dv_style is not None:
            result["divider_style"] = dv_style
        dv_ignore_padding = _pbi_literal(dvp.get("ignorePadding", {}))
        if dv_ignore_padding is not None:
            result["divider_ignorePadding"] = dv_ignore_padding

    # Spacing
    for sp_entry in vco.get("spacing", []):
        spp = sp_entry.get("properties", {})
        spacing: dict[str, Any] = {}
        for sp_key in ("customizeSpacing", "verticalSpacing",
                       "spaceBelowTitle", "spaceBelowSubTitle",
                       "spaceBelowTitleArea"):
            v = _pbi_literal(spp.get(sp_key, {}))
            if v is not None:
                spacing[sp_key] = v
        if spacing:
            result["spacing"] = spacing

    return result


def _extract_visual_link(vco: dict) -> Optional[dict]:
    """Extract visual link (bookmark/back/page navigation) from VCO."""
    for vl in vco.get("visualLink", []):
        vp = vl.get("properties", {})
        show = _pbi_literal(vp.get("show", {}))
        if not show:
            continue
        link: dict[str, Any] = {}
        link_type = _pbi_literal(vp.get("type", {}))
        if link_type:
            link["type"] = link_type
        bookmark = _pbi_literal(vp.get("bookmark", {}))
        if bookmark:
            link["bookmark"] = bookmark
        page = _pbi_literal(vp.get("page", {}))
        if page:
            link["page"] = page
        url = _pbi_literal(vp.get("url", {}))
        if url:
            link["url"] = url
        return link
    return None


def _extract_chart_objects(vis: dict) -> Optional[dict]:
    """Extract chart-level object settings: legend, labels, axes, layout, general."""
    objects = vis.get("objects", {})
    if not objects:
        return None

    result: dict[str, Any] = {}

    # Legend
    for lg in objects.get("legend", []):
        lp = lg.get("properties", {})
        legend: dict[str, Any] = {}
        show = _pbi_literal(lp.get("show", {}))
        if show is not None:
            legend["show"] = show
        position = _pbi_literal(lp.get("position", {}))
        if position:
            legend["position"] = position
        show_gradient = _pbi_literal(lp.get("showGradientLegend", {}))
        if show_gradient is not None:
            legend["show_gradient"] = show_gradient
        # Extended legend styling
        lg_font_size = _pbi_literal(lp.get("fontSize", {}))
        if lg_font_size is not None:
            legend["fontSize"] = lg_font_size
        lg_font_family = _pbi_literal(lp.get("fontFamily", {}))
        if lg_font_family:
            legend["fontFamily"] = lg_font_family
        lg_font_color = _extract_color_from_prop(lp.get("fontColor", {}))
        if lg_font_color:
            legend["fontColor"] = lg_font_color
        lg_title_text = _pbi_literal(lp.get("titleText", {}))
        if lg_title_text:
            legend["titleText"] = lg_title_text
        lg_show_title = _pbi_literal(lp.get("showTitle", {}))
        if lg_show_title is not None:
            legend["showTitle"] = lg_show_title
        if legend:
            result["legend"] = legend

    # Labels
    for lb in objects.get("labels", []):
        lp = lb.get("properties", {})
        labels: dict[str, Any] = {}
        show = _pbi_literal(lp.get("show", {}))
        if show is not None:
            labels["show"] = show
        position = _pbi_literal(lp.get("labelPosition", {}))
        if position:
            labels["position"] = position
        color = _extract_color_from_prop(lp.get("color", {}))
        if color:
            labels["color"] = color
        font_size = _pbi_literal(lp.get("fontSize", {}))
        if font_size is not None:
            labels["fontSize"] = font_size
        # Additional PBI label properties
        font_family = _pbi_literal(lp.get("fontFamily", {}))
        if font_family:
            labels["fontFamily"] = font_family
        display_units = _pbi_literal(lp.get("labelDisplayUnits", {}))
        if display_units is not None:
            labels["displayUnits"] = display_units
        precision = _pbi_literal(lp.get("labelPrecision", {}))
        if precision is not None:
            labels["precision"] = precision
        transparency = _pbi_literal(lp.get("transparency", {}))
        if transparency is not None:
            labels["transparency"] = transparency
        if labels:
            result["labels"] = labels

    # Category labels (card subtitle / category display)
    for cl in objects.get("categoryLabels", []):
        clp = cl.get("properties", {})
        cat_labels: dict[str, Any] = {}
        show = _pbi_literal(clp.get("show", {}))
        if show is not None:
            cat_labels["show"] = show
        font_size = _pbi_literal(clp.get("fontSize", {}))
        if font_size is not None:
            cat_labels["fontSize"] = font_size
        color = _extract_color_from_prop(clp.get("color", {}))
        if color:
            cat_labels["color"] = color
        if cat_labels:
            result["category_labels"] = cat_labels

    # Category axis
    for ca in objects.get("categoryAxis", []):
        cp = ca.get("properties", {})
        axis: dict[str, Any] = {}
        show = _pbi_literal(cp.get("show", {}))
        if show is not None:
            axis["show"] = show
        show_title = _pbi_literal(cp.get("showAxisTitle", {}))
        if show_title is not None:
            axis["show_title"] = show_title
        axis_type = _pbi_literal(cp.get("axisType", {}))
        if axis_type is not None:
            axis["axis_type"] = axis_type
        inner_padding = _pbi_literal(cp.get("innerPadding", {}))
        if inner_padding is not None:
            axis["inner_padding"] = inner_padding
        # Font styling on category axis
        ca_font_size = _pbi_literal(cp.get("fontSize", {}))
        if ca_font_size is not None:
            axis["fontSize"] = ca_font_size
        ca_font_family = _pbi_literal(cp.get("fontFamily", {}))
        if ca_font_family:
            axis["fontFamily"] = ca_font_family
        ca_font_color = _extract_color_from_prop(cp.get("fontColor", {}))
        if ca_font_color:
            axis["fontColor"] = ca_font_color
        ca_title_text = _pbi_literal(cp.get("titleText", {}))
        if ca_title_text:
            axis["title_text"] = ca_title_text
        ca_label_angle = _pbi_literal(cp.get("labelAngle", {}))
        if ca_label_angle is not None:
            axis["label_angle"] = ca_label_angle
        if axis:
            result["category_axis"] = axis

    # Value axis
    for va in objects.get("valueAxis", []):
        vp = va.get("properties", {})
        axis: dict[str, Any] = {}
        show = _pbi_literal(vp.get("show", {}))
        if show is not None:
            axis["show"] = show
        show_title = _pbi_literal(vp.get("showAxisTitle", {}))
        if show_title is not None:
            axis["show_title"] = show_title
        # Font styling on value axis
        va_font_size = _pbi_literal(vp.get("fontSize", {}))
        if va_font_size is not None:
            axis["fontSize"] = va_font_size
        va_font_family = _pbi_literal(vp.get("fontFamily", {}))
        if va_font_family:
            axis["fontFamily"] = va_font_family
        va_font_color = _extract_color_from_prop(vp.get("fontColor", {}))
        if va_font_color:
            axis["fontColor"] = va_font_color
        va_title_text = _pbi_literal(vp.get("titleText", {}))
        if va_title_text:
            axis["title_text"] = va_title_text
        # Min/Max (start/end)
        va_start = _pbi_literal(vp.get("start", {}))
        if va_start is not None:
            axis["start"] = va_start
        va_end = _pbi_literal(vp.get("end", {}))
        if va_end is not None:
            axis["end"] = va_end
        # Display units and precision
        va_display_units = _pbi_literal(vp.get("labelDisplayUnits", {}))
        if va_display_units is not None:
            axis["displayUnits"] = va_display_units
        va_precision = _pbi_literal(vp.get("labelPrecision", {}))
        if va_precision is not None:
            axis["precision"] = va_precision
        # Gridlines
        va_gridlines = _pbi_literal(vp.get("gridlines", {}))
        if va_gridlines is not None:
            axis["gridlines"] = va_gridlines
        va_gridline_color = _extract_color_from_prop(vp.get("gridlineColor", {}))
        if va_gridline_color:
            axis["gridlineColor"] = va_gridline_color
        if axis:
            result["value_axis"] = axis

    # General (layout mode: Compact/Tabular for matrix)
    for g in objects.get("general", []):
        gp = g.get("properties", {})
        layout = _pbi_literal(gp.get("layout", {}))
        if layout:
            result["general_layout"] = layout

    # Row headers (matrix stepped layout)
    for rh in objects.get("rowHeaders", []):
        rp = rh.get("properties", {})
        row_h: dict[str, Any] = {}
        indent = _pbi_literal(rp.get("steppedLayoutIndentation", {}))
        if indent is not None:
            row_h["stepped_indentation"] = indent
        outline = _pbi_literal(rp.get("outlineStyle", {}))
        if outline:
            row_h["outline_style"] = outline
        if row_h:
            result["row_headers"] = row_h

    # Grid (matrix)
    for gr in objects.get("grid", []):
        gp = gr.get("properties", {})
        grid: dict[str, Any] = {}
        horiz = _pbi_literal(gp.get("gridHorizontal", {}))
        if horiz is not None:
            grid["horizontal"] = horiz
        vert = _pbi_literal(gp.get("gridVertical", {}))
        if vert is not None:
            grid["vertical"] = vert
        if grid:
            result["grid"] = grid

    # Column headers (matrix)
    for ch in objects.get("columnHeaders", []):
        cp = ch.get("properties", {})
        col_h: dict[str, Any] = {}
        bg = _extract_color_from_prop(cp.get("backColor", {}))
        if bg:
            col_h["back_color"] = bg
        wrap = _pbi_literal(cp.get("wordWrap", {}))
        if wrap is not None:
            col_h["word_wrap"] = wrap
        outline = _pbi_literal(cp.get("outlineStyle", {}))
        if outline is not None:
            col_h["outline_style"] = outline
        auto_size = _pbi_literal(cp.get("autoSizeColumnWidth", {}))
        if auto_size is not None:
            col_h["auto_size_column_width"] = auto_size
        if col_h:
            result["column_headers"] = col_h

    # Layout (chart gap/overlap)
    for lo in objects.get("layout", []):
        lp = lo.get("properties", {})
        layout: dict[str, Any] = {}
        for k in ("clusteredGapSize", "clusteredGapOverlaps",
                  "clusteredGapOverlapReverse",
                  "seriesOrderReversed", "seriesOrderSorted"):
            v = _pbi_literal(lp.get(k, {}))
            if v is not None:
                layout[k] = v
        if layout:
            result["chart_layout"] = layout

    # Card (multiRowCard accent bar)
    for cd in objects.get("card", []):
        cdp = cd.get("properties", {})
        card_props: dict[str, Any] = {}
        bar_color = _extract_color_from_prop(cdp.get("barColor", {}))
        if bar_color:
            card_props["barColor"] = bar_color
        bar_weight = _pbi_literal(cdp.get("barWeight", {}))
        if bar_weight is not None:
            card_props["barWeight"] = bar_weight
        if card_props:
            result["card"] = card_props

    # Data labels (multiRowCard value labels)
    for dl in objects.get("dataLabels", []):
        dlp = dl.get("properties", {})
        data_labels: dict[str, Any] = {}
        font_family = _pbi_literal(dlp.get("fontFamily", {}))
        if font_family:
            data_labels["fontFamily"] = font_family
        font_size = _pbi_literal(dlp.get("fontSize", {}))
        if font_size is not None:
            data_labels["fontSize"] = font_size
        if data_labels:
            result["data_labels"] = data_labels

    # Data point border visibility
    for dp in objects.get("dataPoint", []):
        dpp = dp.get("properties", {})
        border_show = _pbi_literal(dpp.get("borderShow", {}))
        if border_show is not None:
            result.setdefault("data_point", {})["border_show"] = border_show
            break  # global flag — first match is sufficient

    # Reference lines (y1 / y2 axis)
    for axis_key, axis_tag in [("y1AxisReferenceLine", "Y1"),
                               ("y2AxisReferenceLine", "Y2")]:
        lines = objects.get(axis_key, [])
        if not lines:
            continue
        ref_list: list[dict[str, Any]] = []
        for rl in lines:
            props = rl.get("properties", {})
            entry: dict[str, Any] = {"axis": axis_tag}
            show = _pbi_literal(props.get("show", {}))
            if show is not None:
                entry["show"] = show
            display_name = _pbi_literal(props.get("displayName", {}))
            if display_name is not None:
                entry["displayName"] = display_name
            # Value can be a literal or a measure/column reference
            val_prop = props.get("value", {})
            val_literal = _pbi_literal(val_prop)
            if val_literal is not None:
                entry["value"] = val_literal
            else:
                # Try measure/column expression
                val_expr = val_prop.get("expr", {}) if isinstance(val_prop, dict) else {}
                val_ref = _extract_field_ref(val_expr) if val_expr else None
                if val_ref:
                    entry["value_ref"] = val_ref
            selector = rl.get("selector", {})
            sel_id = selector.get("id")
            if sel_id is not None:
                entry["selector_id"] = sel_id
            if entry:
                ref_list.append(entry)
        if ref_list:
            result.setdefault("reference_lines", []).extend(ref_list)

    # --- Matrix/Table: columnFormatting (data bars, font color per column) ---
    col_fmt_entries = objects.get("columnFormatting", [])
    if col_fmt_entries:
        col_formatting: list[dict[str, Any]] = []
        for cf in col_fmt_entries:
            cfp = cf.get("properties", {})
            entry: dict[str, Any] = {}
            # Target column via selector.metadata
            sel = cf.get("selector", {})
            metadata = sel.get("metadata")
            if metadata:
                entry["column"] = metadata
            # Font color
            fc = _extract_color_from_prop(cfp.get("fontColor", {}))
            if fc:
                entry["fontColor"] = fc
            # Data bars
            db_prop = cfp.get("dataBars", {})
            if db_prop and isinstance(db_prop, dict):
                data_bar: dict[str, Any] = {}
                for db_key in ("positiveColor", "negativeColor", "axisColor"):
                    c = _extract_color_from_prop(db_prop.get(db_key, {}))
                    if c:
                        data_bar[db_key] = c
                for db_key in ("reverseDirection", "hideText"):
                    v = _pbi_literal(db_prop.get(db_key, {}))
                    if v is not None:
                        data_bar[db_key] = v
                total_opt = _pbi_literal(db_prop.get("totalMatchingOption", {}))
                if total_opt is not None:
                    data_bar["totalMatchingOption"] = total_opt
                if data_bar:
                    entry["dataBars"] = data_bar
            if entry:
                col_formatting.append(entry)
        if col_formatting:
            result["column_formatting"] = col_formatting

    # --- Matrix/Table: columnWidth (per-column widths) ---
    col_width_entries = objects.get("columnWidth", [])
    if col_width_entries:
        col_widths: dict[str, float] = {}
        for cw in col_width_entries:
            cwp = cw.get("properties", {})
            val = _pbi_literal(cwp.get("value", {}))
            sel = cw.get("selector", {})
            metadata = sel.get("metadata")
            if metadata and val is not None:
                col_widths[metadata] = val
        if col_widths:
            result["column_widths"] = col_widths

    # --- Matrix/Table: values (conditional formatting — backColor, fontColor) ---
    val_entries = objects.get("values", [])
    if val_entries:
        cond_rules: list[dict[str, Any]] = []
        for ve in val_entries:
            vep = ve.get("properties", {})
            sel = ve.get("selector", {})
            metadata = sel.get("metadata")
            rule: dict[str, Any] = {}
            if metadata:
                rule["column"] = metadata
            # Back color — may be simple or conditional (Cases / FillRule)
            bg_prop = vep.get("backColor", {})
            bg_color = _extract_color_from_prop(bg_prop)
            if bg_color:
                rule["backColor"] = bg_color
            else:
                # Check for conditional formatting expression
                solid = bg_prop.get("solid", {}).get("color", {}).get("expr", {}) if isinstance(bg_prop, dict) else {}
                cond = solid.get("Conditional", {})
                fill_rule = solid.get("FillRule", {})
                if cond.get("Cases"):
                    cases = []
                    for c in cond["Cases"]:
                        case_val = c.get("Value", {}).get("Literal", {}).get("Value", "")
                        if case_val:
                            cases.append(case_val.strip("'"))
                    if cases:
                        rule["backColor_conditional"] = {"type": "cases", "colors": cases}
                elif fill_rule.get("FillRule"):
                    fr = fill_rule["FillRule"]
                    grad_type = "linearGradient2" if "linearGradient2" in fr else "linearGradient3" if "linearGradient3" in fr else None
                    if grad_type:
                        grad = fr[grad_type]
                        gradient: dict[str, Any] = {"type": grad_type}
                        for gk in ("min", "mid", "max"):
                            gv = grad.get(gk, {}).get("color", {}).get("Literal", {}).get("Value", "")
                            if gv:
                                gradient[gk] = gv.strip("'")
                        rule["backColor_conditional"] = gradient
            # Font color — similarly handle conditional
            fc_prop = vep.get("fontColor", {})
            fc_color = _extract_color_from_prop(fc_prop)
            if fc_color:
                rule["fontColor"] = fc_color
            else:
                solid_fc = fc_prop.get("solid", {}).get("color", {}).get("expr", {}) if isinstance(fc_prop, dict) else {}
                fill_rule_fc = solid_fc.get("FillRule", {})
                if fill_rule_fc.get("FillRule"):
                    fr_fc = fill_rule_fc["FillRule"]
                    grad_type_fc = "linearGradient2" if "linearGradient2" in fr_fc else "linearGradient3" if "linearGradient3" in fr_fc else None
                    if grad_type_fc:
                        grad_fc = fr_fc[grad_type_fc]
                        gradient_fc: dict[str, Any] = {"type": grad_type_fc}
                        for gk in ("min", "mid", "max"):
                            gv = grad_fc.get(gk, {}).get("color", {}).get("Literal", {}).get("Value", "")
                            if gv:
                                gradient_fc[gk] = gv.strip("'")
                        rule["fontColor_conditional"] = gradient_fc
            if rule:
                cond_rules.append(rule)
        if cond_rules:
            result["values_formatting"] = cond_rules

    # --- Matrix: subTotals configuration ---
    for st in objects.get("subTotals", []):
        stp = st.get("properties", {})
        sub_totals: dict[str, Any] = {}
        for sk in ("rowSubtotals", "columnSubtotals",
                   "rowSubtotalsPosition", "columnSubtotalsPosition",
                   "perRowLevel", "perColumnLevel"):
            v = _pbi_literal(stp.get(sk, {}))
            if v is not None:
                sub_totals[sk] = v
        if sub_totals:
            result["sub_totals"] = sub_totals

    # --- Matrix: total (grand total formatting) ---
    for tt in objects.get("total", []):
        ttp = tt.get("properties", {})
        total_fmt: dict[str, Any] = {}
        tt_bg = _extract_color_from_prop(ttp.get("backColor", {}))
        if tt_bg:
            total_fmt["backColor"] = tt_bg
        tt_fc = _extract_color_from_prop(ttp.get("fontColor", {}))
        if tt_fc:
            total_fmt["fontColor"] = tt_fc
        tt_bold = _pbi_literal(ttp.get("bold", {}))
        if tt_bold is not None:
            total_fmt["bold"] = tt_bold
        tt_fs = _pbi_literal(ttp.get("fontSize", {}))
        if tt_fs is not None:
            total_fmt["fontSize"] = tt_fs
        if total_fmt:
            result["total"] = total_fmt

    # --- Chart: plotArea transparency ---
    for pa in objects.get("plotArea", []):
        pap = pa.get("properties", {})
        pa_transparency = _pbi_literal(pap.get("transparency", {}))
        if pa_transparency is not None:
            result["plotArea_transparency"] = pa_transparency

    return result or None


def _generate_native_slicers(slicer_visuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert PBI slicer visuals (transferred as visual JSONs) into native
    unified slicer entries for slicers.yaml.

    Maps PBI slicer config to the native slicer format:
    - mode='Dropdown' → type='dropdown'
    - mode='Between'  → type='date_range'
    - mode='Basic'/'List'/None → type='list'
    - Advanced slicer (tile cards) → type='list'
    """
    # ── Phase 1: detect sync groups with heterogeneous columns ──
    # PBI sync groups share filter values across slicers. When a group has
    # fieldChanges=true, members can be bound to different columns. PBI writes
    # the shared filter value into every member's general.filter, even if the
    # value doesn't belong to that member's column (e.g. Year=2020 written
    # into a Monthnumber slicer). We detect this and clear invalid defaults.
    from collections import Counter
    sync_group_cols: dict[str, list[tuple[str, str]]] = {}  # group_name → [(column, vis_id)]
    for vj in slicer_visuals:
        sc = vj.get("slicer_config") or {}
        sg = sc.get("_sync_group") or {}
        sg_name = sg.get("groupName", "")
        if sg_name and sg.get("fieldChanges", False):
            enc = vj.get("encodings") or {}
            col_ref = enc.get("columns") or enc.get("category") or {}
            col = col_ref.get("column", "")
            vis_id = vj.get("id", "")
            sync_group_cols.setdefault(sg_name, []).append((col, vis_id))

    # For each group with mixed columns, clear ALL members' defaults.
    # When fieldChanges=true, PBI syncs raw filter values across members even
    # when they refer to different columns. E.g. Monthnumber='12' gets written
    # into a Year slicer as Year='12', which is invalid. Clearing all members
    # is safe because the persisted value comes from PBI's sync mechanism, not
    # from a deliberate user choice for each individual slicer.
    _clear_defaults_for: set[str] = set()  # vis_ids whose defaults should be cleared
    for sg_name, members in sync_group_cols.items():
        cols = [m[0] for m in members]
        if len(set(cols)) > 1:
            # Heterogeneous columns — clear ALL members' defaults
            for _col, vid in members:
                _clear_defaults_for.add(vid)

    slicers: list[dict[str, Any]] = []
    for vj in slicer_visuals:
        vis_id = vj.get("id", "")
        if not vis_id:
            continue

        # Extract column reference from encodings
        enc = vj.get("encodings") or {}
        col_ref = enc.get("columns") or enc.get("category") or {}
        if isinstance(col_ref, list):
            col_ref = col_ref[0] if col_ref else {}
        table = col_ref.get("table", "")
        column = col_ref.get("column", "")
        if not table or not column:
            continue

        sc = vj.get("slicer_config") or {}
        pbi_mode = str(sc.get("mode") or "").strip()
        single_select = sc.get("single_select", False)
        is_advanced = sc.get("is_advanced", False)
        is_hidden = bool(vj.get("hidden"))

        # Map PBI mode to native type
        if pbi_mode.lower() == "dropdown":
            slicer_type = "dropdown"
        elif pbi_mode.lower() == "between":
            slicer_type = "date_range"
        else:
            slicer_type = "list"

        # Layout from visual
        layout = vj.get("layout") or {}
        page_id = vj.get("page_id", "")

        # Build the unified slicer entry
        # --- Slicer title: prefer explicit title, then column name ---
        raw_title = vj.get("title", "")
        # Generic fallbacks from transfer (e.g. "slicer visual") are useless
        _GENERIC_TITLES = {"slicer visual", "advancedslicervisual visual", ""}
        if raw_title.strip().lower() in _GENERIC_TITLES:
            # Use readable column reference as title
            raw_title = f"{table}.{column}"

        # --- Default values from slicer_config ---
        default_vals_raw: list[str] = sc.get("default_values") or []
        # Clear sync-group artifact defaults (e.g. Year=2020 on Monthnumber slicer)
        if vis_id in _clear_defaults_for:
            default_vals_raw = []
        default_vals: list[Any] = []
        for dv in default_vals_raw:
            # PBI integer literals have 'L' suffix (e.g. "2020L" → 2020)
            if isinstance(dv, str) and dv.endswith("L") and dv[:-1].lstrip("-").isdigit():
                default_vals.append(int(dv[:-1]))
            else:
                default_vals.append(dv)

        slicer_entry: dict[str, Any] = {
            "id": f"sd_pbi_{vis_id}",
            "name": f"{table}[{column}]",
            "title": raw_title,
            "column": {
                "type": "ColumnRef",
                "table": table,
                "column": column,
            },
            "type": slicer_type,
            "behavior": {
                "apply_to": "all_visuals",
                "auto_apply": True,
            },
            "selection": {
                "mode": "values" if default_vals else "all",
                "values": default_vals,
            },
            "ui": {
                "multi": not single_select,
                "search": slicer_type == "dropdown",
            },
        }

        # Selection defaults for date_range
        if slicer_type == "date_range":
            slicer_entry["selection"] = {
                "mode": "all",
                "start": None,
                "end": None,
            }

        # Page placement
        if page_id:
            slicer_entry["pages"] = {
                page_id: {
                    "visible": not is_hidden,
                    "sync": True,
                    "layout": {
                        "x": layout.get("x", 0),
                        "y": layout.get("y", 0),
                        "w": layout.get("w", 240),
                        "h": layout.get("h", 260),
                    },
                },
            }

        # Preserve PBI source reference
        slicer_entry["_pbi_source_visual"] = vis_id

        # Advanced slicer styling
        if is_advanced:
            slicer_entry["ui"]["style"] = sc.get("style", "Cards")

        slicers.append(slicer_entry)

    return slicers


def _extract_slicer_config(vis: dict) -> Optional[dict]:
    """Extract slicer-specific config (mode, selection, advanced slicer layout)."""
    objects = vis.get("objects", {})
    vtype = vis.get("visualType", "")
    if not objects and vtype not in ("slicer", "advancedSlicerVisual"):
        return None

    result: dict[str, Any] = {}

    # Mode: Dropdown / Basic / List
    for d in objects.get("data", []):
        mode = _pbi_literal(d.get("properties", {}).get("mode", {}))
        if mode:
            result["mode"] = mode

    # Selection: single select
    for s in objects.get("selection", []):
        strict = _pbi_literal(s.get("properties", {}).get("strictSingleSelect", {}))
        if strict is not None:
            result["single_select"] = strict

    # Advanced slicer: layout, shape, value, image, overflow, padding, fill
    if vtype == "advancedSlicerVisual":
        result["is_advanced"] = True

        # Layout grid
        for lo in objects.get("layout", []):
            lp = lo.get("properties", {})
            for k in ("rowCount", "columnCount", "style", "orientation",
                       "customizePadding"):
                v = _pbi_literal(lp.get(k, {}))
                if v is not None:
                    result[k] = v

        # Tile shape / corner radius
        for sr in objects.get("shapeCustomRectangle", []):
            sp = sr.get("properties", {})
            tile = _pbi_literal(sp.get("tileShape", {}))
            if tile:
                result["tile_shape"] = tile
            curve = _pbi_literal(sp.get("rectangleRoundedCurve", {}))
            if curve is not None:
                result["rounded_curve"] = curve
            custom_style = _pbi_literal(sp.get("rectangleRoundedCurveCustomStyle", {}))
            if custom_style is not None:
                result["rounded_curve_custom"] = custom_style

        # Value text formatting (alignment, font size)
        for vl in objects.get("value", []):
            vp = vl.get("properties", {})
            align = _pbi_literal(vp.get("horizontalAlignment", {}))
            if align:
                result["value_alignment"] = align
            fsize = _pbi_literal(vp.get("fontSize", {}))
            if fsize is not None:
                result["value_fontSize"] = fsize

        # Overflow behaviour
        for ov in objects.get("overFlow", []):
            op = ov.get("properties", {})
            ofs = _pbi_literal(op.get("overFlowStyle", {}))
            if ofs is not None:
                result["overflow_style"] = ofs
            ofd = _pbi_literal(op.get("overFlowDirection", {}))
            if ofd is not None:
                result["overflow_direction"] = ofd

        # Image settings (tile images)
        for im in objects.get("image", []):
            ip = im.get("properties", {})
            for k in ("imageFit", "padding", "setAsBackGround",
                       "ignorePadding", "position", "saturation"):
                v = _pbi_literal(ip.get(k, {}))
                if v is not None:
                    result["image_" + k] = v

        # Padding / margins
        for pd in objects.get("padding", []):
            pp = pd.get("properties", {})
            for k in ("paddingSelection", "topMargin", "bottomMargin"):
                v = _pbi_literal(pp.get(k, {}))
                if v is not None:
                    result["padding_" + k] = v

        # Custom fill toggle
        for fc in objects.get("fillCustom", []):
            fp = fc.get("properties", {})
            show = _pbi_literal(fp.get("show", {}))
            if show is not None:
                result["fill_custom_show"] = show

    # Pre-set general filter (default selected values) — applies to ALL slicer types
    for gn in objects.get("general", []):
        gp = gn.get("properties", {})
        filt_wrapper = gp.get("filter", {})
        # PBIR uses double nesting: properties.filter.filter.{Version, Where...}
        filt = filt_wrapper.get("filter", filt_wrapper) if isinstance(filt_wrapper, dict) else {}
        if filt and isinstance(filt, dict):
            where = filt.get("Where", [])
            for w in where:
                cond = w.get("Condition", {})
                in_clause = cond.get("In", {})
                values_list = in_clause.get("Values", [])
                pre_selected: list[str] = []
                for val_arr in values_list:
                    if isinstance(val_arr, list):
                        for item in val_arr:
                            if isinstance(item, dict) and "Literal" in item:
                                lit = item["Literal"].get("Value", "")
                                # Strip surrounding quotes
                                if lit.startswith("'") and lit.endswith("'"):
                                    lit = lit[1:-1]
                                pre_selected.append(lit)
                if pre_selected:
                    result["default_values"] = pre_selected

    # Annotate with sync group info so _generate_native_slicers can validate
    sg = vis.get("syncGroup")
    if sg:
        result["_sync_group"] = sg

    return result or None


def _read_yaml(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Row-count verification — compare source crawl vs transferred output
# ---------------------------------------------------------------------------

def verify_report_transfer(
    report_dir: str,
    output_project_dir: str,
) -> dict:
    """
    Compare crawler row counts from the source PBIR report against the
    transferred output. Returns a dict with per-category matches/mismatches.

    This is the "check at the end with the comparison of the rows" that
    ensures nothing is lost during transfer.
    """
    # 1. Crawl the source report
    source_summary = crawl_report_summary(report_dir)
    if "error" in source_summary:
        return {"error": source_summary["error"]}

    source_totals = source_summary.get("totals", {})

    # 2. Count transferred items from output
    reports_dir = os.path.join(output_project_dir, "reports")
    visuals_dir = os.path.join(reports_dir, "visuals")

    transferred = {
        "visuals": 0,
        "pages": 0,
        "filters": 0,
        "sort": 0,
        "field_parameters": 0,
        "native_calcs": 0,
        "column_formatting": 0,
        "values_formatting": 0,
        "column_widths": 0,
        "hierarchy_levels": 0,
        "reference_lines": 0,
        "expansion_states": 0,
        "slicer_sync_groups": 0,
        "scope_selectors": 0,
        "datapoint_selectors": 0,
        "cached_filters": 0,
        "visual_selector_objects": 0,
        "label_overrides": 0,
        "encodings_total": 0,
    }

    # Count pages
    pages_yaml = os.path.join(reports_dir, "pages.yaml")
    if os.path.isfile(pages_yaml):
        pd = _read_yaml(pages_yaml)
        transferred["pages"] = len(pd.get("pages", []))

    # Count filters
    filters_yaml = os.path.join(reports_dir, "filters.yaml")
    if os.path.isfile(filters_yaml):
        fd = _read_yaml(filters_yaml)
        transferred["filters"] += len(fd.get("report_filters", []))
        for pf_list in fd.get("page_filters", {}).values():
            transferred["filters"] += len(pf_list)
        for vf_list in fd.get("visual_filters", {}).values():
            transferred["filters"] += len(vf_list)

    # Count per-visual fields from transferred JSON files
    if os.path.isdir(visuals_dir):
        for vfile in os.listdir(visuals_dir):
            if not vfile.endswith(".json"):
                continue
            vpath = os.path.join(visuals_dir, vfile)
            try:
                with open(vpath, encoding="utf-8") as f:
                    vj = json.load(f)
            except Exception:
                continue

            transferred["visuals"] += 1

            # Encodings
            enc = vj.get("encodings", {})
            for role, refs in enc.items():
                if isinstance(refs, list):
                    transferred["encodings_total"] += len(refs)
                elif refs:
                    transferred["encodings_total"] += 1

            # Sort
            transferred["sort"] += len(vj.get("sort", []))

            # Field parameters
            transferred["field_parameters"] += len(vj.get("field_parameters", []))

            # Native calcs
            transferred["native_calcs"] += len(vj.get("native_calcs", []))

            # Hierarchy levels
            transferred["hierarchy_levels"] += len(vj.get("hierarchy_levels", []))

            # Expansion states
            transferred["expansion_states"] += len(vj.get("expansion_states", []))

            # Slicer sync group
            if vj.get("slicer_sync_group"):
                transferred["slicer_sync_groups"] += 1

            # Cached filters
            transferred["cached_filters"] += len(vj.get("cached_filters", []))

            # Label overrides
            transferred["label_overrides"] += len(vj.get("label_overrides", {}))

            # Format sub-items
            fmt = vj.get("format", {})
            transferred["column_formatting"] += len(fmt.get("column_formatting", []))
            transferred["values_formatting"] += len(fmt.get("values_formatting", []))
            transferred["column_widths"] += len(fmt.get("column_widths", []))
            transferred["reference_lines"] += len(fmt.get("reference_lines", []))
            transferred["scope_selectors"] += len(fmt.get("scope_selectors", []))
            transferred["datapoint_selectors"] += len(fmt.get("datapoint_selectors", []))
            transferred["visual_selector_objects"] += len(
                fmt.get("visual_selector_objects", []))

    # Count bookmarks
    bookmarks_yaml = os.path.join(reports_dir, "bookmarks.yaml")
    if os.path.isfile(bookmarks_yaml):
        bd = _read_yaml(bookmarks_yaml)
        transferred["bookmarks"] = len(bd.get("bookmarks", []))

    # 3. Build comparison
    comparison = {
        "source": {
            "pages": source_summary.get("pages", 0),
            "visuals": source_summary.get("visuals_total", 0),
            "report_filters": source_summary.get("report_filters", 0),
            "bookmarks": source_summary.get("bookmarks", 0),
            "crawler_totals": source_totals,
        },
        "transferred": transferred,
        "matches": {},
        "mismatches": {},
    }

    # Map source crawler categories → transferred keys
    category_map = {
        "order_by": "sort",
        "field_parameters": "field_parameters",
        "native_calcs": "native_calcs",
        "column_formatting": "column_formatting",
        "values_formatting": "values_formatting",
        "column_widths": "column_widths",
        "hierarchy_levels": "hierarchy_levels",
        "reference_lines": "reference_lines",
        "expansion_queryrefs": "expansion_states",
        "slicer_sync_group": "slicer_sync_groups",
        "scope_selectors": "scope_selectors",
        "datapoint_selectors": "datapoint_selectors",
        "cached_filter_display_items": "cached_filters",
        "visual_selector_objects": "visual_selector_objects",
        "column_properties_labels": "label_overrides",
    }

    for src_cat, dest_key in category_map.items():
        src_count = source_totals.get(src_cat, 0)
        dest_count = transferred.get(dest_key, 0)
        entry = {"source": src_count, "transferred": dest_count}
        if src_count == dest_count:
            comparison["matches"][src_cat] = entry
        else:
            comparison["mismatches"][src_cat] = entry

    # Structural counts
    for struct_key in ["pages", "visuals", "bookmarks"]:
        src_val = comparison["source"].get(struct_key, 0)
        dest_val = transferred.get(struct_key, 0)
        entry = {"source": src_val, "transferred": dest_val}
        if src_val == dest_val:
            comparison["matches"][struct_key] = entry
        else:
            comparison["mismatches"][struct_key] = entry

    comparison["all_match"] = len(comparison["mismatches"]) == 0

    return comparison


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        report_dir = os.path.join(os.path.dirname(__file__),
            "PowerBI%20AdventureWorksNewFormat", "Test.Report")
    else:
        report_dir = sys.argv[1]

    print("=== Preview ===")
    preview = preview_report_transfer(report_dir)
    print(json.dumps(preview.get("summary", {}), indent=2))
    print(f"\nPages: {len(preview.get('pages', []))}")
    for p in preview.get("pages", []):
        print(f"  {p['order']}. {p['name']} ({p['page_id']}) "
              f"{'[hidden]' if p['hidden'] else ''}"
              f"{'[drillthrough]' if p['is_drillthrough'] else ''}")
    print(f"\nVisuals: {len(preview.get('visuals', []))}")
    for v in preview.get("visuals", []):
        status = "✓" if v["is_supported"] else "✗"
        print(f"  {status} {v['visual_id'][:12]} | {v['visual_type_pbi']:30s} → {v['visual_type_project']:15s} | "
              f"{v['page']} | {v['field_count']} fields | {v['filter_count']} filters")

    # Execute to a temp output
    import tempfile
    out_dir = os.path.join(tempfile.gettempdir(), "pbi_transfer_test")
    print(f"\n=== Execute Transfer → {out_dir} ===")
    result = execute_report_transfer(report_dir, out_dir)
    print(f"Pages: {result.pages_created}")
    print(f"Visuals: {result.visuals_created}")
    print(f"Filters: {result.filters_transferred}")
    print(f"Bookmarks: {result.bookmarks_transferred}")
    print(f"Sort configs: {result.sort_configs_transferred}")
    print(f"Field parameters: {result.field_parameters_transferred}")
    print(f"Native calcs: {result.native_calcs_transferred}")
    print(f"Reference lines: {result.reference_lines_transferred}")
    print(f"Column formatting: {result.column_formatting_transferred}")
    print(f"Values formatting: {result.values_formatting_transferred}")
    print(f"Column widths: {result.column_widths_transferred}")
    print(f"Hierarchy levels: {result.hierarchy_levels_transferred}")
    print(f"Slicer sync groups: {result.slicer_sync_groups_transferred}")
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  * {w}")
    if result.unsupported_visual_types:
        print(f"Unsupported types: {set(result.unsupported_visual_types)}")

    # Print a sample visual
    visuals_dir = os.path.join(out_dir, "reports", "visuals")
    if os.path.isdir(visuals_dir):
        files = os.listdir(visuals_dir)
        if files:
            sample = os.path.join(visuals_dir, files[0])
            print(f"\n=== Sample Visual: {files[0]} ===")
            with open(sample) as f:
                print(json.dumps(json.load(f), indent=2)[:2000])

    # Verify row-count comparison
    print("\n=== Row-Count Verification ===")
    verification = verify_report_transfer(report_dir, out_dir)
    if verification.get("all_match"):
        print("ALL ROWS MATCH")
    else:
        print("MISMATCHES DETECTED:")

    matches = verification.get("matches", {})
    mismatches = verification.get("mismatches", {})

    print(f"\n{'Category':<35s} {'Source':>8s} {'Transferred':>12s} {'Status':>8s}")
    print("-" * 65)
    for cat, entry in sorted({**matches, **mismatches}.items()):
        src = entry["source"]
        dest = entry["transferred"]
        status = "OK" if cat in matches else "MISMATCH"
        print(f"  {cat:<33s} {src:>8d} {dest:>12d} {status:>8s}")


# ---------------------------------------------------------------------------
# Theme extraction — PBI theme JSON → project ReportingTheme
# ---------------------------------------------------------------------------

def extract_pbi_theme(report_dir: str) -> dict:
    """
    Extract Power BI theme from a PBIR .Report directory and convert it
    to the project's ReportingTheme format.

    Returns a dict matching the ReportingTheme interface:
      name, dataColors, visualCard, font, chart, canvas, defaultSize
    """
    report_path = Path(report_dir)

    # 1. Locate the theme JSON file
    theme_json = _find_pbi_theme_file(report_path)
    if theme_json is None:
        raise FileNotFoundError(
            f"No Power BI theme file found in {report_dir}. "
            "Expected StaticResources/SharedResources/BaseThemes/*.json"
        )

    with open(theme_json, encoding="utf-8") as f:
        pbi = json.load(f)

    return _convert_pbi_theme(pbi)


def _find_pbi_theme_file(report_path: Path) -> Optional[Path]:
    """Locate the PBI theme JSON in a .Report directory."""
    # Try the standard PBIR location first
    base_themes_dir = report_path / "StaticResources" / "SharedResources" / "BaseThemes"
    if base_themes_dir.is_dir():
        for f in base_themes_dir.glob("*.json"):
            return f

    # Try reading report.json for explicit theme reference
    report_json = report_path / "definition" / "report.json"
    if report_json.exists():
        try:
            with open(report_json, encoding="utf-8") as f:
                rj = json.load(f)
            theme_coll = rj.get("themeCollection", {})
            base = theme_coll.get("baseTheme", {})
            # resourcePackages[0].items[0].path gives relative path
            for rp in rj.get("resourcePackages", []):
                for item in rp.get("items", []):
                    p = item.get("path", "")
                    if p.endswith(".json") and "theme" in p.lower():
                        candidate = report_path / "StaticResources" / "SharedResources" / p
                        if candidate.exists():
                            return candidate
        except Exception:
            pass

    # Fallback: search recursively
    for f in report_path.rglob("*.json"):
        if "theme" in f.stem.lower() or "BaseThemes" in str(f):
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
                if "dataColors" in d:
                    return f
            except Exception:
                continue

    return None


def _convert_pbi_theme(pbi: dict) -> dict:
    """Convert a PBI theme JSON object to the project's ReportingTheme dict."""
    name = pbi.get("name", "Power BI Theme")

    # dataColors — PBI can have up to 41+ colors; we keep the first 8-12
    raw_colors = pbi.get("dataColors", [])
    data_colors = raw_colors[:12] if raw_colors else [
        "#118DFF", "#12239E", "#E66C37", "#6B007B",
        "#E044A7", "#744EC2", "#D9B300", "#D64550",
    ]

    # Font from textClasses
    text_classes = pbi.get("textClasses", {})
    label_class = text_classes.get("label", {})
    title_class = text_classes.get("title", {})
    header_class = text_classes.get("header", {})

    font_family = (
        label_class.get("fontFace")
        or header_class.get("fontFace")
        or "Segoe UI, sans-serif"
    )
    size_body = label_class.get("fontSize", 11)
    size_title = title_class.get("fontSize", 14)
    color_body = label_class.get("color", "")
    color_title = title_class.get("color", "")

    # Semantic colors
    foreground = pbi.get("foreground", "#252423")
    background = pbi.get("background", "#FFFFFF")
    table_accent = pbi.get("tableAccent", "#118DFF")

    # Build the ReportingTheme
    theme: dict = {
        "name": name,
        "dataColors": data_colors,
        "visualCard": {
            "borderRadius": 4,
            "borderWidth": 1,
            "borderColor": "",
            "shadow": "sm",
            "padding": 0,
            "background": "",
        },
        "font": {
            "family": f"{font_family}, sans-serif" if "sans-serif" not in font_family.lower() else font_family,
            "sizeBody": min(max(size_body, 8), 24),
            "sizeTitle": min(max(size_title, 10), 32),
            "colorBody": color_body or foreground,
            "colorTitle": color_title or foreground,
        },
        "chart": {
            "showGridlines": True,
            "gridlineColor": "",
            "axisColor": foreground if foreground != "#252423" else "",
            "plotBackground": "transparent",
            "legendPosition": "bottom",
        },
        "canvas": {
            "background": background if background != "#FFFFFF" else "",
        },
        "defaultSize": {
            "width": 420,
            "height": 320,
        },
        # Semantic / conditional-formatting colors from PBI theme
        "semantic": {
            "foreground": foreground,
            "tableAccent": table_accent,
            "good": pbi.get("good", ""),
            "bad": pbi.get("bad", ""),
            "neutral": pbi.get("neutral", ""),
            "hyperlink": pbi.get("hyperlink", ""),
        },
        # Extra PBI-specific metadata (not in ReportingTheme but useful for preview)
        "_pbi_meta": {
            "foreground": foreground,
            "background": background,
            "tableAccent": table_accent,
            "good": pbi.get("good", ""),
            "bad": pbi.get("bad", ""),
            "neutral": pbi.get("neutral", ""),
            "hyperlink": pbi.get("hyperlink", ""),
            "allDataColors": raw_colors,
        },
    }

    return theme
