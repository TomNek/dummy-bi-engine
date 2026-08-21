"""Canonical report import from PowerBI_Tool Report_Documentation.xlsx.

PowerBI_Tool remains the authoritative writer for the documentation workbook.
This module treats that workbook as the report interchange artifact, builds a
typed canonical view from its sheets, and emits this project's native report
artifacts for rendering.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

import yaml

from dax_project.report_documentation_parameters import (
    CanonicalVisualParameter,
    build_documentation_parameter_catalogue_from_sheets,
    parameters_to_dicts,
    summarize_parameter_coverage,
)
from dax_project.report_documentation_format_crosswalk import (
    build_plotly_setting_crosswalk,
    promote_documentation_format_properties,
)
from dax_project.report_documentation_surfaces import (
    apply_page_surface_sidecars,
    apply_visual_surface_sidecars,
    build_report_sidecars,
)
from dax_project.report_transfer import _VISUAL_TYPE_MAP, _map_encoding_role, _map_visual_type
from dax_project.save import save_slicers


_DOC_VISUAL_TYPE_MAP: dict[str, str] = {
    "cardVisual": "card",
    "listSlicer": "slicer",
    "textSlicer": "slicer",
    "columnChart": "column",
    "hundredPercentStackedAreaChart": "area",
}


def _load_native_visual_types() -> set[str]:
    registry_path = Path(__file__).with_name("visual_types.yaml")
    try:
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return set()
    visual_types = registry.get("visual_types") if isinstance(registry, Mapping) else None
    if isinstance(visual_types, Mapping):
        return {str(name) for name in visual_types.keys()}
    return set()


_NATIVE_VISUAL_TYPES = _load_native_visual_types()


@dataclass(frozen=True)
class CanonicalFieldRef:
    kind: str
    table: str = ""
    field: str = ""
    display_name: str = ""
    aggregation: str = ""
    is_field_parameter: bool = False
    source: dict[str, Any] = dc_field(default_factory=dict)

    def to_native_expr(self) -> Optional[dict[str, Any]]:
        if self.kind == "measure" and self.field:
            out: dict[str, Any] = {"type": "MeasureRef", "name": self.field}
            if self.table:
                out["table"] = self.table
            return out
        if self.kind == "column" and self.table and self.field:
            return {"type": "ColumnRef", "table": self.table, "column": self.field}
        if self.kind == "hierarchy" and self.field:
            return {"type": "HierarchyRef", "name": self.field}
        if self.kind == "field_parameter":
            name = self.table or self.field
            if name:
                return {"type": "ParamRef", "name": name}
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "table": self.table,
            "field": self.field,
            "display_name": self.display_name,
            "aggregation": self.aggregation,
            "is_field_parameter": self.is_field_parameter,
            "source": dict(self.source),
        }


@dataclass(frozen=True)
class CanonicalVisualField:
    role: str
    encoding: str
    ref: CanonicalFieldRef
    hidden: bool = False
    active: bool = True
    source: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "encoding": self.encoding,
            "ref": self.ref.to_dict(),
            "hidden": self.hidden,
            "active": self.active,
            "source": dict(self.source),
        }


@dataclass(frozen=True)
class CanonicalPageSpec:
    id: str
    source_id: str
    title: str
    order: int
    width: float = 1280
    height: float = 720
    hidden: bool = False
    page_type: str = ""
    source: dict[str, Any] = dc_field(default_factory=dict)

    def to_native_page(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "title": self.title, "order": self.order}
        if self.width != 1280 or self.height != 720:
            out["width"] = self.width
            out["height"] = self.height
        if self.hidden:
            out["hidden"] = True
        if self.page_type:
            out["page_type"] = self.page_type
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "title": self.title,
            "order": self.order,
            "width": self.width,
            "height": self.height,
            "hidden": self.hidden,
            "page_type": self.page_type,
            "source": dict(self.source),
        }


@dataclass(frozen=True)
class CanonicalVisualSpec:
    id: str
    source_id: str
    page_id: str
    source_page_id: str
    title: str
    subtitle: str
    pbi_visual_type: str
    visual_type: str
    layout: dict[str, Any]
    fields: list[CanonicalVisualField] = dc_field(default_factory=list)
    format: dict[str, Any] = dc_field(default_factory=dict)
    interactions: dict[str, Any] = dc_field(default_factory=dict)
    hidden: bool = False
    parent_group: str = ""
    supported: bool = True
    source: dict[str, Any] = dc_field(default_factory=dict)

    def to_native_visual(self) -> dict[str, Any]:
        title = self.title or _derive_auto_title(self.fields) or f"{self.pbi_visual_type} visual"
        out: dict[str, Any] = {
            "id": self.id,
            "title": title,
            "subtitle": self.subtitle,
            "visual_type": self.visual_type or self.pbi_visual_type,
            "page_id": self.page_id,
            "layout": dict(self.layout),
            "encodings": _fields_to_encodings(self.fields),
            "format": dict(self.format),
            "advanced_plotly_patch": {},
            "interactions": _normalize_interactions(self.interactions),
            "_documentation_source": {
                "visual_id": self.source_id,
                "visual_type": self.pbi_visual_type,
                "page_id": self.source_page_id,
                **dict(self.source),
            },
        }
        dynamic_bindings = _dynamic_text_bindings(self.fields)
        if dynamic_bindings.get("title"):
            out["dynamic_title"] = dynamic_bindings["title"]
        if dynamic_bindings.get("subtitle"):
            out["dynamic_subtitle"] = dynamic_bindings["subtitle"]
        sparkline_sidecars = _sparkline_sidecars(self.fields)
        if sparkline_sidecars:
            out["sparklines"] = sparkline_sidecars
            native_calcs = list(out.get("native_calcs") or [])
            native_calcs.append(
                {
                    "status": "sparkline_sidecar",
                    "unsupported_reason": "SparklineData workbook refs are preserved outside normal visual query encodings until executable sparkline metadata is exported.",
                    "sparklines": sparkline_sidecars,
                }
            )
            out["native_calcs"] = native_calcs
        if self.hidden:
            out["hidden"] = True
        if self.parent_group:
            out["parent_group"] = self.parent_group
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "page_id": self.page_id,
            "source_page_id": self.source_page_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "pbi_visual_type": self.pbi_visual_type,
            "visual_type": self.visual_type,
            "layout": dict(self.layout),
            "fields": [item.to_dict() for item in self.fields],
            "format": dict(self.format),
            "interactions": dict(self.interactions),
            "hidden": self.hidden,
            "parent_group": self.parent_group,
            "supported": self.supported,
            "source": dict(self.source),
        }


@dataclass(frozen=True)
class CanonicalReportSpec:
    dataset: str
    report: str
    source_path: str
    pages: list[CanonicalPageSpec]
    visuals: list[CanonicalVisualSpec]
    filters: list[dict[str, Any]] = dc_field(default_factory=list)
    bookmarks: list[dict[str, Any]] = dc_field(default_factory=list)
    visual_parameters: list[CanonicalVisualParameter] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "report": self.report,
            "source_path": self.source_path,
            "pages": [page.to_dict() for page in self.pages],
            "visuals": [visual.to_dict() for visual in self.visuals],
            "filters": list(self.filters),
            "bookmarks": list(self.bookmarks),
            "visual_parameters": parameters_to_dicts(self.visual_parameters),
            "warnings": list(self.warnings),
        }


@dataclass
class DocumentationTransferResult:
    project_path: str
    pages_created: int = 0
    visuals_created: int = 0
    filters_transferred: int = 0
    bookmarks_transferred: int = 0
    slicers_transferred: int = 0
    interactions_transferred: int = 0
    warnings: list[str] = dc_field(default_factory=list)
    unsupported_visual_types: list[str] = dc_field(default_factory=list)
    unsupported_visuals_preserved: int = 0
    parameters_catalogued: int = 0
    parameter_gaps: int = 0
    coverage_artifact: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": self.project_path,
            "pages_created": self.pages_created,
            "visuals_created": self.visuals_created,
            "filters_transferred": self.filters_transferred,
            "bookmarks_transferred": self.bookmarks_transferred,
            "slicers_transferred": self.slicers_transferred,
            "interactions_transferred": self.interactions_transferred,
            "warnings": list(self.warnings),
            "unsupported_visual_types": sorted(set(self.unsupported_visual_types)),
            "unsupported_visuals_preserved": self.unsupported_visuals_preserved,
            "parameters_catalogued": self.parameters_catalogued,
            "parameter_gaps": self.parameter_gaps,
            "coverage_artifact": self.coverage_artifact,
        }


def load_canonical_report_from_documentation(
    xlsx_path: str | os.PathLike[str],
    *,
    dataset: str | None = None,
    report: str | None = None,
) -> CanonicalReportSpec:
    """Load a canonical report spec from Report_Documentation.xlsx."""
    workbook_path = Path(xlsx_path)
    if not workbook_path.is_file():
        raise FileNotFoundError(str(workbook_path))

    pd = _require_pandas()
    sheets = pd.read_excel(workbook_path, sheet_name=None)

    containers = _filter_frame(_sheet(sheets, "Visual Containers"), dataset=dataset, report=report)
    report_rows = _filter_frame(_sheet(sheets, "Reports"), dataset=dataset, report=report)
    visual_properties = _filter_frame(_sheet(sheets, "Visual Properties"), dataset=dataset, report=report)
    interactions = _filter_frame(_sheet(sheets, "Edit Interactions"), dataset=dataset, report=report)
    pages_sheet = _filter_frame(_sheet(sheets, "Page Metadata"), dataset=dataset, report=report)
    filters_sheet = _filter_frame(_sheet(sheets, "Filters"), dataset=dataset, report=report)
    bookmarks_sheet = _filter_frame(_sheet(sheets, "Bookmarks"), dataset=dataset, report=report)

    if containers.empty:
        raise ValueError("Report documentation must contain at least one Visual Containers row")

    dataset_name = dataset or _first_sheet_value(containers, "Dataset") or _first_sheet_value(report_rows, "Dataset")
    report_name = report or _first_sheet_value(containers, "Report") or _first_sheet_value(report_rows, "Report")

    pages, page_lookup = _build_pages(containers, pages_sheet)
    fields_by_visual = _build_fields_by_visual(report_rows)
    properties_by_visual = _build_properties_by_visual(visual_properties)
    interactions_by_visual = _build_interactions_by_visual(interactions)

    warnings: list[str] = []
    visuals: list[CanonicalVisualSpec] = []
    used_visual_ids: set[str] = set()
    for _, row in containers.iterrows():
        source_visual_id = _cell_text(row, "VisualID") or _cell_text(row, "Name")
        if not source_visual_id:
            continue
        pbi_visual_type = _cell_text(row, "VisualType") or "unknown"
        project_visual_type = _map_documentation_visual_type(pbi_visual_type)
        supported = _is_supported_documentation_visual_type(pbi_visual_type, project_visual_type)
        if not supported:
            warnings.append(f"Unsupported visual type {pbi_visual_type!r} for visual {source_visual_id!r}")
            project_visual_type = pbi_visual_type

        native_visual_id = _stable_id("doc", source_visual_id, used_visual_ids)
        source_page_id = _cell_text(row, "PageID") or _cell_text(row, "Page") or "page1"
        page_id = page_lookup.get(source_page_id) or page_lookup.get(_cell_text(row, "Page")) or pages[0].id
        layout = _layout_from_container(row)
        format_options = _format_from_properties(
            properties_by_visual.get(source_visual_id, []),
            pbi_visual_type=pbi_visual_type,
        )
        interactions_config = interactions_by_visual.get(source_visual_id, {})

        visuals.append(
            CanonicalVisualSpec(
                id=native_visual_id,
                source_id=source_visual_id,
                page_id=page_id,
                source_page_id=source_page_id,
                title=_cell_text(row, "Title"),
                subtitle=_cell_text(row, "Subtitle"),
                pbi_visual_type=pbi_visual_type,
                visual_type=project_visual_type,
                layout=layout,
                fields=fields_by_visual.get(source_visual_id, []),
                format=format_options,
                interactions=interactions_config,
                hidden=_cell_bool(row, "Hidden"),
                parent_group=_cell_text(row, "ParentGroup"),
                supported=supported,
                source={"json_path": _cell_text(row, "JsonPath")},
            )
        )

    filters = _dataframe_records(filters_sheet)
    bookmarks = _dataframe_records(bookmarks_sheet)
    visual_parameters = build_documentation_parameter_catalogue_from_sheets(
        sheets,
        dataset=dataset,
        report=report,
    )
    return CanonicalReportSpec(
        dataset=dataset_name,
        report=report_name,
        source_path=str(workbook_path),
        pages=pages,
        visuals=visuals,
        filters=filters,
        bookmarks=bookmarks,
        visual_parameters=visual_parameters,
        warnings=warnings,
    )


def preview_report_documentation_transfer(
    xlsx_path: str | os.PathLike[str],
    *,
    dataset: str | None = None,
    report: str | None = None,
    include_parameters: bool = False,
    parameter_limit: int = 100,
) -> dict[str, Any]:
    spec = load_canonical_report_from_documentation(xlsx_path, dataset=dataset, report=report)
    unsupported = sorted({visual.pbi_visual_type for visual in spec.visuals if not visual.supported})
    coverage = summarize_parameter_coverage(spec.visual_parameters)
    plotly_setting_crosswalk = build_plotly_setting_crosswalk(spec.visual_parameters)
    preview: dict[str, Any] = {
        "dataset": spec.dataset,
        "report": spec.report,
        "source_path": spec.source_path,
        "summary": {
            "total_pages": len(spec.pages),
            "total_visuals": len(spec.visuals),
            "supported_visuals": sum(1 for visual in spec.visuals if visual.supported),
            "unsupported_visuals": sum(1 for visual in spec.visuals if not visual.supported),
            "unsupported_types": unsupported,
            "total_fields": sum(len(visual.fields) for visual in spec.visuals),
            "filters": len(spec.filters),
            "bookmarks": len(spec.bookmarks),
        },
        "parameter_coverage": coverage,
        "plotly_setting_crosswalk": plotly_setting_crosswalk,
        "pipeline_status": _pipeline_status(coverage, plotly_setting_crosswalk),
        "pages": [page.to_dict() for page in spec.pages],
        "visuals": [visual.to_dict() for visual in spec.visuals],
        "warnings": list(spec.warnings),
    }
    if include_parameters:
        limit = max(0, int(parameter_limit))
        preview["visual_parameters"] = parameters_to_dicts(spec.visual_parameters[:limit])
        preview["visual_parameters_truncated"] = len(spec.visual_parameters) > limit
    return preview


def execute_report_documentation_transfer(
    xlsx_path: str | os.PathLike[str],
    output_project_dir: str | os.PathLike[str],
    *,
    dataset: str | None = None,
    report: str | None = None,
    skip_unsupported: bool = True,
    preserve_unsupported: bool = True,
    merge_existing: bool = False,
) -> DocumentationTransferResult:
    """Emit native dummy BI report artifacts from a documentation workbook."""
    spec = load_canonical_report_from_documentation(xlsx_path, dataset=dataset, report=report)
    output_path = Path(output_project_dir)
    reports_dir = output_path / "reports"
    visuals_dir = reports_dir / "visuals"
    visuals_dir.mkdir(parents=True, exist_ok=True)

    result = DocumentationTransferResult(project_path=str(output_path), warnings=list(spec.warnings))
    parameter_coverage = summarize_parameter_coverage(spec.visual_parameters)
    plotly_setting_crosswalk = build_plotly_setting_crosswalk(spec.visual_parameters)
    result.parameters_catalogued = int(parameter_coverage.get("total_parameters") or 0)
    result.parameter_gaps = int(parameter_coverage.get("gap_count") or 0)

    if not merge_existing:
        for existing in visuals_dir.glob("doc_*.json"):
            existing.unlink()

    pages_payload = {"pages": [page.to_native_page() for page in spec.pages]}
    source_page_to_native = _source_page_to_native(spec.pages)
    apply_page_surface_sidecars(
        pages_payload["pages"],
        spec.visual_parameters,
        source_page_to_native=source_page_to_native,
    )
    pages_path = reports_dir / "pages.yaml"
    if merge_existing and pages_path.is_file():
        pages_payload = _merge_pages_payload(_read_yaml(pages_path), pages_payload)
    _write_yaml(pages_path, pages_payload)
    result.pages_created = len(spec.pages)

    native_id_by_source = {visual.source_id: visual.id for visual in spec.visuals}
    parameters_by_visual = _parameters_by_visual(spec.visual_parameters)
    imported_slicers: list[dict[str, Any]] = []
    for visual in spec.visuals:
        if not visual.supported:
            result.unsupported_visual_types.append(visual.pbi_visual_type)
            if skip_unsupported and not preserve_unsupported:
                continue
            result.unsupported_visuals_preserved += 1
        native_visual = visual.to_native_visual()
        if not visual.supported:
            _mark_unsupported_visual(native_visual, visual)
        visual_parameters = parameters_by_visual.get(visual.source_id, [])
        if visual_parameters:
            native_visual["documentation_parameters"] = parameters_to_dicts(visual_parameters)
            apply_visual_surface_sidecars(
                native_visual,
                visual_parameters,
                source_page_to_native=source_page_to_native,
            )
        _rewrite_interaction_targets(native_visual, native_id_by_source)
        if native_visual.get("interactions", {}).get("interaction_targets"):
            result.interactions_transferred += len(native_visual["interactions"]["interaction_targets"])
        if imported_slicer := _slicer_payload_from_visual(native_visual):
            imported_slicers.append(imported_slicer)
        (visuals_dir / f"{visual.id}.json").write_text(
            json.dumps(native_visual, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result.visuals_created += 1

    if imported_slicers:
        save_slicers(str(output_path), {"slicers": imported_slicers})
        result.slicers_transferred = len(imported_slicers)

    filters_payload = {"report_filters": [], "page_filters": {}, "visual_filters": {}}
    if spec.filters:
        filters_payload["documentation_filters"] = list(spec.filters)
        result.filters_transferred = len(spec.filters)
    _write_yaml(reports_dir / "filters.yaml", filters_payload)

    if spec.bookmarks:
        _write_yaml(reports_dir / "bookmarks.yaml", {"documentation_bookmarks": list(spec.bookmarks)})
        result.bookmarks_transferred = len(spec.bookmarks)

    coverage_path = reports_dir / "documentation_parameter_coverage.json"
    report_sidecars = build_report_sidecars(spec.visual_parameters)
    coverage_path.write_text(
        json.dumps(
            {
                "coverage": parameter_coverage,
                "plotly_setting_crosswalk": plotly_setting_crosswalk,
                "pipeline_status": _pipeline_status(parameter_coverage, plotly_setting_crosswalk),
                **report_sidecars,
                "parameters": parameters_to_dicts(spec.visual_parameters),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result.coverage_artifact = str(coverage_path)

    return result


def _parameters_by_visual(parameters: list[CanonicalVisualParameter]) -> dict[str, list[CanonicalVisualParameter]]:
    grouped: dict[str, list[CanonicalVisualParameter]] = {}
    for parameter in parameters:
        if parameter.visual_id:
            grouped.setdefault(parameter.visual_id, []).append(parameter)
    return grouped


def _pipeline_status(parameter_coverage: Mapping[str, Any], plotly_setting_crosswalk: Mapping[str, Any]) -> dict[str, Any]:
    gap_count = int(parameter_coverage.get("gap_count") or 0)
    unresolved_settings = int(plotly_setting_crosswalk.get("unresolved_count") or 0)
    return {
        "canonical_to_dummy_bi_visuals": "implemented_not_complete",
        "native_visual_artifacts": "emitted",
        "all_parameters_non_gap": gap_count == 0,
        "plotly_setting_crosswalk_complete": unresolved_settings == 0,
        "remaining_parameter_gaps": gap_count,
        "remaining_unresolved_visual_settings": unresolved_settings,
    }


def _source_page_to_native(pages: list[CanonicalPageSpec]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for page in pages:
        for key in (page.source_id, page.title, page.id):
            if key:
                lookup[str(key)] = page.id
    return lookup


def _mark_unsupported_visual(native_visual: dict[str, Any], visual: CanonicalVisualSpec) -> None:
    native_visual["visual_type"] = "group"
    native_visual["render_blocked"] = {
        "reason": "unsupported_power_bi_visual",
        "message": f"Power BI visual type {visual.pbi_visual_type!r} is preserved for round-trip but is not renderable as a native Dummy BI visual yet.",
    }
    native_visual["unsupported_visual"] = {
        "source_visual_id": visual.source_id,
        "source_visual_type": visual.pbi_visual_type,
        "preservation_status": "preserve_only",
        "unsupported_reason": "No Dummy BI family adapter exists for this Power BI visual token yet.",
        "source": dict(visual.source),
    }


def _require_pandas():
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pandas and openpyxl are required to read Report_Documentation.xlsx") from exc
    return pd


def _sheet(sheets: Mapping[str, Any], name: str):
    pd = _require_pandas()
    frame = sheets.get(name)
    if frame is None:
        return pd.DataFrame()
    return frame


def _filter_frame(frame: Any, *, dataset: str | None, report: str | None):
    if frame is None or frame.empty:
        return frame
    out = frame
    if dataset and "Dataset" in out.columns:
        out = out[out["Dataset"].map(lambda value: _normalize_key(value) == _normalize_key(dataset))]
    if report and "Report" in out.columns:
        out = out[out["Report"].map(lambda value: _normalize_key(value) == _normalize_key(report))]
    return out


def _build_pages(containers: Any, pages_sheet: Any) -> tuple[list[CanonicalPageSpec], dict[str, str]]:
    source_rows = pages_sheet if pages_sheet is not None and not pages_sheet.empty else containers
    page_keys: list[tuple[str, str, Any]] = []
    seen: set[str] = set()
    for _, row in source_rows.iterrows():
        source_id = _cell_text(row, "PageID") or _cell_text(row, "Page") or _cell_text(row, "PageName")
        title = _cell_text(row, "Page") or _cell_text(row, "DisplayName") or source_id or "Page"
        key = _normalize_key(source_id or title)
        if not key or key in seen:
            continue
        seen.add(key)
        page_keys.append((source_id or title, title, row))

    if not page_keys:
        page_keys = [("page1", "Page 1", {})]

    used_page_ids: set[str] = set()
    pages: list[CanonicalPageSpec] = []
    lookup: dict[str, str] = {}
    for order, (source_id, title, row) in enumerate(page_keys, 1):
        native_page_id = _stable_id("doc_page", source_id, used_page_ids)
        width = _cell_number(row, "Width", default=_cell_number(row, "PageWidth", default=1280))
        height = _cell_number(row, "Height", default=_cell_number(row, "PageHeight", default=720))
        page_type = _page_type_from_row(row)
        hidden = _cell_bool(row, "Hidden") or _cell_text(row, "Visibility").lower() == "hiddeninviewmode"
        page = CanonicalPageSpec(
            id=native_page_id,
            source_id=source_id,
            title=title or source_id,
            order=order,
            width=width,
            height=height,
            hidden=hidden,
            page_type=page_type,
            source={"json_path": _cell_text(row, "JsonPath")},
        )
        pages.append(page)
        lookup[source_id] = native_page_id
        lookup[title] = native_page_id
    return pages, lookup


def _build_fields_by_visual(report_rows: Any) -> dict[str, list[CanonicalVisualField]]:
    fields_by_visual: dict[str, list[CanonicalVisualField]] = {}
    if report_rows is None or report_rows.empty:
        return fields_by_visual
    for _, row in report_rows.iterrows():
        visual_id = _cell_text(row, "VisualID")
        if not visual_id:
            continue
        role = _role_from_row(row)
        if not role:
            continue
        table = _cell_text(row, "Table")
        field_name = _cell_text(row, "Field") or _cell_text(row, "Value")
        if not field_name and not table:
            continue
        pbi_visual_type = _cell_text(row, "VisualType")
        role_visual_type = _map_documentation_visual_type(pbi_visual_type) or pbi_visual_type
        encoding = _encoding_for_documentation_role(role, role_visual_type)
        kind = _field_kind(row)
        ref_source = {
            "used_in": _cell_text(row, "UsedIn"),
            "json_path": _cell_text(row, "JsonPath"),
            "original_json": _cell_text(row, "OriginalJson"),
        }
        sparkline = _sparkline_payload_from_row(row, table, field_name)
        if sparkline:
            kind = "sparkline"
            encoding = "sparkline"
            ref_source["sparkline"] = sparkline
        else:
            kind, table, field_name, normalized_source = _normalize_workbook_field_reference(
                kind=kind,
                table=table,
                field_name=field_name,
                row=row,
            )
            if normalized_source:
                ref_source["normalized_reference"] = normalized_source
        ref = CanonicalFieldRef(
            kind=kind,
            table=table,
            field=field_name,
            display_name=field_name,
            aggregation=_cell_text(row, "AggregationFunction"),
            is_field_parameter=_cell_bool(row, "Is Field Parameter"),
            source=ref_source,
        )
        if ref.to_native_expr() is None and kind != "sparkline":
            continue
        active_text = _cell_text(row, "Active").lower()
        fields_by_visual.setdefault(visual_id, []).append(
            CanonicalVisualField(
                role=role,
                encoding=encoding,
                ref=ref,
                hidden=_cell_bool(row, "Hidden"),
                active=False if active_text == "false" else True,
                source={"condition": _cell_text(row, "Condition")},
            )
        )
    return fields_by_visual


def _build_properties_by_visual(visual_properties: Any) -> dict[str, list[dict[str, Any]]]:
    properties_by_visual: dict[str, list[dict[str, Any]]] = {}
    if visual_properties is None or visual_properties.empty:
        return properties_by_visual
    for _, row in visual_properties.iterrows():
        visual_id = _cell_text(row, "VisualID")
        if not visual_id:
            continue
        properties_by_visual.setdefault(visual_id, []).append(
            {
                "group": _cell_text(row, "PropertyGroup"),
                "property": _cell_text(row, "Property"),
                "value": _cell_value(row, "Value"),
                "selector": _cell_text(row, "Selector"),
                "json_path": _cell_text(row, "JsonPath"),
            }
        )
    return properties_by_visual


def _build_interactions_by_visual(interactions: Any) -> dict[str, dict[str, Any]]:
    interactions_by_visual: dict[str, dict[str, Any]] = {}
    if interactions is None or interactions.empty:
        return interactions_by_visual
    for _, row in interactions.iterrows():
        source_id = _cell_text(row, "SourceID") or _cell_text(row, "SourceVisualID") or _cell_text(row, "Source")
        target_id = _cell_text(row, "TargetID") or _cell_text(row, "TargetVisualID") or _cell_text(row, "Target")
        if not source_id or not target_id:
            continue
        enabled_text = _cell_text(row, "Enabled")
        enabled = True if not enabled_text else _cell_bool(row, "Enabled")
        mode = _interaction_mode(row, enabled)
        entry = interactions_by_visual.setdefault(source_id, {"affects_others": True, "is_affected": True, "mode": "highlight", "interaction_targets": {}})
        entry["interaction_targets"][target_id] = mode
    return interactions_by_visual


def _map_documentation_visual_type(pbi_visual_type: str) -> str:
    return _DOC_VISUAL_TYPE_MAP.get(pbi_visual_type, _map_visual_type(pbi_visual_type))


def _is_supported_documentation_visual_type(pbi_visual_type: str, project_visual_type: str) -> bool:
    if pbi_visual_type in _DOC_VISUAL_TYPE_MAP or pbi_visual_type in _VISUAL_TYPE_MAP:
        return True
    return project_visual_type in _NATIVE_VISUAL_TYPES


def _layout_from_container(row: Any) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "x": round(_cell_number(row, "X", default=0)),
        "y": round(_cell_number(row, "Y", default=0)),
        "w": round(_cell_number(row, "Width", default=300)),
        "h": round(_cell_number(row, "Height", default=200)),
    }
    z_value = _cell_value(row, "Z")
    if not _is_blank(z_value):
        layout["z"] = z_value
    tab_order = _cell_value(row, "TabOrder")
    if not _is_blank(tab_order):
        layout["tabOrder"] = tab_order
    return layout


def _format_from_properties(properties: list[dict[str, Any]], *, pbi_visual_type: str = "") -> dict[str, Any]:
    if not properties:
        return {}
    return promote_documentation_format_properties(properties, pbi_visual_type=pbi_visual_type)


def _fields_to_encodings(fields: list[CanonicalVisualField]) -> dict[str, Any]:
    encodings: dict[str, Any] = {}
    for field_spec in fields:
        if field_spec.hidden or not field_spec.active:
            continue
        if field_spec.encoding in {"dynamic_title", "dynamic_subtitle", "sparkline"}:
            continue
        expr = field_spec.ref.to_native_expr()
        if expr is None:
            continue
        existing = encodings.get(field_spec.encoding)
        if existing is None:
            encodings[field_spec.encoding] = expr
        elif isinstance(existing, list):
            existing.append(expr)
        else:
            encodings[field_spec.encoding] = [existing, expr]
    return encodings


def _derive_auto_title(fields: list[CanonicalVisualField]) -> str:
    value_label = ""
    category_label = ""
    for field_spec in fields:
        if field_spec.encoding in {"dynamic_title", "dynamic_subtitle", "sparkline"}:
            continue
        if field_spec.encoding in {"y", "values", "value"} and not value_label:
            value_label = field_spec.ref.display_name or field_spec.ref.field
        if field_spec.encoding in {"x", "names", "rows", "columns", "path"} and not category_label:
            category_label = field_spec.ref.display_name or field_spec.ref.field
    if value_label and category_label and value_label.lower() != category_label.lower():
        return f"{value_label} by {category_label}"
    return value_label or category_label


def _dynamic_text_bindings(fields: list[CanonicalVisualField]) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for field_spec in fields:
        if field_spec.encoding not in {"dynamic_title", "dynamic_subtitle"}:
            continue
        expr = field_spec.ref.to_native_expr()
        if expr is None:
            continue
        key = "title" if field_spec.encoding == "dynamic_title" else "subtitle"
        bindings[key] = {
            "expression": expr,
            "source": {
                **dict(field_spec.source),
                "ref": field_spec.ref.to_dict(),
            },
        }
    return bindings


def _sparkline_sidecars(fields: list[CanonicalVisualField]) -> list[dict[str, Any]]:
    sidecars: list[dict[str, Any]] = []
    for field_spec in fields:
        if field_spec.encoding != "sparkline":
            continue
        payload = field_spec.ref.source.get("sparkline") if isinstance(field_spec.ref.source, Mapping) else None
        if not isinstance(payload, Mapping):
            continue
        sidecars.append(
            {
                **dict(payload),
                "source": {
                    **dict(field_spec.source),
                    "ref": field_spec.ref.to_dict(),
                },
            }
        )
    return sidecars


def _encoding_for_documentation_role(role: str, visual_type: str) -> str:
    role_key = _normalize_key(role).replace("_", "")
    if role_key == "title":
        return "dynamic_title"
    if role_key == "subtitle":
        return "dynamic_subtitle"
    return _map_encoding_role(role, visual_type)


def _normalize_workbook_field_reference(
    *,
    kind: str,
    table: str,
    field_name: str,
    row: Any,
) -> tuple[str, str, str, dict[str, Any]]:
    if kind == "hierarchy":
        normalized = _normalize_hierarchy_level_field_ref(table, field_name, row)
        if normalized:
            return "column", normalized["table"], normalized["column"], normalized
        return kind, table, field_name, {}

    if kind != "column":
        return kind, table, field_name, {}

    if normalized := _normalize_date_variation_ref(table, field_name):
        return "column", normalized["table"], normalized["column"], normalized
    if normalized := _normalize_model_hierarchy_level_ref(table, field_name, row):
        return "column", normalized["table"], normalized["column"], normalized
    return kind, table, field_name, {}


_DATE_VARIATION_LEVELS = {
    "jahr": "Year",
    "year": "Year",
    "quartal": "Quarter",
    "quarter": "Quarter",
    "monat": "Monthnumber",
    "month": "Monthnumber",
    "tag": "Date",
    "day": "Date",
    "date": "Date",
}


def _normalize_date_variation_ref(table: str, field_name: str) -> dict[str, Any] | None:
    parts = [part for part in _to_text(field_name).split(".") if part]
    if len(parts) < 4 or parts[1].lower() != "variation":
        return None
    level = parts[-1]
    column = _DATE_VARIATION_LEVELS.get(level.lower())
    if not column:
        return None
    return {
        "kind": "date_variation_level",
        "table": table or parts[0],
        "column": column,
        "source_field": field_name,
        "base_column": parts[0],
        "hierarchy": parts[2],
        "level": level,
    }


def _normalize_hierarchy_level_field_ref(table: str, field_name: str, row: Any) -> dict[str, Any] | None:
    if not table or not field_name:
        return None
    if _cell_text(row, "Field Type").lower() not in {"", "column", "unknown"}:
        return None

    level = _to_text(field_name).strip().strip("'\"")
    if not level:
        return None

    local_date_table = table.lower().startswith("localdatetable_")
    date_column = _DATE_VARIATION_LEVELS.get(level.lower())
    if local_date_table and date_column:
        return {
            "kind": "date_hierarchy_level",
            "table": "Date",
            "column": date_column,
            "source_table": table,
            "source_field": field_name,
            "level": level,
        }

    return {
        "kind": "model_hierarchy_level",
        "table": table,
        "column": level,
        "source_field": field_name,
        "level": level,
    }


def _normalize_model_hierarchy_level_ref(table: str, field_name: str, row: Any) -> dict[str, Any] | None:
    field_text = _to_text(field_name)
    if "." not in field_text:
        return None
    original_json = _cell_text(row, "OriginalJson")
    if "hierarchy" not in field_text.lower() and "Hierarchy" not in original_json:
        return None
    hierarchy_name, level = field_text.rsplit(".", 1)
    level = level.strip().strip("'\"")
    if not table or not level:
        return None
    return {
        "kind": "model_hierarchy_level",
        "table": table,
        "column": level,
        "source_field": field_name,
        "hierarchy": hierarchy_name.strip().strip("'\""),
        "level": level,
    }


_SPARKLINE_DATA_RE = re.compile(
    r"SparklineData\(\s*(?P<measure_table>.+?)\.(?P<measure>.+?)_\[(?P<axis_table>.+?)\.(?P<axis_column>.+?)\]\s*\)",
    re.IGNORECASE,
)


def _sparkline_payload_from_row(row: Any, table: str, field_name: str) -> dict[str, Any] | None:
    raw = _cell_text(row, "OriginalJson")
    match = _SPARKLINE_DATA_RE.search(raw)
    if not match and "_[" in field_name and field_name.endswith("]"):
        match = _SPARKLINE_DATA_RE.search(f"SparklineData({table}.{field_name})")
    if not match:
        return None
    measure_table = match.group("measure_table").strip().strip("'\"")
    measure_name = match.group("measure").strip().strip("'\"")
    axis_table = match.group("axis_table").strip().strip("'\"")
    axis_column = match.group("axis_column").strip().strip("'\"")
    return {
        "type": "SparklineDataRef",
        "measure": {"type": "MeasureRef", "table": measure_table, "name": measure_name},
        "axis": {"type": "ColumnRef", "table": axis_table, "column": axis_column},
        "source_query_ref": field_name,
        "source_expression": raw,
    }


def _normalize_interactions(raw: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        "affects_others": bool(raw.get("affects_others", True)),
        "is_affected": bool(raw.get("is_affected", True)),
        "mode": str(raw.get("mode") or "highlight"),
    }
    targets = raw.get("interaction_targets")
    if isinstance(targets, Mapping):
        out["interaction_targets"] = dict(targets)
    return out


def _rewrite_interaction_targets(native_visual: dict[str, Any], native_id_by_source: Mapping[str, str]) -> None:
    targets = native_visual.get("interactions", {}).get("interaction_targets")
    if not isinstance(targets, Mapping):
        return
    rewritten: dict[str, str] = {}
    for source_target_id, mode in targets.items():
        native_target_id = native_id_by_source.get(str(source_target_id))
        if native_target_id:
            rewritten[native_target_id] = str(mode)
    native_visual.setdefault("interactions", {})["interaction_targets"] = rewritten


def _slicer_payload_from_visual(native_visual: MutableMapping[str, Any]) -> dict[str, Any] | None:
    if str(native_visual.get("visual_type") or "").lower() != "slicer":
        return None
    column_ref = _first_column_ref(native_visual.get("encodings"))
    if not column_ref:
        # F1: detect non-ColumnRef slicer refs (hierarchy / field_parameter / measure)
        # so the gap is visible in the preservation sidecar instead of silently dropped.
        non_column_kind = _first_non_column_slicer_ref_kind(native_visual.get("encodings"))
        if non_column_kind:
            slicer_state = native_visual.get("slicer_state")
            if not isinstance(slicer_state, MutableMapping):
                slicer_state = dict(slicer_state) if isinstance(slicer_state, Mapping) else {}
                native_visual["slicer_state"] = slicer_state
            slicer_state.setdefault("unsupported_kind", non_column_kind)
        return None

    slicer_state = native_visual.get("slicer_state") if isinstance(native_visual.get("slicer_state"), Mapping) else {}
    selection_state = native_visual.get("selection_state") if isinstance(native_visual.get("selection_state"), Mapping) else {}
    slicer_mode = str(slicer_state.get("slicer_mode") or slicer_state.get("mode") or "list").strip().lower()
    slicer_type = "dropdown" if "drop" in slicer_mode else "list"
    layout = native_visual.get("layout") if isinstance(native_visual.get("layout"), Mapping) else {}
    page_id = str(native_visual.get("page_id") or "").strip()
    sync_group = str(native_visual.get("slicer_sync_group") or slicer_state.get("sync_group_name") or "").strip()
    strict_single = bool(selection_state.get("strict_single_select"))

    payload: dict[str, Any] = {
        "id": str(native_visual.get("id") or ""),
        "name": str(native_visual.get("title") or native_visual.get("id") or "Slicer"),
        "title": str(native_visual.get("title") or ""),
        "column": column_ref,
        "type": slicer_type,
        "behavior": {"apply_to": "all_visuals", "auto_apply": True},
        "selection": {"mode": "all", "values": []},
        "ui": {"multi": not strict_single, "search": True},
        "pages": {},
    }
    if page_id:
        payload["pages"][page_id] = {
            "visible": not bool(native_visual.get("hidden")),
            "sync": bool(sync_group),
            "layout": {
                "x": int(layout.get("x") or 0),
                "y": int(layout.get("y") or 0),
                "w": int(layout.get("w") or layout.get("width") or 240),
                "h": int(layout.get("h") or layout.get("height") or 160),
            },
        }
    if sync_group:
        payload["sync_group"] = sync_group
    return payload


def _first_column_ref(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        if value.get("type") == "ColumnRef" and value.get("table") and value.get("column"):
            return {"type": "ColumnRef", "table": str(value["table"]), "column": str(value["column"])}
        for item in value.values():
            found = _first_column_ref(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_column_ref(item)
            if found:
                return found
    return None


_NON_COLUMN_SLICER_REF_KINDS: dict[str, str] = {
    "HierarchyRef": "hierarchy",
    "ParamRef": "field_parameter",
    "MeasureRef": "measure",
}


def _first_non_column_slicer_ref_kind(value: Any) -> str | None:
    """Walk encodings and return the first non-ColumnRef slicer ref kind found.

    Used to flag slicers on hierarchies, field parameters, or measure ranges
    so they appear in the preservation sidecar instead of being silently dropped
    by the ColumnRef-only `_first_column_ref` walker.
    """
    if isinstance(value, Mapping):
        ref_type = value.get("type")
        if isinstance(ref_type, str) and ref_type in _NON_COLUMN_SLICER_REF_KINDS:
            return _NON_COLUMN_SLICER_REF_KINDS[ref_type]
        for item in value.values():
            found = _first_non_column_slicer_ref_kind(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_non_column_slicer_ref_kind(item)
            if found:
                return found
    return None


def _role_from_row(row: Any) -> str:
    role = _cell_text(row, "Role")
    if role:
        return role
    used_in = _cell_text(row, "UsedIn")
    if used_in.startswith("Projection:"):
        return used_in.split(":", 1)[1]
    if used_in.lower().startswith("projection") and ":" in used_in:
        return used_in.split(":", 1)[1]
    return ""


def _field_kind(row: Any) -> str:
    if _cell_bool(row, "Is Field Parameter"):
        return "field_parameter"
    if _cell_bool(row, "Is Hierarchy"):
        return "hierarchy"
    field_type = _cell_text(row, "Field Type").lower()
    if field_type == "measure":
        return "measure"
    return "column"


def _interaction_mode(row: Any, enabled: bool) -> str:
    if not enabled:
        return "none"
    raw = (_cell_text(row, "InteractionType") or _cell_text(row, "Type") or _cell_text(row, "Mode")).lower()
    if "none" in raw or "no" in raw:
        return "none"
    if "filter" in raw and "highlight" not in raw:
        return "filter"
    if _cell_bool(row, "DrillPropagates"):
        return "filter"
    return "highlight"


def _page_type_from_row(row: Any) -> str:
    page_type = _cell_text(row, "PageType") or _cell_text(row, "Type")
    page_type_lower = page_type.lower()
    if "drill" in page_type_lower:
        return "drillthrough"
    if "tooltip" in page_type_lower:
        return "tooltip"
    return ""


def _merge_pages_payload(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    existing_pages = list(existing.get("pages") or []) if isinstance(existing, Mapping) else []
    existing_ids = {str(page.get("id")) for page in existing_pages if isinstance(page, Mapping)}
    for page in incoming.get("pages") or []:
        if isinstance(page, Mapping) and str(page.get("id")) not in existing_ids:
            existing_pages.append(dict(page))
    return {"pages": existing_pages}


def _write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True), encoding="utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _dataframe_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        cleaned = {str(key): _json_safe(value) for key, value in raw.items() if not _is_blank(value)}
        if cleaned:
            records.append(cleaned)
    return records


def _first_sheet_value(frame: Any, column: str) -> str:
    if frame is None or frame.empty or column not in frame.columns:
        return ""
    for value in frame[column].tolist():
        text = _to_text(value)
        if text:
            return text
    return ""


def _cell_text(row: Any, column: str) -> str:
    return _to_text(_cell_value(row, column))


def _cell_number(row: Any, column: str, *, default: float) -> float:
    value = _cell_value(row, column)
    if _is_blank(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cell_bool(row: Any, column: str) -> bool:
    value = _cell_value(row, column)
    if isinstance(value, bool):
        return value
    text = _to_text(value).lower()
    return text in {"1", "true", "yes", "y", "on"}


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
        pd = _require_pandas()
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
    return value


def _normalize_key(value: Any) -> str:
    return _to_text(value).strip().lower()


def _stable_id(prefix: str, raw_value: str, used: set[str]) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_value.strip())[:48].strip("_")
    if not slug:
        slug = "item"
    candidate = f"{prefix}_{slug}"
    base = candidate
    counter = 2
    while candidate.upper() in used:
        candidate = f"{base}_{counter}"
        counter += 1
    used.add(candidate.upper())
    return candidate
