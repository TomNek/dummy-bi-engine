"""
Server routes for PBIR Report Transfer.

Provides endpoints to:
- Preview a PBIR .Report directory (analysis without writing)
- Execute the transfer into the current project
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Body
from fastapi.responses import JSONResponse


def register_report_transfer_routes(app):
    """Register report transfer endpoints on the FastAPI app."""

    from dax_ui.server._runtime_helpers import _ok, _err

    @app.get("/runtime/report-transfer/documentation/schema")
    def runtime_report_documentation_schema():
        """Return the workbook sheets consumed by the report-documentation importer."""
        return _ok({
            "required_sheets": ["Visual Containers"],
            "optional_sheets": [
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
            ],
            "coverage_artifact": "reports/documentation_parameter_coverage.json",
            "execute_options": {
                "skip_unsupported": True,
                "preserve_unsupported": True,
                "merge_existing": False,
            },
            "emitted_sidecars": [
                "query_options",
                "visual_header",
                "visual_actions",
                "container_format",
                "documentation_format_crosswalk",
                "tooltip_page_id",
                "selection_state",
                "slicer_state",
                "static_asset",
                "static_resources",
                "page_format",
                "drillthrough",
                "diagnostics",
                "unsupported_visual",
            ],
            "preview_endpoint": "/runtime/report-transfer/documentation/preview",
            "execute_endpoint": "/runtime/report-transfer/documentation/execute",
        })

    @app.post("/runtime/report-transfer/preview")
    def runtime_report_transfer_preview(payload: dict = Body(default_factory=dict)):
        """
        Analyze a PBIR .Report directory and return a transfer plan
        without writing anything to disk.

        Body: {"report_dir": "/path/to/Model.Report"}
        """
        report_dir = str(payload.get("report_dir") or "").strip()
        if not report_dir:
            return _err(400, "report_dir is required")

        rdir = Path(report_dir)
        if not rdir.is_dir():
            return _err(400, f"Not a directory: {report_dir}")

        defn = rdir / "definition"
        if not defn.is_dir():
            return _err(400, f"No definition/ folder found in {report_dir}. Expected a PBIR .Report directory.")

        pages_dir = defn / "pages"
        if not pages_dir.is_dir():
            return _err(400, f"No definition/pages/ folder found in {report_dir}. Is this a valid PBIR .Report directory?")

        try:
            from dax_project.report_transfer import preview_report_transfer
            preview = preview_report_transfer(report_dir)
        except Exception as exc:
            return _err(400, f"Failed to analyze report: {exc}")

        if "error" in preview:
            return _err(400, preview["error"])

        return _ok(preview)

    @app.post("/runtime/report-transfer/execute")
    def runtime_report_transfer_execute(payload: dict = Body(default_factory=dict)):
        """
        Execute the PBIR → project report transfer.

        Body: {
            "report_dir": "/path/to/Model.Report",
            "output_project": "my_project" | "/absolute/path/to/project",
            "skip_unsupported": true,
            "merge_existing": false
        }
        """
        report_dir = str(payload.get("report_dir") or "").strip()
        if not report_dir:
            return _err(400, "report_dir is required")

        output_project = str(payload.get("output_project") or "").strip()
        if not output_project:
            # Default to currently loaded project
            output_project = os.environ.get("DAX_PROJECT_PATH", "")
        if not output_project:
            return _err(400, "output_project is required (or set DAX_PROJECT_PATH)")

        skip_unsupported = bool(payload.get("skip_unsupported", True))
        merge_existing = bool(payload.get("merge_existing", False))

        rdir = Path(report_dir)
        if not rdir.is_dir():
            return _err(400, f"Not a directory: {report_dir}")

        defn = rdir / "definition"
        if not defn.is_dir():
            return _err(400, f"No definition/ folder found in {report_dir}.")

        # Resolve output project to absolute path if relative
        if not os.path.isabs(output_project):
            output_project = os.path.join(os.getcwd(), output_project)

        try:
            from dax_project.report_transfer import execute_report_transfer
            result = execute_report_transfer(
                report_dir,
                output_project,
                skip_unsupported=skip_unsupported,
                merge_existing=merge_existing,
            )
        except Exception as exc:
            return _err(400, f"Transfer failed: {exc}")

        # Auto-apply PBI theme if available — makes colors match PBI visuals
        theme_applied = False
        try:
            from dax_project.report_transfer import extract_pbi_theme
            theme = extract_pbi_theme(report_dir)
            save_theme = {k: v for k, v in theme.items() if not k.startswith("_")}
            reports_dir = Path(output_project) / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            import json as _json_t
            with open(reports_dir / "reporting_theme.json", "w", encoding="utf-8") as f:
                _json_t.dump(save_theme, f, indent=2, ensure_ascii=False)
            theme_applied = True
        except Exception:
            pass  # theme extraction is best-effort

        return _ok({
            "project_path": result.project_path,
            "pages_created": result.pages_created,
            "visuals_created": result.visuals_created,
            "filters_transferred": result.filters_transferred,
            "bookmarks_transferred": result.bookmarks_transferred,
            "interactions_transferred": result.interactions_transferred,
            "warnings": result.warnings,
            "unsupported_visual_types": list(set(result.unsupported_visual_types)),
            "theme_applied": theme_applied,
        })

    @app.post("/runtime/report-transfer/documentation/preview")
    def runtime_report_documentation_preview(payload: dict = Body(default_factory=dict)):
        """
        Analyze a PowerBI_Tool Report_Documentation.xlsx workbook without writing.

        Body: {
            "documentation_path": "/path/to/Report_Documentation.xlsx",
            "dataset": "optional dataset filter",
            "report": "optional report filter"
        }
        """
        documentation_path = str(payload.get("documentation_path") or payload.get("xlsx_path") or "").strip()
        if not documentation_path:
            return _err(400, "documentation_path is required")

        workbook_path = Path(documentation_path)
        if not workbook_path.is_file():
            return _err(400, f"Not a file: {documentation_path}")

        try:
            from dax_project.report_documentation_canonical import preview_report_documentation_transfer
            preview = preview_report_documentation_transfer(
                workbook_path,
                dataset=str(payload.get("dataset") or "").strip() or None,
                report=str(payload.get("report") or "").strip() or None,
                include_parameters=bool(payload.get("include_parameters", False)),
                parameter_limit=int(payload.get("parameter_limit", 100)),
            )
        except Exception as exc:
            return _err(400, f"Failed to analyze report documentation: {exc}")

        return _ok(preview)

    @app.post("/runtime/report-transfer/documentation/execute")
    def runtime_report_documentation_execute(payload: dict = Body(default_factory=dict)):
        """
        Execute Report_Documentation.xlsx -> project report transfer.

        Body: {
            "documentation_path": "/path/to/Report_Documentation.xlsx",
            "output_project": "my_project" | "/absolute/path/to/project",
            "skip_unsupported": true,
            "preserve_unsupported": true,
            "merge_existing": false
        }
        """
        documentation_path = str(payload.get("documentation_path") or payload.get("xlsx_path") or "").strip()
        if not documentation_path:
            return _err(400, "documentation_path is required")

        output_project = str(payload.get("output_project") or "").strip()
        if not output_project:
            output_project = os.environ.get("DAX_PROJECT_PATH", "")
        if not output_project:
            return _err(400, "output_project is required (or set DAX_PROJECT_PATH)")

        workbook_path = Path(documentation_path)
        if not workbook_path.is_file():
            return _err(400, f"Not a file: {documentation_path}")

        if not os.path.isabs(output_project):
            output_project = os.path.join(os.getcwd(), output_project)

        try:
            from dax_project.report_documentation_canonical import execute_report_documentation_transfer
            result = execute_report_documentation_transfer(
                workbook_path,
                output_project,
                dataset=str(payload.get("dataset") or "").strip() or None,
                report=str(payload.get("report") or "").strip() or None,
                skip_unsupported=bool(payload.get("skip_unsupported", True)),
                preserve_unsupported=bool(payload.get("preserve_unsupported", True)),
                merge_existing=bool(payload.get("merge_existing", False)),
            )
        except Exception as exc:
            return _err(400, f"Documentation transfer failed: {exc}")

        return _ok(result.to_dict())

    @app.post("/runtime/report-transfer/theme")
    def runtime_report_transfer_theme(payload: dict = Body(default_factory=dict)):
        """
        Extract PBI theme from a PBIR .Report directory and optionally
        apply it to the current project.

        Body: {
            "report_dir": "/path/to/Model.Report",
            "apply": false          // if true, saves as reporting_theme.json
        }

        Returns the extracted theme in ReportingTheme format.
        """
        report_dir = str(payload.get("report_dir") or "").strip()
        if not report_dir:
            return _err(400, "report_dir is required")

        rdir = Path(report_dir)
        if not rdir.is_dir():
            return _err(400, f"Not a directory: {report_dir}")

        try:
            from dax_project.report_transfer import extract_pbi_theme
            theme = extract_pbi_theme(report_dir)
        except FileNotFoundError as exc:
            return _err(400, str(exc))
        except Exception as exc:
            return _err(400, f"Failed to extract theme: {exc}")

        should_apply = bool(payload.get("apply", False))
        if should_apply:
            # Save as the project's reporting theme
            project_path = os.environ.get("DAX_PROJECT_PATH", "")
            if not project_path:
                return _err(400, "No project loaded (DAX_PROJECT_PATH not set)")
            if not os.path.isabs(project_path):
                project_path = os.path.join(os.getcwd(), project_path)

            # Remove _pbi_meta before saving (it's preview-only)
            save_theme = {k: v for k, v in theme.items() if not k.startswith("_")}
            reports_dir = Path(project_path) / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            theme_path = reports_dir / "reporting_theme.json"
            import json
            with open(theme_path, "w", encoding="utf-8") as f:
                json.dump(save_theme, f, indent=2, ensure_ascii=False)

        return _ok(theme)
