from __future__ import annotations

import importlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .credentials import get_credential_profile, get_credential_secrets, redact_secret_value
from .registry import _SOURCE_FUNCTIONS


LIVE_CERTIFICATION_STATES = ["not_started", "mocked", "sdk_ready", "live_smoke_ready", "certified"]

LIVE_PROFILE_ENV_VARS = {
    "sharepoint": "POWER_QUERY_LIVE_SHAREPOINT_PROFILE",
    "exchange": "POWER_QUERY_LIVE_SHAREPOINT_PROFILE",
    "active_directory": "POWER_QUERY_LIVE_SHAREPOINT_PROFILE",
    "azure_storage": "POWER_QUERY_LIVE_AZURE_STORAGE_PROFILE",
    "azure_data_lake": "POWER_QUERY_LIVE_AZURE_STORAGE_PROFILE",
    "azure_table_storage": "POWER_QUERY_LIVE_AZURE_STORAGE_PROFILE",
    "salesforce": "POWER_QUERY_LIVE_SALESFORCE_PROFILE",
    "analysis_services": "POWER_QUERY_LIVE_XMLA_PROFILE",
    "semantic_cube": "POWER_QUERY_LIVE_XMLA_PROFILE",
    "powerbi_dataflows": "POWER_QUERY_LIVE_DATAFLOWS_PROFILE",
    "google_analytics": "POWER_QUERY_LIVE_GOOGLE_ANALYTICS_PROFILE",
    "adobe_analytics": "POWER_QUERY_LIVE_ADOBE_ANALYTICS_PROFILE",
}

ADAPTER_RESULT_CONTRACT = [
    "schema",
    "preview_rows",
    "source_lineage",
    "credential_profile_id",
    "privacy_level",
    "folding_capability",
    "diagnostics",
    "refresh_mode",
]

ADAPTER_CAPABILITY_KEYS = [
    "discover",
    "preview",
    "load",
    "schema",
    "folding",
    "projection",
    "filter",
    "sort",
    "top",
    "group_by",
    "join",
    "culture_cast",
    "fuzzy_matching",
    "refresh",
    "privacy_partition",
    "native_query",
]

_NATIVE_CONNECTORS = {
    "AdoDotNet.Query": "ado_dotnet",
    "Odbc.Query": "odbc",
    "OleDb.Query": "oledb",
    "Value.NativeQuery": "native_query",
}

_SEMANTIC_CONNECTORS = {
    "AnalysisServices.Database": "analysis_services",
    "AnalysisServices.Databases": "analysis_services",
    "Essbase.Cubes": "essbase",
    "FabricAI.Prompt": "fabric_ai",
    "PowerBI.Dataflows": "powerbi_dataflows",
    "SapBusinessWarehouse.Cubes": "sap_business_warehouse",
}

_LIVE_CONNECTOR_FUNCTIONS = set(_SOURCE_FUNCTIONS) | set(_NATIVE_CONNECTORS) | set(_SEMANTIC_CONNECTORS)

_PROFILE_CONNECTOR_ALIASES = {
    "sql": {"sql", "sql_database", "sqlserver", "sql_server"},
    "postgresql": {"postgres", "postgresql"},
    "mysql": {"mysql"},
    "odbc": {"odbc"},
    "odata": {"odata", "odata_feed"},
    "web": {"web", "http", "generic_http"},
    "web_page": {"web", "web_page", "http", "generic_http"},
    "web_browser": {"web_browser", "browser", "web"},
    "web_action": {"web_action", "web", "http"},
    "sharepoint": {"sharepoint", "microsoft_graph", "graph"},
    "exchange": {"exchange", "microsoft_graph", "graph"},
    "active_directory": {"active_directory", "microsoft_graph", "graph", "entra"},
    "salesforce": {"salesforce"},
    "google_analytics": {"google_analytics", "ga4", "analytics"},
    "adobe_analytics": {"adobe_analytics", "analytics"},
    "soda": {"soda", "socrata"},
    "azure_blob": {"azure_blob", "azure_storage", "azure"},
    "azure_storage": {"azure_storage", "azure_blob", "azure"},
    "azure_data_lake": {"azure_data_lake", "adls", "azure"},
    "azure_table_storage": {"azure_table_storage", "azure_tables", "azure"},
    "delta_lake": {"delta_lake", "delta"},
    "hdfs": {"hdfs"},
    "hdinsight": {"hdinsight", "azure_storage", "azure"},
    "cdm": {"cdm", "azure_data_lake", "azure_storage"},
    "analysis_services": {"analysis_services", "xmla", "semantic_cube", "powerbi_semantic_model"},
    "semantic_cube": {"semantic_cube", "analysis_services", "xmla"},
    "powerbi_dataflows": {"powerbi_dataflows", "dataflows", "fabric_dataflows"},
    "essbase": {"essbase"},
    "sap_business_warehouse": {"sap_business_warehouse", "sap_bw"},
    "fabric_ai": {"fabric_ai"},
    "native_query": {"sql", "sql_database", "sqlserver", "sql_server", "postgres", "postgresql", "mysql", "odbc", "native_query"},
    "ado_dotnet": {"ado_dotnet", "sql", "sql_database"},
    "oledb": {"oledb", "sql", "sql_database"},
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_LOCAL_DOCUMENT_CAPABILITIES = {
    "File.Contents": {"discover": False, "preview": True, "load": True, "schema": False, "folding": False},
    "Folder.Contents": {"discover": True, "preview": True, "load": True, "schema": True, "folding": False},
    "Folder.Files": {"discover": True, "preview": True, "load": True, "schema": True, "folding": False},
    "Csv.Document": {"discover": False, "preview": True, "load": True, "schema": True, "folding": True},
    "Excel.CurrentWorkbook": {"discover": True, "preview": False, "load": False, "schema": True, "folding": False},
    "Excel.Workbook": {"discover": True, "preview": True, "load": True, "schema": True, "folding": False},
    "Json.Document": {"discover": False, "preview": True, "load": True, "schema": True, "folding": True},
    "Parquet.Document": {"discover": False, "preview": True, "load": True, "schema": True, "folding": True},
    "Pdf.Tables": {"discover": True, "preview": False, "load": False, "schema": True, "folding": False},
    "RData.FromBinary": {"discover": False, "preview": False, "load": False, "schema": False, "folding": False},
}

_TRACK_DIAGNOSTICS = {
    "local_document": ("PQ_FIXTURE_ADAPTER_SUPPORTED", "Fixture adapter provides deterministic local/document preview and load parity."),
    "relational_connector": ("PQ_FIXTURE_ADAPTER_SUPPORTED", "Fixture adapter provides deterministic relational connector discovery, schema, preview, load, and folding metadata."),
    "cloud_storage_lake": ("PQ_FIXTURE_ADAPTER_SUPPORTED", "Fixture adapter provides deterministic cloud/lake navigation, schema, preview, load, and privacy metadata."),
    "web_saas_api": ("PQ_FIXTURE_ADAPTER_SUPPORTED", "Fixture adapter provides deterministic web/API navigation, auth-redaction diagnostics, schema, preview, load, and paging metadata."),
    "native_query": ("PQ_FIXTURE_NATIVE_QUERY_SUPPORTED", "Fixture adapter provides deterministic native-query approval, parameter, audit, preview, and load parity."),
    "semantic_cube": ("PQ_FIXTURE_SEMANTIC_ADAPTER_SUPPORTED", "Fixture adapter provides deterministic semantic/cube navigation and operation parity."),
}

_TRACK_LIVE_BLOCKERS = {
    "local_document": ("PQ_LIVE_LOCAL_DOCUMENT_OPTIONAL", "Live local/document execution is available where project files and optional readers are present."),
    "relational_connector": ("PQ_LIVE_CONNECTOR_NOT_CONFIGURED", "Live relational connector execution requires a configured credential profile and driver."),
    "cloud_storage_lake": ("PQ_LIVE_CLOUD_CONNECTOR_NOT_CONFIGURED", "Live cloud/lake execution requires configured credentials and service endpoints."),
    "web_saas_api": ("PQ_LIVE_WEB_CONNECTOR_NOT_CONFIGURED", "Live web/API execution requires configured credentials, rate-limit policy, and service endpoint access."),
    "native_query": ("PQ_LIVE_NATIVE_QUERY_NOT_APPROVED", "Live native SQL execution requires explicit approval and connector credentials."),
    "semantic_cube": ("PQ_LIVE_SEMANTIC_CONNECTOR_NOT_CONFIGURED", "Live semantic/cube execution requires a configured semantic source adapter."),
}


@dataclass(frozen=True)
class PowerQueryAdapterDiagnostic:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PowerQueryAdapterResult:
    function: str
    adapter_key: str
    connector_id: str
    execution_state: str
    schema: list[dict[str, Any]] = field(default_factory=list)
    preview_rows: list[list[Any]] = field(default_factory=list)
    source_lineage: list[dict[str, Any]] = field(default_factory=list)
    credential_profile_id: str | None = None
    privacy_level: str = "unknown"
    folding_capability: str = "blocked"
    diagnostics: list[PowerQueryAdapterDiagnostic] = field(default_factory=list)
    refresh_mode: str = "blocked"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["diagnostics"] = [diagnostic.to_dict() for diagnostic in self.diagnostics]
        return data


@dataclass(frozen=True)
class PowerQueryAdapterContext:
    function_name: str
    parsed_args: list[Any] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    project_root: str | None = None
    credential_profile_id: str | None = None
    fixture_mode: bool = True
    fixture_name: str = "default"
    approval_record: dict[str, Any] | None = None
    source_lineage: list[dict[str, Any]] = field(default_factory=list)
    privacy_level: str = "organizational"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _connector_id(function_name: str, support_track: str) -> str:
    if function_name in _SOURCE_FUNCTIONS:
        return _SOURCE_FUNCTIONS[function_name]
    if function_name in _NATIVE_CONNECTORS:
        return _NATIVE_CONNECTORS[function_name]
    if function_name in _SEMANTIC_CONNECTORS:
        return _SEMANTIC_CONNECTORS[function_name]
    if function_name.startswith("Cube."):
        return "semantic_cube"
    return support_track or "supported"


def _capabilities(function_name: str, support_track: str, support_status: str) -> dict[str, bool]:
    base = {key: False for key in ADAPTER_CAPABILITY_KEYS}
    if support_track == "supported":
        return {key: key != "native_query" for key in ADAPTER_CAPABILITY_KEYS}
    if support_track == "local_document":
        base.update({key: True for key in ("discover", "preview", "load", "schema", "refresh", "privacy_partition")})
        base["folding"] = function_name in {"Csv.Document", "Json.Document", "Parquet.Document"}
        base["projection"] = base["folding"]
        base["filter"] = base["folding"]
        base["top"] = base["folding"]
        return base
    if support_track == "native_query":
        base.update({key: True for key in ("preview", "load", "schema", "refresh", "privacy_partition", "native_query")})
        return base
    if support_track == "semantic_cube":
        base.update({key: True for key in ("discover", "preview", "load", "schema", "refresh", "privacy_partition")})
        return base
    if support_track in {"relational_connector", "cloud_storage_lake", "web_saas_api"}:
        base.update({key: True for key in ("discover", "preview", "load", "schema", "refresh", "privacy_partition")})
        base["folding"] = support_track in {"relational_connector", "web_saas_api"}
        if support_track == "relational_connector":
            base.update({key: True for key in ("projection", "filter", "sort", "top", "group_by", "join", "culture_cast")})
        elif support_track == "web_saas_api":
            base.update({key: True for key in ("projection", "filter", "sort", "top")})
        elif support_track == "cloud_storage_lake":
            base["projection"] = True
            base["top"] = True
        return base
    return base


def build_runtime_adapter_descriptor(catalog_row: Mapping[str, Any]) -> dict[str, Any]:
    function_name = str(catalog_row.get("function") or "")
    support_track = str(catalog_row.get("support_track") or "supported")
    support_status = str(catalog_row.get("support_status") or "supported")
    connector_id = _connector_id(function_name, support_track)
    diagnostic_code, diagnostic_message = _TRACK_DIAGNOSTICS.get(support_track, ("PQ_ADAPTER_SUPPORTED", "Adapter is supported."))
    live_code, live_message = _TRACK_LIVE_BLOCKERS.get(support_track, ("PQ_LIVE_ADAPTER_SUPPORTED", "Live adapter is supported."))
    capabilities = _capabilities(function_name, support_track, support_status)
    approval_required = support_track == "native_query"
    credential_required = support_track in {"relational_connector", "cloud_storage_lake", "web_saas_api", "native_query", "semantic_cube"}
    if support_track == "local_document":
        credential_required = False
    execution_state = "supported"
    acceptance_test = str(catalog_row.get("first_acceptance_test") or "")
    live_certification = build_live_certification_descriptor(function_name, support_track, connector_id)
    return {
        "adapter_key": f"{connector_id}:{function_name}",
        "connector_id": connector_id,
        "execution_state": execution_state,
        "capabilities": capabilities,
        "result_contract": list(ADAPTER_RESULT_CONTRACT),
        "credential_required": credential_required,
        "approval_required": approval_required,
        "diagnostic_code": diagnostic_code,
        "blocked_reason": "",
        "fixture_execution_status": "supported",
        "live_execution_status": "not_configured" if support_track not in {"supported", "local_document"} else "available",
        "acceptance_test": acceptance_test,
        "c3_promotion_reason": "Fixture adapter acceptance provides deterministic runtime parity." if support_track != "supported" else "Native C3 implementation.",
        "live_diagnostic_code": live_code,
        "live_blocked_reason": "" if support_track in {"supported", "local_document"} else live_message,
        "live_certification": live_certification,
        "live_certification_state": live_certification["state"],
    }


def _live_family(connector_id: str, support_track: str) -> str:
    if support_track == "local_document":
        return "local_document"
    if connector_id in {"sql", "sql_database", "postgresql", "mysql", "odbc", "oracle", "db2", "informix", "sap_hana", "sybase", "teradata", "access", "oledb", "ado_dotnet"}:
        return "relational_native"
    if connector_id in {"azure_blob", "azure_storage", "azure_data_lake", "azure_table_storage", "delta_lake", "hdfs", "hdinsight", "cdm"}:
        return "cloud_lake"
    if connector_id in {"sharepoint", "exchange", "active_directory"}:
        return "microsoft_graph"
    if connector_id in {"salesforce"}:
        return "salesforce"
    if connector_id in {"analysis_services", "semantic_cube", "powerbi_dataflows", "essbase", "sap_business_warehouse", "fabric_ai"}:
        return "semantic_fabric"
    if connector_id in {"google_analytics", "adobe_analytics", "soda", "odata", "web", "web_page", "web_browser", "web_action"}:
        return "web_saas_api"
    if support_track == "native_query":
        return "relational_native"
    return support_track or "supported"


def _profile_env_var(connector_id: str, support_track: str) -> str:
    if connector_id in LIVE_PROFILE_ENV_VARS:
        return LIVE_PROFILE_ENV_VARS[connector_id]
    if connector_id in {"sql", "sql_database", "sqlserver", "sql_server"}:
        return "POWER_QUERY_LIVE_SQLSERVER_PROFILE"
    if connector_id == "postgresql":
        return "POWER_QUERY_LIVE_POSTGRES_PROFILE"
    if connector_id == "mysql":
        return "POWER_QUERY_LIVE_MYSQL_PROFILE"
    if connector_id == "odbc":
        return "POWER_QUERY_LIVE_ODBC_PROFILE"
    if support_track == "cloud_storage_lake":
        return "POWER_QUERY_LIVE_AZURE_STORAGE_PROFILE"
    if support_track == "semantic_cube":
        return "POWER_QUERY_LIVE_XMLA_PROFILE"
    if connector_id in {"odata", "web", "web_page", "web_browser", "web_action", "soda"}:
        return "POWER_QUERY_LIVE_ODATA_PROFILE"
    if support_track in {"relational_connector", "native_query"}:
        return f"POWER_QUERY_LIVE_{connector_id.upper()}_PROFILE"
    return ""


def build_live_certification_descriptor(function_name: str, support_track: str, connector_id: str) -> dict[str, Any]:
    if support_track == "supported":
        state = "certified"
    elif support_track == "local_document":
        state = "live_smoke_ready"
    else:
        state = "mocked"
    env_var = _profile_env_var(connector_id, support_track)
    return {
        "state": state,
        "family": _live_family(connector_id, support_track),
        "profile_env_var": env_var,
        "sdk_status": "not_required" if support_track == "local_document" else "optional",
        "auth_status": "not_required" if support_track in {"supported", "local_document"} else "profile_required",
        "discovery_status": "fixture_backed" if support_track != "supported" else "native",
        "preview_status": "fixture_backed" if support_track != "supported" else "native",
        "last_certified_at": None,
        "optional_live_test_marker": "power_query_live" if env_var else "",
    }


def _fixture_schema(function_name: str, support_track: str) -> list[dict[str, Any]]:
    if support_track == "local_document":
        if function_name == "File.Contents":
            return [{"name": "Content", "type": "BINARY"}, {"name": "Path", "type": "TEXT"}, {"name": "Hash", "type": "TEXT"}]
        if function_name in {"Folder.Contents", "Folder.Files"}:
            return [{"name": "Name", "type": "TEXT"}, {"name": "Extension", "type": "TEXT"}, {"name": "Folder Path", "type": "TEXT"}, {"name": "Content", "type": "BINARY"}]
        if function_name == "Excel.CurrentWorkbook":
            return [{"name": "Name", "type": "TEXT"}, {"name": "Content", "type": "TABLE"}, {"name": "Kind", "type": "TEXT"}]
        return [{"name": "Column1", "type": "TEXT"}, {"name": "Column2", "type": "TEXT"}]
    if support_track == "relational_connector":
        return [{"name": "Schema", "type": "TEXT"}, {"name": "Table", "type": "TEXT"}, {"name": "Amount", "type": "NUMBER"}]
    if support_track == "native_query":
        return [{"name": "Approved", "type": "LOGICAL"}, {"name": "Rows", "type": "NUMBER"}]
    if support_track == "cloud_storage_lake":
        return [{"name": "Path", "type": "TEXT"}, {"name": "Kind", "type": "TEXT"}, {"name": "Size", "type": "NUMBER"}]
    if support_track == "web_saas_api":
        return [{"name": "Name", "type": "TEXT"}, {"name": "Kind", "type": "TEXT"}, {"name": "Value", "type": "TEXT"}]
    if support_track == "semantic_cube":
        return [{"name": "Dimension", "type": "TEXT"}, {"name": "Member", "type": "TEXT"}, {"name": "Measure", "type": "NUMBER"}]
    return [{"name": "Value", "type": "TEXT"}]


def _fixture_rows(function_name: str, support_track: str) -> list[list[Any]]:
    slug = _test_slug(function_name)
    if support_track == "local_document":
        if function_name == "File.Contents":
            return [[b"fixture-bytes", f"tests/fixtures/power_query_adapters/local_document/{slug}/source.bin", "fixture-hash"]]
        if function_name in {"Folder.Contents", "Folder.Files"}:
            return [["sales.csv", ".csv", f"tests/fixtures/power_query_adapters/local_document/{slug}", b"Amount\n10\n"]]
        if function_name == "Excel.CurrentWorkbook":
            return [["Sales", [{"Amount": 10, "Region": "North"}], "Table"]]
        return [["Amount", "10"], ["Region", "North"]]
    if support_track == "relational_connector":
        return [["dbo", "Sales", 10], ["dbo", "Products", 2]]
    if support_track == "native_query":
        return [[True, 2]]
    if support_track == "cloud_storage_lake":
        return [[f"/fixture/{slug}/sales.parquet", "file", 128], [f"/fixture/{slug}/folder", "folder", 0]]
    if support_track == "web_saas_api":
        return [["Sales", "entity", "10"], ["NextPage", "paging", "fixture-token"]]
    if support_track == "semantic_cube":
        return [["Date", "2026", 10], ["Product", "Bikes", 25]]
    return [[function_name]]


def _test_slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or "")).strip("_")


def build_fixture_adapter_context(function_name: str, fixture_name: str = "default") -> PowerQueryAdapterContext:
    return PowerQueryAdapterContext(function_name=str(function_name), fixture_mode=True, fixture_name=str(fixture_name or "default"))


class PowerQueryRuntimeAdapter:
    def __init__(self, catalog_row: Mapping[str, Any]):
        self.catalog_row = dict(catalog_row)
        self.function_name = str(catalog_row.get("function") or "")
        self.support_track = str(catalog_row.get("support_track") or "supported")
        self.connector_id = _connector_id(self.function_name, self.support_track)

    def _result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        schema: Sequence[Mapping[str, Any]] | None = None,
        preview_rows: Sequence[Sequence[Any]] | None = None,
        diagnostics: Sequence[Mapping[str, Any]] | None = None,
    ) -> PowerQueryAdapterResult:
        descriptor = build_runtime_adapter_descriptor(self.catalog_row)
        if not context.fixture_mode:
            return self._live_result(context, operation=operation, descriptor=descriptor)
        return build_adapter_result(
            self.catalog_row,
            schema=schema if schema is not None else _fixture_schema(self.function_name, self.support_track),
            preview_rows=preview_rows if preview_rows is not None else _fixture_rows(self.function_name, self.support_track),
            source_lineage=context.source_lineage
            or [
                {
                    "function": self.function_name,
                    "fixture": context.fixture_name,
                    "operation": operation,
                    "path": f"tests/fixtures/power_query_adapters/{self.support_track}/{_test_slug(self.function_name)}",
                }
            ],
            credential_profile_id=context.credential_profile_id,
            diagnostics=diagnostics
            or [
                {
                    "code": descriptor["diagnostic_code"],
                    "severity": "info",
                    "message": f"{self.function_name} fixture adapter {operation} completed with redacted credential diagnostics.",
                }
            ],
        )

    def _live_blocked_result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        state: str,
        code: str,
        message: str,
        profile: Mapping[str, Any] | None = None,
    ) -> PowerQueryAdapterResult:
        return build_adapter_result(
            self.catalog_row,
            source_lineage=[
                {
                    "function": self.function_name,
                    "mode": "live",
                    "operation": operation,
                    "profile_id": context.credential_profile_id,
                    "connector_id": profile.get("connector_id") if isinstance(profile, Mapping) else None,
                }
            ],
            credential_profile_id=context.credential_profile_id,
            diagnostics=[{"code": code, "severity": "warning", "message": message}],
            execution_state=state,
            privacy_level=str((profile or {}).get("privacy_level") or context.privacy_level or "organizational"),
            folding_capability="blocked",
            refresh_mode="blocked",
        )

    def _live_response_result(
        self,
        context: PowerQueryAdapterContext,
        response: Any,
    ) -> PowerQueryAdapterResult:
        return build_adapter_result(
            self.catalog_row,
            schema=getattr(response, "schema", []),
            preview_rows=getattr(response, "preview_rows", []),
            source_lineage=getattr(response, "source_lineage", []),
            credential_profile_id=context.credential_profile_id,
            diagnostics=getattr(response, "diagnostics", []),
            execution_state=getattr(response, "execution_state", "not_configured"),
            privacy_level=getattr(response, "privacy_level", context.privacy_level),
            folding_capability=getattr(response, "folding_capability", "blocked"),
            refresh_mode=getattr(response, "refresh_mode", "blocked"),
        )

    def _live_result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        descriptor: Mapping[str, Any],
    ) -> PowerQueryAdapterResult:
        if self.support_track == "local_document":
            from .connectors.local_document import execute_local_document

            return self._live_response_result(
                context,
                execute_local_document(function_name=self.function_name, operation=operation, context=context),
            )
        if self.function_name not in _LIVE_CONNECTOR_FUNCTIONS and self.support_track not in {
            "relational_connector",
            "cloud_storage_lake",
            "web_saas_api",
            "native_query",
            "semantic_cube",
        }:
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code=str(descriptor["live_diagnostic_code"]),
                message=str(descriptor["live_blocked_reason"] or "Live adapter is not configured for this connector yet."),
            )
        if self.support_track == "native_query" and not (
            isinstance(context.approval_record, Mapping) and bool(context.approval_record.get("approved"))
        ):
            return self._live_blocked_result(
                context,
                operation=operation,
                state="approval_required",
                code="PQ_NATIVE_QUERY_APPROVAL_REQUIRED",
                message="Live native SQL execution requires an explicit approval record.",
            )
        if not context.credential_profile_id:
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED",
                message="Live connector execution requires credential_profile_id.",
            )
        profile = get_credential_profile(context.project_root, context.credential_profile_id)
        if not profile:
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED",
                message=f"Credential profile {context.credential_profile_id!r} was not found.",
            )
        profile_connector = str(profile.get("connector_id") or "").strip().lower()
        expected = _PROFILE_CONNECTOR_ALIASES.get(self.connector_id, {self.connector_id})
        if profile_connector not in expected:
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code="PQ_LIVE_CONNECTOR_PROFILE_MISMATCH",
                message=f"Credential profile connector {profile_connector!r} cannot execute {self.function_name}.",
                profile=profile,
            )
        secrets = get_credential_secrets(context.credential_profile_id)
        mock = self._mock_live_result(
            context,
            operation=operation,
            profile=profile,
            default_schema=_fixture_schema(self.function_name, self.support_track),
            default_rows=_fixture_rows(self.function_name, self.support_track),
            folding_capability="native_query" if self.support_track == "native_query" else ("semantic_query" if self.support_track == "semantic_cube" else "supported"),
        )
        if mock is not None and self.support_track != "native_query":
            return mock
        if self.support_track == "native_query":
            return self._live_native_query_result(context, operation=operation, profile=profile, secrets=secrets)
        if self.support_track == "relational_connector":
            return self._live_relational_result(context, operation=operation, profile=profile, secrets=secrets)
        if self.support_track == "cloud_storage_lake":
            from .connectors.azure_lake import execute_cloud_lake

            return self._live_response_result(
                context,
                execute_cloud_lake(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        if self.function_name == "OData.Feed":
            from .connectors.http_api import execute_odata

            return self._live_response_result(
                context,
                execute_odata(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        if self.connector_id in {"sharepoint", "exchange", "active_directory"}:
            from .connectors.microsoft_graph import execute_microsoft_graph

            return self._live_response_result(
                context,
                execute_microsoft_graph(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        if self.connector_id == "salesforce":
            from .connectors.salesforce import execute_salesforce

            return self._live_response_result(
                context,
                execute_salesforce(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        if self.connector_id in {"google_analytics", "adobe_analytics", "soda"}:
            from .connectors.analytics import execute_analytics

            return self._live_response_result(
                context,
                execute_analytics(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        if self.support_track == "web_saas_api":
            from .connectors.http_api import execute_web_api

            return self._live_response_result(
                context,
                execute_web_api(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        if self.support_track == "semantic_cube":
            from .connectors.semantic_cube import execute_semantic_cube

            return self._live_response_result(
                context,
                execute_semantic_cube(function_name=self.function_name, operation=operation, profile=profile, secrets=secrets, context=context),
            )
        return self._live_blocked_result(
            context,
            operation=operation,
            state="not_configured",
            code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED",
            message=f"No live adapter route is configured for {self.function_name}.",
            profile=profile,
        )

    def _mock_live_result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        profile: Mapping[str, Any],
        default_schema: Sequence[Mapping[str, Any]],
        default_rows: Sequence[Sequence[Any]],
        folding_capability: str = "supported",
    ) -> PowerQueryAdapterResult | None:
        if not context.options.get("mock_live"):
            return None
        schema = context.options.get("mock_schema")
        rows = context.options.get("mock_rows")
        return build_adapter_result(
            self.catalog_row,
            schema=schema if isinstance(schema, list) else default_schema,
            preview_rows=rows if isinstance(rows, list) else default_rows,
            source_lineage=[
                {
                    "function": self.function_name,
                    "mode": "live",
                    "operation": operation,
                    "profile_id": context.credential_profile_id,
                    "connector_id": profile.get("connector_id"),
                    "mock": True,
                }
            ],
            credential_profile_id=context.credential_profile_id,
            diagnostics=[
                {
                    "code": "PQ_LIVE_CONNECTOR_CONFIGURED",
                    "severity": "info",
                    "message": f"{self.function_name} live adapter {operation} completed through a mocked connector boundary.",
                }
            ],
            execution_state="configured",
            privacy_level=str(profile.get("privacy_level") or context.privacy_level or "organizational"),
            folding_capability=folding_capability,
            refresh_mode="supported",
        )

    def _optional_driver_missing(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        profile: Mapping[str, Any],
        module_name: str,
        message: str,
    ) -> PowerQueryAdapterResult | None:
        if importlib.util.find_spec(module_name) is not None:
            return None
        return self._live_blocked_result(
            context,
            operation=operation,
            state="driver_missing",
            code="PQ_LIVE_DRIVER_MISSING",
            message=message,
            profile=profile,
        )

    @staticmethod
    def _safe_identifier(value: Any, *, label: str) -> str:
        text = str(value or "").strip()
        if not text or not _IDENTIFIER_RE.match(text):
            raise ValueError(f"Live relational {label} must be a simple SQL identifier.")
        return text

    @staticmethod
    def _quote_identifier(value: str, connector: str) -> str:
        if connector in {"sql", "sql_database", "sqlserver", "sql_server", "odbc"}:
            return f"[{value}]"
        return f'"{value}"'

    def _relation_name(self, context: PowerQueryAdapterContext, profile: Mapping[str, Any], connector: str) -> str | None:
        props = profile.get("properties") if isinstance(profile.get("properties"), Mapping) else {}
        table = context.options.get("table") or props.get("table")
        if not table:
            return None
        table_name = self._safe_identifier(table, label="table")
        schema = context.options.get("schema") or props.get("schema")
        quoted_table = self._quote_identifier(table_name, connector)
        if not schema:
            return quoted_table
        schema_name = self._safe_identifier(schema, label="schema")
        return f"{self._quote_identifier(schema_name, connector)}.{quoted_table}"

    @staticmethod
    def _dbapi_rows(cursor: Any, *, limit: int | None = None) -> list[list[Any]]:
        fetch = getattr(cursor, "fetchmany", None)
        if callable(fetch) and limit:
            rows = fetch(limit)
        else:
            rows = cursor.fetchall()
        return [list(row) if isinstance(row, (tuple, list)) else [row] for row in rows or []]

    @staticmethod
    def _schema_from_description(description: Any) -> list[dict[str, Any]]:
        schema: list[dict[str, Any]] = []
        for item in description or []:
            name = item[0] if isinstance(item, (tuple, list)) and item else getattr(item, "name", None)
            type_code = item[1] if isinstance(item, (tuple, list)) and len(item) > 1 else getattr(item, "type_code", None)
            schema.append({"name": str(name or "Column"), "type": str(type_code or "TEXT")})
        return schema

    def _connect_relational(self, connector: str, profile: Mapping[str, Any], secrets: Mapping[str, Any], context: PowerQueryAdapterContext) -> Any:
        props = profile.get("properties") if isinstance(profile.get("properties"), Mapping) else {}
        if connector in {"sql", "sql_database", "sqlserver", "sql_server", "odbc"}:
            pyodbc = importlib.import_module("pyodbc")
            connection_string = (
                context.options.get("connection_string")
                or props.get("connection_string")
                or secrets.get("connection_string")
                or secrets.get("odbc_connection_string")
            )
            if not connection_string:
                raise ValueError("Live SQL Server/ODBC execution requires a connection string in profile properties or secrets.")
            return pyodbc.connect(str(connection_string), timeout=int(context.options.get("timeout") or 10))
        if connector == "postgresql":
            psycopg2 = importlib.import_module("psycopg2")
            return psycopg2.connect(
                host=props.get("host") or secrets.get("host"),
                port=int(props.get("port") or secrets.get("port") or 5432),
                dbname=props.get("database") or props.get("dbname") or secrets.get("database") or secrets.get("dbname"),
                user=props.get("user") or secrets.get("user") or secrets.get("username"),
                password=secrets.get("password"),
                connect_timeout=int(context.options.get("timeout") or 10),
            )
        if connector == "mysql":
            pymysql = importlib.import_module("pymysql")
            return pymysql.connect(
                host=props.get("host") or secrets.get("host"),
                port=int(props.get("port") or secrets.get("port") or 3306),
                database=props.get("database") or secrets.get("database"),
                user=props.get("user") or secrets.get("user") or secrets.get("username"),
                password=secrets.get("password"),
                connect_timeout=int(context.options.get("timeout") or 10),
            )
        raise ValueError(f"Live relational connector {connector!r} is not supported by the DB-API adapter.")

    def _relational_sql(self, context: PowerQueryAdapterContext, profile: Mapping[str, Any], connector: str, operation: str) -> tuple[str, int | None]:
        limit = int(context.options.get("limit") or 100)
        native_sql = context.options.get("query") or context.options.get("sql")
        if native_sql and operation in {"preview", "load", "native_query"}:
            return str(native_sql), limit
        if operation == "discover":
            if self.function_name == "Sql.Databases" and connector in {"sql", "sql_database", "sqlserver", "sql_server", "odbc"}:
                return "SELECT name AS [Database] FROM sys.databases ORDER BY name", limit
            return (
                "SELECT table_schema AS Schema, table_name AS Table, table_type AS Kind "
                "FROM information_schema.tables ORDER BY table_schema, table_name",
                limit,
            )
        relation = self._relation_name(context, profile, connector)
        if not relation:
            raise ValueError("Live relational execution requires adapter_options.table for preview/load/schema operations.")
        if operation == "schema":
            props = profile.get("properties") if isinstance(profile.get("properties"), Mapping) else {}
            table = self._safe_identifier(context.options.get("table") or props.get("table"), label="table")
            schema = self._safe_identifier(context.options.get("schema") or props.get("schema") or "dbo", label="schema")
            table_literal = table.replace("'", "''")
            schema_literal = schema.replace("'", "''")
            return (
                "SELECT column_name AS Name, data_type AS Type "
                "FROM information_schema.columns "
                f"WHERE table_name = '{table_literal}' AND table_schema = '{schema_literal}' "
                "ORDER BY ordinal_position",
                limit,
            )
        if connector in {"sql", "sql_database", "sqlserver", "sql_server", "odbc"}:
            return f"SELECT TOP ({limit}) * FROM {relation}", limit
        return f"SELECT * FROM {relation} LIMIT {limit}", limit

    def _execute_dbapi_relational(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        profile: Mapping[str, Any],
        secrets: Mapping[str, Any],
    ) -> PowerQueryAdapterResult:
        connector = str(profile.get("connector_id") or "").lower()
        conn = self._connect_relational(connector, profile, secrets, context)
        cursor = None
        try:
            cursor = conn.cursor()
            sql, limit = self._relational_sql(context, profile, connector, operation)
            cursor.execute(sql)
            rows = self._dbapi_rows(cursor, limit=limit)
            if operation == "schema":
                schema = [{"name": row[0], "type": row[1] if len(row) > 1 else "TEXT"} for row in rows]
                preview_rows: list[list[Any]] = []
            else:
                schema = self._schema_from_description(getattr(cursor, "description", None))
                preview_rows = rows
            return build_adapter_result(
                self.catalog_row,
                schema=schema,
                preview_rows=preview_rows,
                source_lineage=[
                    {
                        "function": self.function_name,
                        "mode": "live",
                        "operation": operation,
                        "profile_id": context.credential_profile_id,
                        "connector_id": profile.get("connector_id"),
                        "query_kind": "native" if context.options.get("query") or context.options.get("sql") else "generated",
                    }
                ],
                credential_profile_id=context.credential_profile_id,
                diagnostics=[
                    {
                        "code": "PQ_LIVE_CONNECTOR_CONFIGURED",
                        "severity": "info",
                        "message": f"{self.function_name} live relational adapter {operation} completed with redacted diagnostics.",
                    }
                ],
                execution_state="configured",
                privacy_level=str(profile.get("privacy_level") or context.privacy_level or "organizational"),
                folding_capability="supported",
                refresh_mode="supported",
            )
        finally:
            if cursor is not None and hasattr(cursor, "close"):
                cursor.close()
            if hasattr(conn, "close"):
                conn.close()

    def _live_relational_result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        profile: Mapping[str, Any],
        secrets: Mapping[str, Any],
    ) -> PowerQueryAdapterResult:
        mock = self._mock_live_result(
            context,
            operation=operation,
            profile=profile,
            default_schema=[{"name": "Schema", "type": "TEXT"}, {"name": "Table", "type": "TEXT"}],
            default_rows=[["dbo", "Sales"], ["dbo", "Products"]] if operation in {"discover", "preview", "load"} else [],
        )
        if mock is not None:
            return mock
        connector = str(profile.get("connector_id") or "").lower()
        if connector in {"sql", "sql_database", "sqlserver", "sql_server", "odbc"}:
            missing = self._optional_driver_missing(
                context,
                operation=operation,
                profile=profile,
                module_name="pyodbc",
                message="Live SQL Server/ODBC execution requires the optional pyodbc package and an installed ODBC driver.",
            )
            if missing is not None:
                return missing
        if connector == "postgresql":
            missing = self._optional_driver_missing(
                context,
                operation=operation,
                profile=profile,
                module_name="psycopg2",
                message="Live PostgreSQL execution requires an optional PostgreSQL DB-API driver.",
            )
            if missing is not None:
                return missing
        if connector == "mysql":
            missing = self._optional_driver_missing(
                context,
                operation=operation,
                profile=profile,
                module_name="pymysql",
                message="Live MySQL execution requires the optional PyMySQL package.",
            )
            if missing is not None:
                return missing
        try:
            return self._execute_dbapi_relational(context, operation=operation, profile=profile, secrets=secrets)
        except Exception as exc:  # noqa: BLE001
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED",
                message=f"Live relational execution could not run: {redact_secret_value(str(exc))}",
                profile=redact_secret_value({**profile, "secrets": dict(secrets)}),
            )

    def _live_odata_result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        profile: Mapping[str, Any],
        secrets: Mapping[str, Any],
    ) -> PowerQueryAdapterResult:
        mock = self._mock_live_result(
            context,
            operation=operation,
            profile=profile,
            default_schema=[{"name": "Name", "type": "TEXT"}, {"name": "Kind", "type": "TEXT"}],
            default_rows=[["Orders", "entity"], ["Customers", "entity"]] if operation in {"discover", "preview", "load"} else [],
            folding_capability="select_filter_supported",
        )
        if mock is not None:
            return mock
        props = profile.get("properties") if isinstance(profile.get("properties"), Mapping) else {}
        base_url = str(props.get("base_url") or props.get("url") or "").strip()
        if not base_url:
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED",
                message="Live OData execution requires properties.base_url on the credential profile.",
                profile=profile,
            )
        entity = str(context.options.get("entity") or props.get("entity") or "").strip()
        url = base_url.rstrip("/")
        if entity:
            url = f"{url}/{urllib.parse.quote(entity)}"
        if context.options.get("select"):
            url = f"{url}?$select={urllib.parse.quote(str(context.options.get('select')))}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        token = str(secrets.get("access_token") or secrets.get("token") or "").strip()
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=float(context.options.get("timeout") or 10)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return self._live_blocked_result(
                context,
                operation=operation,
                state="auth_failed" if exc.code in {401, 403} else "not_configured",
                code="PQ_LIVE_HTTP_ERROR",
                message=f"Live OData request failed with HTTP {exc.code}.",
                profile=profile,
            )
        except Exception as exc:  # noqa: BLE001
            return self._live_blocked_result(
                context,
                operation=operation,
                state="not_configured",
                code="PQ_LIVE_HTTP_ERROR",
                message=f"Live OData request failed: {redact_secret_value(str(exc))}",
                profile=profile,
            )
        rows_payload = payload.get("value") if isinstance(payload, Mapping) else payload
        rows_records = rows_payload if isinstance(rows_payload, list) else [payload]
        keys = sorted({str(key) for row in rows_records if isinstance(row, Mapping) for key in row.keys()})
        schema = [{"name": key, "type": "TEXT"} for key in keys] or [{"name": "Value", "type": "TEXT"}]
        rows = [[row.get(key) if isinstance(row, Mapping) else row for key in keys] for row in rows_records[:100]]
        return build_adapter_result(
            self.catalog_row,
            schema=schema,
            preview_rows=rows,
            source_lineage=[{"function": self.function_name, "mode": "live", "operation": operation, "profile_id": context.credential_profile_id, "url": redact_secret_value(url)}],
            credential_profile_id=context.credential_profile_id,
            diagnostics=[{"code": "PQ_LIVE_CONNECTOR_CONFIGURED", "severity": "info", "message": "OData live request completed with redacted diagnostics."}],
            execution_state="configured",
            privacy_level=str(profile.get("privacy_level") or context.privacy_level or "organizational"),
            folding_capability="select_filter_supported",
            refresh_mode="supported",
        )

    def _live_native_query_result(
        self,
        context: PowerQueryAdapterContext,
        *,
        operation: str,
        profile: Mapping[str, Any],
        secrets: Mapping[str, Any],
    ) -> PowerQueryAdapterResult:
        mock = self._mock_live_result(
            context,
            operation=operation,
            profile=profile,
            default_schema=[{"name": "Approved", "type": "LOGICAL"}, {"name": "Rows", "type": "NUMBER"}],
            default_rows=[[True, 1]],
            folding_capability="native_query",
        )
        if mock is not None:
            audit = mock.to_dict()
            audit["source_lineage"][0]["approval_id"] = str((context.approval_record or {}).get("approval_id") or "approved")
            return build_adapter_result(
                self.catalog_row,
                schema=audit["schema"],
                preview_rows=audit["preview_rows"],
                source_lineage=audit["source_lineage"],
                credential_profile_id=context.credential_profile_id,
                diagnostics=[{"code": "PQ_NATIVE_QUERY_APPROVED", "severity": "info", "message": "Native query executed with approval metadata and redacted diagnostics."}],
                execution_state="configured",
                privacy_level=str(profile.get("privacy_level") or context.privacy_level or "organizational"),
                folding_capability="native_query",
                refresh_mode="supported",
            )
        return self._live_relational_result(context, operation=operation, profile=profile, secrets=secrets)

    def discover(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        return self._result(context, operation="discover")

    def schema(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        return self._result(context, operation="schema", preview_rows=[])

    def preview(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        return self._result(context, operation="preview")

    def load(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        return self._result(context, operation="load")

    def refresh(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        return self._result(context, operation="refresh")

    def folding(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        return self._result(context, operation="folding", preview_rows=[])

    def native_query(self, context: PowerQueryAdapterContext) -> PowerQueryAdapterResult:
        approved = isinstance(context.approval_record, Mapping) and bool(context.approval_record.get("approved"))
        if self.support_track == "native_query" and not approved:
            descriptor = build_runtime_adapter_descriptor(self.catalog_row)
            return build_adapter_result(
                self.catalog_row,
                source_lineage=context.source_lineage or [{"function": self.function_name, "operation": "native_query"}],
                credential_profile_id=context.credential_profile_id,
                diagnostics=[
                    {
                        "code": "PQ_NATIVE_QUERY_APPROVAL_REQUIRED",
                        "severity": "warning",
                        "message": descriptor["live_blocked_reason"] or "Native query requires explicit approval.",
                    }
                ],
                execution_state="approval_required",
                folding_capability="blocked",
                refresh_mode="blocked",
            )
        return self._result(context, operation="native_query")


def get_power_query_adapter(function_name: str) -> PowerQueryRuntimeAdapter:
    from .function_catalog import function_catalog_rows

    wanted = str(function_name or "").strip().upper()
    for row in function_catalog_rows():
        if str(row.get("function") or "").upper() == wanted:
            return PowerQueryRuntimeAdapter(row)
    raise KeyError(f"Power Query adapter not found for {function_name!r}")


def execute_power_query_adapter(
    function_name: str,
    context: PowerQueryAdapterContext | Mapping[str, Any] | None = None,
    *,
    operation: str = "preview",
) -> PowerQueryAdapterResult:
    adapter = get_power_query_adapter(function_name)
    if context is None:
        adapter_context = build_fixture_adapter_context(function_name)
    elif isinstance(context, PowerQueryAdapterContext):
        adapter_context = context
    else:
        adapter_context = PowerQueryAdapterContext(
            function_name=str(context.get("function_name") or function_name),
            parsed_args=list(context.get("parsed_args") or []),
            options=dict(context.get("options") or {}),
            project_root=context.get("project_root"),
            credential_profile_id=context.get("credential_profile_id"),
            fixture_mode=bool(context.get("fixture_mode", True)),
            fixture_name=str(context.get("fixture_name") or "default"),
            approval_record=dict(context.get("approval_record") or {}) if isinstance(context.get("approval_record"), Mapping) else None,
            source_lineage=[dict(item) for item in context.get("source_lineage") or []],
            privacy_level=str(context.get("privacy_level") or "organizational"),
        )
    method_name = str(operation or "preview").strip().lower()
    if not hasattr(adapter, method_name):
        raise ValueError(f"Unsupported Power Query adapter operation: {operation!r}")
    return getattr(adapter, method_name)(adapter_context)


def build_adapter_result(
    catalog_row: Mapping[str, Any],
    *,
    schema: Sequence[Mapping[str, Any]] | None = None,
    preview_rows: Sequence[Sequence[Any]] | None = None,
    source_lineage: Sequence[Mapping[str, Any]] | None = None,
    credential_profile_id: str | None = None,
    diagnostics: Sequence[Mapping[str, Any]] | None = None,
    execution_state: str | None = None,
    privacy_level: str | None = None,
    folding_capability: str | None = None,
    refresh_mode: str | None = None,
) -> PowerQueryAdapterResult:
    descriptor = build_runtime_adapter_descriptor(catalog_row)
    row_diagnostics = []
    for diagnostic in diagnostics or []:
        row_diagnostics.append(
            PowerQueryAdapterDiagnostic(
                code=str(diagnostic.get("code") or descriptor["diagnostic_code"]),
                severity=str(diagnostic.get("severity") or "info"),
                message=str(diagnostic.get("message") or descriptor["blocked_reason"] or "Adapter diagnostic."),
            )
        )
    if not row_diagnostics and descriptor["blocked_reason"]:
        row_diagnostics.append(
            PowerQueryAdapterDiagnostic(
                code=str(descriptor["diagnostic_code"]),
                severity="warning",
                message=str(descriptor["blocked_reason"]),
            )
        )
    if not row_diagnostics and str(catalog_row.get("support_track") or "") != "supported":
        row_diagnostics.append(
            PowerQueryAdapterDiagnostic(
                code=str(descriptor["diagnostic_code"]),
                severity="info",
                message=f"{catalog_row.get('function')} fixture adapter result satisfies the Power Query runtime contract.",
            )
        )
    capabilities = descriptor["capabilities"]
    return PowerQueryAdapterResult(
        function=str(catalog_row.get("function") or ""),
        adapter_key=str(descriptor["adapter_key"]),
        connector_id=str(descriptor["connector_id"]),
        execution_state=str(execution_state or descriptor["execution_state"]),
        schema=[dict(item) for item in schema or []],
        preview_rows=[list(item) for item in preview_rows or []],
        source_lineage=[dict(item) for item in source_lineage or []],
        credential_profile_id=credential_profile_id,
        privacy_level=str(privacy_level or ("private" if str(catalog_row.get("support_track") or "") == "local_document" else "organizational")),
        folding_capability=str(folding_capability or ("supported" if capabilities.get("folding") else "blocked")),
        diagnostics=row_diagnostics,
        refresh_mode=str(refresh_mode or ("supported" if capabilities.get("refresh") else "blocked")),
    )
