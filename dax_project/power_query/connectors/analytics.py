from __future__ import annotations

from typing import Any, Mapping

from .common import bearer_headers, blocked_response, configured_response, http_json_get, infer_schema_from_records, json_records, normalize_url, profile_id, properties, rows_from_records


def execute_analytics(
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
    connector = str(profile.get("connector_id") or "analytics")
    endpoint = str(options.get("endpoint") or props.get("endpoint") or props.get("url") or "").strip()
    if function_name == "GoogleAnalytics.Accounts" and not endpoint:
        endpoint = "https://analyticsadmin.googleapis.com/v1beta/accounts"
    if function_name == "AdobeAnalytics.Cubes" and not endpoint:
        company_id = str(options.get("company_id") or props.get("company_id") or "").strip()
        endpoint = f"https://analytics.adobe.io/api/{company_id}/reports" if company_id else ""
    if not endpoint:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires an API endpoint or provider-specific profile metadata.", connector_id=connector, profile_id=pid)
    if function_name != "Soda.Feed" and not (secrets.get("access_token") or secrets.get("token") or secrets.get("api_key")):
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires OAuth or API-key credentials.", connector_id=connector, profile_id=pid)
    url = normalize_url(endpoint, query=options.get("query") if isinstance(options.get("query"), Mapping) else None)
    payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=float(options.get("timeout") or 10))
    if error:
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed" if status in {401, 403} else "not_configured", code="PQ_LIVE_HTTP_ERROR", message=f"{function_name} request failed: {error}", connector_id=connector, profile_id=pid)
    records = json_records(payload)
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=int(options.get("limit") or 100)), connector_id=connector, profile_id=pid, source={"url": url}, folding_capability="select_filter_supported")

