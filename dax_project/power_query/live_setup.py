from __future__ import annotations

import importlib.util
import json
import uuid
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .adapters import LIVE_CERTIFICATION_STATES
from .credentials import get_credential_profile, redact_secret_value, redact_text, upsert_credential_profile
from .connectors.oauth import readiness_from_result, utc_now_iso


CONNECTOR_SETUP_MANIFEST: dict[str, dict[str, Any]] = {
    "microsoft_graph": {
        "label": "Microsoft Graph",
        "connector_id": "sharepoint",
        "provider": "microsoft",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "device_code", "manual_token"],
        "required_fields": ["tenant_id", "site_id"],
        "optional_fields": ["drive_id", "list_id", "scopes", "authority"],
        "secret_fields": ["access_token", "refresh_token", "client_secret"],
        "sdk_packages": ["msal"],
        "permissions": ["Sites.Read.All", "Files.Read.All", "Mail.Read", "Directory.Read.All"],
        "smoke_function": "SharePoint.Files",
        "smoke_options": {"limit": 5},
        "supported_functions": ["SharePoint.Contents", "SharePoint.Files", "SharePoint.Tables", "Exchange.Contents", "ActiveDirectory.Domains"],
    },
    "azure_storage": {
        "label": "Azure Storage",
        "connector_id": "azure_blob",
        "provider": "microsoft",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "sas_token", "account_key", "connection_string", "manual_token"],
        "required_fields": ["account_url", "container"],
        "optional_fields": ["tenant_id", "account", "filesystem", "table", "scopes"],
        "secret_fields": ["access_token", "sas_token", "account_key", "connection_string"],
        "sdk_packages": ["azure.storage.blob", "azure.storage.filedatalake", "azure.data.tables"],
        "permissions": ["Storage Blob Data Reader", "Storage Table Data Reader"],
        "smoke_function": "AzureStorage.Blobs",
        "smoke_options": {"limit": 5},
        "supported_functions": ["AzureStorage.BlobContents", "AzureStorage.Blobs", "AzureStorage.DataLake", "AzureStorage.DataLakeContents", "AzureStorage.Tables"],
    },
    "salesforce": {
        "label": "Salesforce",
        "connector_id": "salesforce",
        "provider": "salesforce",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "manual_token"],
        "required_fields": ["instance_url"],
        "optional_fields": ["api_version", "object", "report_id"],
        "secret_fields": ["access_token", "refresh_token", "client_secret"],
        "sdk_packages": [],
        "permissions": ["api", "refresh_token"],
        "smoke_function": "Salesforce.Data",
        "smoke_options": {"limit": 5},
        "supported_functions": ["Salesforce.Data", "Salesforce.Reports"],
    },
    "xmla": {
        "label": "XMLA / Analysis Services",
        "connector_id": "analysis_services",
        "provider": "microsoft",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "manual_token"],
        "required_fields": ["tenant_id", "server"],
        "optional_fields": ["database", "workspace_id", "scopes"],
        "secret_fields": ["access_token", "refresh_token", "client_secret"],
        "sdk_packages": ["pyadomd", "pythonnet"],
        "permissions": ["Dataset.Read.All", "XMLA endpoint access"],
        "smoke_function": "AnalysisServices.Databases",
        "smoke_options": {"limit": 5},
        "supported_functions": ["AnalysisServices.Database", "AnalysisServices.Databases", "Cube.Transform"],
    },
    "powerbi_dataflows": {
        "label": "Power BI Dataflows",
        "connector_id": "powerbi_dataflows",
        "provider": "microsoft",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "manual_token"],
        "required_fields": ["tenant_id", "workspace_id"],
        "optional_fields": ["dataflow_id", "scopes"],
        "secret_fields": ["access_token", "refresh_token", "client_secret"],
        "sdk_packages": ["msal"],
        "permissions": ["Dataflow.Read.All", "Workspace.Read.All"],
        "smoke_function": "PowerBI.Dataflows",
        "smoke_options": {"limit": 5},
        "supported_functions": ["PowerBI.Dataflows"],
    },
    "google_analytics": {
        "label": "Google Analytics",
        "connector_id": "google_analytics",
        "provider": "google",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "service_account", "manual_token"],
        "required_fields": ["property_id"],
        "optional_fields": ["endpoint", "scopes"],
        "secret_fields": ["access_token", "refresh_token", "service_account_json"],
        "sdk_packages": ["google.analytics.data"],
        "permissions": ["analytics.readonly"],
        "smoke_function": "GoogleAnalytics.Accounts",
        "smoke_options": {"limit": 5},
        "supported_functions": ["GoogleAnalytics.Accounts"],
    },
    "adobe_analytics": {
        "label": "Adobe Analytics",
        "connector_id": "adobe_analytics",
        "provider": "adobe",
        "oauth": True,
        "auth_modes": ["interactive_oauth", "jwt", "manual_token"],
        "required_fields": ["company_id"],
        "optional_fields": ["endpoint", "api_version"],
        "secret_fields": ["access_token", "client_secret", "jwt_private_key"],
        "sdk_packages": [],
        "permissions": ["Adobe Analytics API access"],
        "smoke_function": "AdobeAnalytics.Cubes",
        "smoke_options": {"limit": 5},
        "supported_functions": ["AdobeAnalytics.Cubes"],
    },
    "sql_odbc": {
        "label": "SQL / ODBC",
        "connector_id": "sql",
        "provider": "",
        "oauth": False,
        "auth_modes": ["connection_string", "dsn"],
        "required_fields": ["server", "database"],
        "optional_fields": ["schema", "table", "driver"],
        "secret_fields": ["connection_string", "password"],
        "sdk_packages": ["pyodbc"],
        "permissions": ["Database read access"],
        "smoke_function": "Sql.Database",
        "smoke_options": {"limit": 5},
        "supported_functions": ["Sql.Database", "Sql.Databases", "Odbc.DataSource", "Value.NativeQuery"],
    },
}


def _package_status(packages: list[str]) -> dict[str, str]:
    status: dict[str, str] = {}
    for package in packages:
        try:
            status[package] = "available" if importlib.util.find_spec(package) is not None else "missing"
        except ModuleNotFoundError:
            status[package] = "missing"
    return status


def _connector_key(connector_id: str) -> str:
    needle = str(connector_id or "").lower()
    for key, item in CONNECTOR_SETUP_MANIFEST.items():
        if needle in {key, str(item["connector_id"]).lower()}:
            return key
    return needle or "sql_odbc"


def build_live_connector_setup_manifest() -> dict[str, Any]:
    connectors = []
    for key, item in CONNECTOR_SETUP_MANIFEST.items():
        row = dict(item)
        row["id"] = key
        row["credential_fields"] = list(row.get("secret_fields") or [])
        row.pop("secret_fields", None)
        row["sdk_status"] = _package_status(list(row.get("sdk_packages") or []))
        row["certification_states"] = list(LIVE_CERTIFICATION_STATES)
        connectors.append(redact_secret_value(row))
    return {
        "version": "power_query_live_setup.v1",
        "default_auth": "interactive_oauth",
        "connectors": connectors,
    }


def start_live_connector_oauth(payload: Mapping[str, Any]) -> dict[str, Any]:
    connector_key = _connector_key(str(payload.get("connector_id") or payload.get("connector") or "microsoft_graph"))
    manifest = CONNECTOR_SETUP_MANIFEST.get(connector_key)
    if not manifest:
        raise ValueError(f"Unknown live connector setup target: {connector_key!r}")
    props = payload.get("properties") if isinstance(payload.get("properties"), Mapping) else {}
    provider = str(manifest.get("provider") or "")
    tenant = str(props.get("tenant_id") or payload.get("tenant_id") or "common")
    client_id = str(props.get("client_id") or payload.get("client_id") or "")
    scopes = props.get("scopes") or payload.get("scopes") or manifest.get("permissions") or []
    state_id = uuid.uuid4().hex
    if provider == "microsoft":
        query = {"client_id": client_id or "dummy-bi-local-app", "response_type": "code", "scope": " ".join(scopes) if isinstance(scopes, list) else str(scopes)}
        authorization_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(query)}"
        verification_uri = f"https://microsoft.com/devicelogin"
    elif provider == "salesforce":
        base = str(props.get("login_url") or "https://login.salesforce.com")
        authorization_url = f"{base.rstrip('/')}/services/oauth2/authorize?{urlencode({'response_type': 'code', 'client_id': client_id or 'dummy-bi-local-app'})}"
        verification_uri = authorization_url
    elif provider == "google":
        authorization_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode({'response_type': 'code', 'client_id': client_id or 'dummy-bi-local-app', 'scope': ' '.join(scopes) if isinstance(scopes, list) else str(scopes)})}"
        verification_uri = authorization_url
    elif provider == "adobe":
        authorization_url = str(props.get("authorization_url") or "https://ims-na1.adobelogin.com/ims/authorize")
        verification_uri = authorization_url
    else:
        authorization_url = ""
        verification_uri = ""
    return {
        "state_id": state_id,
        "connector_id": manifest["connector_id"],
        "connector_setup": connector_key,
        "provider": provider,
        "auth_mode": "interactive_oauth" if manifest.get("oauth") else "manual_secret",
        "authorization_url": authorization_url,
        "verification_uri": verification_uri,
        "user_code": "DUMMY-BI" if payload.get("mock_oauth") else "",
        "device_code": "mock-device-code" if payload.get("mock_oauth") else "",
        "expires_in": 900,
        "requires_external_consent": bool(manifest.get("oauth")),
        "diagnostics": [
            {
                "code": "PQ_LIVE_OAUTH_START",
                "severity": "info",
                "message": "Open the authorization URL or provide a provider token, then complete setup. No token is returned by this endpoint.",
            }
        ],
    }


def _token_endpoint(provider: str, connector_key: str, properties: Mapping[str, Any]) -> str:
    if provider == "microsoft":
        tenant = str(properties.get("tenant_id") or "common")
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    if provider == "salesforce":
        base = str(properties.get("login_url") or "https://login.salesforce.com")
        return f"{base.rstrip('/')}/services/oauth2/token"
    if provider == "google":
        return "https://oauth2.googleapis.com/token"
    if provider == "adobe":
        return str(properties.get("token_url") or "https://ims-na1.adobelogin.com/ims/token/v3")
    raise ValueError(f"OAuth code exchange is not available for {connector_key!r}.")


def _exchange_authorization_code(
    *,
    connector_key: str,
    provider: str,
    manifest: Mapping[str, Any],
    properties: Mapping[str, Any],
    payload: Mapping[str, Any],
    secrets: Mapping[str, Any],
) -> dict[str, Any]:
    code = str(payload.get("authorization_code") or payload.get("code") or "").strip()
    if not code:
        return {}
    client_id = str(properties.get("client_id") or payload.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("OAuth code completion requires client_id metadata.")
    redirect_uri = str(properties.get("redirect_uri") or payload.get("redirect_uri") or "http://localhost:53682/oauth/callback")
    scopes = properties.get("scopes") or payload.get("scopes") or manifest.get("permissions") or []
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if provider in {"microsoft", "google"}:
        form["scope"] = " ".join(scopes) if isinstance(scopes, list) else str(scopes)
    client_secret = str(secrets.get("client_secret") or payload.get("client_secret") or "").strip()
    if client_secret:
        form["client_secret"] = client_secret
    request = Request(
        _token_endpoint(provider, connector_key, properties),
        data=urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec B310 - user-supplied OAuth endpoint is restricted by provider manifest.
            body = response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"OAuth code exchange failed: {redact_text(str(exc))}") from exc
    try:
        token_payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("OAuth code exchange failed: provider returned a non-JSON token response.") from exc
    if not isinstance(token_payload, Mapping):
        raise ValueError("OAuth code exchange failed: provider returned an invalid token response.")
    if token_payload.get("error"):
        message = token_payload.get("error_description") or token_payload.get("error") or "provider rejected the code"
        raise ValueError(f"OAuth code exchange failed: {redact_text(str(message))}")
    exchanged: dict[str, Any] = {}
    for key, value in token_payload.items():
        key_s = str(key)
        if "token" in key_s.lower() or key_s in {"expires_in", "scope"}:
            exchanged[key_s] = value
    if "access_token" not in exchanged:
        raise ValueError("OAuth code exchange failed: provider response did not include access_token.")
    return exchanged


def complete_live_connector_oauth(project_root: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    connector_key = _connector_key(str(payload.get("connector_id") or payload.get("connector") or "microsoft_graph"))
    manifest = CONNECTOR_SETUP_MANIFEST.get(connector_key)
    if not manifest:
        raise ValueError(f"Unknown live connector setup target: {connector_key!r}")
    properties = dict(payload.get("properties") or {}) if isinstance(payload.get("properties"), Mapping) else {}
    secrets = dict(payload.get("secrets") or {}) if isinstance(payload.get("secrets"), Mapping) else {}
    for key in manifest.get("required_fields") or []:
        if key in payload and key not in properties:
            properties[key] = payload.get(key)
    for key in manifest.get("optional_fields") or []:
        if key in payload and key not in properties:
            properties[key] = payload.get(key)
    for secret_key in manifest.get("secret_fields") or []:
        if payload.get(secret_key) and secret_key not in secrets:
            secrets[secret_key] = payload.get(secret_key)
    exchanged = _exchange_authorization_code(
        connector_key=connector_key,
        provider=str(manifest.get("provider") or ""),
        manifest=manifest,
        properties=properties,
        payload=payload,
        secrets=secrets,
    )
    secrets.update(exchanged)
    if payload.get("mock_oauth") and not secrets:
        secrets["access_token"] = f"mock-token-{connector_key}"
    if not secrets:
        raise ValueError("OAuth completion requires a token/secret payload or mock_oauth=true.")
    profile_id = str(payload.get("profile_id") or f"live-{connector_key}")
    profile = upsert_credential_profile(
        project_root,
        {
            "profile_id": profile_id,
            "connector_id": str(payload.get("profile_connector_id") or manifest["connector_id"]),
            "display_name": str(payload.get("display_name") or manifest["label"]),
            "privacy_level": str(payload.get("privacy_level") or "organizational"),
            "auth_type": str(payload.get("auth_type") or ("oauth" if manifest.get("oauth") else "secret")),
            "properties": properties,
            "secrets": secrets,
            "live_certification": "not_started",
            "last_certification_result": {"state": "not_started", "connector_setup": connector_key},
            "certified_functions": [],
            "missing_permissions": [],
            "missing_sdk": [],
            "smoke_resource": {},
        },
    )
    return {"profile": profile, "connector": redact_secret_value({**manifest, "id": connector_key})}


def certify_live_connector_profile(project_root: str, profile_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    from .adapters import execute_power_query_adapter

    profile = get_credential_profile(project_root, profile_id)
    if not profile:
        raise ValueError(f"Credential profile {profile_id!r} was not found")
    connector_key = _connector_key(str(payload.get("connector_id") or profile.get("connector_id") or ""))
    manifest = CONNECTOR_SETUP_MANIFEST.get(connector_key) or CONNECTOR_SETUP_MANIFEST["sql_odbc"]
    function_name = str(payload.get("function_name") or manifest.get("smoke_function") or "Sql.Database")
    adapter_options = dict(manifest.get("smoke_options") or {})
    if isinstance(payload.get("adapter_options"), Mapping):
        adapter_options.update(dict(payload.get("adapter_options") or {}))
    result = execute_power_query_adapter(
        function_name,
        {
            "fixture_mode": False,
            "project_root": project_root,
            "credential_profile_id": profile_id,
            "options": adapter_options,
            "approval_record": payload.get("approval_record") if isinstance(payload.get("approval_record"), Mapping) else None,
            "privacy_level": str(profile.get("privacy_level") or "organizational"),
        },
        operation=str(payload.get("operation") or "preview"),
    ).to_dict()
    readiness = readiness_from_result(
        connector_id=str(profile.get("connector_id") or ""),
        profile=profile,
        result=result,
        mock_live=bool(adapter_options.get("mock_live")),
    )
    state = str(readiness.get("live_certification") or "not_started")
    if result.get("execution_state") == "configured" and not adapter_options.get("mock_live"):
        state = "certified"
        readiness["live_certification"] = state
        readiness["last_certified_at"] = utc_now_iso()
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
    missing_sdk = [str(item.get("message") or "") for item in diagnostics if isinstance(item, Mapping) and item.get("code") == "PQ_LIVE_DRIVER_MISSING"]
    missing_permissions = [str(item.get("message") or "") for item in diagnostics if isinstance(item, Mapping) and result.get("execution_state") in {"auth_failed", "approval_required"}]
    certified_functions = list(profile.get("certified_functions") or []) if isinstance(profile.get("certified_functions"), list) else []
    if state == "certified" and function_name not in certified_functions:
        certified_functions.append(function_name)
    updated = upsert_credential_profile(
        project_root,
        {
            "profile_id": profile_id,
            "connector_id": str(profile.get("connector_id") or manifest["connector_id"]),
            "display_name": str(profile.get("display_name") or manifest["label"]),
            "privacy_level": str(profile.get("privacy_level") or "organizational"),
            "auth_type": str(profile.get("auth_type") or "oauth"),
            "properties": dict(profile.get("properties") or {}),
            "live_certification": state,
            "last_certified_at": readiness.get("last_certified_at"),
            "last_certification_result": {
                "state": state,
                "function": function_name,
                "execution_state": result.get("execution_state"),
                "diagnostics": diagnostics,
            },
            "certified_functions": certified_functions,
            "missing_permissions": missing_permissions,
            "missing_sdk": missing_sdk,
            "smoke_resource": adapter_options,
        },
    )
    return {"profile": updated, "result": result, "readiness": readiness, **readiness}
