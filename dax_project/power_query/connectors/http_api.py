from __future__ import annotations

import urllib.parse
from typing import Any, Mapping

from .common import (
    bearer_headers,
    blocked_response,
    configured_response,
    http_json_get,
    infer_schema_from_records,
    json_records,
    normalize_url,
    profile_id,
    properties,
    rows_from_records,
)


def _profile_url(profile: Mapping[str, Any], *keys: str) -> str:
    props = properties(profile)
    for key in keys:
        value = props.get(key)
        if value:
            return str(value)
    return ""


def execute_web_api(
    *,
    function_name: str,
    operation: str,
    profile: Mapping[str, Any],
    secrets: Mapping[str, Any],
    context: Any,
) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    connector_id = str(profile.get("connector_id") or "web")
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    timeout = float(options.get("timeout") or 10)

    if function_name == "Web.BrowserContents":
        try:
            import playwright  # type: ignore  # noqa: F401
        except Exception:
            return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message="Web.BrowserContents live execution requires Playwright browser runtime.", connector_id=connector_id, profile_id=pid, privacy_level=str(profile.get("privacy_level") or "public"))

    if function_name == "WebAction.Request" and not (
        isinstance(getattr(context, "approval_record", None), Mapping) and bool(getattr(context, "approval_record", {}).get("approved"))
    ):
        return blocked_response(function_name=function_name, operation=operation, state="approval_required", code="PQ_WEB_ACTION_APPROVAL_REQUIRED", message="WebAction.Request requires explicit approval before live execution.", connector_id=connector_id, profile_id=pid, privacy_level=str(profile.get("privacy_level") or "organizational"))

    url = str(options.get("url") or _profile_url(profile, "url", "base_url", "endpoint") or "").strip()
    if not url:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires properties.url/base_url or adapter_options.url.", connector_id=connector_id, profile_id=pid, privacy_level=str(profile.get("privacy_level") or "organizational"))

    if function_name == "Soda.Feed":
        url = normalize_url(url, query={"$limit": options.get("limit") or 100})
    payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=timeout)
    if error:
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed" if status in {401, 403} else "not_configured", code="PQ_LIVE_HTTP_ERROR", message=f"{function_name} request failed: {error}", connector_id=connector_id, profile_id=pid, privacy_level=str(profile.get("privacy_level") or "organizational"))
    records = json_records(payload)
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=int(options.get("limit") or 100)), connector_id=connector_id, profile_id=pid, source={"url": url}, folding_capability="select_filter_supported" if function_name in {"OData.Feed", "Soda.Feed"} else "not_foldable", privacy_level=str(profile.get("privacy_level") or "organizational"))


def execute_odata(
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
    base_url = str(props.get("base_url") or props.get("url") or "").strip()
    if not base_url:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="Live OData execution requires properties.base_url on the credential profile.", connector_id="odata", profile_id=pid)
    query = {}
    if options.get("select"):
        query["$select"] = options.get("select")
    if options.get("filter"):
        query["$filter"] = options.get("filter")
    url = normalize_url(base_url, str(options.get("entity") or props.get("entity") or ""))
    if query:
        url = f"{url}?{'&'.join(f'{key}={urllib.parse.quote(str(value))}' for key, value in query.items())}"
    payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=float(options.get("timeout") or 10))
    if error:
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed" if status in {401, 403} else "not_configured", code="PQ_LIVE_HTTP_ERROR", message=f"Live OData request failed: {error}", connector_id="odata", profile_id=pid)
    records = json_records(payload)
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema), connector_id="odata", profile_id=pid, source={"url": url, "next_link": payload.get("@odata.nextLink") if isinstance(payload, Mapping) else None}, folding_capability="select_filter_supported")
