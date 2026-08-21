from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..credentials import redact_secret_value


@dataclass(frozen=True)
class LiveConnectorResponse:
    execution_state: str
    schema: list[dict[str, Any]] = field(default_factory=list)
    preview_rows: list[list[Any]] = field(default_factory=list)
    source_lineage: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    folding_capability: str = "blocked"
    refresh_mode: str = "blocked"
    privacy_level: str = "organizational"


def blocked_response(
    *,
    function_name: str,
    operation: str,
    state: str,
    code: str,
    message: str,
    connector_id: str | None = None,
    profile_id: str | None = None,
    privacy_level: str = "organizational",
) -> LiveConnectorResponse:
    return LiveConnectorResponse(
        execution_state=state,
        source_lineage=[
            {
                "function": function_name,
                "mode": "live",
                "operation": operation,
                "profile_id": profile_id,
                "connector_id": connector_id,
            }
        ],
        diagnostics=[{"code": code, "severity": "warning", "message": redact_secret_value(message)}],
        privacy_level=privacy_level,
    )


def configured_response(
    *,
    function_name: str,
    operation: str,
    schema: Sequence[Mapping[str, Any]],
    rows: Sequence[Sequence[Any]],
    connector_id: str | None = None,
    profile_id: str | None = None,
    source: Mapping[str, Any] | None = None,
    folding_capability: str = "supported",
    refresh_mode: str = "supported",
    privacy_level: str = "organizational",
    message: str | None = None,
) -> LiveConnectorResponse:
    lineage = {
        "function": function_name,
        "mode": "live",
        "operation": operation,
        "profile_id": profile_id,
        "connector_id": connector_id,
    }
    if source:
        lineage.update(redact_secret_value(dict(source)))
    return LiveConnectorResponse(
        execution_state="configured",
        schema=[dict(item) for item in schema],
        preview_rows=[list(item) for item in rows],
        source_lineage=[lineage],
        diagnostics=[
            {
                "code": "PQ_LIVE_CONNECTOR_CONFIGURED",
                "severity": "info",
                "message": message or f"{function_name} live adapter {operation} completed with redacted diagnostics.",
            }
        ],
        folding_capability=folding_capability,
        refresh_mode=refresh_mode,
        privacy_level=privacy_level,
    )


def properties(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    props = (profile or {}).get("properties")
    return dict(props) if isinstance(props, Mapping) else {}


def profile_id(profile: Mapping[str, Any] | None, fallback: str | None = None) -> str | None:
    return str((profile or {}).get("profile_id") or fallback or "") or None


def infer_schema_from_records(records: Sequence[Any]) -> list[dict[str, Any]]:
    keys = sorted({str(key) for row in records if isinstance(row, Mapping) for key in row.keys()})
    if not keys:
        return [{"name": "Value", "type": "TEXT"}]
    return [{"name": key, "type": "TEXT"} for key in keys]


def rows_from_records(records: Sequence[Any], schema: Sequence[Mapping[str, Any]], *, limit: int = 100) -> list[list[Any]]:
    names = [str(item.get("name") or "Value") for item in schema]
    rows: list[list[Any]] = []
    for item in list(records)[:limit]:
        if isinstance(item, Mapping):
            rows.append([item.get(name) for name in names])
        else:
            rows.append([item])
    return rows


def json_records(payload: Any) -> list[Any]:
    if isinstance(payload, Mapping):
        value = payload.get("value")
        if isinstance(value, list):
            return value
        return [payload]
    if isinstance(payload, list):
        return payload
    return [{"Value": payload}]


def bearer_headers(secrets: Mapping[str, Any], *, accept: str = "application/json") -> dict[str, str]:
    headers = {"Accept": accept}
    token = str(secrets.get("access_token") or secrets.get("token") or secrets.get("bearer_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api_key = str(secrets.get("api_key") or secrets.get("apikey") or "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def http_json_get(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10) -> tuple[Any, str | None, int | None]:
    request = urllib.request.Request(url, headers=dict(headers or {"Accept": "application/json"}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw), None, getattr(response, "status", None)
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}", exc.code
    except Exception as exc:  # noqa: BLE001
        return None, str(redact_secret_value(str(exc))), None


def normalize_url(base_url: str, *parts: str, query: Mapping[str, Any] | None = None) -> str:
    url = str(base_url or "").rstrip("/")
    for part in parts:
        text = str(part or "").strip("/")
        if text:
            url = f"{url}/{urllib.parse.quote(text, safe='()/,$=?:&')}"
    if query:
        clean = {key: value for key, value in query.items() if value is not None and str(value) != ""}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean)}"
    return url

