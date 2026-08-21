"""Shared runtime route helpers extracted from _runtime_routes.

These are the foundational utilities used by virtually every route handler:
_ok, _err, _resolve_project_path_runtime, _measure_to_json, etc.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from fastapi.responses import JSONResponse

from dax_ui.server._engine import (
    _norm_project_key,
    _ENGINE_LOCK,
    _ENGINE_CACHE,
)
import dax_ui.server._engine as _engine_mod

logger = logging.getLogger(__name__)

_PUBLIC_RUNTIME_ERRORS = {
    "OAuth completion requires a token/secret payload or mock_oauth=true.": (
        "OAuth completion requires a token/secret payload or mock_oauth=true."
    ),
}

__all__ = [
    "_sorted_pages",
    "_select_page_id",
    "_ok",
    "_err",
    "_slicer_error_code_from_exc",
    "_resolve_project_path_runtime",
    "_invalidate_engine_cache_for_project",
    "_measure_to_json",
    "_table_to_json",
    "_coalesce_expr_payload",
    "_coalesce_limit",
    "_describe_columns_from_from_source",
]

def _sorted_pages(pages: list[Any]) -> list[Any]:
    # Stable: by order (if present), else file order.
    indexed = list(enumerate(pages))
    indexed.sort(key=lambda it: (getattr(it[1], "order", None) is None, getattr(it[1], "order", 0) or 0, it[0]))
    return [p for _i, p in indexed]


def _select_page_id(pages: list[Any], requested: Optional[str]) -> str:
    if not pages:
        return "page1"
    pages_sorted = _sorted_pages(pages)
    page_ids = {getattr(p, "id", "").upper(): getattr(p, "id", "") for p in pages_sorted}
    if requested is None or str(requested).strip() == "":
        return getattr(pages_sorted[0], "id", "page1") or "page1"
    key = str(requested).strip().upper()
    if key not in page_ids:
        raise ValueError(f"Unknown page: {requested!r}")
    return page_ids[key]


def _ok(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": True, **dict(payload)}


def _err(status_code: int, message: str, **extra: Any) -> JSONResponse:
    logger.warning("Runtime request failed: %s", message)
    public_message = _PUBLIC_RUNTIME_ERRORS.get(message, "Runtime request failed")
    body: dict[str, Any] = {"ok": False, "error": public_message}
    body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


def _slicer_error_code_from_exc(exc: Exception, *, default: str) -> str:
    """Map exceptions to stable slicer error codes.

    UI must not display raw backend error strings; it maps these codes.
    """

    if isinstance(exc, ValueError):
        msg = str(exc)
        msg_l = msg.lower()
        if "slicer default" in msg_l and ("measure" in msg_l or "defaults" in msg_l):
            return "E_SLICER_DEFAULT_FAILED"
        if "date binding required" in msg_l or "date_range" in msg_l and "binding" in msg_l and "date" in msg_l:
            return "E_SLICER_DATE_BINDING_REQUIRED"
        if "unknown table" in msg_l or "unknown column" in msg_l:
            return "E_SLICER_INVALID_BINDING"
        # Treat missing/empty bindings as invalid field selection.
        # This keeps UI messaging deterministic when a user clears a table/column.
        if "column.table" in msg_l and "column.column" in msg_l and "required" in msg_l:
            return "E_SLICER_INVALID_BINDING"
        return "E_SLICER_VALIDATION_FAILED"
    return default


def _validate_server_mode_path(resolved: Path, label: str = "Path") -> None:
    """SEC-14: Reject paths outside DAX_PROJECT_PATH when DAX_SERVER_MODE=server."""
    mode = os.environ.get("DAX_SERVER_MODE", "author")
    if mode != "server":
        return
    allowed_root = os.environ.get("DAX_PROJECT_PATH", "").strip()
    if not allowed_root:
        return
    allowed_resolved = Path(allowed_root).resolve()
    try:
        resolved.relative_to(allowed_resolved)
    except ValueError:
        raise ValueError(
            f"{label} must be within the configured DAX_PROJECT_PATH. "
            f"Resolved path is outside the allowed root."
        )


def _resolve_project_path_runtime(project: Optional[str]) -> str:
    # Contract: accept ?project= or env DAX_PROJECT_PATH.
    path = (project or os.environ.get("DAX_PROJECT_PATH") or "").strip()
    if not path:
        raise ValueError("project not provided")
    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(str(p))
    resolved = p.resolve()

    # SEC-09 / SEC-14: In server mode, restrict to the configured project root(s).
    _validate_server_mode_path(resolved, "Project path")

    return str(resolved)


def _invalidate_engine_cache_for_project(project_path: str) -> None:
    """Drop cached compiled measures/relationships so changes take effect immediately."""

    project_key = _norm_project_key(project_path)
    with _ENGINE_LOCK:
        _ENGINE_CACHE.pop(project_key, None)
        active = _engine_mod._ACTIVE_ENGINE
        if active is not None and active[0] == project_key:
            _engine_mod._ACTIVE_ENGINE = None

    # Also invalidate the load_project() mtime-based cache so the next
    # render picks up the freshly saved model files.
    try:
        from dax_project import invalidate_load_project_cache
        invalidate_load_project_cache(project_path)
    except ImportError:
        pass

    # Invalidate the per-thread DuckDB connection cache so the next render
    # opens a fresh connection with updated sources / calc tables.
    try:
        from dax_ui.server._duckdb import invalidate_duckdb_connection_cache
        invalidate_duckdb_connection_cache()
    except ImportError:
        pass

    # Invalidate render result + SQL plan caches so stale data is not served.
    try:
        from dax_ui.server._render_cache import invalidate_all_caches
        invalidate_all_caches()
    except ImportError:
        pass


def _measure_to_json(m: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(m, "name", "")),
        "dax": str(getattr(m, "dax", "")),
        "description": getattr(m, "description", None),
        "folder": getattr(m, "folder", None),
        "format": getattr(m, "format", None),
    }


def _table_to_json(t: Any) -> dict[str, Any]:
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
    return {
        "name": str(getattr(t, "name", "")),
        "expression": getattr(t, "expression", None),
        "is_calculated": bool(getattr(t, "is_calculated", False)),
        "description": getattr(t, "description", None),
        "folder": getattr(t, "folder", None),
        "columns": cols,
    }


def _coalesce_expr_payload(payload: Mapping[str, Any]) -> Optional[str]:
    # Back-compat: accept both {expression: ...} and older {dax: ...}
    v = payload.get("expression")
    if isinstance(v, str) and v.strip():
        return v
    v2 = payload.get("dax")
    if isinstance(v2, str) and v2.strip():
        return v2
    return None


def _coalesce_limit(payload: Mapping[str, Any], *, default: int) -> int:
    v = payload.get("limit")
    try:
        n = int(v)
    except Exception:
        n = int(default)
    if n <= 0:
        n = int(default)
    # Keep previews bounded.
    return min(n, 1000)


def _describe_columns_from_from_source(con: Any, from_source_sql: str) -> list[dict[str, str]]:
    q = f"DESCRIBE SELECT * FROM {from_source_sql}"
    rows = con.execute(q).fetchall()
    out: list[dict[str, str]] = []
    for r in rows:
        if not r:
            continue
        name = str(r[0])
        typ = str(r[1]) if len(r) > 1 else "UNKNOWN"
        out.append({"name": name, "type": typ})
    return out
