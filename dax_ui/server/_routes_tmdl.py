"""
Server routes for the TMDL → Project converter.

Provides endpoints to:
- Preview a TMDL folder (parse and return metadata without writing)
- Convert a TMDL folder into a project directory
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import Body
from fastapi.responses import JSONResponse


def register_tmdl_converter_routes(app):
    """Register TMDL converter endpoints on the FastAPI app."""

    from dax_ui.server._runtime_helpers import _ok, _err

    @app.post("/runtime/tmdl/preview")
    def runtime_tmdl_preview(payload: dict = Body(default_factory=dict)):
        """
        Parse a TMDL definition folder and return a preview of the model
        without writing anything to disk.

        Body: {"definition_path": "/path/to/definition/"}
        """
        definition_path = str(payload.get("definition_path") or "").strip()
        if not definition_path:
            return _err(400, "definition_path is required")

        defn = Path(definition_path)
        if not defn.is_dir():
            return _err(400, f"Not a directory: {definition_path}")

        # Check if this looks like a TMDL definition folder
        tables_dir = defn / "tables"
        if not tables_dir.is_dir():
            # Maybe the user pointed at the parent (SemanticModel folder)
            alt = defn / "definition"
            if alt.is_dir() and (alt / "tables").is_dir():
                defn = alt
            else:
                return _err(400, f"No tables/ folder found in {definition_path}. Expected a TMDL definition/ directory.")

        try:
            from dax_project.tmdl_converter import parse_tmdl_folder, _should_skip_table, _extract_data_source
        except ImportError as exc:
            return _err(500, f"tmdl_converter module not available: {exc}")

        try:
            model = parse_tmdl_folder(str(defn))
        except Exception as exc:
            return _err(400, f"Failed to parse TMDL folder: {exc}")

        # Build preview response
        tables = []
        for tbl in model.tables:
            skip = _should_skip_table(tbl.name)
            csv_path = None
            is_calc = False
            for p in tbl.partitions:
                if p.kind == "calculated":
                    is_calc = True
                elif p.kind == "m":
                    src = _extract_data_source(p)
                    if src and src.path:
                        csv_path = src.path

            tables.append({
                "name": tbl.name,
                "columns": len(tbl.columns),
                "measures": len(tbl.measures),
                "hierarchies": len(tbl.hierarchies),
                "is_calculated": is_calc,
                "is_hidden": tbl.is_hidden,
                "has_calc_group": tbl.calc_group is not None,
                "csv_source": csv_path,
                "csv_exists": bool(csv_path and Path(csv_path).exists()),
                "will_skip": skip,
            })

        relationships = []
        for rel in model.relationships:
            relationships.append({
                "from": f"{rel.from_table}.{rel.from_column}",
                "to": f"{rel.to_table}.{rel.to_column}",
                "active": rel.is_active,
            })

        roles = []
        for role in model.roles:
            roles.append({
                "name": role.name,
                "rules": len(role.rules),
            })

        return _ok({
            "definition_path": str(defn),
            "tables": tables,
            "relationships": relationships,
            "roles": roles,
            "summary": {
                "total_tables": len(tables),
                "importable_tables": len([t for t in tables if not t["will_skip"]]),
                "skipped_tables": len([t for t in tables if t["will_skip"]]),
                "total_relationships": len(relationships),
                "total_roles": len(roles),
                "total_measures": sum(t["measures"] for t in tables),
                "data_sources_found": len([t for t in tables if t["csv_exists"]]),
                "data_sources_missing": len([t for t in tables if t["csv_source"] and not t["csv_exists"]]),
            },
        })

    @app.post("/runtime/tmdl/convert")
    def runtime_tmdl_convert(payload: dict = Body(default_factory=dict)):
        """
        Convert a TMDL definition folder into a project directory.

        Body: {
            "definition_path": "/path/to/definition/",
            "output_path": "adventureworks_project",
            "project_name": "AdventureWorks",
            "copy_data": true,
            "skip_hidden_tables": false
        }
        """
        definition_path = str(payload.get("definition_path") or "").strip()
        output_path = str(payload.get("output_path") or "").strip()
        project_name = payload.get("project_name")
        copy_data = payload.get("copy_data", True)
        skip_hidden = payload.get("skip_hidden_tables", False)

        if not definition_path:
            return _err(400, "definition_path is required")
        if not output_path:
            return _err(400, "output_path is required")

        # SEC-16: Validate paths against server-mode restriction
        from dax_ui.server._runtime_helpers import _validate_server_mode_path
        try:
            _validate_server_mode_path(Path(definition_path).resolve(), "definition_path")
        except ValueError as exc:
            return _err(403, str(exc))

        defn = Path(definition_path)
        if not defn.is_dir():
            return _err(400, f"Not a directory: {definition_path}")

        # Auto-detect definition/ subfolder
        tables_dir = defn / "tables"
        if not tables_dir.is_dir():
            alt = defn / "definition"
            if alt.is_dir() and (alt / "tables").is_dir():
                defn = alt
            else:
                return _err(400, f"No tables/ folder found in {definition_path}")

        # Resolve output path
        out = Path(output_path)
        if not out.is_absolute():
            # Relative to the workspace root (same level as sample_project)
            workspace = Path(os.environ.get("DAX_PROJECT_PATH", ".")).resolve().parent
            out = workspace / output_path

        # SEC-16: Validate output path against server-mode restriction
        try:
            _validate_server_mode_path(out.resolve(), "output_path")
        except ValueError as exc:
            return _err(403, str(exc))

        try:
            from dax_project.tmdl_converter import convert_tmdl_to_project
        except ImportError as exc:
            return _err(500, f"tmdl_converter module not available: {exc}")

        try:
            result = convert_tmdl_to_project(
                definition_dir=str(defn),
                output_dir=str(out),
                copy_data=copy_data,
                project_name=project_name,
                skip_hidden_tables=skip_hidden,
            )
        except Exception as exc:
            return _err(400, f"Conversion failed: {exc}")

        return _ok({
            "project_path": result.project_path,
            "tables_created": result.tables_created,
            "measures_created": result.measures_created,
            "relationships_created": result.relationships_created,
            "hierarchies_created": result.hierarchies_created,
            "roles_created": result.roles_created,
            "calc_groups_created": result.calc_groups_created,
            "data_files_copied": result.data_files_copied,
            "data_files_missing": result.data_files_missing,
            "skipped_tables": result.skipped_tables,
            "warnings": result.warnings,
        })
