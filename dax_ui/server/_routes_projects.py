"""Local project-management routes shared by all desktop editions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import Body, File as FastAPIFile, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from dax_ui.project_manager import (
    add_recent_project,
    create_new_project,
    export_project_zip,
    import_project_zip,
    list_directories,
    load_recent_projects,
    refresh_project_data,
    remove_recent_project,
    save_project_as,
)
from dax_ui.server._runtime_helpers import (
    _invalidate_engine_cache_for_project,
    _resolve_project_path_runtime,
    _validate_runtime_path,
)


def _ok(payload: dict) -> dict:
    return {"ok": True, **payload}


def _err(status_code: int, message: str) -> JSONResponse:
    del message
    safe_message = {
        400: "The project operation could not be completed.",
        403: "The selected path is not allowed.",
        404: "The requested project was not found.",
        413: "The uploaded project is too large.",
    }.get(status_code, "An internal project error occurred.")
    return JSONResponse(status_code=status_code, content={"ok": False, "error": safe_message})


def _selected_path(raw: str, label: str, *, must_exist: bool = False) -> Path:
    """Normalize a user-selected path and enforce the active runtime policy."""
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    resolved = Path(value).expanduser().resolve()
    _validate_runtime_path(resolved, label)
    if must_exist and (not resolved.exists() or not resolved.is_dir()):
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def register_project_routes(app) -> None:
    """Register desktop project browse/create/import/export operations."""

    @app.get("/runtime/project/recent")
    def project_recent():
        return _ok({"projects": load_recent_projects()})

    @app.post("/runtime/project/recent/add")
    async def project_recent_add(body: dict = Body(default_factory=dict)):
        try:
            project = _selected_path(body.get("path", ""), "Project path", must_exist=True)
            if not (project / "model").is_dir():
                return _err(400, "Selected folder is not a Dummy BI Engine project")
            projects = add_recent_project(str(project), str(body.get("name") or "").strip() or None)
            return _ok({"projects": projects})
        except ValueError as exc:
            return _err(403, str(exc))
        except FileNotFoundError as exc:
            return _err(400, str(exc))

    @app.post("/runtime/project/recent/remove")
    async def project_recent_remove(body: dict = Body(default_factory=dict)):
        path = str(body.get("path") or "").strip()
        if not path:
            return _err(400, "path is required")
        return _ok({"projects": remove_recent_project(path)})

    @app.get("/runtime/project/browse")
    def project_browse(path: Optional[str] = None):
        configured = os.environ.get("DAX_PROJECT_PATH", "").strip()
        if configured and not Path(configured).expanduser().is_dir():
            configured = ""
        base = path or configured or os.getcwd()
        try:
            current = _selected_path(base, "Browse path", must_exist=True)
            return _ok({"current": str(current), "items": list_directories(str(current))})
        except ValueError as exc:
            return _err(403, str(exc))
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return _err(400, str(exc))

    @app.post("/runtime/project/create")
    async def project_create(body: dict = Body(default_factory=dict)):
        try:
            target = _selected_path(body.get("path", ""), "Project path")
            name = str(body.get("name") or "").strip() or None
            resolved = create_new_project(str(target), name)
            return _ok({"project": resolved, "name": name or Path(resolved).name})
        except ValueError as exc:
            return _err(400, str(exc))
        except (FileExistsError, OSError) as exc:
            return _err(400, str(exc))

    @app.post("/runtime/project/save_as")
    async def project_save_as(body: dict = Body(default_factory=dict)):
        try:
            source = _selected_path(body.get("source", ""), "Source project", must_exist=True)
            target = _selected_path(body.get("target", ""), "Target project")
            resolved = save_project_as(str(source), str(target))
            return _ok({"project": resolved, "name": Path(resolved).name})
        except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
            return _err(400, str(exc))

    @app.get("/runtime/project/export")
    def project_export(project: Optional[str] = None):
        try:
            resolved = _resolve_project_path_runtime(project)
            archive = export_project_zip(resolved)
            filename = Path(resolved).name.replace('"', "") or "dummy-bi-project"
            return StreamingResponse(
                archive,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{filename}.zip"'},
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            return _err(400, str(exc))

    max_upload_bytes = int(os.environ.get("DAX_MAX_UPLOAD_BYTES", 100 * 1024 * 1024))

    @app.post("/runtime/project/import")
    async def project_import(
        file: UploadFile = FastAPIFile(...),
        target: Optional[str] = None,
    ):
        try:
            destination = _selected_path(target or "", "Target project")
            chunks: list[bytes] = []
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_upload_bytes:
                    return _err(413, f"Upload exceeds maximum size of {max_upload_bytes} bytes")
                chunks.append(chunk)
            resolved = import_project_zip(b"".join(chunks), str(destination))
            return _ok({"project": resolved, "name": Path(resolved).name})
        except (ValueError, FileNotFoundError, OSError) as exc:
            return _err(400, str(exc))

    @app.post("/runtime/project/refresh")
    async def project_refresh(body: dict = Body(default_factory=dict)):
        try:
            project = _resolve_project_path_runtime(str(body.get("project") or ""))
            _invalidate_engine_cache_for_project(project)
            return _ok(refresh_project_data(project))
        except (ValueError, FileNotFoundError, OSError) as exc:
            return _err(400, str(exc))
