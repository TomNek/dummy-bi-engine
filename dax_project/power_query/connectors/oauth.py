from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from typing import Any, Mapping

from ..credentials import get_credential_secrets, redact_secret_value


PROVIDER_SECRET_KEYS = {
    "microsoft": ("access_token", "token", "bearer_token", "client_secret", "refresh_token"),
    "salesforce": ("access_token", "token", "client_secret", "refresh_token"),
    "google": ("access_token", "token", "service_account_json", "refresh_token"),
    "adobe": ("access_token", "token", "client_secret", "jwt_private_key"),
}

PROVIDER_REQUIRED_PROPERTIES = {
    "microsoft": ("tenant_id",),
    "salesforce": ("instance_url",),
    "google": ("property_id",),
    "adobe": ("company_id",),
}

PROVIDER_OPTIONAL_PACKAGES = {
    "microsoft": ("msal",),
    "salesforce": (),
    "google": ("google.analytics.data",),
    "adobe": (),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def optional_package_status(provider: str) -> str:
    packages = PROVIDER_OPTIONAL_PACKAGES.get(provider, ())
    if not packages:
        return "not_required"
    missing = []
    for package in packages:
        try:
            if importlib.util.find_spec(package) is None:
                missing.append(package)
        except ModuleNotFoundError:
            missing.append(package)
    return "missing" if missing else "available"


def provider_token_status(provider: str, profile: Mapping[str, Any], *, profile_id: str | None = None) -> dict[str, Any]:
    props = profile.get("properties") if isinstance(profile.get("properties"), Mapping) else {}
    secrets = get_credential_secrets(profile_id or str(profile.get("profile_id") or ""))
    secret_keys = PROVIDER_SECRET_KEYS.get(provider, ("access_token", "token"))
    missing_properties = [key for key in PROVIDER_REQUIRED_PROPERTIES.get(provider, ()) if not props.get(key)]
    has_secret = any(secrets.get(key) for key in secret_keys)
    state = "configured" if has_secret and not missing_properties else "not_configured"
    if missing_properties:
        state = "metadata_missing"
    return {
        "provider": provider,
        "auth_status": state,
        "sdk_status": optional_package_status(provider),
        "missing_properties": missing_properties,
        "accepted_secret_keys": list(secret_keys),
        "scopes": redact_secret_value(props.get("scopes") or []),
        "authority": redact_secret_value(props.get("authority") or ""),
        "token_available": bool(has_secret),
    }


def connector_provider(connector_id: str) -> str:
    connector = str(connector_id or "").lower()
    if connector in {"sharepoint", "exchange", "active_directory", "microsoft_graph", "graph", "powerbi_dataflows", "analysis_services", "semantic_cube"}:
        return "microsoft"
    if connector == "salesforce":
        return "salesforce"
    if connector in {"google_analytics", "ga4"}:
        return "google"
    if connector == "adobe_analytics":
        return "adobe"
    return ""


def readiness_from_result(
    *,
    connector_id: str,
    profile: Mapping[str, Any],
    result: Mapping[str, Any],
    mock_live: bool = False,
) -> dict[str, Any]:
    state = str(result.get("execution_state") or "unknown")
    provider = connector_provider(connector_id)
    token = provider_token_status(provider, profile, profile_id=str(profile.get("profile_id") or "")) if provider else {
        "provider": "",
        "auth_status": "configured" if state == "configured" else "not_configured",
        "sdk_status": "not_required",
        "missing_properties": [],
        "token_available": False,
    }
    if state == "driver_missing":
        sdk_status = "missing"
    elif state in {"configured", "approval_required", "not_configured"}:
        sdk_status = str(token.get("sdk_status") or "not_required")
    else:
        sdk_status = "unknown"
    auth_status = str(token.get("auth_status") or "not_configured")
    if state == "auth_failed":
        auth_status = "auth_failed"
    if state == "approval_required":
        auth_status = "approval_required"
    if state == "configured":
        auth_status = "configured"
    discovery_status = "configured" if result.get("schema") or result.get("source_lineage") else state
    preview_status = "configured" if result.get("preview_rows") else state
    certification_state = "mocked" if mock_live else "not_started"
    if state == "configured" and mock_live:
        certification_state = "mocked"
    elif state == "configured":
        certification_state = "live_smoke_ready"
    elif sdk_status == "available" and auth_status in {"configured", "metadata_missing"}:
        certification_state = "sdk_ready"
    return {
        "live_certification": certification_state,
        "sdk_status": sdk_status,
        "auth_status": auth_status,
        "discovery_status": discovery_status,
        "preview_status": preview_status,
        "last_certified_at": utc_now_iso() if certification_state == "live_smoke_ready" else None,
        "provider": provider,
        "oauth": redact_secret_value(token),
    }
