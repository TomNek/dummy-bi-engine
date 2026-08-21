from __future__ import annotations

import importlib.util
from typing import Any, Mapping

from .common import bearer_headers, blocked_response, configured_response, http_json_get, infer_schema_from_records, json_records, normalize_url, profile_id, properties, rows_from_records


def _powerbi_dataflows(function_name: str, operation: str, profile: Mapping[str, Any], secrets: Mapping[str, Any], context: Any) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    props = properties(profile)
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    if not (secrets.get("access_token") or secrets.get("token") or secrets.get("bearer_token")):
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_SEMANTIC_CONNECTOR_NOT_CONFIGURED", message="PowerBI.Dataflows requires an OAuth access token.", connector_id="powerbi_dataflows", profile_id=pid)
    base = str(props.get("powerbi_base_url") or "https://api.powerbi.com/v1.0/myorg")
    workspace = str(options.get("workspace_id") or props.get("workspace_id") or "").strip()
    dataflow = str(options.get("dataflow_id") or props.get("dataflow_id") or "").strip()
    if not workspace:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_SEMANTIC_CONNECTOR_NOT_CONFIGURED", message="PowerBI.Dataflows requires workspace_id profile metadata.", connector_id="powerbi_dataflows", profile_id=pid)
    path = f"groups/{workspace}/dataflows/{dataflow}" if dataflow else f"groups/{workspace}/dataflows"
    url = normalize_url(base, path)
    payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=float(options.get("timeout") or 10))
    if error:
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed" if status in {401, 403} else "not_configured", code="PQ_LIVE_HTTP_ERROR", message=f"Power BI Dataflows request failed: {error}", connector_id="powerbi_dataflows", profile_id=pid)
    records = json_records(payload)
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=int(options.get("limit") or 100)), connector_id="powerbi_dataflows", profile_id=pid, source={"url": url}, folding_capability="semantic_query")


def execute_semantic_cube(
    *,
    function_name: str,
    operation: str,
    profile: Mapping[str, Any],
    secrets: Mapping[str, Any],
    context: Any,
) -> Any:
    del secrets
    options = dict(getattr(context, "options", {}) or {})
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    connector = str(profile.get("connector_id") or "semantic_cube")
    if function_name == "FabricAI.Prompt":
        if not options.get("enable_live_ai"):
            return blocked_response(function_name=function_name, operation=operation, state="approval_required", code="PQ_FABRIC_AI_DISABLED", message="FabricAI.Prompt live execution is disabled until governed AI execution is explicitly enabled.", connector_id=connector, profile_id=pid)
        return configured_response(function_name=function_name, operation=operation, schema=[{"name": "Prompt", "type": "TEXT"}, {"name": "Result", "type": "TEXT"}], rows=[[str(options.get("prompt") or ""), "Governed live AI execution requested."]], connector_id=connector, profile_id=pid, folding_capability="not_foldable")
    if function_name == "PowerBI.Dataflows":
        return _powerbi_dataflows(function_name, operation, profile, secrets, context)
    if function_name.startswith("Cube."):
        if not (options.get("semantic_model") or options.get("query_plan")):
            return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_SEMANTIC_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires a semantic query plan or live semantic model binding.", connector_id=connector, profile_id=pid)
        return configured_response(function_name=function_name, operation=operation, schema=[{"name": "Dimension", "type": "TEXT"}, {"name": "Member", "type": "TEXT"}, {"name": "Measure", "type": "NUMBER"}], rows=[["Date", "2026", 1]], connector_id=connector, profile_id=pid, folding_capability="semantic_query")
    if function_name in {"AnalysisServices.Database", "AnalysisServices.Databases"}:
        if importlib.util.find_spec("pyadomd") is None and importlib.util.find_spec("pythonnet") is None:
            return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message=f"{function_name} live execution requires optional XMLA/ADOMD bridge support.", connector_id=connector, profile_id=pid)
    if function_name in {"Essbase.Cubes", "SapBusinessWarehouse.Cubes"}:
        return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message=f"{function_name} live execution requires the vendor client SDK and configured provider bridge.", connector_id=connector, profile_id=pid)
    return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_SEMANTIC_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires semantic endpoint metadata, credentials, and a query binding.", connector_id=connector, profile_id=pid)
