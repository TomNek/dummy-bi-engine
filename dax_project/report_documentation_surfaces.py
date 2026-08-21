"""Surface writers for Report_Documentation.xlsx imports.

The parameter catalogue is the ledger. This module turns catalogued workbook rows
into typed Dummy BI sidecars so workbook-backed Power BI features are preserved
without adding large inline branches to the canonical importer.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping, MutableMapping

from dax_project.report_documentation_parameters import CanonicalVisualParameter


def apply_visual_surface_sidecars(
    native_visual: MutableMapping[str, Any],
    parameters: Iterable[CanonicalVisualParameter],
    *,
    source_page_to_native: Mapping[str, str] | None = None,
) -> None:
    """Attach typed visual sidecars derived from workbook parameter rows."""

    parameter_list = list(parameters)
    if not parameter_list:
        return
    page_lookup = source_page_to_native or {}
    by_surface = _group_by_surface(parameter_list)

    if query_parameters := by_surface.get("queryOptions"):
        native_visual["query_options"] = _query_options_payload(query_parameters)
    if header_parameters := by_surface.get("visualHeader"):
        native_visual["visual_header"] = _visual_header_payload(header_parameters)
    action_parameters = [*by_surface.get("visualAction", []), *by_surface.get("buttonAction", [])]
    if action_parameters:
        native_visual["visual_actions"] = _visual_actions_payload(action_parameters)
    if container_parameters := by_surface.get("containerChrome"):
        native_visual["container_format"] = _object_payload(container_parameters)
    if tooltip_parameters := by_surface.get("tooltip"):
        _apply_tooltip_payload(native_visual, tooltip_parameters, page_lookup)
    if selection_parameters := by_surface.get("selection"):
        native_visual["selection_state"] = _property_payload(selection_parameters)
    if slicer_parameters := by_surface.get("slicerState"):
        slicer_state = _property_payload(slicer_parameters)
        native_visual["slicer_state"] = slicer_state
        sync_group = slicer_state.get("sync_group_name")
        if sync_group:
            native_visual["slicer_sync_group"] = sync_group
    if static_parameters := by_surface.get("staticAsset"):
        native_visual["static_asset"] = _static_asset_payload(static_parameters, native_visual.get("visual_type"))
    if resource_parameters := by_surface.get("resource"):
        native_visual["static_resources"] = _resources_payload(resource_parameters)
    if analytics_parameters := by_surface.get("analytics"):
        native_visual["analytics"] = _object_rows_payload(analytics_parameters)
    if conditional_parameters := by_surface.get("conditionalFormatting"):
        native_visual["conditional_formatting"] = _object_rows_payload(conditional_parameters)
    if table_matrix_parameters := by_surface.get("tableMatrixFormat"):
        native_visual["table_matrix_format"] = _object_payload(table_matrix_parameters)
    if visual_calc_parameters := by_surface.get("visualCalculation"):
        existing_calcs = native_visual.get("native_calcs")
        if not isinstance(existing_calcs, list):
            existing_calcs = []
        existing_calcs.append(
            {
                "status": "requires_powerbi_tool_extraction",
                "unsupported_reason": "Report_Documentation.xlsx currently exposes only visual-calculation presence flags, not expression text or axis/reset/order metadata.",
                "source_parameters": _source_refs(visual_calc_parameters),
            }
        )
        native_visual["native_calcs"] = existing_calcs
    _sync_visual_format(native_visual)
    _sync_static_content(native_visual)


def apply_page_surface_sidecars(
    pages: list[MutableMapping[str, Any]],
    parameters: Iterable[CanonicalVisualParameter],
    *,
    source_page_to_native: Mapping[str, str],
) -> None:
    """Attach page/drillthrough sidecars to pages.yaml payload entries."""

    pages_by_id = {str(page.get("id")): page for page in pages if isinstance(page, MutableMapping)}
    grouped: dict[tuple[str, str], list[CanonicalVisualParameter]] = defaultdict(list)
    for parameter in parameters:
        if parameter.visual_id or parameter.surface not in {"page", "drillthrough"}:
            continue
        native_page_id = _lookup_page_id(parameter, source_page_to_native)
        if native_page_id:
            grouped[(native_page_id, parameter.surface)].append(parameter)

    for (native_page_id, surface), surface_parameters in grouped.items():
        page = pages_by_id.get(native_page_id)
        if page is None:
            continue
        if surface == "drillthrough":
            page["drillthrough"] = _property_payload(surface_parameters)
        else:
            page["page_format"] = _property_payload(surface_parameters)


def build_report_sidecars(parameters: Iterable[CanonicalVisualParameter]) -> dict[str, Any]:
    """Return report-level diagnostics/settings preserved outside render state."""

    by_surface = _group_by_surface(parameters)
    sidecars: dict[str, Any] = {}
    if settings := by_surface.get("reportSetting"):
        sidecars["report_settings"] = _property_payload(settings)
    if diagnostics := by_surface.get("health"):
        sidecars["diagnostics"] = _object_rows_payload(diagnostics)
    return sidecars


def _group_by_surface(parameters: Iterable[CanonicalVisualParameter]) -> dict[str, list[CanonicalVisualParameter]]:
    grouped: dict[str, list[CanonicalVisualParameter]] = defaultdict(list)
    for parameter in parameters:
        grouped[parameter.surface].append(parameter)
    return grouped


def _query_options_payload(parameters: list[CanonicalVisualParameter]) -> dict[str, Any]:
    payload = _property_payload(parameters)
    top_n: dict[str, Any] = {}
    data_reduction: dict[str, Any] = {}
    sort: dict[str, Any] = {}
    for parameter in parameters:
        name = parameter.property_name
        value = _json_safe(parameter.example_value)
        if name == "TopNCount":
            top_n["count"] = value
        elif name == "TopNDirection":
            top_n["direction"] = value
        elif name == "TopNOrderField":
            top_n["order_field"] = value
        elif name.startswith("DataReduction"):
            data_reduction[_snake(name.removeprefix("DataReduction"))] = value
        elif name.startswith("Sort"):
            sort[_snake(name.removeprefix("Sort"))] = value
        elif name == "ShowItemsWithNoData":
            payload["show_items_with_no_data"] = _boolish(value)
    if top_n:
        payload["top_n"] = top_n
    if data_reduction:
        payload["data_reduction"] = data_reduction
    if sort:
        payload["sort"] = sort
    return payload


def _visual_header_payload(parameters: list[CanonicalVisualParameter]) -> dict[str, Any]:
    payload = _object_payload(parameters)
    icons: dict[str, Any] = {}
    for parameter in parameters:
        value = _json_safe(parameter.example_value)
        if parameter.property_name == "VisualHeaderIcons":
            for token in _split_tokens(value):
                icons[token] = True
        elif parameter.object_name.lower() == "vc:visualheader" and parameter.property_name:
            icons[parameter.property_name] = _boolish(value)
    if icons:
        payload["icons"] = icons
    return payload


def _visual_actions_payload(parameters: list[CanonicalVisualParameter]) -> list[dict[str, Any]]:
    properties = _property_payload(parameters)
    action_type_raw = _to_text(properties.get("action_type") or properties.get("type"))
    action_type = action_type_raw
    bookmark_target = properties.get("bookmark_target") or properties.get("bookmark")
    page_target = (
        properties.get("page")
        or properties.get("page_target")
        or properties.get("destination_page")
        or properties.get("drillthrough_page")
    )
    url_target = properties.get("url") or properties.get("web_url")
    target: dict[str, Any] = {}
    normalized = action_type_raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    if bookmark_target:
        target = {"type": "bookmark", "id": bookmark_target}
        action_type = action_type or "bookmark"
    elif normalized in {"drillthrough", "drill"} and page_target:
        target = {"type": "drillthrough", "id": page_target}
        action_type = "drillthrough"
    elif page_target:
        target = {"type": "page", "id": page_target}
        action_type = action_type or "pageNavigation"
    elif url_target:
        target = {"type": "url", "url": url_target}
        action_type = action_type or "webUrl"
    elif normalized in {"back", "navigateback"}:
        action_type = "back"
    elif normalized in {"applyallslicers", "applyslicers"}:
        action_type = "applyAllSlicers"
    elif normalized in {"clearallslicers", "clearslicers", "resetslicers"}:
        action_type = "clearAllSlicers"
    return [
        {
            "type": action_type or "unknown",
            "target": target,
            "properties": {key: value for key, value in properties.items() if key != "source_parameters"},
            "source_parameters": properties.get("source_parameters", []),
        }
    ]


def _apply_tooltip_payload(
    native_visual: MutableMapping[str, Any],
    parameters: list[CanonicalVisualParameter],
    source_page_to_native: Mapping[str, str],
) -> None:
    payload = _property_payload(parameters)
    page_id = payload.get("custom_tooltip_page_id") or payload.get("page_id") or payload.get("tooltip_page_id")
    if page_id:
        source_page_id = _to_text(page_id)
        native_page_id = source_page_to_native.get(source_page_id) or source_page_id
        native_visual["tooltip_page_id"] = native_page_id
        payload["source_page_id"] = source_page_id
        payload["page_id"] = native_page_id
    native_visual["tooltip"] = payload


def _static_asset_payload(parameters: list[CanonicalVisualParameter], visual_type: Any) -> dict[str, Any]:
    payload = _object_payload(parameters)
    properties = {
        key: value
        for key, value in payload.items()
        if key not in {"source_parameters", "objects", "properties"}
    }
    payload["properties"] = properties
    text = properties.get("text") or properties.get("plain_text")
    paragraphs = properties.get("paragraphs")
    if paragraphs:
        parsed_paragraphs = _parse_jsonish(paragraphs)
        payload["paragraphs"] = parsed_paragraphs
        properties["paragraphs"] = parsed_paragraphs
    if text:
        payload["text"] = text
    if visual_type:
        payload["visual_type"] = _to_text(visual_type)
    return payload


def _resources_payload(parameters: list[CanonicalVisualParameter]) -> list[dict[str, Any]]:
    properties = _property_payload(parameters)
    return [
        {
            "name": properties.get("image_name") or properties.get("name"),
            "resource": properties.get("image_resource") or properties.get("resource"),
            "scaling": properties.get("image_scaling") or properties.get("scaling"),
            "properties": {key: value for key, value in properties.items() if key != "source_parameters"},
            "source_parameters": properties.get("source_parameters", []),
        }
    ]


def _sync_visual_format(native_visual: MutableMapping[str, Any]) -> None:
    container_format = native_visual.get("container_format")
    if not isinstance(container_format, Mapping):
        return
    objects = container_format.get("objects")
    if not isinstance(objects, Mapping):
        return

    visual_format = dict(native_visual.get("format") or {})
    for object_name, properties in objects.items():
        if not isinstance(properties, Mapping):
            continue
        normalized = _to_text(object_name).lower().removeprefix("vc:")
        if normalized in {"background", "visualbackground"}:
            _copy_bool(properties, visual_format, "show", "background_show")
            if color := _color_value(properties.get("color") or properties.get("fill") or properties.get("background_color")):
                visual_format["backgroundColor"] = color
        elif normalized in {"border", "outline"}:
            _copy_bool(properties, visual_format, "show", "border_show")
            if color := _color_value(properties.get("color") or properties.get("border_color")):
                visual_format["borderColor"] = color
            _copy_number(properties, visual_format, ("width", "weight", "border_width"), "border_width")
            _copy_number(properties, visual_format, ("radius", "border_radius"), "visualBorderRadius")
        elif normalized in {"title", "visualtitle"}:
            _copy_bool(properties, visual_format, "show", "showTitle")
            if text := properties.get("text") or properties.get("title"):
                visual_format["title"] = _to_text(text)
            _copy_number(properties, visual_format, ("font_size", "fontSize", "text_size"), "visualHeaderFontSize")
            # F3: promote title text styling so React VisualCard can render it.
            if color := _color_value(properties.get("color") or properties.get("font_color") or properties.get("text_color")):
                visual_format["titleColor"] = color
            if align := _to_text(properties.get("alignment") or properties.get("align") or properties.get("text_align")):
                visual_format["titleAlign"] = align.lower()
            if properties.get("bold") is not None or properties.get("font_weight") is not None:
                weight = properties.get("font_weight")
                if weight is None:
                    weight = "bold" if _boolish(properties.get("bold")) else "normal"
                visual_format["titleFontWeight"] = _to_text(weight)
            if properties.get("italic") is not None or properties.get("font_style") is not None:
                style = properties.get("font_style")
                if style is None:
                    style = "italic" if _boolish(properties.get("italic")) else "normal"
                visual_format["titleFontStyle"] = _to_text(style)
        elif normalized in {"subtitle", "subTitle".lower(), "visualsubtitle"}:
            _copy_bool(properties, visual_format, "show", "showSubtitle")
            if text := properties.get("text") or properties.get("title") or properties.get("subtitle"):
                native_visual["subtitle"] = _to_text(text)
        elif normalized in {"visualheader", "header"}:
            _copy_bool(properties, visual_format, "show", "showVisualHeader")
        elif normalized in {"dropshadow", "shadow"}:
            # F3: normalize workbook keys to the camelCase keys React VisualCard reads.
            visual_format["drop_shadow"] = _normalize_drop_shadow(properties)
        elif normalized == "padding":
            visual_format["padding"] = {
                key: _json_safe(properties[key])
                for key in ("top", "right", "bottom", "left")
                if key in properties
            }
    if visual_format:
        native_visual["format"] = visual_format


def _copy_bool(source: Mapping[str, Any], target: MutableMapping[str, Any], source_key: str, target_key: str) -> None:
    if source_key in source:
        target[target_key] = _boolish(source.get(source_key))


def _copy_number(source: Mapping[str, Any], target: MutableMapping[str, Any], source_keys: tuple[str, ...], target_key: str) -> None:
    for source_key in source_keys:
        if source_key not in source:
            continue
        value = source.get(source_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[target_key] = value
            return
        text = _to_text(value)
        if not text:
            continue
        try:
            target[target_key] = float(text) if "." in text else int(text)
            return
        except ValueError:
            continue


def _color_value(value: Any) -> str:
    if isinstance(value, Mapping):
        if value.get("color"):
            return _to_text(value.get("color"))
        solid = value.get("solid")
        if isinstance(solid, Mapping) and solid.get("color"):
            return _to_text(solid.get("color"))
    return _to_text(value)


_DROP_SHADOW_KEY_MAP: dict[str, str] = {
    "show": "show",
    "color": "shadowColor",
    "shadow_color": "shadowColor",
    "blur": "shadowBlur",
    "shadow_blur": "shadowBlur",
    "distance": "shadowDistance",
    "shadow_distance": "shadowDistance",
    "offset": "shadowDistance",
    "spread": "shadowSpread",
    "shadow_spread": "shadowSpread",
    "transparency": "transparency",
    "opacity": "transparency",
}


def _normalize_drop_shadow(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Map workbook drop-shadow keys to the camelCase keys React VisualCard reads."""
    out: dict[str, Any] = {}
    for raw_key, raw_value in properties.items():
        key = _to_text(raw_key).lower()
        if not key:
            continue
        target = _DROP_SHADOW_KEY_MAP.get(key)
        if target == "shadowColor":
            color = _color_value(raw_value)
            if color:
                out[target] = color
        elif target == "show":
            out[target] = _boolish(raw_value)
        elif target:
            value = _json_safe(raw_value)
            if value is None:
                continue
            try:
                text = str(value)
                out[target] = float(text) if "." in text else int(text)
            except (TypeError, ValueError):
                out[target] = value
    return out


def _sync_static_content(native_visual: MutableMapping[str, Any]) -> None:
    visual_type = _to_text(native_visual.get("visual_type")).lower()
    if visual_type not in {"textbox", "button", "shape", "image"}:
        return

    content = dict(native_visual.get("static_content") or {})
    static_asset = native_visual.get("static_asset")
    asset_properties = static_asset.get("properties") if isinstance(static_asset, Mapping) else {}
    if not isinstance(asset_properties, Mapping):
        asset_properties = {}

    if visual_type == "textbox":
        text = asset_properties.get("text") or _paragraph_text(static_asset.get("paragraphs") if isinstance(static_asset, Mapping) else None)
        if text:
            content.setdefault("text", text)
        content.setdefault("backgroundColor", "transparent")
    elif visual_type == "button":
        label = asset_properties.get("text") or asset_properties.get("label") or asset_properties.get("title")
        if label:
            content.setdefault("label", label)
        button_type = _button_type(asset_properties.get("icon_type") or asset_properties.get("shape_type"))
        if button_type:
            content.setdefault("buttonType", button_type)
        content.setdefault("style", "default")
    elif visual_type == "shape":
        shape_type = _shape_type(asset_properties.get("shape_type") or asset_properties.get("tile_shape") or asset_properties.get("icon_type"))
        if shape_type:
            content.setdefault("shapeType", shape_type)
        content.setdefault("opacity", 1.0)
    elif visual_type == "image":
        resources = native_visual.get("static_resources")
        first_resource = resources[0] if isinstance(resources, list) and resources else {}
        if isinstance(first_resource, Mapping):
            if first_resource.get("name"):
                content.setdefault("alt", first_resource.get("name"))
            if first_resource.get("scaling"):
                content.setdefault("fit", str(first_resource.get("scaling")).lower())

    action = _static_action(native_visual.get("visual_actions"))
    if action and visual_type in {"button", "shape", "textbox", "image"}:
        content["action"] = action
    if content:
        native_visual["static_content"] = content


def _static_action(actions: Any) -> dict[str, str] | None:
    if not isinstance(actions, list) or not actions:
        return None
    action = actions[0]
    if not isinstance(action, Mapping):
        return None
    target = action.get("target")
    if isinstance(target, Mapping):
        target_type = _to_text(target.get("type")).lower()
        if target_type == "bookmark" and target.get("id"):
            return {"type": "bookmark", "target": _to_text(target.get("id"))}
        if target_type in {"page", "pagenavigation"} and target.get("id"):
            return {"type": "page", "target": _to_text(target.get("id"))}
        if target_type == "drillthrough" and target.get("id"):
            return {"type": "drillthrough", "target": _to_text(target.get("id"))}
        if target_type in {"url", "weburl"} and target.get("url"):
            return {"type": "url", "target": _to_text(target.get("url"))}
    action_type_raw = _to_text(action.get("type"))
    action_type = action_type_raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    properties = action.get("properties") if isinstance(action.get("properties"), Mapping) else {}
    if action_type == "bookmark" and properties.get("bookmark_target"):
        return {"type": "bookmark", "target": _to_text(properties.get("bookmark_target"))}
    if action_type in {"back", "navigateback"}:
        return {"type": "back"}
    if action_type in {"applyallslicers", "applyslicers"}:
        return {"type": "apply-all-slicers"}
    if action_type in {"clearallslicers", "clearslicers", "resetslicers"}:
        return {"type": "clear-all-slicers"}
    if action_type in {"drillthrough", "drill"}:
        target_id = properties.get("drillthrough_page") or properties.get("page") or properties.get("destination_page")
        if target_id:
            return {"type": "drillthrough", "target": _to_text(target_id)}
        return {"type": "drillthrough"}
    return None


def _paragraph_text(paragraphs: Any) -> str:
    if isinstance(paragraphs, str):
        parsed = _parse_jsonish(paragraphs)
        if isinstance(parsed, str):
            return parsed.strip()
        return _paragraph_text(parsed)
    if not isinstance(paragraphs, list):
        return ""
    lines: list[str] = []
    for paragraph in paragraphs:
        if isinstance(paragraph, Mapping):
            if paragraph.get("text"):
                lines.append(_to_text(paragraph.get("text")))
            elif isinstance(paragraph.get("text_runs"), list):
                lines.append("".join(_to_text(run.get("value")) for run in paragraph["text_runs"] if isinstance(run, Mapping)))
    return "\n".join(line for line in lines if line)


def _button_type(value: Any) -> str:
    raw = _to_text(value)
    normalized = _shape_type(raw)
    aliases = {
        "rightArrow": "right-arrow",
        "leftArrow": "left-arrow",
        "back": "back",
        "bookmark": "bookmark",
        "information": "information",
        "help": "help",
        "reset": "reset",
    }
    return aliases.get(raw, normalized)


def _shape_type(value: Any) -> str:
    raw = _to_text(value)
    aliases = {
        "rightArrow": "arrow-right",
        "leftArrow": "arrow-left",
        "upArrow": "arrow-up",
        "downArrow": "arrow-down",
        "roundedRectangle": "rounded-rectangle",
    }
    return aliases.get(raw, raw)


def _property_payload(parameters: list[CanonicalVisualParameter]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for parameter in parameters:
        key = _snake(parameter.property_name or parameter.object_name)
        if not key:
            continue
        _put_value(payload, key, _json_safe(parameter.example_value))
    payload["source_parameters"] = _source_refs(parameters)
    return payload


def _object_payload(parameters: list[CanonicalVisualParameter]) -> dict[str, Any]:
    payload = _property_payload(parameters)
    objects: dict[str, dict[str, Any]] = {}
    for parameter in parameters:
        object_name = parameter.object_name or "object"
        property_name = _snake(parameter.property_name or "value") or "value"
        objects.setdefault(object_name, {})[property_name] = _json_safe(parameter.example_value)
    if objects:
        payload["objects"] = objects
    return payload


def _object_rows_payload(parameters: list[CanonicalVisualParameter]) -> list[dict[str, Any]]:
    return [
        {
            "object_name": parameter.object_name,
            "property_name": parameter.property_name,
            "selector_kind": parameter.selector_kind,
            "value": _json_safe(parameter.example_value),
            "source_parameter": _source_ref(parameter),
        }
        for parameter in parameters
    ]


def _source_refs(parameters: Iterable[CanonicalVisualParameter]) -> list[dict[str, Any]]:
    return [_source_ref(parameter) for parameter in parameters]


def _source_ref(parameter: CanonicalVisualParameter) -> dict[str, Any]:
    return {
        "parameter_id": parameter.parameter_id,
        "surface": parameter.surface,
        "workbook_source_sheet": parameter.workbook_source_sheet,
        "json_pointer": parameter.json_pointer,
        "object_name": parameter.object_name,
        "property_name": parameter.property_name,
        "example_value": _json_safe(parameter.example_value),
    }


def _lookup_page_id(parameter: CanonicalVisualParameter, source_page_to_native: Mapping[str, str]) -> str:
    for candidate in (parameter.page_id, parameter.page):
        if candidate and candidate in source_page_to_native:
            return source_page_to_native[candidate]
    return ""


def _put_value(payload: dict[str, Any], key: str, value: Any) -> None:
    if key not in payload:
        payload[key] = value
        return
    existing = payload[key]
    if isinstance(existing, list):
        existing.append(value)
    else:
        payload[key] = [existing, value]


def _split_tokens(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_to_text(item) for item in value if _to_text(item)]
    text = _to_text(value)
    if not text:
        return []
    return [token.strip() for token in re.split(r"[,;|]", text) if token.strip()]


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return _json_safe(value)
    text = value.strip()
    if not text:
        return ""
    if text[0] not in "[{\"":
        return text
    try:
        return json.loads(text)
    except Exception:
        return text


def _snake(value: str) -> str:
    text = _to_text(value)
    if not text:
        return ""
    text = text.replace(":", "_").replace(".", "_")
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_").lower()


def _boolish(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    text = _to_text(value).lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return _json_safe(value)


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
