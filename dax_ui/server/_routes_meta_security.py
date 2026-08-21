"""Auto-extracted route module from dax_ui.server._runtime_routes."""

import copy
import datetime
import json
import logging
import os
import re
import time
import uuid
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Optional

from starlette.requests import Request

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

from dax_ui.server._runtime_helpers import *  # noqa: F403
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

# Module-level helpers from __init__
from dax_ui.server import (
    _json_safe_with_path,
    _get_version,
    _get_build,
)

# Cross-module route helpers
from dax_ui.server._routes_core import (
    _calc_groups_meta_from_model,
    _validate_calc_group_selections_against_model,
    _hierarchies_meta_from_model,
    _field_parameters_meta_from_model,
    _validate_field_parameter_selections_against_model,
    _build_virtual_tables,
    _what_if_parameters_meta_from_model,
    _validate_what_if_selections_against_model,
)
from dax_ui.server._routes_model_ext import (
    _load_model_layouts,
)

# Enterprise types (conditional)
try:
    from dax_engine.explanations.loader import (
        Playbook,
        _playbook_to_dict,
        _driver_to_dict,
        load_playbooks,
        save_playbook,
    )
    from dax_engine.explanations.engine import ExplanationEngine, static_value_resolver
    from dax_engine.explanations.models import ExplanationNode
    from dax_engine.explanations.evidence import EvidenceResolver
    from dax_engine.explanations.subscriptions import (
        load_subscription as _load_sub_file,
        load_subscriptions,
        save_subscription,
        run_subscription,
        _subscription_to_dict,
    )
    _HAS_ENTERPRISE_EXPLANATIONS = True
except ImportError:
    _HAS_ENTERPRISE_EXPLANATIONS = False
    Playbook = type(None)  # type: ignore[misc,assignment]
    ExplanationEngine = type(None)  # type: ignore[misc,assignment]
    ExplanationNode = type(None)  # type: ignore[misc,assignment]
    EvidenceResolver = type(None)  # type: ignore[misc,assignment]

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
    pass  # Enterprise explanations not available



def _enterprise_only(feature: str):
    """Return a 501 JSONResponse for enterprise-only features in Community Edition."""
    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=501,
        content={
            "ok": False,
            "error": "enterprise_feature",
            "feature": feature,
            "message": f"{feature} requires the Enterprise Edition.",
        },
    )


def register_meta_security_routes(app):
    from fastapi import Body, HTTPException
    from fastapi.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    _forecast_cache: dict[str, dict] = {}

    @app.get("/runtime/meta")
    def runtime_meta(request: Request, project: Optional[str] = None):
        """Return project resolution info for bootstrapping the runtime UI.

        Resolution order:
        - query param `project` (if provided)
        - env var `DAX_PROJECT_PATH`
        - else None

        This endpoint is intentionally safe to call without a project.
        """

        errors: list[str] = []
        source: Optional[str] = None
        active: Optional[str] = None

        if project is not None and str(project).strip():
            source = "query"
            try:
                active = _resolve_project_path_runtime(project)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                active = None
        else:
            env_path = (os.environ.get("DAX_PROJECT_PATH") or "").strip()
            if env_path:
                source = "env"
                try:
                    active = _resolve_project_path_runtime(None)
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
                    active = None

        # Determine user role from auth state (server mode) or default to admin (author mode)
        mode = os.environ.get("DAX_SERVER_MODE", "author")
        auth_user = getattr(request.state, 'auth_user', None) if hasattr(request, 'state') else None
        if mode == "author":
            user_role = "admin"  # desktop mode: full access
        elif auth_user:
            user_role = auth_user.role
        else:
            user_role = "viewer"  # unauthenticated server access: read-only

        return _ok(
            {
                "active_project": active,
                "active_project_source": source,
                "projects": [],
                "errors": errors,
                "ready": len(errors) == 0 and active is not None,
                "version": _get_version(),
                "build": _get_build(),
                "mode": mode,
                "user_role": user_role,
            }
        )

    @app.get("/runtime/license/status")
    def runtime_license_status(request: Request):
        """Return the current license/trial status.

        This endpoint is admin-only in production (server mode). In author
        mode it is always accessible.

        Resolution:
        - ``DAX_LICENSE_PATH`` env var ΓåÆ license.json path
        - Else: ``<project_root>/license.json`` if it exists
        - Else: trial / community mode

        Returns a JSON envelope with license status, tier, licensee, expiry,
        days_remaining, trial flag, and version_ok.  Never blocks runtime.
        """
        import os as _os

        try:
            from dax_engine.licensing import LicenseValidator, LicenseStatus, LicenseTier
            from dax_engine.licensing_trial import TrialManager
        except ImportError:
            return _ok({
                "valid": False,
                "status": "community",
                "tier": "community",
                "licensee": "(community edition)",
                "expires": None,
                "days_remaining": None,
                "trial": False,
                "version_ok": True,
                "message": "License validation requires the Enterprise Edition.",
            })

        # --- Resolve license file path ---
        license_path = _os.environ.get("DAX_LICENSE_PATH", "").strip() or None
        if license_path is None:
            # Check project root fallback
            project_env = _os.environ.get("DAX_PROJECT_PATH", "").strip()
            if project_env:
                candidate = Path(project_env) / "license.json"
                if candidate.exists():
                    license_path = str(candidate)

        # --- Vendor public key (embedded) ---
        # NOTE: This is the *demo* public key shipped with the repo for
        # development / testing.  Production builds replace this via the
        # build pipeline.
        vendor_key_hex = _os.environ.get(
            "DAX_LICENSE_PUBLIC_KEY",
            "0" * 64,  # placeholder ΓÇö real key injected at build time
        )

        try:
            validator = LicenseValidator(vendor_key_hex)
            result = validator.check(license_path, _get_version())
        except Exception as exc:  # noqa: BLE001
            return _ok({
                "valid": False,
                "status": "error",
                "tier": "community",
                "licensee": "(unknown)",
                "expires": None,
                "days_remaining": None,
                "trial": False,
                "version_ok": True,
                "message": f"License check failed: {exc}",
            })

        # --- Trial enrichment ---
        trial_info = None
        is_trial = False
        if result.status == LicenseStatus.MISSING:
            try:
                trial_path = _os.environ.get("DAX_TRIAL_PATH", "").strip() or None
                tm = TrialManager(trial_path)
                trial_info = tm.get_or_start_trial()
                is_trial = True
            except Exception:  # noqa: BLE001
                pass

        expires_str = result.expires.isoformat() if result.expires else None
        days_rem = result.days_remaining

        # If in trial mode, override days_remaining with trial info
        if trial_info is not None:
            days_rem = trial_info.days_remaining
            expires_str = (trial_info.trial_start.__class__.today()
                           + __import__("datetime").timedelta(days=days_rem)
                           ).isoformat() if days_rem is not None else None

        return _ok({
            "valid": result.status in (
                LicenseStatus.VALID,
                LicenseStatus.TRIAL_ACTIVE,
            ),
            "status": result.status.value,
            "tier": result.tier.value,
            "licensee": result.licensee,
            "expires": expires_str,
            "days_remaining": days_rem,
            "trial": is_trial or (result.license.trial if result.license else False),
            "version_ok": result.version_ok,
            "message": result.message,
        })

    @app.get("/runtime/security/meta")
    def runtime_security_meta(request: Request, project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            role_name, _role = _resolve_security_for_request(model=model, request=request, payload=None)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        roles = sorted(list((getattr(model, "security_roles", {}) or {}).keys()), key=lambda s: str(s).upper())
        return _ok(
            {
                "roles": roles,
                "default_role": getattr(model, "default_role", None),
                "active_role": role_name,
            }
        )

    @app.get("/runtime/security/roles")
    def runtime_security_roles_get(project: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        return _ok(
            {
                "default_role": getattr(model, "default_role", None),
                "roles": _security_roles_to_json(model),
            }
        )

    @app.put("/runtime/security/roles")
    def runtime_security_roles_put(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        roles_payload = payload.get("roles")
        if roles_payload is None:
            roles_payload = []
        if not isinstance(roles_payload, list):
            return _err(400, "roles must be a list")

        # Guard: prevent wiping all roles if roles already exist (lockout protection)
        if len(roles_payload) == 0:
            existing_roles = _security_roles_to_json(model)
            if existing_roles:
                return _err(
                    400,
                    "Cannot remove all security roles. At least one role must remain "
                    "to prevent lockout. Delete individual roles instead.",
                )

        default_role = payload.get("default_role")
        if default_role is not None and (not isinstance(default_role, str) or not default_role.strip()):
            return _err(400, "default_role must be a non-empty string if provided")

        errors: list[str] = []
        seen: set[str] = set()
        for i, rr in enumerate(roles_payload):
            if not isinstance(rr, Mapping):
                errors.append(f"roles[{i}] must be an object")
                continue
            nm = rr.get("name")
            if not isinstance(nm, str) or not nm.strip():
                errors.append(f"roles[{i}].name must be a non-empty string")
                continue
            key = nm.strip().upper()
            if key in seen:
                errors.append(f"duplicate role name: {nm.strip()!r}")
            else:
                seen.add(key)

            errors.extend(_validate_single_role_payload(project_path=project_path, model=model, role_payload=rr))

        if default_role is not None and isinstance(default_role, str) and default_role.strip():
            if default_role.strip().upper() not in seen:
                errors.append(f"default_role not found in roles: {default_role.strip()!r}")

        if errors:
            msg = "Security role validation failed:\n" + "\n".join(f"- {e}" for e in errors)
            return _err(400, msg)

        try:
            save_security_yaml(
                project_path,
                roles=[dict(r) for r in roles_payload if isinstance(r, Mapping)],
                default_role=default_role.strip() if isinstance(default_role, str) and default_role.strip() else None,
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        # Reload and return canonical view.
        try:
            model2, _pages2, _visuals2 = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        return _ok(
            {
                "default_role": getattr(model2, "default_role", None),
                "roles": _security_roles_to_json(model2),
            }
        )

    @app.post("/runtime/security/roles/validate")
    def runtime_security_roles_validate(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            model, _pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        role_payload = payload.get("role") if isinstance(payload.get("role"), Mapping) else payload
        errors = _validate_single_role_payload(project_path=project_path, model=model, role_payload=role_payload)
        if errors:
            msg = "Role validation failed:\n" + "\n".join(f"- {e}" for e in errors)
            return _err(400, msg)
        return _ok({"ok": True})

    @app.get("/runtime/explanations/playbooks")
    def runtime_list_playbooks(project: Optional[str] = None):
        """List all explanation playbooks in the project."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            playbooks = load_playbooks(project_path)
            result = []
            for name, pb in playbooks.items():
                result.append({
                    "name": pb.name,
                    "version": pb.version,
                    "description": pb.description,
                    "entry_edu_count": len(pb.entry_edus),
                    "driver_count": len(pb.drivers),
                })
            return _ok({"playbooks": result})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/explanations/playbooks/{name}")
    def runtime_get_playbook(name: str, project: Optional[str] = None):
        """Get a specific playbook by name."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            playbooks = load_playbooks(project_path)
            if name not in playbooks:
                return _err(400, f"Playbook not found: {name!r}")
            return _ok({"playbook": _playbook_to_dict(playbooks[name])})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/explanations/playbooks/{name}")
    def runtime_save_playbook(name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Create or update a playbook."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            from dax_engine.explanations.loader import load_playbook as _load_pb_file
            import tempfile, yaml  # noqa: E401

            # Validate the payload by writing to a temp file and parsing it
            payload_with_name = {**payload, "name": name}
            # SEC-23: Use NamedTemporaryFile instead of deprecated mktemp (TOCTOU)
            tmp_fd = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
            tmp = Path(tmp_fd.name)
            tmp_fd.close()
            try:
                tmp.write_text(
                    yaml.dump(payload_with_name, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
                pb = _load_pb_file(tmp)
            finally:
                tmp.unlink(missing_ok=True)

            save_playbook(project_path, pb)
            return _ok({"playbook": _playbook_to_dict(pb)})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/explanations/playbooks/{name}")
    def runtime_delete_playbook(name: str, project: Optional[str] = None):
        """Delete a playbook."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            from dax_engine.explanations.loader import _sanitize_id
            explanations_dir = Path(project_path) / "explanations"
            file_path = explanations_dir / f"{_sanitize_id(name)}.yaml"
            if not file_path.exists():
                return _err(400, f"Playbook not found: {name!r}")
            file_path.unlink()
            return _ok({"deleted": name})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/explanations/playbooks/{name}/graph")
    def runtime_playbook_graph(name: str, project: Optional[str] = None):
        """Return the EDU relationship graph for a playbook.

        Returns nodes (EDUs) and edges (driver links) suitable for rendering
        a navigable diagram of the parent-child EDU decomposition tree.
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            playbooks = load_playbooks(project_path)
            if name not in playbooks:
                return _err(400, f"Playbook not found: {name!r}")
            pb = playbooks[name]

            # Collect all known EDU IDs (entry EDUs define explicit nodes)
            entry_ids = {e.id for e in pb.entry_edus}

            # Build nodes from entry EDUs
            nodes = []
            node_ids_seen: set = set()
            for edu in pb.entry_edus:
                drivers_for = pb.get_drivers_for_edu(edu.id, edu.metric)
                nodes.append({
                    "id": edu.id,
                    "name": edu.id,
                    "metric": edu.metric,
                    "comparator": edu.comparator.value if hasattr(edu.comparator, 'value') else str(edu.comparator),
                    "driver_count": len(drivers_for),
                    "is_entry": True,
                    "description": edu.description or "",
                })
                node_ids_seen.add(edu.id)

            # Build edges and discover implicit child nodes from drivers
            edges = []
            for driver in pb.drivers:
                parent_id = driver.parent_edu_id
                # Ensure parent node exists (may be an implicit node from a child_metric)
                if parent_id not in node_ids_seen:
                    drivers_for = pb.get_drivers_for_edu(parent_id, parent_id)
                    nodes.append({
                        "id": parent_id,
                        "name": parent_id,
                        "metric": parent_id,
                        "comparator": "",
                        "driver_count": len(drivers_for),
                        "is_entry": False,
                        "description": "",
                    })
                    node_ids_seen.add(parent_id)

                if driver.mode == "additive" and driver.child_metrics:
                    for i, cm in enumerate(driver.child_metrics):
                        if isinstance(cm, dict):
                            metric_name = cm.get("metric", "")
                            sign = cm.get("sign", 1)
                        else:
                            metric_name = cm
                            sign = driver.child_signs[i] if i < len(driver.child_signs) else 1

                        child_id = metric_name
                        if child_id not in node_ids_seen:
                            child_drivers = pb.get_drivers_for_edu(child_id, metric_name)
                            nodes.append({
                                "id": child_id,
                                "name": child_id,
                                "metric": metric_name,
                                "comparator": "",
                                "driver_count": len(child_drivers),
                                "is_entry": False,
                                "description": "",
                            })
                            node_ids_seen.add(child_id)

                        edges.append({
                            "from": parent_id,
                            "to": child_id,
                            "mode": "additive",
                            "child_metric": metric_name,
                            "sign": "+" if sign >= 0 else "-",
                            "driver_id": driver.id,
                            "description": driver.description or "",
                        })

                elif driver.mode == "dimensional":
                    dim_label = f"{driver.dimension_table}.{driver.dimension_column}" if driver.dimension_table else driver.dimension_column
                    dim_node_id = f"{parent_id}__dim__{driver.id}"
                    if dim_node_id not in node_ids_seen:
                        nodes.append({
                            "id": dim_node_id,
                            "name": f"By {dim_label}",
                            "metric": "",
                            "comparator": "",
                            "driver_count": 0,
                            "is_entry": False,
                            "description": driver.description or f"Dimensional split by {dim_label}",
                        })
                        node_ids_seen.add(dim_node_id)
                    edges.append({
                        "from": parent_id,
                        "to": dim_node_id,
                        "mode": "dimensional",
                        "child_metric": dim_label,
                        "sign": "",
                        "driver_id": driver.id,
                        "description": driver.description or f"Split by {dim_label}",
                    })

                elif driver.mode == "effect" and driver.effects:
                    for effect in driver.effects:
                        effect_node_id = f"{parent_id}__eff__{effect}"
                        if effect_node_id not in node_ids_seen:
                            nodes.append({
                                "id": effect_node_id,
                                "name": f"{effect} effect",
                                "metric": "",
                                "comparator": "",
                                "driver_count": 0,
                                "is_entry": False,
                                "description": driver.description or f"{effect} effect on {parent_id}",
                            })
                            node_ids_seen.add(effect_node_id)
                        edges.append({
                            "from": parent_id,
                            "to": effect_node_id,
                            "mode": "effect",
                            "child_metric": effect,
                            "sign": "",
                            "driver_id": driver.id,
                            "description": driver.description or f"{effect} effect",
                        })

            return _ok({"nodes": nodes, "edges": edges})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    def _build_evidence_resolver(playbook: Playbook, con) -> EvidenceResolver:
        """Build an EvidenceResolver that executes queries against the given DuckDB connection."""

        def _query_executor(sql: str) -> list[dict[str, Any]]:
            """Execute a read-only SQL query and return list of row dicts."""
            result = con.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = []
            for row in result.fetchall():
                rows.append({col: val for col, val in zip(columns, row)})
            return rows

        return EvidenceResolver(playbook, _query_executor)

    @app.get("/runtime/explanations/evidence/{playbook_name}/{node_path:path}")
    def runtime_get_evidence(playbook_name: str, node_path: str, project: Optional[str] = None):
        """Return evidence data for a specific node in a playbook.

        node_path is the driver_id to look up the evidence provider.
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        con = None
        try:
            project_path = _resolve_project_path_runtime(project)
            playbooks = load_playbooks(project_path)
            if playbook_name not in playbooks:
                return _err(400, f"Playbook not found: {playbook_name!r}")

            playbook = playbooks[playbook_name]

            # Find driver by node_path (which is the driver_id)
            driver = playbook.get_driver(node_path)
            if driver is None:
                return _err(400, f"Driver not found: {node_path!r}")

            if not driver.evidence_provider_id:
                return _err(400, f"Driver {node_path!r} has no evidence provider")

            provider = playbook.get_evidence_provider(driver.evidence_provider_id)
            if provider is None:
                return _err(400, f"Evidence provider {driver.evidence_provider_id!r} not found")

            model, pages, visuals = load_project(project_path)
            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            resolver = _build_evidence_resolver(playbook, con)

            # Build a minimal node to pass to the resolver
            node = ExplanationNode(
                edu_id="evidence_query",
                metric="",
                driver_id=node_path,
                grain={},
            )

            result = resolver.resolve(node)
            if result is None:
                return _err(400, "Evidence resolution failed")

            return _ok(result.to_dict())
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.post("/runtime/explanations/execute/{name}")
    def runtime_execute_playbook(name: str, project: Optional[str] = None, include_evidence: bool = False, payload: dict = Body(default_factory=dict)):
        """Execute a playbook and return the explanation tree.

        The playbook defines the decision tree. The server evaluates measures
        using the semantic engine (compile DAX -> DuckDB SQL -> execute).

        Optional payload:
        - filters: runtime filters to apply during evaluation
        - role: security role name to apply
        - grain_overrides: dict of grain key -> value overrides for entry EDUs
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        con = None
        try:
            playbooks = load_playbooks(project_path)
            if name not in playbooks:
                return _err(400, f"Playbook not found: {name!r}")

            playbook = playbooks[name]
            model, pages, visuals = load_project(project_path)

            # Apply grain overrides to entry EDUs if provided
            grain_overrides = payload.get("grain_overrides")
            if grain_overrides and isinstance(grain_overrides, dict):
                from dataclasses import replace as _dc_replace
                new_edus = []
                for edu in playbook.entry_edus:
                    merged_grain = {**edu.grain, **grain_overrides}
                    new_edus.append(_dc_replace(edu, grain=merged_grain))
                playbook = _dc_replace(playbook, entry_edus=new_edus)

            # Apply security if requested
            request_role = payload.get("role")
            if request_role:
                role = get_role(model, request_role)
                if role:
                    model = apply_ols(model, role)

            # Build DuckDB connection
            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            # Build value resolver that evaluates measures via the semantic engine
            # Prepare engine once (measures, relationships, table sources).
            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

            def _resolve_single_measure(measure_name: str) -> Optional[float]:
                """Compile and execute a single measure, return scalar float or None."""
                # Verify measure exists
                found = False
                for m in model.measures:
                    if (m.name if hasattr(m, "name") else str(m)) == measure_name:
                        found = True
                        break
                if not found:
                    return None
                try:
                    from dax_engine.ir import MeasureRef as _MRef
                    mref = _MRef(name=measure_name)
                    with _ENGINE_LOCK:
                        _table_ir, sql = plan_card_query(
                            mref,
                            filters=[],
                            model=model,
                        )
                    result = con.execute(
                        dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                    ).fetchone()
                    return float(result[0]) if result and result[0] is not None else None
                except Exception:
                    return None

            def _value_resolver(metric, comparator, grain):
                """Resolve (actual, base) for a metric using semantic engine."""
                actual = _resolve_single_measure(metric)

                # Base value uses a comparator-specific measure
                # (e.g. "EBITDA PY" for previous_period, "EBITDA Budget" for budget).
                base_metric = f"{metric} PY" if comparator.value == "previous_period" else f"{metric} Budget"
                base = _resolve_single_measure(base_metric)

                return (actual, base)

            def _dimensional_resolver(metric, comparator, grain, dim_table, dim_column):
                """Resolve a metric split by a dimension column.

                Uses SUMMARIZECOLUMNS with the dimension column as a GROUP BY
                argument, giving back (dim_val, actual, base) tuples.
                """
                from dax_engine.ir import ColumnRef as _CRef, MeasureRef as _MRef

                def _grouped_query(measure_name):
                    """Execute measure grouped by dimension, return {dim_val: float}."""
                    found = False
                    for m in model.measures:
                        if (m.name if hasattr(m, "name") else str(m)) == measure_name:
                            found = True
                            break
                    if not found:
                        return {}
                    try:
                        mref = _MRef(name=measure_name)
                        dim_col = _CRef(table=dim_table, column=dim_column)
                        with _ENGINE_LOCK:
                            _table_ir, sql = plan_card_query(
                                mref,
                                filters=[dim_col],
                                model=model,
                            )
                        rows = con.execute(
                            dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                        ).fetchall()
                        # Rows are (dim_value, measure_value)
                        return {
                            str(r[0]): float(r[1]) if r[1] is not None else None
                            for r in rows
                            if r[0] is not None
                        }
                    except Exception:
                        logger.warning("Dimensional query failed for %s by %s.%s", measure_name, dim_table, dim_column, exc_info=True)
                        return {}

                actual_map = _grouped_query(metric)
                base_metric = f"{metric} PY" if comparator.value == "previous_period" else f"{metric} Budget"
                base_map = _grouped_query(base_metric)

                # Merge dimension values from both maps, skip irrelevant zeros
                all_dims = sorted(set(actual_map.keys()) | set(base_map.keys()))
                result = []
                for dim_val in all_dims:
                    a = actual_map.get(dim_val)
                    b = base_map.get(dim_val)
                    # Skip dimension values where both actual and base are zero/None
                    if (a is None or a == 0) and (b is None or b == 0):
                        continue
                    result.append((dim_val, a, b))
                return result

            engine = ExplanationEngine(
                playbook=playbook,
                value_resolver=_value_resolver,
                dimensional_resolver=_dimensional_resolver,
                evidence_resolver=_build_evidence_resolver(playbook, con) if include_evidence else None,
            )

            result = engine.execute()

            # Determine comparator label and narrative depth from payload
            comparator_label = "budget"
            if playbook.entry_edus:
                comp = playbook.entry_edus[0].comparator
                if comp.value == "previous_period":
                    comparator_label = "prior year"
            narrative_depth = payload.get("narrative_depth", "children")

            # Serialize with narratives using the rich serializer
            serialized_nodes = []
            for node in result.nodes:
                serialized_nodes.append(_serialize_explanation_node(
                    node,
                    comparator_label=comparator_label,
                    narrative_depth=narrative_depth,
                ))

            return _ok({
                "playbook_name": playbook.name,
                "playbook_version": playbook.version,
                "nodes": serialized_nodes,
                "metadata": {"max_depth": engine._max_depth},
            })
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/explanations/subscriptions")
    def runtime_list_subscriptions(project: Optional[str] = None):
        """List all subscriptions for the current project."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Subscriptions")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))
        try:
            subs = load_subscriptions(project_path)
            return _ok({"subscriptions": [_subscription_to_dict(s) for s in subs.values()]})
        except Exception as exc:
            return _err(400, str(exc))

    @app.get("/runtime/explanations/subscriptions/{name}")
    def runtime_get_subscription(name: str, project: Optional[str] = None):
        """Get a single subscription by name."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Subscriptions")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))
        try:
            subs = load_subscriptions(project_path)
            if name not in subs:
                return _err(400, f"Subscription not found: {name!r}")
            return _ok({"subscription": _subscription_to_dict(subs[name])})
        except Exception as exc:
            return _err(400, str(exc))

    @app.put("/runtime/explanations/subscriptions/{name}")
    def runtime_save_subscription(name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Create or update a subscription."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Subscriptions")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))
        try:
            # Write raw YAML then re-parse to validate
            import yaml as _sub_yaml
            payload.setdefault("name", name)
            subs_dir = Path(project_path) / "explanations" / "subscriptions"
            subs_dir.mkdir(parents=True, exist_ok=True)
            from dax_engine.explanations.loader import _sanitize_id
            file_path = subs_dir / f"{_sanitize_id(name)}.yaml"
            file_path.write_text(
                _sub_yaml.dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            # Validate
            sub = _load_sub_file(file_path)
            return _ok({"subscription": _subscription_to_dict(sub)})
        except Exception as exc:
            return _err(400, str(exc))

    @app.delete("/runtime/explanations/subscriptions/{name}")
    def runtime_delete_subscription(name: str, project: Optional[str] = None):
        """Delete a subscription."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Subscriptions")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))
        try:
            from dax_engine.explanations.loader import _sanitize_id
            subs_dir = Path(project_path) / "explanations" / "subscriptions"
            file_path = subs_dir / f"{_sanitize_id(name)}.yaml"
            if not file_path.exists():
                return _err(400, f"Subscription not found: {name!r}")
            file_path.unlink()
            return _ok({"deleted": name})
        except Exception as exc:
            return _err(400, str(exc))

    @app.post("/runtime/explanations/subscriptions/{name}/trigger")
    def runtime_trigger_subscription(name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Manually trigger a subscription (execute playbook + deliver).

        This executes the referenced playbook, checks delivery conditions,
        and dispatches to all channels. Useful for testing subscriptions.
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Subscriptions")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        con = None
        try:
            subs = load_subscriptions(project_path)
            if name not in subs:
                return _err(400, f"Subscription not found: {name!r}")

            sub = subs[name]
            playbooks = load_playbooks(project_path)
            if sub.playbook not in playbooks:
                return _err(400, f"Subscription references unknown playbook: {sub.playbook!r}")

            playbook = playbooks[sub.playbook]
            model, pages, visuals = load_project(project_path)

            # Apply grain overrides from subscription
            if sub.grain_overrides:
                from dataclasses import replace as _dc_replace
                new_edus = []
                for edu in playbook.entry_edus:
                    merged_grain = {**edu.grain, **sub.grain_overrides}
                    new_edus.append(_dc_replace(edu, grain=merged_grain))
                playbook = _dc_replace(playbook, entry_edus=new_edus)

            # Apply security if specified
            if sub.role:
                role = get_role(model, sub.role)
                if role:
                    model = apply_ols(model, role)

            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            # Prepare engine once for this project
            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

            def _resolve_single_measure_sub(measure_name):
                found = False
                for m in model.measures:
                    if (m.name if hasattr(m, "name") else str(m)) == measure_name:
                        found = True
                        break
                if not found:
                    return None
                try:
                    from dax_engine.ir import MeasureRef as _MRef
                    mref = _MRef(name=measure_name)
                    with _ENGINE_LOCK:
                        _table_ir, sql = plan_card_query(
                            mref, filters=[], model=model,
                        )
                    result = con.execute(
                        dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                    ).fetchone()
                    return float(result[0]) if result and result[0] is not None else None
                except Exception:
                    return None

            # Reuse the same value resolver pattern as execute endpoint
            def _value_resolver(metric, comparator, grain):
                actual = _resolve_single_measure_sub(metric)
                base_metric = f"{metric} PY" if comparator.value == "previous_period" else f"{metric} Budget"
                base = _resolve_single_measure_sub(base_metric)
                return (actual, base)

            def _dimensional_resolver_sub(metric, comparator, grain, dim_table, dim_column):
                from dax_engine.ir import ColumnRef as _CRef, MeasureRef as _MRef

                def _grouped_query(measure_name):
                    found = False
                    for m in model.measures:
                        if (m.name if hasattr(m, "name") else str(m)) == measure_name:
                            found = True
                            break
                    if not found:
                        return {}
                    try:
                        mref = _MRef(name=measure_name)
                        dim_col = _CRef(table=dim_table, column=dim_column)
                        with _ENGINE_LOCK:
                            _table_ir, sql = plan_card_query(
                                mref, filters=[dim_col], model=model,
                            )
                        rows = con.execute(
                            dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                        ).fetchall()
                        return {
                            str(r[0]): float(r[1]) if r[1] is not None else None
                            for r in rows if r[0] is not None
                        }
                    except Exception:
                        return {}

                actual_map = _grouped_query(metric)
                base_metric = f"{metric} PY" if comparator.value == "previous_period" else f"{metric} Budget"
                base_map = _grouped_query(base_metric)
                all_dims = sorted(set(actual_map.keys()) | set(base_map.keys()))
                return [(d, actual_map.get(d), base_map.get(d)) for d in all_dims]

            engine = ExplanationEngine(
                playbook=playbook,
                value_resolver=_value_resolver,
                dimensional_resolver=_dimensional_resolver_sub,
            )
            explanation_result = engine.execute()

            # Run subscription delivery
            delivery = run_subscription(sub, explanation_result)
            return _ok({"delivery": delivery.to_dict()})
        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/explanations/virtual-fields/{playbook_name}")
    def runtime_list_virtual_fields(playbook_name: str, project: Optional[str] = None):
        """List available virtual fields for a playbook.

        Returns two virtual fields per entry EDU:
        - ``[metric].Value`` (measure, Decimal) — the computed delta
        - ``[metric].Description`` (dimension, Text) — driver name/label
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        try:
            playbooks = load_playbooks(project_path)
            if playbook_name not in playbooks:
                return _err(400, f"Playbook not found: {playbook_name!r}")

            from dax_engine.explanations.virtual_fields import EDUVirtualFieldProvider

            provider = EDUVirtualFieldProvider(playbook=playbooks[playbook_name])
            fields = provider.list_fields()
            return _ok({
                "playbook": playbook_name,
                "fields": [f.to_dict() for f in fields],
            })
        except Exception as exc:
            return _err(400, str(exc))

    @app.post("/runtime/explanations/virtual-fields/{playbook_name}/data")
    def runtime_virtual_field_data(playbook_name: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Return virtual field data for a given filter context.

        Request body:
            field: "Value" | "Description"
            edu_id: str ΓÇö the entry EDU ID
            filters: dict ΓÇö optional grain/filter overrides

        Response (Description field):
            rows: [{description: str, value: float|null}, ...]
            edu_id: str

        Response (Value field):
            value: float|null
            edu_id: str
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Explanations")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:
            return _err(400, str(exc))

        field_type = str(payload.get("field") or "").strip()
        edu_id = str(payload.get("edu_id") or "").strip()
        filter_context = payload.get("filters") or {}

        if field_type not in ("Value", "Description"):
            return _err(400, f"field must be 'Value' or 'Description', got {field_type!r}")
        if not edu_id:
            return _err(400, "edu_id is required")

        con = None
        try:
            playbooks = load_playbooks(project_path)
            if playbook_name not in playbooks:
                return _err(400, f"Playbook not found: {playbook_name!r}")

            playbook = playbooks[playbook_name]
            model, _pages, _visuals = load_project(project_path)

            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

            def _resolve_single(measure_name):
                found = any(
                    (m.name if hasattr(m, "name") else str(m)) == measure_name
                    for m in model.measures
                )
                if not found:
                    return None
                try:
                    from dax_engine.ir import MeasureRef as _MRef
                    mref = _MRef(name=measure_name)
                    with _ENGINE_LOCK:
                        _t, sql = plan_card_query(mref, filters=[], model=model)
                    result = con.execute(
                        dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                    ).fetchone()
                    return float(result[0]) if result and result[0] is not None else None
                except Exception:
                    return None

            def _vf_value_resolver(metric, comparator, grain):
                actual = _resolve_single(metric)
                base_metric = f"{metric} PY" if comparator.value == "previous_period" else f"{metric} Budget"
                base = _resolve_single(base_metric)
                return (actual, base)

            def _vf_dim_resolver(metric, comparator, grain, dim_table, dim_column):
                from dax_engine.ir import ColumnRef as _CRef, MeasureRef as _MRef

                def _grouped(measure_name):
                    found = any(
                        (m.name if hasattr(m, "name") else str(m)) == measure_name
                        for m in model.measures
                    )
                    if not found:
                        return {}
                    try:
                        mref = _MRef(name=measure_name)
                        dim_col = _CRef(table=dim_table, column=dim_column)
                        with _ENGINE_LOCK:
                            _t, sql = plan_card_query(mref, filters=[dim_col], model=model)
                        rows = con.execute(
                            dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                        ).fetchall()
                        return {str(r[0]): float(r[1]) if r[1] is not None else None for r in rows if r[0] is not None}
                    except Exception:
                        return {}

                actual_map = _grouped(metric)
                base_metric = f"{metric} PY" if comparator.value == "previous_period" else f"{metric} Budget"
                base_map = _grouped(base_metric)
                all_dims = sorted(set(actual_map.keys()) | set(base_map.keys()))
                return [(d, actual_map.get(d), base_map.get(d)) for d in all_dims]

            from dax_engine.explanations.virtual_fields import EDUVirtualFieldProvider

            provider = EDUVirtualFieldProvider(
                playbook=playbook,
                value_resolver=_vf_value_resolver,
                dimensional_resolver=_vf_dim_resolver,
            )

            if field_type == "Value":
                value = provider.value_field(edu_id, filter_context=filter_context if filter_context else None)
                return _ok({"edu_id": edu_id, "value": value})
            else:
                rows = provider.description_field(edu_id, filter_context=filter_context if filter_context else None)
                return _ok({
                    "edu_id": edu_id,
                    "rows": [{"description": desc, "value": val} for desc, val in rows],
                })
        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.post("/runtime/explanations/prune-candidates")
    def runtime_prune_candidates(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Run statistical candidate pruning on a measure with given dimensions.

        Request body:
            measure: str ΓÇö name of the KPI measure to explain
            candidates: list[str] ΓÇö dimension columns in "Table.Column" format
            playbook: str ΓÇö (optional) playbook name for context

        Response:
            selected_dimensions: list of CandidateScore dicts (ranked)
            rejected_dimensions: list of CandidateScore dicts
            cumulative_variance_explained: float
            total_candidates_screened: int
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("ML Analytics")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = str(payload.get("measure") or "").strip()
        candidates = payload.get("candidates") or []
        exclude_measure_source_tables = bool(payload.get("exclude_measure_source_tables", True))
        exclude_id_like = bool(payload.get("exclude_id_like", True))
        max_distinct_ratio_raw = payload.get("max_distinct_ratio", 0.95)
        min_avg_group_size_raw = payload.get("min_avg_group_size", 2.0)
        # playbook_name = str(payload.get("playbook") or "").strip()  # reserved for future use

        if not measure_name:
            return _err(400, "measure is required")
        if not isinstance(candidates, list):
            return _err(400, "candidates must be a list of 'Table.Column' strings")

        try:
            max_distinct_ratio = float(max_distinct_ratio_raw)
            min_avg_group_size = float(min_avg_group_size_raw)
        except Exception:
            return _err(400, "max_distinct_ratio and min_avg_group_size must be numeric")

        if not (0.0 <= max_distinct_ratio <= 1.0):
            return _err(400, "max_distinct_ratio must be between 0 and 1")
        if min_avg_group_size < 0.0:
            return _err(400, "min_avg_group_size must be >= 0")

        # Empty candidates → trivially empty result
        if not candidates:
            try:
                from dax_engine.explanations.candidate_pruning import PruningResult as _PR
                return _ok(_PR(target_measure=measure_name).to_dict())
            except ImportError:
                return _ok({"target_measure": measure_name, "kept": [], "pruned": [], "errors": []})

        # Validate & parse candidate format
        parsed_candidates: list[tuple[str, str]] = []
        for c in candidates:
            if not isinstance(c, str) or "." not in c:
                return _err(400, f"Invalid candidate format: {c!r} ΓÇö expected 'Table.Column'")
            tbl, col = c.split(".", 1)
            if not tbl or not col:
                return _err(400, f"Invalid candidate format: {c!r} ΓÇö table and column must be non-empty")
            parsed_candidates.append((tbl, col))

        con = None
        try:
            model, _pages, _visuals = load_project(project_path)

            # Filter out synthetic/virtual semantic tables from candidate pruning.
            # These tables exist for authoring UX parity and are not physical dimensions.
            calculated_table_names_upper = {
                str(getattr(t, "name", "") or "").upper()
                for t in getattr(model, "tables", []) or []
                if (bool(getattr(t, "is_calculated", False)) or bool(getattr(t, "expression", None)))
                and str(getattr(t, "name", "") or "").strip()
            }
            virtual_table_names_upper = {
                str(vt.get("name", "")).upper()
                for vt in _build_virtual_tables(model)
                if isinstance(vt, Mapping) and str(vt.get("name", "")).strip()
            }

            def _is_synthetic_candidate_table(table_name: str) -> bool:
                t_upper = str(table_name or "").upper()
                if not t_upper:
                    return False
                if t_upper in calculated_table_names_upper:
                    return True
                if t_upper in virtual_table_names_upper:
                    return True
                # Defensive fallback for stale UI payloads that only include the
                # virtual semantic naming pattern.
                return t_upper.startswith("FIELDPARAMS_") or t_upper.startswith("CALCGROUP_") or t_upper.startswith("WHATIF_")

            parsed_candidates = [
                (tbl, col) for (tbl, col) in parsed_candidates if not _is_synthetic_candidate_table(tbl)
            ]

            if not parsed_candidates:
                from dax_engine.explanations.candidate_pruning import PruningResult as _PR
                return _ok(_PR(target_measure=measure_name).to_dict())

            table_map: dict[str, str] = {col: tbl for tbl, col in parsed_candidates}

            # Validate measure exists
            measure_lookup: dict[str, Any] = {
                str(getattr(m, "name", "") or "").upper(): m
                for m in getattr(model, "measures", []) or []
                if str(getattr(m, "name", "") or "").strip()
            }
            measure_obj = measure_lookup.get(measure_name.upper())
            if measure_obj is None:
                return _err(400, f"Unknown measure: {measure_name!r}")

            if exclude_measure_source_tables:
                def _normalize_measure_token(token: str) -> str:
                    t = str(token or "").strip()
                    if t.startswith("[") and t.endswith("]") and len(t) >= 2:
                        t = t[1:-1]
                    return t.strip()

                def _collect_measure_dependency_tables(root_measure_name: str) -> set[str]:
                    from dax_project.introspection import _extract_measure_dependencies

                    tables_upper: set[str] = set()
                    visited: set[str] = set()
                    stack: list[str] = [root_measure_name]

                    while stack:
                        current = _normalize_measure_token(stack.pop())
                        if not current:
                            continue
                        current_upper = current.upper()
                        if current_upper in visited:
                            continue
                        visited.add(current_upper)

                        m_obj = measure_lookup.get(current_upper)
                        if m_obj is None:
                            continue

                        dax_text = str(getattr(m_obj, "dax", "") or "").strip()
                        if not dax_text:
                            continue

                        deps = _extract_measure_dependencies(model, dax_text)
                        for t in (deps.get("tables") or set()):
                            t_name = str(t or "").strip()
                            if t_name:
                                tables_upper.add(t_name.upper())
                        for m_ref in (deps.get("measures") or set()):
                            child = _normalize_measure_token(str(m_ref or ""))
                            if child and child.upper() not in visited:
                                stack.append(child)

                    return tables_upper

                measure_source_tables_upper = _collect_measure_dependency_tables(measure_name)
                parsed_candidates = [
                    (tbl, col)
                    for (tbl, col) in parsed_candidates
                    if str(tbl or "").upper() not in measure_source_tables_upper
                ]

                if not parsed_candidates:
                    from dax_engine.explanations.candidate_pruning import PruningResult as _PR
                    return _ok(_PR(target_measure=measure_name).to_dict())

            # Build DuckDB connection
            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

            # Preflight candidate columns before building grouped SQL.
            # In persistent DuckDB mode, model schema can drift from the physical DB
            # (e.g., model has Sales.Discount but DB table is older). Catch this
            # early with a focused error instead of a long Binder stack trace.
            calc_cols_by_table: dict[str, set[str]] = {}
            for tbl in model.tables:
                tbl_name = str(getattr(tbl, "name", "") or "")
                cols = getattr(tbl, "columns", []) or []
                calc_cols: set[str] = set()
                for col_obj in cols:
                    col_name = str(getattr(col_obj, "name", "") or "")
                    is_calc = bool(getattr(col_obj, "is_calculated", False)) or bool(getattr(col_obj, "expression", None))
                    if col_name and is_calc:
                        calc_cols.add(col_name.lower())
                if tbl_name:
                    calc_cols_by_table[tbl_name.lower()] = calc_cols

            def _quote_ident(name: str) -> str:
                return '"' + str(name).replace('"', '""') + '"'

            missing_candidates: list[str] = []
            for tbl, col in parsed_candidates:
                if col.lower() in calc_cols_by_table.get(tbl.lower(), set()):
                    continue
                try:
                    con.execute(f"SELECT {_quote_ident(col)} FROM {_quote_ident(tbl)} LIMIT 0")
                except Exception:
                    missing_candidates.append(f"{tbl}.{col}")

            if missing_candidates:
                cols_str = ", ".join(sorted(set(missing_candidates)))
                hint = (
                    " If DAX_DUCKDB_PATH is set, ensure the physical DuckDB schema is "
                    "refreshed/rebuilt to match the project model."
                )
                return _err(400, f"Candidate column(s) not available in active DuckDB source: {cols_str}.{hint}")

            # Build grouped query with all candidate dimensions
            from dax_engine.ir import MeasureRef as _MRef, ColumnRef as _CRef

            mref = _MRef(name=measure_name)
            dim_cols = [_CRef(table=t, column=c) for t, c in parsed_candidates]

            with _ENGINE_LOCK:
                _table_ir, sql = plan_card_query(mref, filters=dim_cols, model=model)

            rows = con.execute(
                dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
            ).fetchall()

            if not rows:
                from dax_engine.explanations.candidate_pruning import PruningResult as _PR
                return _ok(_PR(
                    target_measure=measure_name,
                    total_candidates_screened=len(parsed_candidates),
                ).to_dict())

            # Extract parallel arrays: first N cols are dimensions, last col is measure
            import numpy as np
            num_dims = len(parsed_candidates)
            measure_values = np.array(
                [float(r[num_dims]) if r[num_dims] is not None else 0.0 for r in rows],
                dtype=float,
            )
            dimension_columns: dict[str, np.ndarray] = {}
            for i, (_tbl, col) in enumerate(parsed_candidates):
                dimension_columns[col] = np.array(
                    [str(r[i]) if r[i] is not None else "" for r in rows]
                )

            # Run the two-stage pruning pipeline
            from dax_engine.explanations.candidate_pruning import CandidatePruner

            pruner = CandidatePruner(
                exclude_id_like=exclude_id_like,
                max_distinct_ratio=max_distinct_ratio,
                min_avg_group_size=min_avg_group_size,
            )
            result = pruner.prune(
                measure_values=measure_values,
                dimension_columns=dimension_columns,
                target_measure=measure_name,
                table_map=table_map,
            )

            return _ok(result.to_dict())
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            # Friendly message for DuckDB column-not-found errors
            if "Binder Error" in msg or "Referenced column" in msg:
                msg = f"Column lookup error during pruning. One or more candidate columns may not exist in the model. Details: {msg}"
            return _err(400, msg)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    def _build_selection_reason(
        *,
        observations: int,
        short_threshold: int,
        min_obs_seasonal: int,
        detected_seasonality_period: Optional[int],
        is_stationary: bool,
    ) -> str:
        if observations < short_threshold:
            return (
                f"Used simple exponential smoothing because only {observations} historical points were available "
                f"(< {short_threshold}), which favors a stable baseline model."
            )
        if detected_seasonality_period is not None and observations >= min_obs_seasonal:
            return (
                f"Used seasonal exponential smoothing (ETS) because repeating patterns were detected "
                f"(period Γëê {detected_seasonality_period}) with enough history ({observations} points)."
            )
        if is_stationary:
            return (
                "Used simple exponential smoothing because the series appears stable over time "
                "(no strong trend/seasonality signal)."
            )
        return (
            "Used linear trend model because the series shows a directional trend "
            "without a strong seasonal pattern."
        )

    def _build_quality_indicator(cv_mape_value: Optional[float]) -> dict[str, str]:
        if cv_mape_value is None:
            return {
                "level": "unknown",
                "label": "Unknown",
                "summary": "Forecast quality could not be estimated from cross-validation metrics.",
            }

        mape_pct = float(cv_mape_value) * 100.0
        if mape_pct <= 10.0:
            return {
                "level": "excellent",
                "label": "Excellent",
                "summary": "Typical forecast error is low; this forecast is generally reliable.",
            }
        if mape_pct <= 20.0:
            return {
                "level": "good",
                "label": "Good",
                "summary": "Typical forecast error is moderate and usually acceptable for planning.",
            }
        if mape_pct <= 35.0:
            return {
                "level": "fair",
                "label": "Fair",
                "summary": "Forecast direction can be useful, but values may deviate noticeably.",
            }
        return {
            "level": "weak",
            "label": "Weak",
            "summary": "Forecast error is high; treat this as directional only and validate manually.",
        }

    def _forecast_model_asset_names(measure_name: str) -> tuple[str, str, str]:
        safe = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(measure_name or "").strip())
        while "__" in safe:
            safe = safe.replace("__", "_")
        safe = safe.strip("_")
        if not safe:
            safe = "Measure"
        table_name = f"Forecast_{safe}"
        csv_rel_path = f"data/forecast_{safe}.csv"
        measure_name_out = f"Forecast {measure_name} (Active)"
        return table_name, csv_rel_path, measure_name_out

    def _materialize_forecast_model_assets(
        *,
        project_path: str,
        measure_name: str,
        version_obj: Any,
    ) -> tuple[str, str]:
        import csv as _csv

        table_name, csv_rel_path, forecast_measure_name = _forecast_model_asset_names(measure_name)
        csv_path = Path(project_path) / csv_rel_path
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = _csv.writer(f)
            writer.writerow([
                "grain_value",
                "forecast_value",
                "forecast_lower",
                "forecast_upper",
                "confidence_level",
                "version",
                "measure_name",
            ])
            for row in list(getattr(version_obj, "rows", []) or []):
                writer.writerow([
                    str(getattr(row, "grain_value", "") or ""),
                    float(getattr(row, "forecast_value", 0.0) or 0.0),
                    float(getattr(row, "forecast_lower", 0.0) or 0.0),
                    float(getattr(row, "forecast_upper", 0.0) or 0.0),
                    float(getattr(row, "confidence_level", 0.95) or 0.95),
                    int(getattr(version_obj, "version", 0) or 0),
                    str(measure_name),
                ])

        upsert_table_yaml(
            project_path,
            name=table_name,
            columns=[
                {"name": "grain_value", "type": "VARCHAR"},
                {"name": "forecast_value", "type": "DOUBLE"},
                {"name": "forecast_lower", "type": "DOUBLE"},
                {"name": "forecast_upper", "type": "DOUBLE"},
                {"name": "confidence_level", "type": "DOUBLE"},
                {"name": "version", "type": "INTEGER"},
                {"name": "measure_name", "type": "VARCHAR"},
            ],
            source={"type": "csv", "path": csv_rel_path},
            is_calculated=False,
            description=f"Auto-generated active forecast baseline for {measure_name}",
            folder="Forecasts",
            table_type="fact",
        )

        update_measure_yaml(
            project_path,
            name=forecast_measure_name,
            dax=f"SUM({table_name}[forecast_value])",
            description=f"Active forecast baseline for {measure_name}",
            folder="Forecasts",
            format="#,0.00",
        )

        return table_name, forecast_measure_name

    def _response_from_persisted_version(
        project_path: str,
        measure_name: str,
        *,
        version: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        try:
            from dax_engine.explanations.forecast_persistence import ForecastStore
        except ImportError:
            return None

        store = ForecastStore(project_path)
        version_obj = store.get_active_version(measure_name) if version is None else store.get_version(measure_name, version)
        if version_obj is None:
            return None

        row_dicts: list[dict[str, Any]] = []
        for row in version_obj.rows:
            row_dicts.append(
                {
                    "grain_value": row.grain_value,
                    "forecast_value": row.forecast_value,
                    "forecast_lower": row.forecast_lower,
                    "forecast_upper": row.forecast_upper,
                }
            )

        cv_rmse_value = version_obj.cv_rmse if version_obj.cv_rmse >= 0 else None
        cv_mape_value = version_obj.cv_mape if version_obj.cv_mape >= 0 else None

        selection_factors = {
            "observations": 0,
            "short_series_threshold": 12,
            "seasonal_min_observations": 24,
            "detected_seasonality_period": None,
            "is_stationary": False,
            "history_periods_requested": None,
            "preprocessing_applied": {
                "robust_preprocess": False,
                "log_transform": False,
                "winsorize_quantile": 0.0,
                "clipped_points": 0,
                "clipped_share": 0.0,
            },
            "algorithm_selection_mode": "heuristic",
            "candidate_algorithms": [],
        }

        response = {
            "measure": measure_name,
            "algorithm": version_obj.algorithm,
            "cv_rmse": cv_rmse_value,
            "cv_mape": cv_mape_value,
            "horizon": len(row_dicts),
            "grain": version_obj.grain_column,
            "version": version_obj.version,
            "selection_reason": (
                "Loaded the active saved forecast version from disk. "
                "The original model-selection diagnostics are shown when newly generated."
            ),
            "selection_factors": selection_factors,
            "quality_indicator": _build_quality_indicator(cv_mape_value),
            "rows": row_dicts,
        }
        return response

    @app.post("/runtime/explanations/forecast")
    def runtime_trigger_forecast(project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Trigger a forecast for a measure.

        Request body:
            measure: str -- name of the measure to forecast
            horizon: int -- number of future periods (default 6)
            grain: str -- time grain column name (default "Month")

        The endpoint:
        1. Validates the measure exists in the model
        2. Queries historical values grouped by the grain column
        3. Runs Forecaster().forecast() with PurgedKFoldCV
        4. Caches and returns the result
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Forecast")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = str(payload.get("measure") or "").strip()
        if not measure_name:
            return _err(400, "measure is required")

        horizon = payload.get("horizon") or payload.get("periods") or 6
        if not isinstance(horizon, int) or horizon < 1:
            return _err(400, f"horizon must be a positive integer, got {horizon!r}")
        if horizon > 120:
            return _err(400, f"horizon too large ({horizon}). Maximum is 120 periods (10 years monthly).")

        grain = str(payload.get("grain") or "Month").strip()

        history_periods_raw = payload.get("history_periods")
        history_periods: Optional[int] = None
        if history_periods_raw is not None and history_periods_raw != "":
            if not isinstance(history_periods_raw, int):
                return _err(400, f"history_periods must be an integer, got {history_periods_raw!r}")
            if history_periods_raw < 8:
                return _err(400, f"history_periods must be >= 8, got {history_periods_raw}")
            if history_periods_raw > 240:
                return _err(400, f"history_periods too large ({history_periods_raw}). Maximum is 240 periods.")
            history_periods = int(history_periods_raw)

        robust_preprocess_raw = payload.get("robust_preprocess", True)
        if not isinstance(robust_preprocess_raw, bool):
            return _err(400, f"robust_preprocess must be boolean, got {robust_preprocess_raw!r}")
        robust_preprocess = bool(robust_preprocess_raw)

        log_transform_raw = payload.get("log_transform", False)
        if not isinstance(log_transform_raw, bool):
            return _err(400, f"log_transform must be boolean, got {log_transform_raw!r}")
        log_transform_requested = bool(log_transform_raw)

        algorithm_selection_mode = str(payload.get("algorithm_selection_mode") or "cv_auto").strip().lower()
        if algorithm_selection_mode not in {"cv_auto", "heuristic"}:
            return _err(400, "algorithm_selection_mode must be 'cv_auto' or 'heuristic'")

        winsorize_quantile = 0.05

        con = None
        try:
            model, _pages, _visuals = load_project(project_path)

            # Verify measure exists
            measure_found = any(
                (m.name if hasattr(m, "name") else str(m)) == measure_name
                for m in model.measures
            )
            if not measure_found:
                return _err(400, f"Measure not found: {measure_name!r}")

            # Find a date/grain column in the model.
            # Search for a column matching the grain name (e.g., "Month") across all tables.
            from dax_engine.ir import ColumnRef as _CRef, MeasureRef as _MRef

            grain_col_ref = None
            for tbl in model.tables:
                tbl_name = tbl.name if hasattr(tbl, "name") else str(tbl)
                cols = tbl.columns if hasattr(tbl, "columns") else []
                for col in cols:
                    col_name = col.name if hasattr(col, "name") else str(col)
                    if col_name.upper() == grain.upper():
                        grain_col_ref = _CRef(table=tbl_name, column=col_name)
                        break
                if grain_col_ref is not None:
                    break

            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

            import numpy as np
            from dax_engine.explanations.forecast import AlgorithmSelector, Forecaster, PurgedKFoldCV, forecast_row_to_dict

            if grain_col_ref is not None:
                # Query measure grouped by grain column
                mref = _MRef(name=measure_name)
                with _ENGINE_LOCK:
                    _table_ir, sql = plan_card_query(
                        mref,
                        filters=[grain_col_ref],
                        model=model,
                    )
                rows = con.execute(
                    dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                ).fetchall()

                if not rows or len(rows) < 2:
                    return _err(400, f"Insufficient historical data for measure {measure_name!r} at grain {grain!r}")

                # rows are (grain_value, measure_value) ΓÇö sort by grain
                sorted_rows = sorted(rows, key=lambda r: str(r[0]) if r[0] is not None else "")
                dates = np.array([str(r[0]) for r in sorted_rows if r[0] is not None and r[1] is not None])
                values = np.array([float(r[1]) for r in sorted_rows if r[0] is not None and r[1] is not None], dtype=np.float64)
            else:
                # No grain column found ΓÇö try evaluating the measure as a scalar series
                # (fallback: generate synthetic index)
                return _err(400, f"Grain column {grain!r} not found in model. Cannot generate time series for forecasting.")

            if history_periods is not None and len(values) > history_periods:
                values = values[-history_periods:]
                dates = dates[-history_periods:]

            if len(values) < 2:
                return _err(400, f"Insufficient non-null data points ({len(values)}) for measure {measure_name!r}")

            clipped_points = 0
            if robust_preprocess and len(values) >= 8:
                lower_q = float(np.quantile(values, winsorize_quantile))
                upper_q = float(np.quantile(values, 1.0 - winsorize_quantile))
                clipped_mask = (values < lower_q) | (values > upper_q)
                clipped_points = int(np.count_nonzero(clipped_mask))
                values = np.clip(values, lower_q, upper_q)

            log_transform_applied = False
            if log_transform_requested:
                if np.any(values <= 0):
                    return _err(400, "log_transform requires strictly positive historical values")
                values = np.log(values)
                log_transform_applied = True

            # Run forecast
            selector = AlgorithmSelector()
            observations = int(len(values))
            detected_seasonality_period = selector._detect_seasonality(values)
            is_stationary = selector._is_stationary(values)
            heuristic_algorithm = selector.select(values, dates)

            forecaster = Forecaster(algorithm_selector=selector)
            candidate_algorithms = ["ses", "linear", "ets"]
            selected_algorithm = heuristic_algorithm

            if algorithm_selection_mode == "cv_auto":
                best_tuple: Optional[tuple[float, float, str]] = None
                cv_for_selection = PurgedKFoldCV(n_splits=min(5, len(values) - 2))
                for candidate in candidate_algorithms:
                    try:
                        cand_rmse, cand_mape = cv_for_selection.evaluate(
                            forecaster,
                            values,
                            dates,
                            measure_name,
                            algorithm=candidate,
                        )
                    except Exception:
                        continue

                    if cand_mape == float("inf"):
                        continue

                    score = (float(cand_mape), float(cand_rmse), candidate)
                    if best_tuple is None or score < best_tuple:
                        best_tuple = score

                if best_tuple is not None:
                    selected_algorithm = best_tuple[2]

            result = forecaster.forecast(
                series=values,
                dates=dates,
                measure_name=measure_name,
                horizon=horizon,
                grain_column=grain,
                algorithm=selected_algorithm,
            )

            # Run cross-validation for quality metrics
            cv = PurgedKFoldCV(n_splits=min(5, len(values) - 2))
            try:
                cv_rmse, cv_mape = cv.evaluate(
                    forecaster,
                    values,
                    dates,
                    measure_name,
                    algorithm=result.algorithm,
                )
            except Exception:
                cv_rmse, cv_mape = float("inf"), float("inf")

            short_threshold = int(getattr(selector, "_short_threshold", 12))
            min_obs_seasonal = int(getattr(selector, "_min_obs_seasonal", 24))
            selection_reason = _build_selection_reason(
                observations=observations,
                short_threshold=short_threshold,
                min_obs_seasonal=min_obs_seasonal,
                detected_seasonality_period=detected_seasonality_period,
                is_stationary=is_stationary,
            )
            if algorithm_selection_mode == "cv_auto":
                selection_reason = (
                    f"{selection_reason} Final model chosen by cross-validation among "
                    f"{', '.join(candidate_algorithms)}: {result.algorithm}."
                )

            cv_mape_response = cv_mape if cv_mape != float("inf") else None
            quality_indicator = _build_quality_indicator(cv_mape_response)

            # Build response
            response_rows = []
            for row in result.rows:
                forecast_value = float(row.forecast_value)
                forecast_lower = float(row.forecast_lower)
                forecast_upper = float(row.forecast_upper)
                if log_transform_applied:
                    forecast_value = float(np.exp(forecast_value))
                    forecast_lower = float(np.exp(forecast_lower))
                    forecast_upper = float(np.exp(forecast_upper))
                response_rows.append({
                    "grain_value": row.grain_value,
                    "forecast_value": forecast_value,
                    "forecast_lower": forecast_lower,
                    "forecast_upper": forecast_upper,
                })

            response = {
                "measure": measure_name,
                "algorithm": result.algorithm,
                "cv_rmse": cv_rmse if cv_rmse != float("inf") else None,
                "cv_mape": cv_mape_response,
                "horizon": horizon,
                "grain": grain,
                "selection_reason": selection_reason,
                "selection_factors": {
                    "observations": observations,
                    "short_series_threshold": short_threshold,
                    "seasonal_min_observations": min_obs_seasonal,
                    "detected_seasonality_period": detected_seasonality_period,
                    "is_stationary": is_stationary,
                    "history_periods_requested": history_periods,
                    "preprocessing_applied": {
                        "robust_preprocess": robust_preprocess,
                        "log_transform": log_transform_applied,
                        "winsorize_quantile": winsorize_quantile,
                        "clipped_points": clipped_points,
                        "clipped_share": float(clipped_points / observations) if observations > 0 else 0.0,
                    },
                    "algorithm_selection_mode": algorithm_selection_mode,
                    "candidate_algorithms": candidate_algorithms,
                },
                "quality_indicator": quality_indicator,
                "rows": response_rows,
            }

            # Cache the result
            cache_key = f"{project_path}::{measure_name}"
            _forecast_cache[cache_key] = response

            # Persist as a versioned forecast baseline
            try:
                from dax_engine.explanations.forecast_persistence import (
                    ForecastStore,
                    ForecastRow as _FRow,
                    ForecastVersion as _FVer,
                )
                from datetime import datetime as _fdt, timezone as _ftz
                import json as _fjson

                store = ForecastStore(project_path)
                forecast_rows = [
                    _FRow(
                        grain_value=r["grain_value"],
                        forecast_value=r["forecast_value"],
                        forecast_lower=r["forecast_lower"],
                        forecast_upper=r["forecast_upper"],
                    )
                    for r in response_rows
                ]
                fver = _FVer(
                    version=0,  # auto-incremented by store
                    measure_name=measure_name,
                    grain_column=grain,
                    rows=forecast_rows,
                    algorithm=result.algorithm,
                    model_params_json=_fjson.dumps(getattr(result, "model_params", {})),
                    training_start=str(dates[0]) if len(dates) > 0 else "",
                    training_end=str(dates[-1]) if len(dates) > 0 else "",
                    cv_rmse=cv_rmse if cv_rmse != float("inf") else -1.0,
                    cv_mape=cv_mape if cv_mape != float("inf") else -1.0,
                    generated_ts=_fdt.now(_ftz.utc).isoformat(),
                    is_active=True,
                )
                ver_num = store.save_version(fver)
                response["version"] = ver_num

                try:
                    active_saved = store.get_active_version(measure_name)
                    if active_saved is not None:
                        table_name, forecast_measure_name = _materialize_forecast_model_assets(
                            project_path=project_path,
                            measure_name=measure_name,
                            version_obj=active_saved,
                        )
                        response["model_artifacts"] = {
                            "table": table_name,
                            "measure": forecast_measure_name,
                        }
                except Exception as _materialize_exc:
                    logger.warning("Failed to materialize forecast model assets: %s", _materialize_exc)
            except Exception as _persist_exc:
                logger.warning("Failed to persist forecast version: %s", _persist_exc)

            return _ok(response)

        except Exception as exc:
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/explanations/forecast/{measure}")
    def runtime_get_forecast(measure: str, project: Optional[str] = None):
        """Return the last forecast result for a measure (if cached).

        Returns 404 if no forecast has been generated for this measure.
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Forecast")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = measure.strip()
        if not measure_name:
            return _err(400, "measure name is required")

        cache_key = f"{project_path}::{measure_name}"
        cached = _forecast_cache.get(cache_key)
        if cached is None:
            try:
                persisted = _response_from_persisted_version(project_path, measure_name)
            except Exception as exc:  # noqa: BLE001
                return _err(400, str(exc))
            if persisted is None:
                return _err(404, f"No forecast found for measure {measure_name!r}. Trigger a forecast first via POST /runtime/explanations/forecast.")
            _forecast_cache[cache_key] = persisted
            return _ok(persisted)

        return _ok(cached)

    @app.get("/runtime/explanations/regime-changes/{playbook_name}")
    def runtime_regime_changes(
        playbook_name: str,
        project: Optional[str] = None,
        date_table: Optional[str] = None,
        date_column: Optional[str] = None,
        grain: Optional[str] = None,
    ):
        """Detect regime changes in driver contribution patterns for a playbook.

        Runs the ``RegimeChangeDetector`` on historical driver contributions
        derived from the playbook's entry EDUs and drivers.  Returns a list
        of detected structural rank-shift events (informational only).
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("ML Analytics")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        con = None
        try:
            playbooks = load_playbooks(project_path)
            if playbook_name not in playbooks:
                return _err(404, f"Playbook not found: {playbook_name!r}")

            playbook = playbooks[playbook_name]
            model, _pages, _visuals = load_project(project_path)

            con = _connect_duckdb_for_project(
                project_path=project_path,
                duckdb_path=os.environ.get("DAX_DUCKDB_PATH"),
                model=model,
            )

            with _ENGINE_LOCK:
                get_prepared_engine(project_path, model)

            # Build driver contribution series from dimensional drivers.
            # For each dimensional driver, we query the measure grouped by
            # the dimension column and collect contribution values per period.
            # If no dimensional drivers or insufficient data, return empty.
            from dax_engine.explanations.regime_change import (
                RegimeChangeDetector,
            )
            from dax_engine.autogen.introspector import ModelIntrospector
            from datetime import datetime as _dt

            def _is_date_like_column(col_name: str, col_type: str) -> bool:
                ctype = (col_type or "").upper()
                cname = (col_name or "").upper()
                if ctype in {"DATE", "DATETIME", "TIMESTAMP", "TIMESTAMPTZ"}:
                    return True
                return "DATE" in cname or cname.endswith("_DT") or cname.endswith("_DATE")

            def _build_date_column_candidates(model_obj: Any) -> list[dict[str, str]]:
                candidates: list[dict[str, str]] = []
                seen: set[tuple[str, str]] = set()
                for table_obj in (getattr(model_obj, "tables", None) or []):
                    table_name = getattr(table_obj, "name", "")
                    if not table_name:
                        continue
                    for col_obj in (getattr(table_obj, "columns", None) or []):
                        col_name = getattr(col_obj, "name", "")
                        col_type = getattr(col_obj, "type", "")
                        if not col_name or not _is_date_like_column(col_name, col_type):
                            continue
                        key = (table_name, col_name)
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append(
                            {
                                "table": table_name,
                                "column": col_name,
                                "ref": f"{table_name}[{col_name}]",
                                "type": str(col_type or ""),
                            }
                        )
                candidates.sort(key=lambda x: (x["table"].upper(), x["column"].upper()))
                return candidates

            def _parse_period_label(raw: Any, selected_grain: str) -> str:
                raw_text = "" if raw is None else str(raw)
                if not raw_text:
                    return ""
                try:
                    parsed = _dt.fromisoformat(raw_text.replace("Z", "+00:00"))
                except Exception:
                    return raw_text

                g = selected_grain.lower()
                if g == "day":
                    return parsed.date().isoformat()
                if g == "week":
                    iso = parsed.isocalendar()
                    return f"{iso.year}-W{iso.week:02d}"
                if g == "month":
                    return f"{parsed.year}-{parsed.month:02d}"
                if g == "quarter":
                    q = ((parsed.month - 1) // 3) + 1
                    return f"{parsed.year}-Q{q}"
                if g == "year":
                    return f"{parsed.year}"
                return raw_text

            allowed_grains = ["Day", "Week", "Month", "Quarter", "Year"]
            requested_grain = str(grain or "").strip()
            normalized_grain = "Month"
            if requested_grain:
                normalized = requested_grain.lower()
                if normalized not in {g.lower() for g in allowed_grains}:
                    return _err(400, f"Invalid grain {requested_grain!r}. Allowed values: {', '.join(allowed_grains)}")
                normalized_grain = next(g for g in allowed_grains if g.lower() == normalized)

            driver_series: dict[str, list[float]] = {}
            periods_evaluated = 0
            entry_metric_name = (
                playbook.entry_edus[0].metric
                if getattr(playbook, "entry_edus", None)
                else None
            )

            date_candidates = _build_date_column_candidates(model)
            introspector = ModelIntrospector(model)
            inferred_table = ""
            inferred_column = ""
            date_info = introspector.detect_date_table()
            if isinstance(date_info, dict):
                inferred_table = str(date_info.get("table") or "")
                inferred_column = str(date_info.get("date_column") or "")

            if not inferred_table or not inferred_column:
                if date_candidates:
                    inferred_table = date_candidates[0]["table"]
                    inferred_column = date_candidates[0]["column"]

            user_overrode_date = bool(str(date_table or "").strip() or str(date_column or "").strip())
            effective_date_table = str(date_table or "").strip() or inferred_table
            effective_date_column = str(date_column or "").strip() or inferred_column
            user_overrode_grain = bool(requested_grain)

            if user_overrode_date and not (effective_date_table and effective_date_column):
                return _err(400, "Both date_table and date_column are required when overriding date axis")

            if effective_date_table and effective_date_column:
                try:
                    _validate_columnref_in_model(model, effective_date_table, effective_date_column)
                except Exception as date_exc:
                    return _err(400, f"Invalid date axis override: {date_exc}")

            period_driver_values: dict[str, dict[str, float]] = {}
            for driver in playbook.drivers:
                if driver.mode != "dimensional":
                    continue
                dim_table = getattr(driver, "dimension_table", None)
                dim_column = getattr(driver, "dimension_column", None)
                if not dim_table or not dim_column:
                    continue

                # Query the metric grouped by the dimension column
                entry_edu = playbook.entry_edus[0] if playbook.entry_edus else None
                if not entry_edu:
                    continue

                metric = entry_edu.metric
                try:
                    from dax_engine.ir import ColumnRef as _CRef, MeasureRef as _MRef

                    mref = _MRef(name=metric)
                    dim_col = _CRef(table=dim_table, column=dim_column)
                    if not effective_date_table or not effective_date_column:
                        continue
                    date_col = _CRef(table=effective_date_table, column=effective_date_column)
                    with _ENGINE_LOCK:
                        _t, sql = plan_card_query(mref, filters=[date_col, dim_col], model=model)
                    rows = con.execute(
                        dax_compiler.normalize_sql(f"SELECT * FROM {sql}")
                    ).fetchall()
                    # Rows are expected as (period_value, dim_value, measure_value).
                    for row in rows:
                        if len(row) < 3:
                            continue
                        period_raw, dim_raw, measure_raw = row[0], row[1], row[2]
                        if period_raw is None or dim_raw is None or measure_raw is None:
                            continue
                        period_key = _parse_period_label(period_raw, normalized_grain)
                        if not period_key:
                            continue
                        driver_key = f"{dim_column}={dim_raw}"
                        period_bucket = period_driver_values.setdefault(period_key, {})
                        period_bucket[driver_key] = period_bucket.get(driver_key, 0.0) + float(measure_raw)
                except Exception:
                    logger.warning(
                        "Regime change query failed for driver %s", driver.id, exc_info=True,
                    )
                    continue

            if period_driver_values:
                period_keys_sorted = sorted(period_driver_values.keys())
                all_drivers = sorted(
                    {
                        drv
                        for period_map in period_driver_values.values()
                        for drv in period_map.keys()
                    }
                )
                for drv in all_drivers:
                    driver_series[drv] = [
                        float(period_driver_values[p].get(drv, 0.0))
                        for p in period_keys_sorted
                    ]

            # Run regime change detection
            detector = RegimeChangeDetector(min_periods=6)
            # Only run if we have series and all are the same length
            events_list: list[dict] = []
            if driver_series:
                # Ensure all series have the same length (trim to min if needed)
                min_len = min(len(v) for v in driver_series.values())
                if min_len >= 2:
                    periods_evaluated = min_len
                    trimmed = {k: v[:min_len] for k, v in driver_series.items()}
                    try:
                        events = detector.detect(trimmed)
                        events_list = [
                            {
                                "driver": e.driver_name,
                                "old_rank": e.old_rank,
                                "new_rank": e.new_rank,
                                "period": e.changepoint_period,
                                "confidence": e.confidence,
                                "measure": entry_metric_name,
                            }
                            for e in events
                        ]
                    except Exception:
                        logger.warning(
                            "Regime change detection failed for playbook %s",
                            playbook_name,
                            exc_info=True,
                        )

            detector_details = {
                "algorithm": "PELT (ruptures)",
                "algorithm_description": (
                    "Exact changepoint detection over per-driver rank series across periods."
                ),
                "cost_model": detector.model,
                "min_periods": detector.min_periods,
                "penalty_formula": "log(n) * penalty_multiplier",
                "penalty_multiplier": detector.penalty_multiplier,
                "confidence_formula": "1 - (cost_split / cost_whole)",
                "informational_only": True,
            }

            analysis_details = {
                "playbook": playbook_name,
                "measure": entry_metric_name,
                "drivers_considered": len(driver_series),
                "periods_evaluated": periods_evaluated,
                "inferred_date_column": (
                    f"{inferred_table}[{inferred_column}]"
                    if inferred_table and inferred_column
                    else None
                ),
                "effective_date_column": (
                    f"{effective_date_table}[{effective_date_column}]"
                    if effective_date_table and effective_date_column
                    else None
                ),
                "grain_inferred": "Month",
                "grain_effective": normalized_grain,
                "date_overridden": user_overrode_date,
                "grain_overridden": user_overrode_grain,
                "date_column_options": date_candidates,
                "grain_options": allowed_grains,
            }

            return _ok(
                {
                    "regime_changes": events_list,
                    "detector": detector_details,
                    "analysis": analysis_details,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @app.get("/runtime/forecast/versions/{measure}")
    def runtime_forecast_versions(measure: str, project: Optional[str] = None):
        """List all forecast versions for a measure."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Forecast")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = measure.strip()
        if not measure_name:
            return _err(400, "measure name is required")

        try:
            # Validate that the measure exists in the model
            model, _pages, _visuals = load_project(project_path)
            known = {m.name for m in model.measures}
            if measure_name not in known:
                return _err(404, f"Measure '{measure_name}' not found in model")

            from dax_engine.explanations.forecast_persistence import ForecastStore
            store = ForecastStore(project_path)
            versions = store.list_versions(measure_name)
            return _ok({"measure": measure_name, "versions": versions})
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/forecast/versions/{measure}/{version}")
    def runtime_forecast_get_version(measure: str, version: int, project: Optional[str] = None):
        """Return full forecast details for a specific persisted version."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Forecast")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = measure.strip()
        if not measure_name:
            return _err(400, "measure name is required")
        if version < 1:
            return _err(400, f"version must be a positive integer, got {version!r}")

        try:
            persisted = _response_from_persisted_version(project_path, measure_name, version=version)
            if persisted is None:
                return _err(404, f"Version {version} not found for measure {measure_name!r}")
            _forecast_cache[f"{project_path}::{measure_name}"] = persisted
            return _ok(persisted)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.put("/runtime/forecast/versions/{measure}/active")
    def runtime_forecast_set_active(measure: str, project: Optional[str] = None, payload: dict = Body(default_factory=dict)):
        """Set the active forecast version for a measure.

        Request body:
            version: int -- the version number to activate
        """
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Forecast")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = measure.strip()
        if not measure_name:
            return _err(400, "measure name is required")

        version_num = payload.get("version")
        if not isinstance(version_num, int) or version_num < 1:
            return _err(400, f"version must be a positive integer, got {version_num!r}")

        try:
            from dax_engine.explanations.forecast_persistence import ForecastStore
            store = ForecastStore(project_path)
            store.set_active(measure_name, version_num)
            try:
                refreshed = _response_from_persisted_version(project_path, measure_name)
                if refreshed is not None:
                    _forecast_cache[f"{project_path}::{measure_name}"] = refreshed
            except Exception:
                pass
            try:
                active_saved = store.get_active_version(measure_name)
                if active_saved is not None:
                    _materialize_forecast_model_assets(
                        project_path=project_path,
                        measure_name=measure_name,
                        version_obj=active_saved,
                    )
            except Exception as _materialize_exc:
                logger.warning("Failed to materialize forecast model assets after activation: %s", _materialize_exc)
            return _ok({"measure": measure_name, "active_version": version_num})
        except ValueError as exc:
            return _err(404, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.delete("/runtime/forecast/versions/{measure}/{version}")
    def runtime_forecast_delete_version(measure: str, version: int, project: Optional[str] = None):
        """Delete a specific forecast version."""
        if not _HAS_ENTERPRISE_EXPLANATIONS:
            return _enterprise_only("Forecast")
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        measure_name = measure.strip()
        if not measure_name:
            return _err(400, "measure name is required")

        try:
            from dax_engine.explanations.forecast_persistence import ForecastStore
            store = ForecastStore(project_path)
            store.delete_version(measure_name, version)
            return _ok({"measure": measure_name, "deleted_version": version})
        except ValueError as exc:
            return _err(404, str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

    @app.get("/runtime/ml/status")
    def runtime_ml_status():
        """Return which ML capabilities are currently available."""
        capabilities: dict[str, bool] = {
            "pruning": False,
            "forecast": False,
            "regime_change": False,
        }
        try:
            from dax_engine.explanations.candidate_pruning import CandidatePruner  # noqa: F401
            capabilities["pruning"] = True
        except ImportError:
            pass
        try:
            from dax_engine.explanations.forecast import Forecaster  # noqa: F401
            capabilities["forecast"] = True
        except ImportError:
            pass
        try:
            from dax_engine.explanations.regime_change import RegimeChangeDetector  # noqa: F401
            capabilities["regime_change"] = True
        except ImportError:
            pass
        return _ok({"capabilities": capabilities})

    @app.get("/runtime")
    def runtime_state(request: Request, project: Optional[str] = None, page: Optional[str] = None):
        try:
            project_path = _resolve_project_path_runtime(project)
        except Exception as exc:  # noqa: BLE001
            # Avoid noisy 400s on initial UI load when neither ?project nor
            # DAX_PROJECT_PATH is provided. The UI treats ok:false as an error
            # and will show the message, but a 200 avoids failing requests in logs.
            return _err(200, str(exc))

        try:
            model, pages, _visuals = load_project(project_path)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            role_name, role = _resolve_security_for_request(model=model, request=request, payload=None)
            model_scoped = apply_ols(model, role)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            current_page = _select_page_id(pages, page)
        except Exception as exc:  # noqa: BLE001
            return _err(400, str(exc))

        try:
            # Registry metadata.
            registry = load_visual_type_registry(project_path)
            registry_json = {
                k: {
                    "key": v.key,
                    "label": v.label,
                    "renderer": v.renderer,
                    "px_func": v.px_func,
                    "static": v.static,
                    "slots": {sn: {"kind": ss.kind, "required": ss.required, "multi": ss.multi} for sn, ss in v.slots.items()},
                }
                for k, v in registry.items()
            }

            # Visuals: read raw JSON to keep encodings JSON-friendly.
            visuals_dir = Path(project_path) / "reports" / "visuals"
            visuals_raw = []
            if visuals_dir.exists() and visuals_dir.is_dir():
                for p in sorted(visuals_dir.glob("*.json")):
                    try:
                        v = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(v, dict):
                            if not isinstance(v.get("page_id"), str) or not str(v.get("page_id") or "").strip():
                                # Back-compat: visuals that predate pages default to the server-selected current_page.
                                v["page_id"] = current_page

                            # Back-compat: older visuals may not have interactions config.
                            v["interactions"] = _normalize_visual_interactions(v.get("interactions"))

                            # Back-compat: PBI-transferred visuals need default format properties
                            # that match PBI behavior (hidden headers, transparent textbox bg, etc.)
                            vid = v.get("id", "")
                            vtype_lower = (v.get("visual_type") or "").lower()
                            is_pbi = vid.startswith("pbi_")
                            if is_pbi:
                                fmt = v.setdefault("format", {})
                                # PBI default: non-chart types hide title; chart types show it.
                                _PBI_CHART_TYPES = {"bar","column","combo","line","area","scatter","pie","donut","treemap","funnel","waterfall","histogram","box","violin","matrix","table"}
                                if "showTitle" not in fmt:
                                    fmt["showTitle"] = vtype_lower in _PBI_CHART_TYPES
                                if "showVisualHeader" not in fmt:
                                    fmt["showVisualHeader"] = vtype_lower in _PBI_CHART_TYPES
                                # PBI default: textbox backgrounds are transparent
                                if vtype_lower == "textbox" and "background_show" not in fmt:
                                    fmt["background_show"] = False

                            # Back-compat: build static_content from textbox_content/shape_properties
                            # if not already present (for visuals transferred before static_content was added).
                            if not v.get("static_content"):
                                vtype = (v.get("visual_type") or "").lower()
                                if vtype == "textbox" and v.get("textbox_content"):
                                    lines = []
                                    first_style: dict = {}
                                    for para in v["textbox_content"]:
                                        parts = [run.get("value", "") for run in para.get("text_runs", [])]
                                        lines.append("".join(parts))
                                        if not first_style:
                                            for run in para.get("text_runs", []):
                                                if run.get("style"):
                                                    first_style = run["style"]
                                                    break
                                    sc: dict = {"text": "\n".join(lines), "backgroundColor": "transparent"}
                                    fs = first_style.get("fontSize", "")
                                    if isinstance(fs, str) and fs.endswith("pt"):
                                        try:
                                            sc["fontSize"] = int(fs.replace("pt", ""))
                                        except ValueError:
                                            pass
                                    if first_style.get("color"):
                                        sc["color"] = first_style["color"]
                                    if first_style.get("fontWeight"):
                                        sc["fontWeight"] = first_style["fontWeight"]
                                    v["static_content"] = sc
                                elif vtype == "shape":
                                    sp = v.get("shape_properties") or {}
                                    sc2: dict = {
                                        "shapeType": sp.get("shape_type", "rectangle"),
                                        "opacity": 1.0,
                                    }
                                    if sp.get("fill_show") is False:
                                        sc2["fill"] = "transparent"
                                    elif sp.get("fill_color"):
                                        sc2["fill"] = sp["fill_color"]
                                    else:
                                        sc2["fill"] = "#FFFFFF"
                                    if sp.get("outline_show") is False:
                                        sc2["stroke"] = "transparent"
                                        sc2["strokeWidth"] = 0
                                    elif sp.get("outline_color"):
                                        sc2["stroke"] = sp["outline_color"]
                                    else:
                                        sc2["stroke"] = "transparent"
                                        sc2["strokeWidth"] = 0
                                    v["static_content"] = sc2

                            if str(v.get("page_id")).strip() == current_page:
                                visuals_raw.append(v)
                    except Exception:
                        continue

            # Build physical tables list (include table_type and storage_mode for Model View classification)
            _table_type_lookup = {t.name.upper(): getattr(t, "table_type", None) for t in model_scoped.tables}
            _table_is_calculated_lookup = {
                t.name.upper(): bool(getattr(t, "is_calculated", False)) or bool(getattr(t, "expression", None))
                for t in model_scoped.tables
            }
            _storage_mode_lookup = {t.name.upper(): getattr(t, "storage_mode", None) for t in model_scoped.tables}
            # Build sort_by_column map per table  {TableName -> {col -> sort_by_col}}
            _sort_by_map: dict[str, dict[str, str]] = {}
            # Build column_types map per table  {TableName -> {col -> type_str}}
            _col_type_map: dict[str, dict[str, str]] = {}
            for _tbl in model_scoped.tables:
                _sbc: dict[str, str] = {}
                _ctm: dict[str, str] = {}
                for _col in _tbl.columns:
                    _sb = getattr(_col, "sort_by_column", None)
                    if _sb:
                        _sbc[_col.name] = _sb
                    _ctm[_col.name] = getattr(_col, "type", "VARCHAR")
                if _sbc:
                    _sort_by_map[_tbl.name] = _sbc
                if _ctm:
                    _col_type_map[_tbl.name] = _ctm
            physical_tables = [
                {
                    "name": t,
                    "columns": list_columns(model_scoped, t),
                    "table_type": _table_type_lookup.get(t.upper()),
                    "is_calculated": _table_is_calculated_lookup.get(t.upper(), False),
                    "storage_mode": _storage_mode_lookup.get(t.upper()) or "import",
                    **({"sort_by_columns": _sort_by_map[t]} if t in _sort_by_map else {}),
                    **({"column_types": _col_type_map[t]} if t in _col_type_map else {}),
                }
                for t in list_tables(model_scoped)
            ]

            # Build virtual tables (Power BI parity: field params, calc groups, what-if)
            virtual_tables = _build_virtual_tables(model_scoped)

            fields = {
                "tables": physical_tables + virtual_tables,
                "measures": [
                    (m if isinstance(m, str) else str(getattr(m, "name", m)))
                    for m in list_measures(model_scoped)
                ],
            }

            calc_groups_meta = _calc_groups_meta_from_model(model_scoped)
            calc_group_selections = load_calc_group_selections(project_path)
            calc_group_selections_flat = flatten_calc_group_selections(calc_group_selections)
            _validate_calc_group_selections_against_model(model_scoped, calc_group_selections_flat)

            field_params_meta = _field_parameters_meta_from_model(model_scoped)
            field_param_selections = load_field_parameter_selections(project_path)
            field_param_selections_flat = flatten_field_parameter_selections(field_param_selections)
            _validate_field_parameter_selections_against_model(model_scoped, field_param_selections_flat)

            what_if_params_meta = _what_if_parameters_meta_from_model(model_scoped)
            what_if_selections = load_what_if_selections(project_path)
            what_if_selections_flat = flatten_what_if_selections(what_if_selections)
            _validate_what_if_selections_against_model(model_scoped, what_if_selections_flat)

            # Load explanation playbooks for the fields pane
            try:
                _playbooks = load_playbooks(project_path)
                explanations_meta = [
                    {
                        "name": pb.name,
                        "version": pb.version,
                        "description": pb.description,
                        "edus": [
                            {
                                "id": edu.id,
                                "metric": edu.metric,
                                "comparator": edu.comparator.value if hasattr(edu.comparator, "value") else str(edu.comparator),
                                "grain": edu.grain,
                            }
                            for edu in pb.entry_edus
                        ],
                        "drivers": [
                            _driver_to_dict(d)
                            for d in pb.drivers
                        ],
                    }
                    for pb in _playbooks.values()
                ]
            except Exception:
                explanations_meta = []


            pages_sorted = _sorted_pages(pages)
            pages_json = []
            for p in pages_sorted:
                page_entry = {
                    "id": getattr(p, "id"),
                    "title": getattr(p, "title"),
                    "order": getattr(p, "order", None),
                }
                page_type = getattr(p, "page_type", None)
                if isinstance(page_type, str) and page_type.strip():
                    page_entry["page_type"] = page_type.strip()
                placeholder_containers = getattr(p, "placeholder_containers", None)
                if isinstance(placeholder_containers, list):
                    page_entry["placeholder_containers"] = [
                        item.strip()
                        for item in placeholder_containers
                        if isinstance(item, str) and item.strip()
                    ]
                # Drillthrough support
                if getattr(p, "drillthrough", False):
                    page_entry["drillthrough"] = True
                    dt_cols = getattr(p, "drillthrough_columns", None)
                    if isinstance(dt_cols, list) and dt_cols:
                        page_entry["drillthrough_columns"] = list(dt_cols)
                # Hidden page support
                if getattr(p, "hidden", False):
                    page_entry["hidden"] = True
                # Page dimensions (default 1280×720)
                p_width = getattr(p, "width", None)
                p_height = getattr(p, "height", None)
                if p_width and p_width != 1280:
                    page_entry["width"] = p_width
                if p_height and p_height != 720:
                    page_entry["height"] = p_height
                pages_json.append(page_entry)

            return _ok(
                {
                    "project": project_path,
                    "pages": pages_json,
                    "current_page": current_page,
                    "visuals": visuals_raw,
                    "filters": [],
                    "calc_groups": calc_groups_meta,
                    "calc_group_selections": {**calc_group_selections, "selections": calc_group_selections_flat},
                    "field_parameters": field_params_meta,
                    "field_parameter_selections": {**field_param_selections, "selections": field_param_selections_flat},
                    "what_if_parameters": what_if_params_meta,
                    "what_if_selections": {**what_if_selections, "selections": what_if_selections_flat},
                    "hierarchies": _hierarchies_meta_from_model(model_scoped),
                    "explanations": explanations_meta,
                    "bookmarks": load_bookmarks(project_path).get("bookmarks", []),
                    # New stable names.
                    "registry": registry_json,
                    "symbols": fields,
                    # Back-compat for existing runtime.js callers.
                    "visual_types": registry_json,
                    "fields": fields,
                    "security": {
                        "roles": sorted(list((getattr(model, "security_roles", {}) or {}).keys()), key=lambda s: str(s).upper()),
                        "default_role": getattr(model, "default_role", None),
                        "active_role": role_name,
                    },
                    "relationships": [
                        {
                            "rel_id": (
                                str(getattr(r, "rel_id", "") or "").strip()
                                or f"{getattr(r, 'from_table', '')}.{getattr(r, 'from_column', '')}->{getattr(r, 'to_table', '')}.{getattr(r, 'to_column', '')}"
                            ),
                            "from_table": getattr(r, "from_table", ""),
                            "from_column": getattr(r, "from_column", ""),
                            "to_table": getattr(r, "to_table", ""),
                            "to_column": getattr(r, "to_column", ""),
                            "active": getattr(r, "active", True),
                            "cross_filter_direction": getattr(r, "cross_filter_direction", "single"),
                            "cardinality": getattr(r, "cardinality", None),
                        }
                        for r in (getattr(model, "relationships", None) or [])
                    ],
                    "model_layouts": _load_model_layouts(project_path),
                    "canvas_url": str(request.base_url)
                    + "runtime/ui?project="
                    + project_path
                    + "&page="
                    + current_page,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _err(400, f"Bootstrap error: {exc}")
