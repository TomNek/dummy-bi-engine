from contextlib import asynccontextmanager
import copy
import datetime
import json
import time
import logging
import os
import threading
import uuid
import sys
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

from starlette.requests import Request

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

import dax_compiler
from dax_engine.ir import MeasureRef, ir_to_dict
from dax_engine.planner import VisualQuerySpec, plan_card_query, plan_visual_query
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
# --- Enterprise modules (conditional) ---
try:
    from dax_ui.server.routes_enterprise import (
        register_enterprise_routes as _register_enterprise_routes,
        _get_viewer_manager,
    )
    _HAS_ENTERPRISE_ROUTES = True
except ImportError:
    _HAS_ENTERPRISE_ROUTES = False
    _get_viewer_manager = None  # type: ignore[assignment]

try:
    from dax_ui.server._explanations import (
        _generate_explanation_narrative,
        _serialize_explanation_node,
        _dim_key_for_row,
        _resolve_supplementary_explanation_metrics,
        _precompute_row_dimensional_lookup,
        _execute_explanation_bindings,
    )
except ImportError:
    logging.getLogger(__name__).info("Enterprise explanations module not available — Community Edition")

# Enterprise types used in annotation positions inside _runtime_routes.
# In community edition these resolve to ``type(None)`` so the inner ``def``
# statements still parse without error (the routes themselves are unreachable).
try:
    from dax_engine.explanations.loader import Playbook
    from dax_engine.explanations.engine import ExplanationEngine
    from dax_engine.explanations.models import ExplanationNode
    from dax_engine.explanations.evidence import EvidenceResolver
except ImportError:
    Playbook = type(None)  # type: ignore[misc,assignment]
    ExplanationEngine = type(None)  # type: ignore[misc,assignment]
    ExplanationNode = type(None)  # type: ignore[misc,assignment]
    EvidenceResolver = type(None)  # type: ignore[misc,assignment]

# --- Community helper modules ---
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


# --- Version helpers (module-level, used by /runtime/meta + desktop) -------
def _get_version() -> str:
    try:
        from dax_ui.version import __version__
        return __version__
    except Exception:
        return "unknown"


def _get_build() -> str:
    try:
        from dax_ui.version import __build__
        return __build__
    except Exception:
        return "unknown"


class OlsVisualBlockedError(Exception):
    def __init__(self, message: str, *, hidden_refs: Optional[list[dict[str, Any]]] = None):
        super().__init__(message)
        self.hidden_refs = hidden_refs or []




















































































































































def create_app() -> "FastAPI":
    import html as _html_mod

    try:
        from fastapi import FastAPI, Form
        from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
        from fastapi.staticfiles import StaticFiles
        from fastapi.templating import Jinja2Templates
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "FastAPI UI dependencies missing. Install: pip install -r requirements-ui.txt"
        ) from exc

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server_file = Path(__file__).resolve()
        repo_root = server_file.parents[2]
        marker = repo_root / "instructions.md"
        logger.info("[runtime] startup cwd=%s server=%s", os.getcwd(), str(server_file))
        if not getattr(sys, "frozen", False) and not marker.exists():
            logger.warning(
                "[runtime] WARNING: expected marker %s missing; you may be running a different repo/cwd than intended",
                str(marker),
            )
        starter = getattr(app.state, "_start_subscription_dispatcher", None)
        if callable(starter):
            try:
                starter()
            except Exception as exc:
                logger.warning("[subscriptions] failed to start dispatcher: %s", exc)
        try:
            yield
        finally:
            stopper = getattr(app.state, "_stop_subscription_dispatcher", None)
            if callable(stopper):
                try:
                    stopper()
                except Exception as exc:
                    logger.warning("[subscriptions] failed to stop dispatcher: %s", exc)

    app = FastAPI(title="Semantic Migration Workbench", lifespan=lifespan)

    # Desktop token auth middleware (active only when DAX_DESKTOP_TOKEN is set)
    try:
        from dax_ui.desktop_auth import DesktopTokenMiddleware
        app.add_middleware(DesktopTokenMiddleware)
    except ImportError:
        pass  # Community edition — middleware not available (no-op when DAX_DESKTOP_TOKEN is unset anyway)

    # Server-mode API key auth (active when DAX_SERVER_MODE=server)
    try:
        from dax_ui.server_auth import ServerAuthMiddleware
        app.add_middleware(ServerAuthMiddleware)
    except ImportError:
        pass  # Community edition — middleware not available (no-op in author mode anyway)

    # Role-based access guard (active when DAX_SERVER_MODE=server)
    try:
        from dax_ui.role_guard import RoleGuardMiddleware
        app.add_middleware(RoleGuardMiddleware)
    except ImportError:
        pass  # Community edition — middleware not available (no-op in author mode anyway)

    # Security middleware (rate limiting, headers, body size, CSRF)
    from dax_ui.server._security_middleware import (
        BodySizeLimitMiddleware,
        CSRFMiddleware,
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )
    app.add_middleware(SecurityHeadersMiddleware)   # SEC-07: response headers
    app.add_middleware(RateLimitMiddleware)          # SEC-03: per-IP rate limiting
    app.add_middleware(BodySizeLimitMiddleware)      # SEC-12: request body size limit
    app.add_middleware(CSRFMiddleware)               # SEC-19: CSRF protection

    dax_ui_dir = Path(__file__).resolve().parents[1]
    templates = Jinja2Templates(directory=str(dax_ui_dir / "templates"))

    static_dir = dax_ui_dir / "static"
    if static_dir.exists() and static_dir.is_dir():
        runtime_js = static_dir / "runtime.js"
        runtime_css = static_dir / "runtime.css"

        @app.get("/static/runtime.js")
        def _static_runtime_js():
            if not runtime_js.exists():
                return HTMLResponse("Not found", status_code=404)
            return FileResponse(
                str(runtime_js),
                media_type="application/javascript",
                headers={"Cache-Control": "no-store"},
            )

        @app.get("/static/runtime.css")
        def _static_runtime_css():
            if not runtime_css.exists():
                return HTMLResponse("Not found", status_code=404)
            return FileResponse(
                str(runtime_css),
                media_type="text/css",
                headers={"Cache-Control": "no-store"},
            )

        # Mount remaining static assets.
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists() and frontend_dist.is_dir():
        react_index = frontend_dist / "index.html"
        react_assets = frontend_dist / "assets"
        react_vite_svg = frontend_dist / "vite.svg"

        if react_assets.exists() and react_assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(react_assets)), name="react-assets")

        if react_vite_svg.exists():
            @app.get("/vite.svg")
            def _react_vite_svg():
                return FileResponse(
                    str(react_vite_svg),
                    media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"},
                )

        # Serve app icons from frontend dist (favicon + React UI topbar logo)
        react_app_icon = frontend_dist / "app-icon.png"
        if react_app_icon.exists():
            @app.get("/app-icon.png")
            def _react_app_icon():
                return FileResponse(
                    str(react_app_icon),
                    media_type="image/png",
                    headers={"Cache-Control": "no-store"},
                )

        react_app_icon_32 = frontend_dist / "app-icon-32.png"
        if react_app_icon_32.exists():
            @app.get("/app-icon-32.png")
            def _react_app_icon_32():
                return FileResponse(
                    str(react_app_icon_32),
                    media_type="image/png",
                    headers={"Cache-Control": "no-store"},
                )

    @app.get("/runtime/ui-react", response_class=HTMLResponse)
    def runtime_ui_react_page(project: Optional[str] = None):
        label_text = "Project: (loading)"
        raw_project = None
        if project is not None and str(project).strip():
            raw_project = str(project).strip()
        else:
            env_path = (os.environ.get("DAX_PROJECT_PATH") or "").strip()
            if env_path:
                raw_project = env_path
        if raw_project:
            label_text = f"Project: {_html_mod.escape(str(Path(raw_project).name))}"
        react_index = frontend_dist / "index.html"
        if not react_index.exists():
            return HTMLResponse(
                f"<div data-testid=\"project-label\" style=\"padding:6px 10px; font-size:12px; color:#666;\">{label_text}</div>",
                status_code=200,
            )
        html = react_index.read_text(encoding="utf-8")
        if "data-testid=\"project-label\"" not in html:
            html = html.replace(
                "<div id=\"root\"></div>",
                f"<div id=\"root\"><div data-testid=\"project-label\" style=\"padding:6px 10px; font-size:12px; color:#666;\">{label_text}</div></div>",
            )
        elif raw_project:
            html = html.replace("Project: (loading)", label_text)
            html = html.replace("Project: (none)", label_text)
        # Inject desktop token into HTML (if running in desktop mode)
        desktop_token = os.environ.get("DAX_DESKTOP_TOKEN", "")
        if desktop_token:
            import json as _json
            safe_token = _json.dumps(desktop_token)  # SEC-21: prevent XSS
            token_script = f'<script>window.__DESKTOP_TOKEN__={safe_token};</script>'
            html = html.replace("</head>", f"{token_script}</head>")
        return HTMLResponse(html)

    @app.get("/server/ui", response_class=HTMLResponse)
    def server_management_ui():
        """Report Server management UI ΓÇö served from the same React build."""
        react_index = frontend_dist / "index.html"
        if not react_index.exists():
            return HTMLResponse(
                "<h3>React build not found</h3><p>Run <code>npm run build</code> in dax_ui/frontend/</p>",
                status_code=200,
            )
        html = react_index.read_text(encoding="utf-8")
        # Strip the project-label placeholder ΓÇö server UI doesn't need it
        html = html.replace(
            '<div data-testid="project-label" style="padding:6px 10px; font-size:12px; color:#666;">Project: (loading)</div>',
            '',
        )
        return HTMLResponse(html)

    @app.get("/runtime/ui", response_class=HTMLResponse)
    def runtime_ui_page(project: Optional[str] = None, legacy: bool = False):
        # React UI is authoritative. Keep the legacy static UI reachable only
        # via explicit opt-in for debugging.
        if not legacy:
            return runtime_ui_react_page(project=project)

        html_path = Path(__file__).parents[1] / "static" / "runtime.html"
        if not html_path.exists():
            return HTMLResponse("Runtime UI not found.", status_code=404)
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/runtime/ui-legacy", response_class=HTMLResponse)
    def runtime_ui_legacy_page():
        html_path = Path(__file__).parents[1] / "static" / "runtime.html"
        if not html_path.exists():
            return HTMLResponse("Runtime UI not found.", status_code=404)
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/canvas", response_class=HTMLResponse)
    def canvas_page(project: Optional[str] = None):
        # Back-compat alias for /runtime/ui.
        return runtime_ui_page(project=project)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, project: Optional[str] = None, msg: Optional[str] = None):
        error = None
        measures = []
        project_path = None
        try:
            if project is not None or os.environ.get("DAX_PROJECT_PATH"):
                project_path = _resolve_project_path(project)
                model, _pages, _visuals = load_project(project_path)
                measures = list_measures(model)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "project": project_path or (project or os.environ.get("DAX_PROJECT_PATH") or ""),
                "measures": measures,
                "error": error,
                "msg": msg,
            },
        )

    @app.get("/measure/{name}", response_class=HTMLResponse, name="get_measure")
    def edit_measure(request: Request, name: str, project: Optional[str] = None, msg: Optional[str] = None):
        project_path = _resolve_project_path(project)
        model, _pages, _visuals = load_project(project_path)
        m = get_measure(model, name)
        if m is None:
            raise ValueError(f"Unknown measure: {name!r}")

        return templates.TemplateResponse(
            "measure.html",
            {
                "request": request,
                "project": project_path,
                "measure": m,
                "msg": msg,
                "validate": None,
            },
        )

    @app.post("/measure/{name}/save")
    def save_measure(
        request: Request,
        name: str,
        project: Optional[str] = None,
        dax: str = Form(""),
        description: str = Form(""),
        folder: str = Form(""),
        format: str = Form(""),
    ):
        project_path = _resolve_project_path(project)
        update_measure_yaml(
            project_path,
            name=name,
            dax=dax,
            description=description,
            folder=folder,
            format=format,
        )

        # Roundtrip reload after save.
        model, _pages, _visuals = load_project(project_path)
        if get_measure(model, name) is None:
            raise RuntimeError("Measure save failed: measure not found after reload")

        url = request.url_for("get_measure", name=name)
        return RedirectResponse(url=f"{url}?project={project_path}&msg=Saved", status_code=303)

    @app.post("/measure/{name}/validate", response_class=HTMLResponse)
    def validate_measure(
        request: Request,
        name: str,
        project: Optional[str] = None,
        dax: str = Form(""),
        description: str = Form(""),
        folder: str = Form(""),
        format: str = Form(""),
    ):
        project_path = _resolve_project_path(project)

        # Validate without forcing a save: run against the current on-disk project.
        model, _pages, _visuals = load_project(project_path)
        m = get_measure(model, name)
        if m is None:
            raise ValueError(f"Unknown measure: {name!r}")

        result = _validate_measure(project_path, name)
        return templates.TemplateResponse(
            "measure.html",
            {
                "request": request,
                "project": project_path,
                "measure": m,
                "msg": None,
                "validate": result,
                # Preserve the form fields shown to the user.
                "draft": {"dax": dax, "description": description, "format": format},
            },
        )

    # --- Enterprise routes (conditional) ---
    # Register these first: Starlette resolves duplicate paths in registration
    # order, while community-only builds still receive the explicit 501 stubs.
    if _HAS_ENTERPRISE_ROUTES:
        _register_enterprise_routes(app)
        logger.info("DAX Engine — Enterprise Edition")
    else:
        logger.info("DAX Engine — Community Edition (AGPL-3.0)")

    _runtime_routes(app)
    _phase14_routes(app)

    return app


def _require_plotly():
    try:
        import pandas as pd  # noqa: F401
        import plotly.express as px  # noqa: F401
        import plotly.graph_objects as go  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Plotly runtime deps missing. Install: pip install -r requirements-ui.txt") from exc


def _filter_kwargs_by_signature(func: Any, kwargs: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Filter kwargs by function signature.

    - If func accepts **kwargs, do not filter.
    - Always drop keys whose value is None.
    - Returns (filtered_kwargs, dropped_kwargs).
    """

    import inspect

    # Remove None-valued kwargs quietly; these are not "unsupported", just absent.
    src = {k: v for k, v in dict(kwargs).items() if v is not None}
    dropped: dict[str, Any] = {}

    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        # Best-effort: if we can't introspect, pass through.
        return (src, dropped)

    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return (src, dropped)

    allowed = set(sig.parameters.keys())
    filtered: dict[str, Any] = {}
    for k, v in src.items():
        if k in allowed:
            filtered[k] = v
        else:
            dropped[k] = v

    return (filtered, dropped)


def _json_safe(obj: Any) -> Any:
    return _json_safe_with_path(obj, path="$", strict=True)


def _test_update_selected_values(*, op: Any, values: Any, clicked: Any, list_order: Any) -> list[Any]:
    """Mirror dax_ui/static/runtime.js:updateSelectedValues.

    This is intentionally small and deterministic to enable regressions without a
    browser/JS runtime. Do not use for production behavior.
    """

    def _key(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    o = str(op or "").strip().lower()
    cur = list(values) if isinstance(values, list) else []
    key = _key(clicked)

    if o == "=":
        return [clicked]
    if o != "in":
        return [clicked]

    selected = {_key(v) for v in cur}
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)

    order = list_order if isinstance(list_order, list) else None
    if order:
        return [v for v in order if _key(v) in selected]

    out = [v for v in cur if _key(v) in selected]
    if key in selected and not any(_key(v) == key for v in out):
        out.append(clicked)
    return out


def _test_highlight_match(*, visual_encodings: Any, selection: Any) -> dict[str, Any]:
    """Test helper for highlight-mode matching.

    Contract (frontend MVP): pick a categorical axis ColumnRef for the visual:
    - encodings.x first
    - else encodings.color
    - else encodings.y (horizontal bar)

    Normalize to colKey: '<table>::<column>' (lowercased)
    Match if selection.colKey equals computed colKey.
    """

    axis = "none"
    col_key = ""

    enc = visual_encodings if isinstance(visual_encodings, Mapping) else {}

    def _colref_key(obj: Any) -> str:
        if not isinstance(obj, Mapping):
            return ""
        if str(obj.get("type") or "") != "ColumnRef":
            return ""
        t = str(obj.get("table") or "").strip().lower()
        c = str(obj.get("column") or "").strip().lower()
        if not t or not c:
            return ""
        return f"{t}::{c}"

    x_key = _colref_key(enc.get("x"))
    if x_key:
        axis, col_key = "x", x_key
    else:
        color_key = _colref_key(enc.get("color"))
        if color_key:
            axis, col_key = "color", color_key
        else:
            y_key = _colref_key(enc.get("y"))
            if y_key:
                axis, col_key = "y", y_key

    sel = selection if isinstance(selection, Mapping) else {}
    sel_key = str(sel.get("colKey") or "").strip().lower()

    return {
        "match": bool(col_key and sel_key and sel_key == col_key),
        "axis": axis,
        "colKey": (col_key or None),
    }


import re as _re_mod


_UNSAFE_NAME_RE = _re_mod.compile(r'[<>"/\\|?*]|\.\.|\x00')
_MAX_NAME_LENGTH = 256


def _validate_safe_name(name: str, *, label: str = "name") -> None:
    """Reject names with HTML tags, path traversal, control chars, or excess length.

    Raises ValueError with a descriptive message if the name is unsafe.
    """
    if not name or not name.strip():
        raise ValueError(f"{label} is required")
    if len(name) > _MAX_NAME_LENGTH:
        raise ValueError(f"{label} exceeds maximum length ({_MAX_NAME_LENGTH} chars)")
    if _UNSAFE_NAME_RE.search(name):
        raise ValueError(
            f"{label} contains forbidden characters (angle brackets, slashes, "
            f"quotes, path traversal, or null bytes are not allowed)"
        )
    # Reject control characters (except space/tab)
    if any(ord(c) < 0x20 and c not in (' ', '\t') for c in name):
        raise ValueError(f"{label} contains control characters")


def _json_safe_with_path(obj: Any, *, path: str, strict: bool) -> Any:
    """Return a JSON-serializable equivalent of obj.

    If strict=True, raises TypeError with a path-specific message for unsupported
    objects instead of silently stringifying.
    """

    # Primitives
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    # pathlib.Path
    if isinstance(obj, Path):
        return str(obj)

    # datetime/date
    try:
        import datetime as _dt

        if isinstance(obj, (_dt.datetime, _dt.date)):
            return obj.isoformat()
    except Exception:
        pass

    # decimal.Decimal
    try:
        from decimal import Decimal as _Decimal

        if isinstance(obj, _Decimal):
            return float(obj)
    except Exception:
        pass

    # numpy scalars/arrays
    try:
        import numpy as _np  # type: ignore

        if isinstance(obj, _np.generic):
            return _json_safe_with_path(obj.item(), path=path, strict=strict)
        if isinstance(obj, _np.ndarray):
            return _json_safe_with_path(obj.tolist(), path=path, strict=strict)
    except Exception:
        pass

    # pandas timestamp-like objects
    try:
        import pandas as _pd  # type: ignore

        if isinstance(obj, _pd.Timestamp):
            return obj.isoformat()
        if isinstance(obj, _pd.DatetimeIndex):
            return [ts.isoformat() for ts in obj.to_pydatetime().tolist()]
        if isinstance(obj, _pd.Series):
            return _json_safe_with_path(obj.tolist(), path=path, strict=strict)
    except Exception:
        pass

    # mappings
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            ks = k if isinstance(k, str) else str(k)
            if ks.isidentifier():
                child_path = f"{path}.{ks}"
            else:
                child_path = f"{path}[{json.dumps(ks)}]"
            out[ks] = _json_safe_with_path(v, path=child_path, strict=strict)
        return out

    # sequences
    if isinstance(obj, (list, tuple, set)):
        return [
            _json_safe_with_path(v, path=f"{path}[{i}]", strict=strict)
            for i, v in enumerate(list(obj))
        ]

    if strict:
        raise TypeError(
            f"Unsupported non-JSON value at {path}: {type(obj).__name__}"
        )
    return str(obj)


def _render_plotly_figure(
    *,
    visual_type: str,
    registry: Mapping[str, Any],
    df: Any,
    resolved_encodings: Mapping[str, Any],
    advanced_patch: Optional[Mapping[str, Any]],
    format_options: Optional[Mapping[str, Any]] = None,
    theme_colors: Optional[list[str]] = None,
    theme_font: Optional[str] = None,
) -> dict[str, Any]:
    _require_plotly()
    import plotly.express as px
    import plotly.graph_objects as go

    vt = registry.get(visual_type)
    if vt is None:
        raise ValueError(f"Unknown visual_type: {visual_type!r}")

    renderer = getattr(vt, "renderer", "")
    px_func = getattr(vt, "px_func", None)

    if renderer == "table":
        header = {"values": list(df.columns)}
        cells = {"values": [df[c].tolist() for c in df.columns]}
        fig = go.Figure(data=[go.Table(header=header, cells=cells)])
    elif renderer == "card":
        val = None
        if len(df.columns) >= 1 and len(df) >= 1:
            val = df.iloc[0, 0]
        fig = go.Figure()
        fig.update_layout(title=str(val))
    elif renderer == "plotly_express":
        if not isinstance(px_func, str) or not px_func:
            raise ValueError(f"visual_type {visual_type!r} missing px_func")

        func = getattr(px, px_func, None)
        if func is None:
            raise ValueError(f"Unknown plotly.express function: {px_func!r}")

        def _field(slot: str) -> Optional[str]:
            v = resolved_encodings.get(slot)
            if v is None:
                return None
            if isinstance(v, list):
                return _expr_output_name(v[0])
            return _expr_output_name(v)

        def _multi_field(slot: str) -> Optional[list[str]]:
            """Resolve a multi-valued slot (e.g., path, dimensions) to a list of column names."""
            v = resolved_encodings.get(slot)
            if v is None:
                return None
            if isinstance(v, list):
                return [n for n in (_expr_output_name(e) for e in v) if n]
            name = _expr_output_name(v)
            return [name] if name else None

        # ── Build generic kwargs from all slot encodings ─────────
        # Map every slot to a kwarg. _filter_kwargs_by_signature will
        # strip any that the target px function doesn't accept.
        kwargs: dict[str, Any] = {}
        slots = getattr(vt, "slots", {}) or {}
        for slot_name in resolved_encodings:
            if slot_name == "tooltip":
                continue  # handled separately below
            val = resolved_encodings[slot_name]
            slot_spec = slots.get(slot_name)
            slot_multi = bool(getattr(slot_spec, "multi", False)) if slot_spec is not None else False
            if isinstance(val, list):
                # Multi-slot: check if function wants a list (e.g., path, dimensions)
                names = [n for n in (_expr_output_name(e) for e in val) if n]
                if names:
                    kwargs[slot_name] = names
            else:
                name = _expr_output_name(val)
                if name:
                    # For multi-slots (e.g., treemap path), always wrap in a list
                    # even when a single value — px.treemap expects path=[...].
                    kwargs[slot_name] = [name] if slot_multi else name

        # Legacy fallback: "value" slot → "y" for backwards compat
        if "y" not in kwargs and "value" in kwargs:
            kwargs["y"] = kwargs.pop("value")

        # ── Small multiples → facet_col mapping ─────────────────
        # The `small_multiples` encoding slot is a user-friendly alias
        # for Plotly's `facet_col` with `facet_col_wrap` auto-grid.
        if "small_multiples" in kwargs:
            sm_col = kwargs.pop("small_multiples")
            # small_multiples takes priority over explicit facet_col
            if "facet_col" not in kwargs:
                kwargs["facet_col"] = sm_col
            else:
                logger.debug("small_multiples overrides facet_col")
                kwargs["facet_col"] = sm_col
            # Determine grid columns: 0 = auto (ceil(sqrt(n_unique)))
            sm_max_cols = 0
            sm_columns_configured = False
            if format_options and isinstance(format_options, Mapping):
                sm_columns_configured = "smallMultiplesMaxColumns" in format_options
                sm_max_cols = int(format_options.get("smallMultiplesMaxColumns", 0))
            if not sm_columns_configured or sm_max_cols == 0:
                # Auto-calculate from data. Keep a deterministic fallback for
                # lightweight dataframe adapters used by render integrations.
                import math
                n_unique = 4
                if hasattr(df, "columns") and sm_col in df.columns:
                    try:
                        n_unique = int(df[sm_col].nunique())
                    except (AttributeError, KeyError, TypeError):
                        pass
                sm_max_cols = max(1, math.ceil(math.sqrt(n_unique)))
            sm_max_cols = max(1, min(6, sm_max_cols))
            kwargs["facet_col_wrap"] = sm_max_cols
        # ─────────────────────────────────────────────────────────

        tooltip = resolved_encodings.get("tooltip")
        hover_data = None
        if isinstance(tooltip, list):
            hover_data = [n for n in (_expr_output_name(t) for t in tooltip) if n]
        if hover_data:
            kwargs["hover_data"] = hover_data

        # Shortcuts for deterministic ordering below
        x = kwargs.get("x")
        y = kwargs.get("y")
        color = kwargs.get("color")

        # ── Orientation handling ─────────────────────────────────
        # When format_options.orientation == "h", swap x/y so Plotly
        # Express renders horizontal bars.
        fmt_orientation = None
        if format_options and isinstance(format_options, Mapping):
            fmt_orientation = format_options.get("orientation")
        if fmt_orientation == "h" and visual_type in ("bar", "column"):
            kwargs["x"] = y  # swap: value on x-axis
            kwargs["y"] = x  # swap: category on y-axis
            kwargs["orientation"] = "h"
        # ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        # ΓöÇΓöÇ Deterministic ordering ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        # DuckDB may return rows in arbitrary order.  Sort the DataFrame
        # by [color, x] so Plotly Express always creates traces in the
        # same order and places categories consistently on the axis.
        df_columns = getattr(df, "columns", ())
        sort_cols = [c for c in (color, x) if c and c in df_columns]
        if sort_cols and hasattr(df, "sort_values"):
            try:
                df = df.sort_values(sort_cols, na_position="last").reset_index(drop=True)
            except Exception:
                pass  # non-sortable dtype ΓÇô fall through unsorted

        # Build explicit category_orders so Plotly Express fixes axis &
        # legend order regardless of how dataframes arrive.
        cat_orders: dict[str, list] = {}
        for col_name in (x, color):
            if col_name and col_name in df_columns:
                try:
                    cat_orders[col_name] = sorted(df[col_name].dropna().unique().tolist(), key=str)
                except Exception:
                    pass
        if cat_orders:
            kwargs["category_orders"] = cat_orders
        # ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

        # ── Format-option-derived px kwargs ──────────────────────
        # These options map to px function parameters, not layout/trace patches.
        if format_options and isinstance(format_options, Mapping):
            _trendline = format_options.get("trendline")
            if _trendline:
                kwargs["trendline"] = _trendline
                _scope = format_options.get("trendlineScope", "trace")
                if _scope == "overall":
                    kwargs["trendline_scope"] = "overall"
            _marginal_x = format_options.get("marginalX")
            if _marginal_x:
                kwargs["marginal_x"] = _marginal_x
            _marginal_y = format_options.get("marginalY")
            if _marginal_y:
                kwargs["marginal_y"] = _marginal_y
            _log_x = format_options.get("logX")
            if _log_x:
                kwargs["log_x"] = True
            _log_y = format_options.get("logY")
            if _log_y:
                kwargs["log_y"] = True
            _pattern = format_options.get("patternShape")
            if _pattern:
                kwargs["pattern_shape_sequence"] = [_pattern]
            _render_mode = format_options.get("renderMode")
            if _render_mode == "webgl":
                kwargs["render_mode"] = "webgl"
            _color_scale = format_options.get("colorContinuousScale")
            if _color_scale:
                kwargs["color_continuous_scale"] = _color_scale
        # ─────────────────────────────────────────────────────────

        # ── Multi-measure pie handling ────────────────────────────
        # PBI donut charts may have multiple measures in `values` but no
        # `names` dimension.  Melt the DataFrame so each measure becomes
        # a row with (measure_name, measure_value).
        if visual_type == "pie" and "names" not in kwargs:
            import pandas as _pd
            vals = kwargs.get("values")
            if isinstance(vals, list) and len(vals) >= 2:
                melt_cols = [c for c in vals if c in df.columns]
                if melt_cols:
                    # Use label_overrides from the visual for display names
                    col_renames = {}
                    _lo = resolved_encodings.get("_label_overrides") or {}
                    for mc in melt_cols:
                        if mc in _lo:
                            col_renames[mc] = _lo[mc]
                    df = df[melt_cols].melt(var_name="_measure_", value_name="_value_")
                    if col_renames:
                        df["_measure_"] = df["_measure_"].map(lambda m: col_renames.get(m, m))
                    kwargs["names"] = "_measure_"
                    kwargs["values"] = "_value_"
            elif isinstance(vals, str) and vals in df.columns:
                # Single measure, no names: use a constant name
                df = df.copy()
                df["_measure_"] = vals
                kwargs["names"] = "_measure_"
                kwargs["values"] = vals

        filtered_kwargs, dropped_kwargs = _filter_kwargs_by_signature(func, kwargs)
        if dropped_kwargs:
            logger.debug(
                "Dropped unsupported plotly kwargs for %s: %s",
                visual_type,
                sorted(dropped_kwargs.keys()),
            )

        fig = func(df, **filtered_kwargs)
    elif renderer == "graph_objects":
        from dax_ui.server._graph_objects import _render_go_chart
        go_type = getattr(vt, "go_type", None)
        if not go_type:
            raise ValueError(f"visual_type {visual_type!r} missing go_type")
        fig_dict = _render_go_chart(
            go_type=go_type,
            df=df,
            resolved_encodings=resolved_encodings,
            format_options=format_options,
        )
        # go.* charts return a dict directly; skip the fig→dict conversion below
        _apply_professional_defaults(fig_dict, visual_type, theme_font=theme_font)
        # Apply theme colors for graph_objects charts
        if theme_colors:
            fig_dict.setdefault("layout", {})["colorway"] = theme_colors
        if format_options is not None:
            fig_dict = _apply_format_patch_to_figure(fig_dict, format_options, visual_type)
        if advanced_patch:
            fig_dict = _deep_merge(fig_dict, dict(advanced_patch))
        return fig_dict
    else:
        raise ValueError(f"Unsupported renderer: {renderer!r}")

    # Plotly figures often contain numpy arrays, which are not JSON serializable
    # by FastAPI's jsonable_encoder. Prefer Plotly's own JSON conversion.
    fig_dict: dict[str, Any]
    try:
        import plotly.io as pio  # type: ignore

        fig_dict = json.loads(pio.to_json(fig, validate=False))
    except Exception:
        fig_dict = fig.to_dict()

    # ── Professional default aesthetics ──────────────────────────
    # Apply polished defaults before user format options / advanced patch.
    # These make charts look modern & end-user-friendly out of the box.
    _apply_professional_defaults(fig_dict, visual_type, theme_font=theme_font)

    # ── Theme colors ─────────────────────────────────────────────
    # If the project has a reporting theme with dataColors, apply them as
    # default colorway BEFORE format options (which may override).
    if theme_colors:
        fig_dict.setdefault("layout", {})["colorway"] = theme_colors
        # Also apply to individual traces since Plotly Express assigns
        # explicit marker.color that overrides layout.colorway
        for i, t in enumerate(fig_dict.get("data", [])):
            c = theme_colors[i % len(theme_colors)]
            ttype = t.get("type", "")
            if ttype in ("bar", "histogram"):
                t.setdefault("marker", {})["color"] = c
            elif ttype in ("scatter", "scattergl"):
                t.setdefault("marker", {})["color"] = c
                if t.get("line"):
                    t["line"]["color"] = c
                elif t.get("mode") and "lines" in str(t.get("mode", "")):
                    t.setdefault("line", {})["color"] = c
            elif ttype == "pie":
                # Pie/donut: set the full color sequence via marker.colors
                pass  # layout.colorway handles pie charts
    # ─────────────────────────────────────────────────────────────

    # Merge order: base figure → format options → advanced_plotly_patch
    if format_options is not None:
        fig_dict = _apply_format_patch_to_figure(fig_dict, format_options, visual_type)
    if advanced_patch:
        fig_dict = _deep_merge(fig_dict, dict(advanced_patch))
    return fig_dict


def _apply_professional_defaults(fig_dict: dict[str, Any], visual_type: str, *, theme_font: Optional[str] = None) -> None:
    """Mutate *fig_dict* in-place with polished Plotly layout defaults.

    Goals: clean margins, no duplicate title (VisualCard header shows it),
    modern font, better hover, subtle grid, rounded bar corners.
    """
    layout = fig_dict.setdefault("layout", {})

    # Remove default Plotly title — the VisualCard header already shows it
    layout["title"] = {"text": ""}

    # Clean, spacious margins — preserve larger margin.t if already set
    # (e.g., stacked combo charts need more top margin for subplot titles)
    # Hierarchical charts (treemap/sunburst/icicle) have no axes — use minimal margins
    _HIERARCHICAL_TYPES = {"treemap", "sunburst", "icicle"}
    existing_margin = layout.get("margin", {})
    existing_t = existing_margin.get("t", 0) if isinstance(existing_margin, dict) else 0
    if visual_type in _HIERARCHICAL_TYPES:
        layout["margin"] = {"l": 4, "r": 4, "t": max(4, existing_t), "b": 4, "pad": 0}
    else:
        layout["margin"] = {"l": 48, "r": 16, "t": max(8, existing_t), "b": 48, "pad": 4}

    # Transparent backgrounds (theme applied by frontend)
    layout["paper_bgcolor"] = "transparent"
    layout["plot_bgcolor"] = "transparent"

    # Modern font defaults — use theme font if available
    _font_family = theme_font or "Inter, system-ui, -apple-system, sans-serif"
    layout.setdefault("font", {}).update({
        "size": 11,
        "family": _font_family,
    })

    # Subtle grid styling
    for ax_key in ("xaxis", "yaxis"):
        ax = layout.setdefault(ax_key, {})
        ax.setdefault("gridcolor", "rgba(0,0,0,0.06)")
        ax.setdefault("gridwidth", 1)
        ax.setdefault("showline", False)
        ax.setdefault("zeroline", True)
        ax.setdefault("zerolinecolor", "rgba(0,0,0,0.1)")
        ax.setdefault("zerolinewidth", 1)
        # Clean tick styling
        ax.setdefault("tickfont", {"size": 10})
        # Remove axis title overflow for category axes
        if ax_key == "xaxis":
            if not ax.get("title") or not ax.get("title", {}).get("text"):
                ax["title"] = {"text": ""}

    # Better hover mode
    layout.setdefault("hoverlabel", {
        "bgcolor": "white",
        "font": {"size": 11, "family": _font_family},
        "bordercolor": "rgba(0,0,0,0.1)",
    })
    layout.setdefault("hovermode", "x unified" if visual_type in ("line", "area", "combo") else "closest")

    # Legend at bottom for cleanliness (hidden for hierarchical charts — labels are inline)
    if visual_type in _HIERARCHICAL_TYPES:
        layout["showlegend"] = False
    else:
        legend = layout.setdefault("legend", {})
        legend.setdefault("orientation", "h")
        legend.setdefault("yanchor", "top")
        legend.setdefault("y", -0.15)
        legend.setdefault("xanchor", "center")
        legend.setdefault("x", 0.5)
        legend.setdefault("font", {"size": 10})

    # ── Per-type trace polish ─────────────────────────────────
    traces = fig_dict.get("data", [])
    for trace in traces:
        ttype = trace.get("type", "")

        if ttype == "bar":
            # Rounded bar corners (Plotly marker.line gives a clean edge)
            marker = trace.setdefault("marker", {})
            marker.setdefault("line", {"width": 0})
            # Better hover template for bars
            if "hovertemplate" not in trace:
                trace["hovertemplate"] = "%{x}: %{y:,.0f}<extra>%{fullData.name}</extra>"

        elif ttype in ("scatter", "scattergl"):
            mode = trace.get("mode", "")
            if "lines" in mode:
                # Slightly thicker lines for readability
                line = trace.setdefault("line", {})
                line.setdefault("width", 2.5)
                # Better markers on line charts
                if "markers" in mode:
                    marker = trace.setdefault("marker", {})
                    marker.setdefault("size", 5)

        elif ttype == "pie":
            # Clean pie chart defaults
            trace.setdefault("hole", 0.35)  # donut style
            trace.setdefault("textinfo", "percent+label")
            trace.setdefault("textposition", "auto")
            trace.setdefault("hovertemplate", "%{label}: %{value:,.0f} (%{percent})<extra></extra>")

    # Bar gap for grouped/stacked bars
    if visual_type in ("bar", "column"):
        layout.setdefault("bargap", 0.2)
        layout.setdefault("bargroupgap", 0.1)



def _resolve_encodings_for_output(*, model: Any, encodings: Mapping[str, Any], param_values: Mapping[str, Any] | None, drill_level: int | None = None):
    """Resolve ParamRef and HierarchyRef for UI/debug output.

    If a ParamRef selection is multi-select, this returns a list of resolved expressions.
    HierarchyRef is resolved to the ColumnRef for the appropriate drill level.
    """

    from dax_engine.ir import ColumnRef as _ColumnRef
    from dax_engine.ir import DaxBinaryOp, DaxFunction, DaxIteratorFunction, DaxWindowFunction, HierarchyRef, ParamRef, SetLiteral

    def _find_fp(fp_name: str) -> Any:
        fps_map = getattr(model, "field_parameters", {}) or {}
        if not isinstance(fps_map, Mapping):
            return None
        for k, fp in fps_map.items():
            if isinstance(k, str) and k.strip() and k.strip().upper() == fp_name.strip().upper():
                return fp
            nm = getattr(fp, "name", None)
            if isinstance(nm, str) and nm.strip() and nm.strip().upper() == fp_name.strip().upper():
                return fp
        return None

    def _selected_keys(fp: Any, fp_name: str) -> list[str]:
        values = param_values or {}
        raw = None
        for k, v in values.items():
            if isinstance(k, str) and k.strip().upper() == fp_name.strip().upper():
                raw = v
                break

        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        if isinstance(raw, list):
            out: list[str] = []
            for it in raw:
                if isinstance(it, str) and it.strip():
                    out.append(it.strip())
            if out:
                return out

        allow_multi = bool(getattr(fp, "allow_multi", False))
        default_items_raw = getattr(fp, "default_items", None)
        if allow_multi and isinstance(default_items_raw, list) and default_items_raw:
            return [str(x).strip() for x in default_items_raw if isinstance(x, str) and str(x).strip()]
        default = getattr(fp, "default", None)
        if isinstance(default, str) and default.strip():
            return [default.strip()]
        return []

    def _resolve_paramref_expr(fp_name: str, key: str) -> Any:
        fp = _find_fp(fp_name)
        if fp is None:
            raise ValueError(f"Unknown field parameter: {fp_name!r}")
        # Support both new (items/name/ref) and legacy (options/key/expr) shapes
        items = list(getattr(fp, "items", []) or getattr(fp, "options", []) or [])
        item = next(
            (it for it in items if str(getattr(it, "name", "") or getattr(it, "key", "")).strip().upper() == key.strip().upper()),
            None,
        )
        if item is None:
            raise ValueError(f"Invalid field parameter value for {fp_name!r}: {key!r}")
        return getattr(item, "ref", None) or getattr(item, "expr", None)

    def _walk(e: Any) -> Any:
        if isinstance(e, HierarchyRef):
            # Resolve HierarchyRef to ColumnRef at the appropriate drill level
            h_map = getattr(model, "hierarchies", {}) or {}
            h_lower = {k.lower(): v for k, v in h_map.items()}
            hierarchy = h_lower.get(e.name.lower())
            if hierarchy is not None and hierarchy.levels:
                lvl_idx = min(drill_level or 0, len(hierarchy.levels) - 1)
                lvl = hierarchy.levels[lvl_idx]
                return _ColumnRef(table=hierarchy.table, column=lvl.column)
            return e
        if isinstance(e, ParamRef):
            fp = _find_fp(e.name)
            if fp is None:
                raise ValueError(f"Unknown field parameter: {e.name!r}")
            keys = _selected_keys(fp, e.name)
            if len(keys) > 1:
                return [_walk(_resolve_paramref_expr(e.name, k)) for k in keys]
            if not keys:
                return e
            return _walk(_resolve_paramref_expr(e.name, keys[0]))
        if isinstance(e, DaxFunction):
            return DaxFunction(e.fn, [_walk(a) for a in e.args])
        if isinstance(e, SetLiteral):
            return SetLiteral([_walk(v) for v in e.values])
        if isinstance(e, DaxBinaryOp):
            return DaxBinaryOp(e.operator, _walk(e.left), _walk(e.right))
        if isinstance(e, DaxIteratorFunction):
            return DaxIteratorFunction(e.fn, _walk(e.table), _walk(e.expr))
        if isinstance(e, DaxWindowFunction):
            order_by = e.order_by
            if order_by is not None:
                order_by = list(order_by)
            return DaxWindowFunction(e.fn, _walk(e.table), _walk(e.expr), order_by=order_by)
        return e

    out: dict[str, Any] = {}
    for k, v in encodings.items():
        # Skip non-expression encodings fields (e.g., tablix layout properties)
        if k == "tablix":
            out[k] = v
            continue
        # Combo layers: resolve y/color inside each layer dict, pass rest through
        if k == "layers" and isinstance(v, list):
            resolved_layers: list[dict[str, Any]] = []
            for lyr in v:
                if not isinstance(lyr, dict):
                    continue
                rl: dict[str, Any] = {}
                for lk, lv in lyr.items():
                    if lk in ("y", "color", "size"):
                        # Resolve encoding expression
                        if lv is None:
                            rl[lk] = None
                        elif isinstance(lv, dict) and lv.get("type") == "ExplanationRef":
                            rl[lk] = lv
                        elif isinstance(lv, dict):
                            rl[lk] = _walk(parse_expr(lv))
                        else:
                            rl[lk] = _walk(lv)
                    else:
                        # Pass through: type, secondary_y, format, name, etc.
                        rl[lk] = lv
                resolved_layers.append(rl)
            out[k] = resolved_layers
            continue
        if v is None:
            out[k] = None
        elif isinstance(v, list):
            out[k] = [
                (it if isinstance(it, dict) and it.get("type") == "ExplanationRef"
                 else _walk(parse_expr(it) if isinstance(it, dict) else it))
                for it in v
            ]
        else:
            if isinstance(v, dict) and v.get("type") == "ExplanationRef":
                out[k] = v
            else:
                expr = parse_expr(v) if isinstance(v, dict) else v
                out[k] = _walk(expr)
    return out




def _runtime_routes(app):
    from fastapi import Body, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    @app.get("/runtime/_fingerprint")
    def _runtime_fingerprint():
        """Debug endpoint to prove which server + runtime assets are actually running."""

        def _read_git_head(repo_root: Path) -> str | None:
            try:
                head = (repo_root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
            except Exception:
                return None
            if head.startswith("ref:"):
                ref = head.split(":", 1)[1].strip()
                ref_path = repo_root / ".git" / ref
                try:
                    return ref_path.read_text(encoding="utf-8").strip() or None
                except Exception:
                    return head
            return head or None

        server_file = Path(__file__).resolve()
        repo_root = server_file.parents[2]
        runtime_js = server_file.parents[1] / "static" / "runtime.js"
        runtime_bytes = b""
        if runtime_js.exists():
            try:
                runtime_bytes = runtime_js.read_bytes()
            except Exception:
                runtime_bytes = b""

        return {
            "ok": True,
            "server_file": str(server_file),
            "cwd": os.getcwd(),
            "python": sys.executable,
            "git_head": _read_git_head(repo_root),
            "runtime_js_path": str(runtime_js),
            "runtime_js_size": int(len(runtime_bytes)),
            "runtime_js_sha1": hashlib.sha1(runtime_bytes).hexdigest() if runtime_bytes else None,
            "runtime_js_sha256": hashlib.sha256(runtime_bytes).hexdigest() if runtime_bytes else None,
        }

    if os.environ.get("DAX_ENABLE_TEST_ENDPOINTS") == "1":
        # SEC-25: Do not register test/diagnostic endpoints in server mode
        _server_mode = os.environ.get("DAX_SERVER_MODE", "author")
        if _server_mode == "server":
            logger.warning("DAX_ENABLE_TEST_ENDPOINTS ignored in server mode (SEC-25)")
        else:
            @app.get("/runtime/_diagnose")
            def _runtime__diagnose():
                return {
                    "ok": True,
                    "cwd": os.getcwd(),
                    "server_file": str(Path(__file__).resolve()),
                    "python": sys.executable,
                    "DAX_PROJECT_PATH": os.environ.get("DAX_PROJECT_PATH"),
                }

            @app.post("/runtime/_test/update_selected_values")
            def _runtime__test_update_selected_values(payload: dict = Body(...)):
                op = payload.get("op")
                values = payload.get("values")
                clicked = payload.get("clicked")
                list_order = payload.get("list_order")
                out = _test_update_selected_values(op=op, values=values, clicked=clicked, list_order=list_order)
                return {"ok": True, "values": out}

            @app.post("/runtime/_test/highlight_match")
            def _runtime__test_highlight_match(payload: dict = Body(...)):
                encodings = payload.get("visualEncodings")
                selection = payload.get("selection")
                out = _test_highlight_match(visual_encodings=encodings, selection=selection)
                return {"ok": True, **out}



    # --- Extracted route modules ---
    from dax_ui.server._routes_core import register_core_routes
    from dax_ui.server._routes_model_ext import register_model_ext_routes
    from dax_ui.server._routes_meta_security import register_meta_security_routes
    from dax_ui.server._routes_visuals import register_visual_routes
    from dax_ui.server._routes_tmdl import register_tmdl_converter_routes
    from dax_ui.server._routes_selection import register_selection_routes
    from dax_ui.server._routes_story import register_story_routes
    from dax_ui.server._routes_report_transfer import register_report_transfer_routes

    register_core_routes(app)
    register_model_ext_routes(app)
    register_meta_security_routes(app)
    register_visual_routes(app)
    register_tmdl_converter_routes(app)
    register_selection_routes(app)
    register_story_routes(app)
    register_report_transfer_routes(app)





# ---------------------------------------------------------------------------



def _phase14_routes(app):
    """Phase 14 routes — environments, folders, pipelines, git history."""
    try:
        from dax_ui.phase14_routes import register_phase14_routes
        register_phase14_routes(app)
    except ImportError:
        logger.info("Phase 14 routes not available — Community Edition")












app = create_app()
