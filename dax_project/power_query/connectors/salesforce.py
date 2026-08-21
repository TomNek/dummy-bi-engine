from __future__ import annotations

from typing import Any, Mapping

from .common import bearer_headers, blocked_response, configured_response, http_json_get, infer_schema_from_records, json_records, normalize_url, profile_id, properties, rows_from_records


def execute_salesforce(
    *,
    function_name: str,
    operation: str,
    profile: Mapping[str, Any],
    secrets: Mapping[str, Any],
    context: Any,
) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    props = properties(profile)
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    base_url = str(props.get("instance_url") or props.get("base_url") or "").rstrip("/")
    api_version = str(props.get("api_version") or options.get("api_version") or "v60.0")
    if not base_url:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="Salesforce live execution requires properties.instance_url/base_url.", connector_id="salesforce", profile_id=pid)
    if not (secrets.get("access_token") or secrets.get("token")):
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="Salesforce live execution requires an OAuth access token.", connector_id="salesforce", profile_id=pid)
    if function_name == "Salesforce.Reports":
        report_id = str(options.get("report_id") or props.get("report_id") or "").strip()
        endpoint = f"services/data/{api_version}/analytics/reports/{report_id}" if report_id else f"services/data/{api_version}/analytics/reports"
    else:
        soql = options.get("soql") or props.get("soql")
        if soql:
            endpoint = f"services/data/{api_version}/query"
            url = normalize_url(base_url, endpoint, query={"q": soql})
            payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=float(options.get("timeout") or 10))
            return _result(function_name, operation, payload, error, status, profile, pid, url, options)
        object_name = str(options.get("object") or props.get("object") or "").strip()
        endpoint = f"services/data/{api_version}/sobjects/{object_name}/describe" if object_name else f"services/data/{api_version}/sobjects"
    url = normalize_url(base_url, endpoint)
    payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=float(options.get("timeout") or 10))
    return _result(function_name, operation, payload, error, status, profile, pid, url, options)


def _result(function_name: str, operation: str, payload: Any, error: str | None, status: int | None, profile: Mapping[str, Any], pid: str | None, url: str, options: Mapping[str, Any]) -> Any:
    if error:
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed" if status in {401, 403} else "not_configured", code="PQ_LIVE_HTTP_ERROR", message=f"Salesforce request failed: {error}", connector_id="salesforce", profile_id=pid)
    records = payload.get("records") if isinstance(payload, Mapping) and isinstance(payload.get("records"), list) else json_records(payload)
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=int(options.get("limit") or 100)), connector_id="salesforce", profile_id=pid, source={"url": url}, folding_capability="select_filter_supported")

