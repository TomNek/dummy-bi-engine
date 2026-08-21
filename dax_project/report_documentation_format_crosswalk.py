"""Format crosswalk helpers for Report_Documentation.xlsx imports.

PowerBI_Tool emits visual object rows as workbook EAV records.  This module
keeps the DAX-side mapping measurable by translating common Power BI object
properties into the existing Dummy BI/Plotly format keys, while reporting rows
that remain sidecar-only.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping

from dax_project.report_documentation_parameters import CanonicalVisualParameter
from dax_project.report_transfer import _map_visual_type


_DOC_VISUAL_TYPE_OVERRIDES = {
    "cardVisual": "card",
    "listSlicer": "slicer",
    "textSlicer": "slicer",
    "columnChart": "column",
    "hundredPercentStackedAreaChart": "area",
}

_LABEL_POSITION_MAP = {
    "Auto": "auto",
    "OutsideEnd": "outside",
    "InsideEnd": "inside",
    "InsideBase": "inside",
    "InsideCenter": "inside",
}

_FORMAT_KEY_MAP: dict[tuple[str, str], str] = {
    ("legend", "show"): "showLegend",
    ("legend", "position"): "legendPosition",
    ("legend", "fontSize"): "legendFontSize",
    ("legend", "fontFamily"): "legendFontFamily",
    ("legend", "fontColor"): "legendFontColor",
    ("legend", "color"): "legendFontColor",
    ("legend", "titleText"): "legendTitleText",
    ("legend", "showTitle"): "legendShowTitle",
    ("legend", "showGradientLegend"): "legendShowGradient",
    ("labels", "show"): "showDataLabels",
    ("labels", "labelPosition"): "dataLabelPosition",
    ("labels", "position"): "dataLabelPosition",
    ("labels", "color"): "dataLabelColor",
    ("labels", "fontSize"): "dataLabelFontSize",
    ("labels", "fontFamily"): "dataLabelFontFamily",
    ("labels", "labelDisplayUnits"): "dataLabelDisplayUnits",
    ("labels", "displayUnits"): "dataLabelDisplayUnits",
    ("labels", "labelPrecision"): "dataLabelPrecision",
    ("labels", "precision"): "dataLabelPrecision",
    ("labels", "transparency"): "dataLabelTransparency",
    ("labels", "labelAngle"): "dataLabelAngle",
    ("dataLabels", "fontSize"): "cardDataLabelsFontSize",
    ("dataLabels", "fontFamily"): "cardDataLabelsFontFamily",
    ("categoryLabels", "show"): "cardCategoryLabelsShow",
    ("categoryLabels", "fontSize"): "cardCategoryFontSize",
    ("categoryLabels", "color"): "cardCategoryColor",
    ("categoryAxis", "show"): "showXAxis",
    ("categoryAxis", "showAxisTitle"): "showXAxisTitle",
    ("categoryAxis", "axisType"): "categoryAxisType",
    ("categoryAxis", "innerPadding"): "categoryAxisInnerPadding",
    ("categoryAxis", "fontSize"): "xAxisFontSize",
    ("categoryAxis", "fontFamily"): "xAxisFontFamily",
    ("categoryAxis", "fontColor"): "xAxisFontColor",
    ("categoryAxis", "titleText"): "xAxisLabel",
    ("categoryAxis", "labelAngle"): "xAxisTickAngle",
    ("valueAxis", "show"): "showYAxis",
    ("valueAxis", "showAxisTitle"): "showYAxisTitle",
    ("valueAxis", "fontSize"): "yAxisFontSize",
    ("valueAxis", "fontFamily"): "yAxisFontFamily",
    ("valueAxis", "fontColor"): "yAxisFontColor",
    ("valueAxis", "titleText"): "yAxisLabel",
    ("valueAxis", "start"): "yAxisMin",
    ("valueAxis", "end"): "yAxisMax",
    ("valueAxis", "gridlines"): "showYAxisGridlines",
    ("valueAxis", "gridlineColor"): "yAxisGridlineColor",
    ("plotArea", "transparency"): "plotAreaTransparency",
    ("layout", "clusteredGapSize"): "bargap",
    ("layout", "clusteredGapOverlaps"): "barMode",
    ("layout", "clusteredGapOverlapReverse"): "clusteredGapOverlapReverse",
    ("layout", "seriesOrderReversed"): "seriesOrderReversed",
    ("layout", "seriesOrderSorted"): "seriesOrderSorted",
    ("seriesLabels", "show"): "seriesLabelsShow",
    ("dataPoint", "borderShow"): "dataPointBorderShow",
    ("card", "barColor"): "cardBarColor",
    ("card", "barWeight"): "cardBarWeight",
    ("rowHeaders", "steppedLayoutIndentation"): "matrixSteppedIndentation",
    ("grid", "gridHorizontal"): "matrixGridHorizontal",
    ("columnHeaders", "backColor"): "matrixColumnHeaderBg",
    ("columnHeaders", "wordWrap"): "matrixColumnHeaderWordWrap",
    ("columnHeaders", "outlineStyle"): "matrixColumnHeaderOutline",
    ("columnHeaders", "autoSizeColumnWidth"): "matrixAutoSizeColumns",
    ("general", "layout"): "matrixLayout",
    ("shape", "outlineShow"): "shape_outline_show",
    ("shape", "outlineColor"): "shape_outline_color",
    ("shape", "outlineWeight"): "shape_outline_weight",
    ("outline", "show"): "shape_outline_show",
    ("outline", "lineColor"): "shape_outline_color",
    ("outline", "weight"): "shape_outline_weight",
    ("fill", "show"): "background_show",
    ("lineStyles", "areaShow"): "fillArea",
    ("columnWidth", "value"): "matrixColumnWidths",
}

_CONTAINER_FORMAT_KEY_MAP: dict[tuple[str, str], str] = {
    ("vc:background", "color"): "backgroundColor",
    ("vc:background", "show"): "background_show",
    ("vc:border", "show"): "border_show",
    ("vc:border", "color"): "borderColor",
    ("vc:border", "width"): "border_width",
    ("vc:border", "radius"): "visualBorderRadius",
    ("vc:title", "show"): "showTitle",
    ("vc:title", "text"): "title",
    ("vc:title", "fontSize"): "visualHeaderFontSize",
    ("vc:title", "color"): "titleColor",
    ("vc:title", "alignment"): "titleAlign",
    ("vc:visualHeader", "show"): "showVisualHeader",
    ("vc:subTitle", "show"): "showSubtitle",
    ("vc:subTitle", "text"): "subtitle",
    ("vc:dropShadow", "show"): "drop_shadow.show",
    ("vc:dropShadow", "preset"): "drop_shadow.preset",
    ("vc:dropShadow", "shadowBlur"): "drop_shadow.shadowBlur",
    ("vc:dropShadow", "shadowDistance"): "drop_shadow.shadowDistance",
    ("vc:dropShadow", "shadowSpread"): "drop_shadow.shadowSpread",
    ("vc:dropShadow", "transparency"): "drop_shadow.transparency",
    ("vc:dropShadow", "color"): "drop_shadow.shadowColor",
    ("vc:padding", "top"): "padding.top",
    ("vc:padding", "right"): "padding.right",
    ("vc:padding", "bottom"): "padding.bottom",
    ("vc:padding", "left"): "padding.left",
}

_VISUAL_SPECIFIC_FORMAT_KEY_MAP: dict[tuple[str, str, str], str] = {
    ("card", "labels", "color"): "cardValueColor",
    ("card", "labels", "fontsize"): "cardValueFontSize",
    ("card", "labels", "fontfamily"): "cardDataLabelsFontFamily",
    ("slicer", "layout", "rowcount"): "slicerRowCount",
    ("slicer", "layout", "columncount"): "slicerColumnCount",
    ("slicer", "layout", "style"): "slicerStyle",
    ("slicer", "layout", "orientation"): "slicerOrientation",
    ("slicer", "layout", "customizepadding"): "slicerCustomizePadding",
    ("slicer", "value", "horizontalalignment"): "slicerValueAlignment",
    ("slicer", "value", "fontsize"): "slicerValueFontSize",
    ("slicer", "overflow", "overflowstyle"): "slicerOverflowStyle",
    ("slicer", "overflow", "overflowdirection"): "slicerOverflowDirection",
    ("slicer", "padding", "paddingselection"): "slicerPaddingSelection",
    ("slicer", "padding", "topmargin"): "slicerPaddingTop",
    ("slicer", "padding", "bottommargin"): "slicerPaddingBottom",
    ("slicer", "fillcustom", "show"): "slicerFillCustomShow",
    ("slicer", "image", "imagefit"): "slicerImageFit",
    ("slicer", "image", "padding"): "slicerImagePadding",
    ("slicer", "image", "setasbackground"): "slicerImageAsBackground",
    ("slicer", "image", "ignorepadding"): "slicerImageIgnorePadding",
    ("slicer", "image", "position"): "slicerImagePosition",
    ("slicer", "image", "saturation"): "slicerImageSaturation",
    ("slicer", "shapecustomrectangle", "tileshape"): "slicerTileShape",
    ("slicer", "shapecustomrectangle", "rectangleroundedcurve"): "slicerRoundedCurve",
    ("slicer", "shapecustomrectangle", "rectangleroundedcurvecustomstyle"): "slicerRoundedCurveCustom",
}

_NATIVE_VISUAL_FORMAT_KEYS = {
    "background_show",
    "border_show",
    "border_width",
    "visualBorderRadius",
    "visualHeaderFontSize",
    "titleColor",
    "titleAlign",
    "showVisualHeader",
    "showSubtitle",
    "subtitle",
    "drop_shadow.show",
    "drop_shadow.preset",
    "drop_shadow.shadowBlur",
    "drop_shadow.shadowDistance",
    "drop_shadow.shadowSpread",
    "drop_shadow.transparency",
    "drop_shadow.shadowColor",
    "padding.top",
    "padding.right",
    "padding.bottom",
    "padding.left",
    "cardDataLabelsFontFamily",
    "cardDataLabelsFontSize",
    "seriesOrderReversed",
    "seriesOrderSorted",
    "seriesLabelsShow",
    "clusteredGapOverlapReverse",
}

_RESOLVED_SETTING_STATUSES = {
    "plotly_format_schema",
    "native_visual_format",
    "native_static_visual",
    "typed_sidecar",
    "summary_flag",
    "unsupported_visual_preserved",
}

_UNSUPPORTED_NATIVE_VISUAL_TYPES = {"decompositionTreeVisual", "keyDriversVisual", "ribbonChart"}

_TYPED_SURFACE_TARGETS: dict[str, str] = {
    "visualHeader": "visual_header",
    "visualAction": "visual_actions/static_content.action",
    "buttonAction": "visual_actions/static_content.action",
    "selection": "selection_state",
    "filter": "filters/visual filters",
    "tooltip": "tooltip",
    "slicerState": "slicer_state/reports/slicers.yaml",
    "selectorFormatting": "format.datapoint_selectors",
    "conditionalFormatting": "conditional_formatting/matrix formatting",
    "tableMatrixFormat": "table_matrix_format",
    "staticAsset": "static_asset/static_content",
    "resource": "static_resources",
}


def promote_documentation_format_properties(
    properties: list[dict[str, Any]],
    *,
    pbi_visual_type: str,
) -> dict[str, Any]:
    """Return native format keys plus preservation rows for workbook properties."""

    if not properties:
        return {}
    native_visual_type = _native_visual_type(pbi_visual_type)
    out: dict[str, Any] = {"documentation_properties": list(properties)}
    rows: list[dict[str, Any]] = []

    for prop in properties:
        group = _to_text(prop.get("group"))
        name = _to_text(prop.get("property"))
        value = _json_safe(prop.get("value"))
        selector = _to_text(prop.get("selector"))
        classification = _classify_setting(
            surface=_surface_for_property_group(group, name),
            native_visual_type=native_visual_type,
            object_name=group,
            property_name=name,
            selector_kind="selector" if selector else "static",
        )
        target_key = classification["plotly_key"]
        status = classification["status"]
        reason = classification["reason"]
        if status in {"plotly_format_schema", "native_visual_format"} and target_key and "." not in target_key:
            out.setdefault(target_key, _convert_format_value(group, name, value))
        rows.append(
            {
                "object_name": group,
                "property_name": name,
                "selector": selector,
                "status": status,
                "native_visual_type": native_visual_type,
                "plotly_key": target_key or "",
                "reason": reason,
            }
        )

    out["documentation_format_crosswalk"] = _crosswalk_row_summary(rows)
    return out


def build_plotly_setting_crosswalk(parameters: Iterable[CanonicalVisualParameter]) -> dict[str, Any]:
    """Summarize workbook visual-setting rows by native Plotly/native target."""

    rows: list[dict[str, Any]] = []
    for parameter in parameters:
        row = _parameter_crosswalk_row(parameter)
        if row:
            rows.append(row)
    return _crosswalk_row_summary(rows, include_rows=True)


def format_key_for_visual_property(object_name: str, property_name: str, native_visual_type: str = "") -> str:
    visual_key = _VISUAL_SPECIFIC_FORMAT_KEY_MAP.get(
        (_normalize_token(native_visual_type), _normalize_token(object_name), _normalize_token(property_name))
    )
    if visual_key:
        return visual_key
    group = _canonical_group(object_name)
    prop = _canonical_property(property_name)
    return _FORMAT_KEY_MAP.get((group, prop), "")


def format_key_applies_to_visual(format_key: str, native_visual_type: str) -> bool:
    schema = _format_schema()
    entry = schema.get(format_key)
    if not entry:
        return False
    applies_to = entry.get("applies_to")
    if not applies_to:
        return True
    return native_visual_type in {str(item) for item in applies_to}


def native_format_key_applies_to_visual(format_key: str, native_visual_type: str) -> bool:
    if format_key_applies_to_visual(format_key, native_visual_type):
        return True
    return format_key in _NATIVE_VISUAL_FORMAT_KEYS


def _parameter_crosswalk_row(parameter: CanonicalVisualParameter) -> dict[str, Any] | None:
    if parameter.workbook_source_sheet != "Visual Properties" and parameter.surface not in {
        "format",
        "containerChrome",
        "visualHeader",
        "selectorFormatting",
        "conditionalFormatting",
        "analytics",
        "tableMatrixFormat",
    }:
        return None

    native_visual_type = _native_visual_type(parameter.visual_type)
    classification = _classify_setting(
        surface=parameter.surface,
        native_visual_type=native_visual_type,
        object_name=parameter.object_name,
        property_name=parameter.property_name,
        selector_kind=parameter.selector_kind,
        workbook_source_sheet=parameter.workbook_source_sheet,
    )

    return {
        "surface": parameter.surface,
        "visual_type": parameter.visual_type,
        "native_visual_type": native_visual_type,
        "object_name": parameter.object_name,
        "property_name": parameter.property_name,
        "selector_kind": parameter.selector_kind,
        "status": classification["status"],
        "plotly_key": classification["plotly_key"],
        "parameter_id": parameter.parameter_id,
        "reason": classification["reason"],
    }


def _crosswalk_row_summary(rows: list[dict[str, Any]], *, include_rows: bool = False) -> dict[str, Any]:
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    by_visual_type = Counter(str(row.get("native_visual_type") or "(unknown)") for row in rows)
    unresolved = [
        row for row in rows
        if row.get("status") not in _RESOLVED_SETTING_STATUSES
    ]
    matched_count = sum(status_counts.get(status, 0) for status in _RESOLVED_SETTING_STATUSES)
    summary: dict[str, Any] = {
        "total_setting_rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "by_native_visual_type": dict(sorted(by_visual_type.items())),
        "plotly_mapped_count": status_counts.get("plotly_format_schema", 0),
        "native_format_mapped_count": status_counts.get("native_visual_format", 0),
        "typed_sidecar_count": status_counts.get("typed_sidecar", 0),
        "native_static_visual_count": status_counts.get("native_static_visual", 0),
        "matched_count": matched_count,
        "unresolved_count": len(unresolved),
        "unresolved_top": _top_unresolved(unresolved),
    }
    if include_rows:
        summary["rows"] = rows[:500]
        summary["rows_truncated"] = len(rows) > 500
    return summary


def _classify_setting(
    *,
    surface: str,
    native_visual_type: str,
    object_name: str,
    property_name: str,
    selector_kind: str = "static",
    workbook_source_sheet: str = "",
) -> dict[str, str]:
    target_key = ""
    status = "sidecar_only"
    reason = ""
    surface = surface or "format"
    object_key = _canonical_group(object_name)
    property_key = _canonical_property(property_name)

    if native_visual_type in _UNSUPPORTED_NATIVE_VISUAL_TYPES:
        return {
            "status": "unsupported_visual_preserved",
            "plotly_key": "unsupported_visual",
            "reason": "unsupported Power BI visual family is preserved but has no native Dummy BI renderer yet",
        }

    if (
        surface == "format"
        and workbook_source_sheet == "Visual Containers"
        and object_key == "visualContainer"
        and property_key in {"HasLegend", "HasDataLabels", "HasSmallMultiple"}
    ):
        return {
            "status": "summary_flag",
            "plotly_key": "",
            "reason": "workbook summary flag, not a visual object setting",
        }

    if surface == "containerChrome":
        target_key = _CONTAINER_FORMAT_KEY_MAP.get(
            (_canonical_container_group(object_name), property_key),
            "",
        )
        if target_key:
            return {"status": "native_visual_format", "plotly_key": target_key, "reason": ""}
        return {
            "status": "typed_sidecar",
            "plotly_key": "container_format",
            "reason": "container property is preserved in the typed container_format sidecar",
        }

    if surface == "analytics":
        if "referenceline" in object_name.lower():
            target_key = "referenceLines"
            if format_key_applies_to_visual(target_key, native_visual_type):
                return {"status": "plotly_format_schema", "plotly_key": target_key, "reason": ""}
        if object_name.lower() == "trend":
            return {"status": "typed_sidecar", "plotly_key": "analytics/trendline", "reason": "trendline payload is preserved in analytics sidecar"}
        if object_name.lower() == "forecast":
            return {"status": "typed_sidecar", "plotly_key": "analytics/forecast", "reason": "forecast payload is preserved in analytics sidecar"}

    if surface == "conditionalFormatting":
        if _normalize_token(object_name) == "columnformatting":
            return {"status": "native_visual_format", "plotly_key": "matrixColumnFormatting", "reason": ""}
        if _normalize_token(object_name) == "values":
            return {"status": "native_visual_format", "plotly_key": "matrixValuesFormatting", "reason": ""}

    if surface == "tableMatrixFormat":
        target_key = format_key_for_visual_property(object_name, property_name, native_visual_type)
        if target_key and native_format_key_applies_to_visual(target_key, native_visual_type):
            status = "plotly_format_schema" if format_key_applies_to_visual(target_key, native_visual_type) else "native_visual_format"
            return {"status": status, "plotly_key": target_key, "reason": ""}
        return {
            "status": "typed_sidecar",
            "plotly_key": _TYPED_SURFACE_TARGETS[surface],
            "reason": "table/matrix property is preserved in table_matrix_format",
        }

    if surface in _TYPED_SURFACE_TARGETS and surface != "staticAsset":
        return {
            "status": "typed_sidecar",
            "plotly_key": _TYPED_SURFACE_TARGETS[surface],
            "reason": f"{surface} maps to a typed Dummy BI sidecar rather than a flat Plotly key",
        }

    if surface == "staticAsset":
        target_key = _static_visual_target(object_name, property_name, native_visual_type)
        return {
            "status": "native_static_visual" if target_key else "typed_sidecar",
            "plotly_key": target_key or _TYPED_SURFACE_TARGETS[surface],
            "reason": "" if target_key else "static asset payload is preserved in static_asset",
        }

    if surface == "format" and native_visual_type == "slicer" and object_key == "data" and property_key == "mode":
        return {
            "status": "typed_sidecar",
            "plotly_key": "slicer_state.mode/reports/slicers.yaml.type",
            "reason": "slicer mode maps to the unified slicer definition, not Plotly",
        }

    target_key = format_key_for_visual_property(object_name, property_name, native_visual_type)
    if selector_kind != "static":
        return {
            "status": "typed_sidecar",
            "plotly_key": "format.datapoint_selectors" if object_key == "dataPoint" else "selector-bound format sidecar",
            "reason": "selector-bound formatting needs selector sidecar preservation before safe flat promotion",
        }
    if target_key and format_key_applies_to_visual(target_key, native_visual_type):
        return {"status": "plotly_format_schema", "plotly_key": target_key, "reason": ""}
    if target_key and native_format_key_applies_to_visual(target_key, native_visual_type):
        return {"status": "native_visual_format", "plotly_key": target_key, "reason": ""}
    if target_key:
        return {
            "status": "schema_not_for_visual_family",
            "plotly_key": target_key,
            "reason": f"{target_key} is not declared for {native_visual_type}",
        }
    return {
        "status": "sidecar_only",
        "plotly_key": "",
        "reason": "no native Plotly/native visual key is registered for this object/property yet",
    }


def _top_unresolved(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = Counter(
        (
            str(row.get("surface") or ""),
            str(row.get("native_visual_type") or ""),
            str(row.get("object_name") or ""),
            str(row.get("property_name") or ""),
            str(row.get("status") or ""),
            str(row.get("reason") or ""),
        )
        for row in rows
    )
    return [
        {
            "surface": surface,
            "native_visual_type": native_visual_type,
            "object_name": object_name,
            "property_name": property_name,
            "status": status,
            "reason": reason,
            "count": count,
        }
        for (surface, native_visual_type, object_name, property_name, status, reason), count in sorted(
            grouped.items(),
            key=lambda item: (-item[1], item[0]),
        )[:25]
    ]


def _convert_format_value(group: str, property_name: str, value: Any) -> Any:
    prop = _canonical_property(property_name)
    if _canonical_group(group) == "labels" and prop in {"labelPosition", "position"}:
        text = _to_text(value)
        return _LABEL_POSITION_MAP.get(text, text.lower() if text else "auto")
    if _canonical_group(group) == "legend" and prop == "position":
        return _to_text(value).lower()
    if _canonical_group(group) == "layout" and prop == "clusteredGapSize":
        number = _numberish(value)
        if isinstance(number, (int, float)):
            return max(0.0, min(1.0, float(number) / 100.0))
    if _canonical_group(group) == "layout" and prop == "clusteredGapOverlaps":
        return "overlay" if _boolish(value) else "group"
    if prop in {"show", "showTitle", "showAxisTitle", "gridlines", "wordWrap", "autoSizeColumnWidth", "borderShow", "seriesOrderReversed", "seriesOrderSorted"}:
        return _boolish(value)
    if prop in {
        "fontSize",
        "labelPrecision",
        "transparency",
        "innerPadding",
        "labelAngle",
        "start",
        "end",
        "clusteredGapSize",
        "barWeight",
        "steppedLayoutIndentation",
        "outlineStyle",
    }:
        return _numberish(value)
    return _color_or_scalar(value)


def _color_or_scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        if value.get("color") is not None:
            return _to_text(value.get("color"))
        solid = value.get("solid")
        if isinstance(solid, Mapping):
            color = solid.get("color")
            if isinstance(color, Mapping):
                literal = color.get("Literal")
                if isinstance(literal, Mapping) and literal.get("Value") is not None:
                    return _to_text(literal.get("Value")).strip("'")
                if color.get("value") is not None:
                    return _to_text(color.get("value"))
            if color is not None:
                return _to_text(color)
    return value


def _format_schema() -> dict[str, dict[str, Any]]:
    try:
        from dax_ui.server._plotly import _FORMAT_SCHEMA  # type: ignore

        return _FORMAT_SCHEMA
    except Exception:
        return {}


def _surface_for_property_group(object_name: str, property_name: str) -> str:
    group_lower = _to_text(object_name).lower()
    prop_lower = _to_text(property_name).lower()
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
    if group_lower in {"columnformatting", "values"} or "databars" in prop_lower:
        return "conditionalFormatting"
    if group_lower in {"columnheaders", "rowheaders", "grid", "columnwidth", "overflow"}:
        return "tableMatrixFormat"
    if group_lower == "general" and prop_lower == "filter.filter":
        return "filter"
    if group_lower in {"shape", "shapecustomrectangle", "icon", "image", "rotation"}:
        return "staticAsset"
    if group_lower == "general" and prop_lower == "paragraphs":
        return "staticAsset"
    return "format"


def _static_visual_target(object_name: str, property_name: str, native_visual_type: str) -> str:
    visual = _normalize_token(native_visual_type)
    group = _normalize_token(object_name)
    prop = _normalize_token(property_name)
    if visual == "textbox" and group == "general" and prop == "paragraphs":
        return "static_content.text"
    if visual in {"shape", "slicer"} and group in {"shape", "shapecustomrectangle"} and prop == "tileshape":
        return "static_content.shapeType"
    if visual == "button" and group == "icon" and prop == "shapetype":
        return "static_content.buttonType"
    if visual == "image" and group == "image" and prop in {"sourcefilename", "sourcefileurl", "sourcefilescaling"}:
        return "static_resources/static_content"
    return ""


def _native_visual_type(pbi_visual_type: str) -> str:
    raw = _to_text(pbi_visual_type)
    return _DOC_VISUAL_TYPE_OVERRIDES.get(raw, _map_visual_type(raw))


def _canonical_group(value: str) -> str:
    text = _to_text(value)
    for known in {
        "legend",
        "labels",
        "categoryLabels",
        "categoryAxis",
        "valueAxis",
        "plotArea",
        "layout",
        "dataPoint",
        "dataLabels",
        "lineStyles",
        "seriesLabels",
        "card",
        "rowHeaders",
        "grid",
        "columnHeaders",
        "columnWidth",
        "general",
        "shape",
        "outline",
        "fill",
        "data",
        "fillCustom",
        "padding",
        "value",
        "image",
        "shapeCustomRectangle",
        "overFlow",
    }:
        if _normalize_token(text) == _normalize_token(known):
            return known
    return text


def _canonical_container_group(value: str) -> str:
    text = _to_text(value)
    if not text.lower().startswith("vc:"):
        return text
    return "vc:" + _canonical_property(text.split(":", 1)[1])


def _canonical_property(value: str) -> str:
    text = _to_text(value)
    aliases = {
        "font_size": "fontSize",
        "fontfamily": "fontFamily",
        "font_family": "fontFamily",
        "fontcolor": "fontColor",
        "font_color": "fontColor",
        "labelposition": "labelPosition",
        "label_position": "labelPosition",
        "labeldisplayunits": "labelDisplayUnits",
        "label_display_units": "labelDisplayUnits",
        "labelprecision": "labelPrecision",
        "label_precision": "labelPrecision",
        "showtitle": "showTitle",
        "show_title": "showTitle",
        "showaxistitle": "showAxisTitle",
        "show_axis_title": "showAxisTitle",
        "axistype": "axisType",
        "axis_type": "axisType",
        "innerpadding": "innerPadding",
        "inner_padding": "innerPadding",
        "titletext": "titleText",
        "title_text": "titleText",
        "labelangle": "labelAngle",
        "label_angle": "labelAngle",
        "gridlinecolor": "gridlineColor",
        "gridline_color": "gridlineColor",
        "clusteredgapsize": "clusteredGapSize",
        "clustered_gap_size": "clusteredGapSize",
        "clusteredgapoverlaps": "clusteredGapOverlaps",
        "clustered_gap_overlaps": "clusteredGapOverlaps",
        "bordershow": "borderShow",
        "border_show": "borderShow",
        "barcolor": "barColor",
        "bar_color": "barColor",
        "barweight": "barWeight",
        "bar_weight": "barWeight",
        "steppedlayoutindentation": "steppedLayoutIndentation",
        "stepped_layout_indentation": "steppedLayoutIndentation",
        "gridhorizontal": "gridHorizontal",
        "grid_horizontal": "gridHorizontal",
        "backcolor": "backColor",
        "back_color": "backColor",
        "wordwrap": "wordWrap",
        "word_wrap": "wordWrap",
        "outlinestyle": "outlineStyle",
        "outline_style": "outlineStyle",
        "autosizecolumnwidth": "autoSizeColumnWidth",
        "auto_size_column_width": "autoSizeColumnWidth",
        "showgradientlegend": "showGradientLegend",
        "show_gradient_legend": "showGradientLegend",
        "clusteredgapoverlapreverse": "clusteredGapOverlapReverse",
        "clustered_gap_overlap_reverse": "clusteredGapOverlapReverse",
        "seriesorderreversed": "seriesOrderReversed",
        "series_order_reversed": "seriesOrderReversed",
        "seriesordersorted": "seriesOrderSorted",
        "series_order_sorted": "seriesOrderSorted",
        "areashow": "areaShow",
        "area_show": "areaShow",
        "linecolor": "lineColor",
        "line_color": "lineColor",
        "fillcolor": "fillColor",
        "fill_color": "fillColor",
        "rowcount": "rowCount",
        "row_count": "rowCount",
        "columncount": "columnCount",
        "column_count": "columnCount",
        "customizepadding": "customizePadding",
        "customize_padding": "customizePadding",
        "horizontalalignment": "horizontalAlignment",
        "horizontal_alignment": "horizontalAlignment",
        "overflowstyle": "overFlowStyle",
        "over_flow_style": "overFlowStyle",
        "overflowdirection": "overFlowDirection",
        "over_flow_direction": "overFlowDirection",
        "paddingselection": "paddingSelection",
        "padding_selection": "paddingSelection",
        "topmargin": "topMargin",
        "top_margin": "topMargin",
        "bottommargin": "bottomMargin",
        "bottom_margin": "bottomMargin",
        "ignorepadding": "ignorePadding",
        "ignore_padding": "ignorePadding",
        "imagefit": "imageFit",
        "image_fit": "imageFit",
        "setasbackground": "setAsBackGround",
        "set_as_back_ground": "setAsBackGround",
        "tileshape": "tileShape",
        "tile_shape": "tileShape",
        "rectangleroundedcurve": "rectangleRoundedCurve",
        "rectangle_rounded_curve": "rectangleRoundedCurve",
        "rectangleroundedcurvecustomstyle": "rectangleRoundedCurveCustomStyle",
        "rectangle_rounded_curve_custom_style": "rectangleRoundedCurveCustomStyle",
        "shapetype": "shapeType",
        "shape_type": "shapeType",
        "shapeangle": "shapeAngle",
        "shape_angle": "shapeAngle",
        "hassmallmultiple": "HasSmallMultiple",
        "has_small_multiple": "HasSmallMultiple",
        "haslegend": "HasLegend",
        "has_legend": "HasLegend",
        "hasdatalabels": "HasDataLabels",
        "has_data_labels": "HasDataLabels",
    }
    return aliases.get(_normalize_token(text), text)


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _to_text(value).lower())


def _boolish(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    text = _to_text(value).lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return value


def _numberish(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = _to_text(value)
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return value


def _json_safe(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text
