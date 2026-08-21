from __future__ import annotations

from typing import Any, Mapping

from .common import bearer_headers, blocked_response, configured_response, http_json_get, infer_schema_from_records, json_records, normalize_url, profile_id, properties, rows_from_records


_GRAPH_FUNCTIONS = {
    "SharePoint.Contents",
    "SharePoint.Files",
    "SharePoint.Tables",
    "Exchange.Contents",
    "ActiveDirectory.Domains",
}


def graph_endpoint(function_name: str, profile: Mapping[str, Any], options: Mapping[str, Any]) -> str:
    props = properties(profile)
    base = str(props.get("graph_base_url") or "https://graph.microsoft.com/v1.0")
    if function_name == "ActiveDirectory.Domains":
        return normalize_url(base, "domains")
    if function_name == "Exchange.Contents":
        mailbox = str(options.get("mailbox") or props.get("mailbox") or "me")
        return normalize_url(base, "me/messages" if mailbox == "me" else f"users/{mailbox}/messages")
    site_id = str(options.get("site_id") or props.get("site_id") or "").strip()
    drive_id = str(options.get("drive_id") or props.get("drive_id") or "").strip()
    list_id = str(options.get("list_id") or props.get("list_id") or "").strip()
    if function_name == "SharePoint.Tables":
        if site_id:
            return normalize_url(base, f"sites/{site_id}/lists")
        return ""
    if function_name in {"SharePoint.Contents", "SharePoint.Files"}:
        if drive_id:
            return normalize_url(base, f"drives/{drive_id}/root/children")
        if site_id:
            return normalize_url(base, f"sites/{site_id}/drive/root/children")
        if list_id and site_id:
            return normalize_url(base, f"sites/{site_id}/lists/{list_id}/items")
    return ""


def execute_microsoft_graph(
    *,
    function_name: str,
    operation: str,
    profile: Mapping[str, Any],
    secrets: Mapping[str, Any],
    context: Any,
) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    if function_name not in _GRAPH_FUNCTIONS:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="No Microsoft Graph adapter is registered for this function.", connector_id=str(profile.get("connector_id") or "graph"), profile_id=pid)
    if not (secrets.get("access_token") or secrets.get("token") or secrets.get("bearer_token")):
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires an OAuth access token in the credential profile secret vault.", connector_id=str(profile.get("connector_id") or "graph"), profile_id=pid)
    url = graph_endpoint(function_name, profile, options)
    if not url:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires site_id, drive_id, list_id, mailbox, or equivalent Graph profile metadata.", connector_id=str(profile.get("connector_id") or "graph"), profile_id=pid)
    payload, error, status = http_json_get(url, headers=bearer_headers(secrets), timeout=float(options.get("timeout") or 10))
    if error:
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed" if status in {401, 403} else "not_configured", code="PQ_LIVE_HTTP_ERROR", message=f"Microsoft Graph request failed: {error}", connector_id=str(profile.get("connector_id") or "graph"), profile_id=pid)
    records = json_records(payload)
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=int(options.get("limit") or 100)), connector_id=str(profile.get("connector_id") or "graph"), profile_id=pid, source={"url": url, "next_link": payload.get("@odata.nextLink") if isinstance(payload, Mapping) else None}, folding_capability="select_filter_supported")

