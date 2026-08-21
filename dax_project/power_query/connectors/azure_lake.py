from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

from .common import blocked_response, configured_response, infer_schema_from_records, profile_id, properties, rows_from_records


_SDK_REQUIREMENTS = {
    "AzureStorage.BlobContents": "azure.storage.blob",
    "AzureStorage.Blobs": "azure.storage.blob",
    "AzureStorage.DataLake": "azure.storage.filedatalake",
    "AzureStorage.DataLakeContents": "azure.storage.filedatalake",
    "AzureStorage.Tables": "azure.data.tables",
    "DeltaLake.Metadata": "deltalake",
    "DeltaLake.Table": "deltalake",
    "Hdfs.Contents": "pyarrow",
    "Hdfs.Files": "pyarrow",
    "HdInsight.Containers": "azure.storage.blob",
    "HdInsight.Contents": "azure.storage.blob",
    "HdInsight.Files": "azure.storage.blob",
}


def _has_package(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _blob_service(profile: Mapping[str, Any], secrets: Mapping[str, Any]) -> Any:
    from azure.storage.blob import BlobServiceClient  # type: ignore

    props = properties(profile)
    connection_string = secrets.get("connection_string") or props.get("connection_string")
    if connection_string:
        return BlobServiceClient.from_connection_string(str(connection_string))
    account_url = props.get("account_url") or secrets.get("account_url")
    account = props.get("account") or secrets.get("account")
    if not account_url and account:
        account_url = f"https://{account}.blob.core.windows.net"
    credential = secrets.get("credential") or secrets.get("sas_token") or secrets.get("account_key") or secrets.get("access_token")
    if not account_url:
        raise ValueError("Azure Blob live execution requires account_url/account or a connection string.")
    return BlobServiceClient(account_url=str(account_url), credential=credential)


def _datalake_service(profile: Mapping[str, Any], secrets: Mapping[str, Any]) -> Any:
    from azure.storage.filedatalake import DataLakeServiceClient  # type: ignore

    props = properties(profile)
    account_url = props.get("account_url") or secrets.get("account_url")
    account = props.get("account") or secrets.get("account")
    if not account_url and account:
        account_url = f"https://{account}.dfs.core.windows.net"
    credential = secrets.get("credential") or secrets.get("sas_token") or secrets.get("account_key") or secrets.get("access_token")
    if not account_url:
        raise ValueError("Azure Data Lake live execution requires account_url/account.")
    return DataLakeServiceClient(account_url=str(account_url), credential=credential)


def _table_service(profile: Mapping[str, Any], secrets: Mapping[str, Any]) -> Any:
    from azure.data.tables import TableServiceClient  # type: ignore

    props = properties(profile)
    connection_string = secrets.get("connection_string") or props.get("connection_string")
    if connection_string:
        return TableServiceClient.from_connection_string(str(connection_string))
    endpoint = props.get("account_url") or props.get("endpoint") or secrets.get("account_url")
    credential = secrets.get("credential") or secrets.get("sas_token") or secrets.get("account_key") or secrets.get("access_token")
    if not endpoint:
        raise ValueError("Azure Tables live execution requires account_url/endpoint or a connection string.")
    return TableServiceClient(endpoint=str(endpoint), credential=credential)


def _azure_blob(function_name: str, operation: str, profile: Mapping[str, Any], secrets: Mapping[str, Any], context: Any) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    props = properties(profile)
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    service = _blob_service(profile, secrets)
    container = str(options.get("container") or props.get("container") or "").strip()
    if not container:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires container metadata.", connector_id=str(profile.get("connector_id") or "azure_blob"), profile_id=pid)
    client = service.get_container_client(container)
    limit = int(options.get("limit") or 100)
    if function_name == "AzureStorage.BlobContents":
        blob_name = str(options.get("path") or options.get("blob") or props.get("path") or "").strip()
        if not blob_name:
            return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="AzureStorage.BlobContents requires blob path metadata.", connector_id="azure_blob", profile_id=pid)
        data = client.download_blob(blob_name).readall()
        schema = [{"name": "Content", "type": "BINARY"}, {"name": "Path", "type": "TEXT"}, {"name": "Size", "type": "NUMBER"}]
        return configured_response(function_name=function_name, operation=operation, schema=schema, rows=[[data, blob_name, len(data)]], connector_id="azure_blob", profile_id=pid, source={"container": container, "path": blob_name}, folding_capability="not_foldable")
    rows = []
    for blob in client.list_blobs(name_starts_with=str(options.get("prefix") or props.get("prefix") or "")):
        rows.append({"Name": getattr(blob, "name", ""), "Size": getattr(blob, "size", 0), "ContentType": getattr(getattr(blob, "content_settings", None), "content_type", ""), "Container": container})
        if len(rows) >= limit:
            break
    schema = infer_schema_from_records(rows)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(rows, schema, limit=limit), connector_id="azure_blob", profile_id=pid, source={"container": container}, folding_capability="not_foldable")


def _azure_datalake(function_name: str, operation: str, profile: Mapping[str, Any], secrets: Mapping[str, Any], context: Any) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    props = properties(profile)
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    service = _datalake_service(profile, secrets)
    filesystem = str(options.get("filesystem") or props.get("filesystem") or props.get("container") or "").strip()
    if not filesystem:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires filesystem/container metadata.", connector_id="azure_data_lake", profile_id=pid)
    file_system_client = service.get_file_system_client(filesystem)
    if function_name == "AzureStorage.DataLakeContents":
        path = str(options.get("path") or props.get("path") or "").strip()
        if not path:
            return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="AzureStorage.DataLakeContents requires file path metadata.", connector_id="azure_data_lake", profile_id=pid)
        data = file_system_client.get_file_client(path).download_file().readall()
        schema = [{"name": "Content", "type": "BINARY"}, {"name": "Path", "type": "TEXT"}, {"name": "Size", "type": "NUMBER"}]
        return configured_response(function_name=function_name, operation=operation, schema=schema, rows=[[data, path, len(data)]], connector_id="azure_data_lake", profile_id=pid, source={"filesystem": filesystem, "path": path}, folding_capability="not_foldable")
    limit = int(options.get("limit") or 100)
    records = []
    for item in file_system_client.get_paths(path=str(options.get("path") or props.get("path") or "")):
        records.append({"Name": getattr(item, "name", ""), "IsDirectory": getattr(item, "is_directory", False), "Size": getattr(item, "content_length", 0), "Filesystem": filesystem})
        if len(records) >= limit:
            break
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=limit), connector_id="azure_data_lake", profile_id=pid, source={"filesystem": filesystem}, folding_capability="not_foldable")


def _azure_tables(function_name: str, operation: str, profile: Mapping[str, Any], secrets: Mapping[str, Any], context: Any) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    props = properties(profile)
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    service = _table_service(profile, secrets)
    table = str(options.get("table") or props.get("table") or "").strip()
    limit = int(options.get("limit") or 100)
    if not table:
        records = [{"Name": item.name} for item in list(service.list_tables())[:limit]]
    else:
        client = service.get_table_client(table)
        records = [dict(item) for item in client.list_entities(results_per_page=limit)]
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema, limit=limit), connector_id="azure_table_storage", profile_id=pid, source={"table": table or None}, folding_capability="select_filter_supported")


def _safe_project_path(project_root: str | None, raw_path: Any) -> Path:
    root = Path(project_root or ".").resolve()
    path = Path(str(raw_path or ""))
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("Path escapes the project root.")
    return resolved


def _cdm_contents(function_name: str, operation: str, profile: Mapping[str, Any], context: Any) -> Any:
    options = dict(getattr(context, "options", {}) or {})
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    path = options.get("path") or properties(profile).get("path")
    if not path:
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message="Cdm.Contents requires a model.json or manifest path.", connector_id="cdm", profile_id=pid)
    try:
        resolved = _safe_project_path(getattr(context, "project_root", None), path)
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CDM_ERROR", message=str(exc), connector_id="cdm", profile_id=pid)
    entities = payload.get("entities") if isinstance(payload, Mapping) else []
    records = entities if isinstance(entities, list) else []
    schema = infer_schema_from_records(records)
    return configured_response(function_name=function_name, operation=operation, schema=schema, rows=rows_from_records(records, schema), connector_id="cdm", profile_id=pid, source={"path": str(resolved)}, folding_capability="not_foldable")


def execute_cloud_lake(
    *,
    function_name: str,
    operation: str,
    profile: Mapping[str, Any],
    secrets: Mapping[str, Any],
    context: Any,
) -> Any:
    pid = profile_id(profile, getattr(context, "credential_profile_id", None))
    connector = str(profile.get("connector_id") or "cloud_lake")
    if function_name == "Cdm.Contents":
        return _cdm_contents(function_name, operation, profile, context)
    requirement = _SDK_REQUIREMENTS.get(function_name)
    if requirement and not _has_package(requirement):
        return blocked_response(function_name=function_name, operation=operation, state="driver_missing", code="PQ_LIVE_DRIVER_MISSING", message=f"{function_name} live execution requires optional package {requirement}.", connector_id=connector, profile_id=pid)
    try:
        if function_name in {"AzureStorage.BlobContents", "AzureStorage.Blobs", "HdInsight.Containers", "HdInsight.Contents", "HdInsight.Files"}:
            return _azure_blob(function_name, operation, profile, secrets, context)
        if function_name in {"AzureStorage.DataLake", "AzureStorage.DataLakeContents"}:
            return _azure_datalake(function_name, operation, profile, secrets, context)
        if function_name == "AzureStorage.Tables":
            return _azure_tables(function_name, operation, profile, secrets, context)
    except Exception as exc:  # noqa: BLE001
        return blocked_response(function_name=function_name, operation=operation, state="auth_failed", code="PQ_LIVE_CLOUD_CONNECTOR_ERROR", message=str(exc), connector_id=connector, profile_id=pid)
    return blocked_response(function_name=function_name, operation=operation, state="not_configured", code="PQ_LIVE_CONNECTOR_NOT_CONFIGURED", message=f"{function_name} requires provider-specific account/container/path metadata and credentials before live execution.", connector_id=connector, profile_id=pid)
