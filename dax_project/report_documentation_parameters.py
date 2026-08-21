"""Parameter catalogue for PowerBI_Tool Report_Documentation.xlsx workbooks."""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping


REPORT_PARAMETER_SHEETS = {
    "Visual Containers",
    "Reports",
    "Selected Visuals",
    "Visual Properties",
    "Edit Interactions",
    "Slicer Metadata",
    "Page Metadata",
    "Filters",
    "Bookmarks",
    "Text Boxes",
    "Buttons & Shapes",
    "Pictures",
    "Report Settings",
    "Report Health",
}

_CONTEXT_COLUMNS = {
    "Dataset",
    "Report",
    "PageID",
    "Page",
    "VisualID",
    "VisualType",
    "JsonPath",
    "OriginalJson",
}

_IDENTITY_COLUMNS = {"Title", "Subtitle", "Hidden", "ParentGroup"}
_LAYOUT_COLUMNS = {"X", "Y", "Z", "Width", "Height", "TabOrder"}
_FIELD_COLUMNS = {
    "UsedIn",
    "Role",
    "Table",
    "Field",
    "Value",
    "Field Type",
    "AggregationFunction",
    "Is Field Parameter",
    "Is Hierarchy",
    "Is Calculated Column",
    "Is Calculation Group",
    "Condition",
}
_QUERY_OPTION_COLUMNS = {
    "DataRoles",
    "DataRoleCount",
    "HasFieldParameters",
    "SortColumn",
    "SortDirection",
    "SortIsDefault",
    "ShowItemsWithNoData",
    "TopNCount",
    "TopNDirection",
    "TopNOrderField",
    "DataReductionStrategy",
    "DataReductionMode",
    "DataReductionPrimaryLimit",
    "DataReductionSeriesLimit",
    "DataReductionMaxPoints",
    "DataReductionConfidence",
    "DataReductionNotes",
}
_FORMAT_FLAG_COLUMNS = {"HasLegend", "HasDataLabels", "HasSmallMultiple"}
_FILTER_COLUMNS = {"HasVisualLevelFilter", "VisualLevelFilterCount", "HasPageLevelFilters", "PageLevelFilterCount", "HasActiveFilter"}
_VISUAL_CALC_COLUMNS = {"HasVisualCalculations", "HasSparkline"}


@dataclass(frozen=True)
class CanonicalVisualParameter:
    """A workbook-emitted report parameter with explicit coverage status."""

    dataset: str
    report: str
    page_id: str
    page: str
    visual_id: str
    visual_type: str
    parameter_id: str
    surface: str
    json_pointer: str
    workbook_source_sheet: str
    object_name: str
    property_name: str
    selector_kind: str
    role: str
    value_type: str
    example_value: Any
    canonical_target: str
    project_target: str
    mapping_status: str
    render_status: str
    round_trip_status: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "Dataset": self.dataset,
            "Report": self.report,
            "PageID": self.page_id,
            "Page": self.page,
            "VisualID": self.visual_id,
            "VisualType": self.visual_type,
            "ParameterID": self.parameter_id,
            "Surface": self.surface,
            "JsonPointer": self.json_pointer,
            "WorkbookSourceSheet": self.workbook_source_sheet,
            "ObjectName": self.object_name,
            "PropertyName": self.property_name,
            "SelectorKind": self.selector_kind,
            "Role": self.role,
            "ValueType": self.value_type,
            "ExampleValue": _json_safe(self.example_value),
            "CanonicalTarget": self.canonical_target,
            "ProjectTarget": self.project_target,
            "MappingStatus": self.mapping_status,
            "RenderStatus": self.render_status,
            "RoundTripStatus": self.round_trip_status,
            "Notes": self.notes,
        }


def build_documentation_parameter_catalogue_from_sheets(
    sheets: Mapping[str, Any],
    *,
    dataset: str | None = None,
    report: str | None = None,
) -> list[CanonicalVisualParameter]:
    """Build parameter rows from report-facing workbook sheets."""

    parameters: list[CanonicalVisualParameter] = []
    for sheet_name, frame in sheets.items():
        if sheet_name not in REPORT_PARAMETER_SHEETS:
            continue
        filtered_frame = _filter_frame(frame, dataset=dataset, report=report)
        if filtered_frame is None or filtered_frame.empty:
            continue
        if sheet_name == "Visual Properties":
            parameters.extend(_parameters_from_visual_properties(sheet_name, filtered_frame))
        elif sheet_name == "Report Settings":
            parameters.extend(_parameters_from_report_settings(sheet_name, filtered_frame))
        elif sheet_name == "Report Health":
            parameters.extend(_parameters_from_report_health(sheet_name, filtered_frame))
        else:
            parameters.extend(_parameters_from_table_cells(sheet_name, filtered_frame))
    return parameters


def summarize_parameter_coverage(parameters: list[CanonicalVisualParameter]) -> dict[str, Any]:
    """Return deterministic coverage counts for preview and saved artifacts."""

    mapping_status = Counter(parameter.mapping_status for parameter in parameters)
    render_status = Counter(parameter.render_status for parameter in parameters)
    round_trip_status = Counter(parameter.round_trip_status for parameter in parameters)
    surfaces = Counter(parameter.surface for parameter in parameters)
    visual_types = Counter(parameter.visual_type or "(report/page)" for parameter in parameters)
    sheets = Counter(parameter.workbook_source_sheet for parameter in parameters)
    high_priority_gap_groups = Counter(
        (
            parameter.surface,
            parameter.object_name,
            parameter.property_name,
            parameter.project_target,
        )
        for parameter in parameters
        if parameter.mapping_status == "gap"
    )
    return {
        "total_parameters": len(parameters),
        "mapping_status": dict(sorted(mapping_status.items())),
        "render_status": dict(sorted(render_status.items())),
        "round_trip_status": dict(sorted(round_trip_status.items())),
        "surfaces": dict(sorted(surfaces.items())),
        "visual_types": dict(sorted(visual_types.items())),
        "workbook_source_sheets": dict(sorted(sheets.items())),
        "gap_count": mapping_status.get("gap", 0),
        "partial_count": mapping_status.get("partial", 0),
        "preserve_only_count": mapping_status.get("preserve_only", 0),
        "exact_count": mapping_status.get("exact", 0),
        "high_priority_gaps": [
            {
                "surface": surface,
                "object_name": object_name,
                "property_name": property_name,
                "project_target": project_target,
                "count": count,
            }
            for (surface, object_name, property_name, project_target), count in sorted(
                high_priority_gap_groups.items(),
                key=lambda item: (-item[1], item[0]),
            )[:25]
        ],
    }


def parameters_to_dicts(parameters: list[CanonicalVisualParameter]) -> list[dict[str, Any]]:
    return [parameter.to_dict() for parameter in parameters]


def _parameters_from_visual_properties(sheet_name: str, frame: Any) -> list[CanonicalVisualParameter]:
    parameters: list[CanonicalVisualParameter] = []
    for row_index, row in frame.iterrows():
        value = _cell_value(row, "Value")
        if _is_blank(value):
            continue
        group = _cell_text(row, "PropertyGroup")
        property_name = _cell_text(row, "Property")
        surface = _surface_for_visual_property(group, property_name)
        parameters.append(
            _make_parameter(
                sheet_name,
                row_index,
                row,
                surface=surface,
                object_name=group,
                property_name=property_name,
                value=value,
                selector=_cell_text(row, "Selector"),
                role="",
                notes="Visual Properties EAV row",
            )
        )
    return parameters


def _parameters_from_report_settings(sheet_name: str, frame: Any) -> list[CanonicalVisualParameter]:
    parameters: list[CanonicalVisualParameter] = []
    for row_index, row in frame.iterrows():
        setting = _cell_text(row, "Setting")
        value = _cell_value(row, "Value")
        if not setting or _is_blank(value):
            continue
        parameters.append(
            _make_parameter(
                sheet_name,
                row_index,
                row,
                surface="reportSetting",
                object_name="report",
                property_name=setting,
                value=value,
                selector="",
                role="",
                notes="Report-level setting preserved for round-trip coverage",
            )
        )
    return parameters


def _parameters_from_report_health(sheet_name: str, frame: Any) -> list[CanonicalVisualParameter]:
    parameters: list[CanonicalVisualParameter] = []
    for row_index, row in frame.iterrows():
        detail = _cell_text(row, "Detail") or _cell_text(row, "Recommendation") or _cell_text(row, "Category")
        severity = _cell_text(row, "Severity")
        if not detail and not severity:
            continue
        parameters.append(
            _make_parameter(
                sheet_name,
                row_index,
                row,
                surface="health",
                object_name=_cell_text(row, "Category") or "reportHealth",
                property_name=severity or "diagnostic",
                value={
                    "detail": detail,
                    "severity": severity,
                    "recommendation": _cell_text(row, "Recommendation"),
                },
                selector="",
                role="",
                notes="Diagnostic row; not render state",
            )
        )
    return parameters


def _parameters_from_table_cells(sheet_name: str, frame: Any) -> list[CanonicalVisualParameter]:
    parameters: list[CanonicalVisualParameter] = []
    for row_index, row in frame.iterrows():
        for column in frame.columns:
            column_name = str(column)
            if column_name in _CONTEXT_COLUMNS:
                continue
            value = _cell_value(row, column_name)
            if _is_blank(value):
                continue
            surface = _surface_for_sheet_column(sheet_name, column_name)
            parameters.append(
                _make_parameter(
                    sheet_name,
                    row_index,
                    row,
                    surface=surface,
                    object_name=_object_name_for_column(sheet_name, column_name),
                    property_name=column_name,
                    value=value,
                    selector="",
                    role=_role_from_row(row),
                    notes="Workbook sheet column",
                )
            )
    return parameters


def _make_parameter(
    sheet_name: str,
    row_index: Any,
    row: Any,
    *,
    surface: str,
    object_name: str,
    property_name: str,
    value: Any,
    selector: str,
    role: str,
    notes: str,
) -> CanonicalVisualParameter:
    coverage = _coverage_for_surface(surface)
    canonical_target, project_target = _targets_for_surface(surface)
    return CanonicalVisualParameter(
        dataset=_cell_text(row, "Dataset"),
        report=_cell_text(row, "Report"),
        page_id=_cell_text(row, "PageID"),
        page=_cell_text(row, "Page"),
        visual_id=_cell_text(row, "VisualID"),
        visual_type=_cell_text(row, "VisualType"),
        parameter_id=_parameter_id(sheet_name, row_index, row, object_name, property_name),
        surface=surface,
        json_pointer=_cell_text(row, "JsonPath"),
        workbook_source_sheet=sheet_name,
        object_name=object_name,
        property_name=property_name,
        selector_kind=_selector_kind(selector),
        role=role,
        value_type=_value_type(value),
        example_value=_json_safe(value),
        canonical_target=canonical_target,
        project_target=project_target,
        mapping_status=coverage["mapping_status"],
        render_status=coverage["render_status"],
        round_trip_status=coverage["round_trip_status"],
        notes=notes,
    )


def _surface_for_sheet_column(sheet_name: str, column_name: str) -> str:
    if sheet_name == "Visual Containers":
        if column_name in _LAYOUT_COLUMNS:
            return "layout"
        if column_name in _IDENTITY_COLUMNS:
            return "identity"
        if column_name in _VISUAL_CALC_COLUMNS:
            return "visualCalculation"
        if column_name in _QUERY_OPTION_COLUMNS:
            return "queryOptions"
        if column_name in _FORMAT_FLAG_COLUMNS:
            return "format"
        if column_name in _FILTER_COLUMNS:
            return "filter"
        if column_name == "DrillFilterOtherVisuals":
            return "interaction"
        if column_name == "CustomTooltipPageID":
            return "tooltip"
        if column_name == "VisualHeaderIcons":
            return "visualHeader"
    if sheet_name in {"Reports", "Selected Visuals"}:
        if column_name in _FIELD_COLUMNS:
            return "projection"
        return "modelReference"
    if sheet_name == "Edit Interactions":
        return "interaction"
    if sheet_name == "Slicer Metadata":
        return "slicerState"
    if sheet_name == "Page Metadata":
        if column_name in {"IsDrillthrough", "CrossReportDrillthrough", "DrillthroughFields", "DrillthroughTable", "DrillthroughField"}:
            return "drillthrough"
        return "page"
    if sheet_name == "Filters":
        return "filter"
    if sheet_name == "Bookmarks":
        return "bookmark"
    if sheet_name == "Text Boxes":
        if column_name in {"HasBookmarkLink", "BookmarkTarget"}:
            return "visualAction"
        return "staticAsset"
    if sheet_name == "Buttons & Shapes":
        if column_name in {"ActionType", "BookmarkTarget"}:
            return "buttonAction"
        return "staticAsset"
    if sheet_name == "Pictures":
        return "resource"
    return "object"


def _surface_for_visual_property(group: str, property_name: str) -> str:
    group_lower = group.lower()
    property_lower = property_name.lower()
    if group_lower == "vc:visualheader":
        return "visualHeader"
    if group_lower == "vc:visuallink":
        return "visualAction"
    if group_lower == "vc:visualtooltip":
        return "tooltip"
    if group_lower.startswith("vc:"):
        return "containerChrome"
    if group_lower == "selection":
        return "selection"
    if group_lower in {"referenceline", "xaxisreferenceline", "y1axisreferenceline", "trend", "forecast"}:
        return "analytics"
    if group_lower in {"columnformatting", "values"} or "databars" in property_lower:
        return "conditionalFormatting"
    if group_lower in {"columnheaders", "rowheaders", "grid", "columnwidth", "overflow"}:
        return "tableMatrixFormat"
    if group_lower == "general" and property_lower == "paragraphs":
        return "staticAsset"
    if group_lower == "general" and "filter" in property_lower:
        return "filter"
    if group_lower in {"shape", "shapecustomrectangle", "icon", "image", "rotation"}:
        return "staticAsset"
    if group_lower == "datapoint":
        return "selectorFormatting"
    return "format"


def _coverage_for_surface(surface: str) -> dict[str, str]:
    if surface in {"identity", "layout", "projection"}:
        return {"mapping_status": "exact", "render_status": "renders", "round_trip_status": "source_preserved"}
    if surface in {"visualCalculation", "customVisual", "mobile"}:
        return {"mapping_status": "gap", "render_status": "not_rendered", "round_trip_status": "source_preserved"}
    if surface in {"visualHeader", "visualAction", "buttonAction"}:
        return {"mapping_status": "partial", "render_status": "stored_only", "round_trip_status": "source_preserved"}
    if surface in {"resource", "staticAsset", "reportSetting", "health", "modelReference"}:
        return {"mapping_status": "preserve_only", "render_status": "stored_only", "round_trip_status": "source_preserved"}
    return {"mapping_status": "partial", "render_status": "stored_only", "round_trip_status": "source_preserved"}


def _targets_for_surface(surface: str) -> tuple[str, str]:
    targets = {
        "identity": ("visual.identity", "visual.id/title/visual_type"),
        "layout": ("visual.layout", "visual.layout"),
        "page": ("page.display", "reports/pages.yaml + page_format"),
        "projection": ("visual.fields[]", "visual.encodings"),
        "queryOptions": ("visual.query_options", "query_options"),
        "visualCalculation": ("visual.visual_calculations[]", "native_calcs"),
        "filter": ("filters[]", "reports/filters.yaml"),
        "format": ("visual.format", "visual.format"),
        "containerChrome": ("visual.container_format", "container_format"),
        "visualHeader": ("visual.visual_header", "visual_header"),
        "visualAction": ("visual.actions[]", "visual_actions"),
        "buttonAction": ("visual.actions[]", "visual_actions"),
        "selectorFormatting": ("visual.selector_formatting[]", "format selector sidecars"),
        "conditionalFormatting": ("visual.conditional_formatting[]", "format.column_formatting/values_formatting"),
        "analytics": ("visual.analytics[]", "format.referenceLines/trendline"),
        "tableMatrixFormat": ("visual.table_matrix_format", "matrix/table format keys"),
        "drillthrough": ("page.drillthrough", "page metadata + button actions"),
        "interaction": ("interactions[]", "visual.interactions"),
        "bookmark": ("bookmarks[]", "reports/bookmarks.yaml"),
        "tooltip": ("visual.tooltip", "tooltip_page_id/encodings.tooltip"),
        "selection": ("visual.selection_state", "selection_state"),
        "slicerState": ("visual.slicer_state", "slicer_sync_group + filters"),
        "staticAsset": ("visual.static_asset", "textbox/shape/image/button sidecars"),
        "resource": ("resources[]", "static_resources"),
        "reportSetting": ("report.settings", "documentation_parameter_coverage.json"),
        "health": ("diagnostics[]", "documentation_parameter_coverage.json"),
        "modelReference": ("model.references[]", "source provenance"),
    }
    return targets.get(surface, ("visual.format", "preserve-only sidecar"))


def _object_name_for_column(sheet_name: str, column_name: str) -> str:
    if sheet_name == "Visual Containers":
        return "visualContainer"
    if sheet_name in {"Reports", "Selected Visuals"}:
        return "fieldBinding"
    if sheet_name == "Page Metadata":
        return "page"
    return sheet_name.replace(" ", "_").lower()


def _role_from_row(row: Any) -> str:
    role = _cell_text(row, "Role")
    if role:
        return role
    used_in = _cell_text(row, "UsedIn")
    if ":" in used_in:
        return used_in.rsplit(":", 1)[-1]
    return ""


def _selector_kind(selector: str) -> str:
    selector_lower = selector.lower()
    if not selector_lower:
        return "static"
    if "metadata" in selector_lower or "queryname" in selector_lower or "column" in selector_lower:
        return "column"
    if "scope" in selector_lower:
        return "scopeIdentity"
    if "data" in selector_lower:
        return "data"
    return "selector"


def _parameter_id(sheet_name: str, row_index: Any, row: Any, object_name: str, property_name: str) -> str:
    raw = "|".join(
        [
            sheet_name,
            str(row_index),
            _cell_text(row, "VisualID"),
            _cell_text(row, "PageID"),
            object_name,
            property_name,
            _cell_text(row, "JsonPath"),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"doc_param_{digest}"


def _filter_frame(frame: Any, *, dataset: str | None, report: str | None):
    if frame is None or frame.empty:
        return frame
    out = frame
    if dataset and "Dataset" in out.columns:
        out = out[out["Dataset"].map(lambda value: _normalize_key(value) == _normalize_key(dataset))]
    if report and "Report" in out.columns:
        out = out[out["Report"].map(lambda value: _normalize_key(value) == _normalize_key(report))]
    return out


def _cell_text(row: Any, column: str) -> str:
    return _to_text(_cell_value(row, column))


def _cell_value(row: Any, column: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(column)
    try:
        return row.get(column)
    except Exception:
        return None


def _to_text(value: Any) -> str:
    if _is_blank(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        import pandas as pd  # type: ignore

        if pd.isna(value):
            return True
    except Exception:
        pass
    return isinstance(value, str) and not value.strip()


def _json_safe(value: Any) -> Any:
    if _is_blank(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items() if not _is_blank(item)}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _value_type(value: Any) -> str:
    value = _json_safe(value)
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def _normalize_key(value: Any) -> str:
    return _to_text(value).strip().lower()