from __future__ import annotations

import os
import re
from typing import Any, Mapping, Optional, Sequence

from .model import MSourceBinding, MSourceMapping
from .parser import parse_m_query
from .registry import _SOURCE_FUNCTIONS


_FILE_CONTENTS_RE = re.compile(r'File\.Contents\(\s*"([^"]+)"\s*\)', re.IGNORECASE)
_FOLDER_RE = re.compile(r'Folder\.(Files|Contents)\(\s*"([^"]+)"\s*\)', re.IGNORECASE)
_SQL_DATABASE_RE = re.compile(r'(?<![A-Za-z0-9_])Sql\.Database\(\s*"([^"]+)"\s*,\s*"([^"]+)"(?:\s*,\s*(\[[\s\S]*?\]))?\s*\)', re.IGNORECASE)
_ODBC_RE = re.compile(r'Odbc\.DataSource\(\s*"([^"]+)"', re.IGNORECASE)
_ODATA_RE = re.compile(r'OData\.Feed\(\s*"([^"]+)"', re.IGNORECASE)
_WEB_RE = re.compile(r'Web\.Contents\(\s*"([^"]+)"', re.IGNORECASE)
_SHAREPOINT_RE = re.compile(r'SharePoint\.(Files|Tables)\(\s*"([^"]+)"', re.IGNORECASE)
_TSV_DELIMITER_RE = re.compile(r'Delimiter\s*=\s*"[\t\\t]"', re.IGNORECASE)

_EXPLICIT_SOURCE_FUNCTIONS = {
    "FILE.CONTENTS",
    "FOLDER.FILES",
    "FOLDER.CONTENTS",
    "SQL.DATABASE",
    "ODBC.DATASOURCE",
    "ODATA.FEED",
    "WEB.CONTENTS",
    "SHAREPOINT.FILES",
    "SHAREPOINT.TABLES",
    "CSV.DOCUMENT",
    "EXCEL.WORKBOOK",
    "JSON.DOCUMENT",
    "XML.TABLES",
    "PARQUET.DOCUMENT",
}

_GENERIC_SOURCE_FUNCTIONS = {
    name.upper(): (name, source_type)
    for name, source_type in _SOURCE_FUNCTIONS.items()
    if name.upper() not in _EXPLICIT_SOURCE_FUNCTIONS
}

_GENERIC_SOURCE_ARG_LABELS: dict[str, tuple[str, ...]] = {
    "ACCESS.DATABASE": ("database", "options"),
    "ACTIVEDIRECTORY.DOMAINS": ("forest", "options"),
    "ADODOTNET.DATASOURCE": ("provider", "connection_string", "options"),
    "ANALYSISSERVICES.DATABASES": ("server", "options"),
    "AZURESTORAGE.BLOBCONTENTS": ("url", "options"),
    "AZURESTORAGE.BLOBS": ("account", "options"),
    "AZURESTORAGE.DATALAKE": ("url", "options"),
    "AZURESTORAGE.DATALAKECONTENTS": ("url", "options"),
    "AZURESTORAGE.TABLES": ("account", "options"),
    "CDM.CONTENTS": ("path", "options"),
    "DB2.DATABASE": ("server", "database", "options"),
    "DELTALAKE.METADATA": ("path", "options"),
    "DELTALAKE.TABLE": ("path", "options"),
    "ESSBASE.CUBES": ("server", "options"),
    "EXCHANGE.CONTENTS": ("mailbox", "options"),
    "HDFS.CONTENTS": ("url", "options"),
    "HDFS.FILES": ("url", "options"),
    "HDINSIGHT.CONTAINERS": ("account", "options"),
    "HDINSIGHT.CONTENTS": ("account", "container", "path", "options"),
    "HDINSIGHT.FILES": ("account", "container", "path", "options"),
    "INFORMIX.DATABASE": ("server", "database", "options"),
    "MYSQL.DATABASE": ("server", "database", "options"),
    "OLEDB.DATASOURCE": ("connection_string", "options"),
    "ORACLE.DATABASE": ("server", "options"),
    "PDF.TABLES": ("file", "options"),
    "POSTGRESQL.DATABASE": ("server", "database", "options"),
    "RDATA.FROMBINARY": ("binary",),
    "SALESFORCE.DATA": ("url", "options"),
    "SALESFORCE.REPORTS": ("url", "options"),
    "SAPBUSINESSWAREHOUSE.CUBES": ("server", "system_number", "client_id", "options"),
    "SAPHANA.DATABASE": ("server", "options"),
    "SHAREPOINT.CONTENTS": ("url", "options"),
    "SODA.FEED": ("url", "options"),
    "SQL.DATABASES": ("server", "options"),
    "SYBASE.DATABASE": ("server", "database", "options"),
    "TERADATA.DATABASE": ("server", "options"),
    "WEB.BROWSERCONTENTS": ("url", "options"),
    "WEB.PAGE": ("html", "options"),
    "WEBACTION.REQUEST": ("method", "url", "options"),
}

_GENERIC_CONNECTOR_SOURCE_TYPES = {
    source_type
    for _name, source_type in _SOURCE_FUNCTIONS.items()
    if source_type not in {"file", "folder", "csv", "json", "parquet", "excel", "xml"}
}

_EXT_TO_TYPE = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".json": "json",
    ".jsonl": "json",
    ".xml": "xml",
    ".xlsx": "excel",
    ".xls": "excel",
    ".xlsm": "excel",
}

_NAVIGATION_SOURCE_BLOCK_KEYS = {
    "item",
    "kind",
    "name",
    "schema",
    "signature",
    "navigation_field",
    "table_name",
    "entity",
    "workspace_id",
    "dataflow_id",
    "list_id",
    "drive_id",
}

_SCHEMA_PROBE_SOURCE_TYPES = {
    "csv",
    "json",
    "parquet",
    "excel",
    "xml",
    "folder",
    "sql",
    "odbc",
    "odata",
    "web",
    "sharepoint",
    "salesforce",
    "azure_blob",
    "azure_datalake",
    "azure_tables",
    "analysis_services",
    "powerbi_dataflows",
    "query_reference",
}


_SOURCE_POLICIES: dict[str, dict[str, Any]] = {
    "csv": {
        "connector_id": "local_file",
        "privacy_level": "private",
        "credential_required": False,
        "pushdown_support": "duckdb_sql_preview",
        "folding_status": "foldable_file_scan",
    },
    "json": {
        "connector_id": "local_file",
        "privacy_level": "private",
        "credential_required": False,
        "pushdown_support": "duckdb_sql_preview",
        "folding_status": "foldable_file_scan",
    },
    "parquet": {
        "connector_id": "local_file",
        "privacy_level": "private",
        "credential_required": False,
        "pushdown_support": "duckdb_sql_preview",
        "folding_status": "foldable_file_scan",
    },
    "excel": {
        "connector_id": "local_file",
        "privacy_level": "private",
        "credential_required": False,
        "pushdown_support": "local_evaluator",
        "folding_status": "connector_adapter_pending",
    },
    "xml": {
        "connector_id": "local_file",
        "privacy_level": "private",
        "credential_required": False,
        "pushdown_support": "local_evaluator",
        "folding_status": "connector_adapter_pending",
    },
    "folder": {
        "connector_id": "local_folder",
        "privacy_level": "private",
        "credential_required": False,
        "pushdown_support": "combine_files_planned",
        "folding_status": "connector_adapter_pending",
    },
    "sql": {
        "connector_id": "sql_database",
        "privacy_level": "organizational",
        "credential_required": True,
        "pushdown_support": "warehouse_native_planned",
        "folding_status": "credential_binding_required",
    },
    "odbc": {
        "connector_id": "odbc",
        "privacy_level": "organizational",
        "credential_required": True,
        "pushdown_support": "connector_native_planned",
        "folding_status": "credential_binding_required",
    },
    "odata": {
        "connector_id": "odata",
        "privacy_level": "organizational",
        "credential_required": True,
        "pushdown_support": "connector_native_planned",
        "folding_status": "credential_binding_required",
    },
    "web": {
        "connector_id": "web",
        "privacy_level": "public",
        "credential_required": False,
        "pushdown_support": "local_evaluator",
        "folding_status": "connector_adapter_pending",
    },
    "sharepoint": {
        "connector_id": "sharepoint",
        "privacy_level": "organizational",
        "credential_required": True,
        "pushdown_support": "connector_native_planned",
        "folding_status": "credential_binding_required",
    },
}


def _policy(source_type: str) -> dict[str, Any]:
    if source_type in _SOURCE_POLICIES:
        return dict(_SOURCE_POLICIES[source_type])
    if source_type in _GENERIC_CONNECTOR_SOURCE_TYPES:
        privacy_level = "public" if source_type in {"web", "web_action", "soda"} else "organizational"
        return {
            "connector_id": source_type or "unknown",
            "privacy_level": privacy_level,
            "credential_required": source_type not in {"excel_current_workbook", "pdf", "rdata"},
            "pushdown_support": "connector_native_planned",
            "folding_status": "connector_adapter_pending",
        }
    return dict(
        _SOURCE_POLICIES.get(
            source_type,
            {
                "connector_id": source_type or "unknown",
                "privacy_level": "unknown",
                "credential_required": True,
                "pushdown_support": "manual_mapping_required",
                "folding_status": "unknown",
            },
        )
    )


def _m_string(value: str) -> str | None:
    text = value.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('""', '"')
    return None


def _static_arg_value(value: str) -> Any:
    string_value = _m_string(value)
    if string_value is not None:
        return string_value
    text = value.strip()
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null":
        return None
    if re.match(r"^-?\d+(?:\.\d+)?$", text):
        try:
            return float(text) if "." in text else int(text)
        except Exception:
            return None
    return None


def _static_arg_summary(args: Sequence[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, arg in enumerate(args):
        value = _static_arg_value(arg)
        item: dict[str, Any] = {"position": idx}
        if value is None and arg.strip().lower() != "null":
            item["kind"] = "expression"
        else:
            item["kind"] = "literal"
            item["value"] = value
        out.append(item)
    return out


def _generic_source_block(function_upper: str, canonical_name: str, source_type: str, args: Sequence[str]) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": source_type,
        "function": canonical_name,
    }
    labels = _GENERIC_SOURCE_ARG_LABELS.get(function_upper, ())
    for idx, label in enumerate(labels):
        if idx >= len(args):
            continue
        value = _static_arg_value(args[idx])
        if value is not None or args[idx].strip().lower() == "null":
            block[label] = value
        else:
            block.setdefault("expression_arguments", []).append({"name": label, "position": idx})
    static_args = _static_arg_summary(args)
    if static_args:
        block["arguments"] = static_args
    return block


def _split_top_level_items(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        elif ch == delimiter and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _direct_call(expression: str) -> tuple[str, list[str]] | None:
    text = (expression or "").strip()
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\s*\(", text)
    if not match:
        return None
    open_idx = text.find("(", match.end() - 1)
    depth = 0
    in_string = False
    i = open_idx
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return match.group(1), _split_top_level_items(text[open_idx + 1 : i])
        i += 1
    return None


def _code_position_mask(text: str) -> list[bool]:
    mask = [True for _ch in text]
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            mask[i] = False
            if ch == '"' and nxt == '"':
                if i + 1 < len(mask):
                    mask[i + 1] = False
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            mask[i] = False
            in_string = True
            i += 1
            continue
        if ch == "/" and nxt == "/":
            mask[i] = False
            if i + 1 < len(mask):
                mask[i + 1] = False
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                mask[i] = False
                i += 1
            continue
        if ch == "/" and nxt == "*":
            mask[i] = False
            if i + 1 < len(mask):
                mask[i + 1] = False
            i += 2
            while i < len(text):
                mask[i] = False
                if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                    mask[i + 1] = False
                    i += 2
                    break
                i += 1
            continue
        i += 1
    return mask


def _iter_code_matches(pattern: re.Pattern[str], text: str):
    mask = _code_position_mask(text)
    for match in pattern.finditer(text):
        if match.start() < len(mask) and mask[match.start()]:
            yield match


def _step_dependency_map(steps: Sequence[Any]) -> dict[str, list[Any]]:
    by_dependency: dict[str, list[Any]] = {}
    for step in steps:
        for dep in getattr(step, "dependencies", []) or []:
            by_dependency.setdefault(str(dep), []).append(step)
    return by_dependency


def _document_type_for_step(step_id: str, dependents: Mapping[str, list[Any]]) -> tuple[str | None, Any | None]:
    for dep_step in dependents.get(step_id, []):
        call = _direct_call(getattr(dep_step, "expression", ""))
        if not call:
            continue
        name = call[0].upper()
        if name == "CSV.DOCUMENT":
            return "csv", dep_step
        if name == "JSON.DOCUMENT":
            return "json", dep_step
        if name == "EXCEL.WORKBOOK":
            return "excel", dep_step
        if name == "XML.TABLES":
            return "xml", dep_step
        if name == "PARQUET.DOCUMENT":
            return "parquet", dep_step
    return None, None


def _navigation_record_from_expression(expression: str, *, extra_fields: Sequence[str] = ()) -> dict[str, str]:
    match = re.search(r"\{\s*(\[[\s\S]*?\])\s*\}\s*(?:\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*\])?", expression)
    if not match:
        return {}
    record_text = match.group(1)
    out: dict[str, str] = {}
    for field in ("Item", "Kind", "Name", "Schema", "Signature", *extra_fields):
        field_match = re.search(rf"\b{field}\s*=\s*(\"(?:[^\"]|\"\")*\")", record_text, flags=re.IGNORECASE)
        if field_match:
            value = _m_string(field_match.group(1))
            if value is not None:
                out[field.lower()] = value
    if match.group(2):
        out["navigation_field"] = match.group(2)
    return out


def _odata_navigation_record_from_expression(expression: str) -> dict[str, str]:
    return _navigation_record_from_expression(expression, extra_fields=("Entity",))


def _call_close_index(text: str, call_start: int) -> int | None:
    open_idx = text.find("(", call_start)
    if open_idx < 0:
        return None
    depth = 0
    in_string = False
    i = open_idx
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _odata_navigation_record_after_call(expression: str, call_start: int) -> dict[str, str]:
    close_idx = _call_close_index(expression, call_start)
    if close_idx is None:
        return {}
    suffix = expression[close_idx + 1 :].lstrip()
    if not suffix.startswith("{"):
        return {}
    return _odata_navigation_record_from_expression(suffix)


def _navigation_record_for_step(step_id: str, dependents: Mapping[str, list[Any]]) -> dict[str, str]:
    for dep_step in dependents.get(step_id, []):
        out = _navigation_record_from_expression(str(getattr(dep_step, "expression", "")))
        if out:
            return out
    return {}


def _navigation_steps_for_step(step_id: str, dependents: Mapping[str, list[Any]]) -> list[Any]:
    out: list[Any] = []
    for dep_step in dependents.get(step_id, []):
        expression = str(getattr(dep_step, "expression", "") or "")
        if _navigation_record_from_expression(expression):
            out.append(dep_step)
    return out


def _odata_navigation_record_for_step(step_id: str, dependents: Mapping[str, list[Any]]) -> dict[str, str]:
    for dep_step in dependents.get(step_id, []):
        out = _odata_navigation_record_from_expression(str(getattr(dep_step, "expression", "")))
        if out:
            return out
    return {}


def _sql_navigation_block(navigation: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    schema = navigation.get("schema")
    item = navigation.get("item")
    kind = navigation.get("kind")
    navigation_field = navigation.get("navigation_field")
    if schema:
        out["schema"] = schema
    if item:
        out["table_name"] = item
    if kind:
        out["kind"] = kind
    if navigation_field:
        out["navigation_field"] = navigation_field
    return out


def _sql_navigation_from_expression(expression: str) -> dict[str, str]:
    return _sql_navigation_block(_navigation_record_from_expression(expression))


def _sql_navigation_for_step(step_id: str, dependents: Mapping[str, list[Any]]) -> dict[str, str]:
    return _sql_navigation_block(_navigation_record_for_step(step_id, dependents))


def _file_type_for_step(path: str, step_id: str, dependents: Mapping[str, list[Any]]) -> tuple[str, Any | None]:
    ext_type = _EXT_TO_TYPE.get(os.path.splitext(path)[1].lower())
    document_type, document_step = _document_type_for_step(step_id, dependents)
    return (ext_type or document_type or "file"), document_step


def _sql_database_options(record_text: str | None) -> dict[str, Any]:
    if not record_text:
        return {}
    out: dict[str, Any] = {}
    query_match = re.search(r'\bQuery\s*=\s*("(?:[^"]|"")*")', record_text, flags=re.IGNORECASE)
    if query_match:
        query = _m_string(query_match.group(1))
        if query is not None:
            out["native_query_sql"] = query
            out["native_query_kind"] = "Sql.Database option Query"
    folding_match = re.search(r'\bEnableFolding\s*=\s*(true|false)', record_text, flags=re.IGNORECASE)
    if folding_match:
        out["enable_folding"] = folding_match.group(1).lower() == "true"
    return out


def _balanced_record_after(text: str, start: int) -> str | None:
    idx = text.find("[", start)
    if idx < 0:
        return None
    depth = 0
    in_string = False
    i = idx
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[idx : i + 1]
        i += 1
    return None


def _record_keys(record_text: str, field: str) -> list[str]:
    match = re.search(rf"\b{re.escape(field)}\s*=\s*\[([\s\S]*?)\]", record_text, flags=re.IGNORECASE)
    if not match:
        return []
    return sorted({key for key in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=", match.group(1))})


def _web_contents_options(text: str, match_end: int) -> dict[str, Any]:
    record = _balanced_record_after(text, match_end)
    if not record:
        return {}
    out: dict[str, Any] = {}
    relative_match = re.search(r'\bRelativePath\s*=\s*("(?:[^"]|"")*")', record, flags=re.IGNORECASE)
    if relative_match:
        value = _m_string(relative_match.group(1))
        if value is not None:
            out["relative_path"] = value
    query_keys = _record_keys(record, "Query")
    if query_keys:
        out["query_keys"] = query_keys
    header_keys = _record_keys(record, "Headers")
    if header_keys:
        out["header_keys"] = header_keys
        out["has_headers"] = True
    api_key_match = re.search(r'\bApiKeyName\s*=\s*("(?:[^"]|"")*")', record, flags=re.IGNORECASE)
    if api_key_match:
        key_name = _m_string(api_key_match.group(1))
        if key_name:
            out["api_key_name"] = key_name
            out["auth_kind"] = "api_key"
            out["_credential_required"] = True
    if any(key.lower() in {"authorization", "apikey", "api_key", "x-api-key"} for key in header_keys):
        out["auth_kind"] = out.get("auth_kind") or "header"
        out["_credential_required"] = True
    if out:
        out["options_preserved"] = True
    return out


def _firewall_partition(source_type: str, block: dict[str, Any], raw_function: str) -> str:
    policy = _policy(source_type)
    identity = str(
        block.get("path")
        or block.get("url")
        or block.get("connection_string")
        or block.get("server")
        or block.get("account")
        or block.get("database")
        or block.get("mailbox")
        or block.get("function")
        or block.get("type")
        or raw_function
    )
    return f"{policy.get('privacy_level') or 'unknown'}:{source_type}:{identity}"


def _binding_step_ids(mapping: MSourceMapping, raw_m: str) -> list[str]:
    try:
        steps, _result_expression, _functions, _diagnostics = parse_m_query(raw_m)
    except Exception:
        return []
    raw_function = str(mapping.raw_function or "").lower()
    tokens: list[str] = []
    for key in (
        "path",
        "url",
        "connection_string",
        "server",
        "database",
        "account",
        "mailbox",
        "workspace_id",
        "dataflow_id",
        "item",
        "name",
        "table_name",
    ):
        value = mapping.source_block.get(key)
        if isinstance(value, str) and value:
            tokens.append(value.lower())
    out: list[str] = []
    for step in steps:
        step_id = str(getattr(step, "id", "") or "")
        expression = str(getattr(step, "expression", "") or "")
        haystack = expression.lower()
        functions = [str(fn).lower() for fn in getattr(step, "functions", []) or []]
        if raw_function and (raw_function in functions or raw_function in haystack):
            out.append(step_id)
            continue
        if any(token and token in haystack for token in tokens):
            out.append(step_id)
    return [step_id for step_id in out if step_id]


def _navigation_chain_from_block(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    record = {key: block[key] for key in sorted(_NAVIGATION_SOURCE_BLOCK_KEYS) if key in block}
    if not record:
        return []
    navigation_field = str(record.pop("navigation_field", "") or "")
    item: dict[str, Any] = {
        "kind": "record_navigation",
        "record": record,
    }
    if navigation_field:
        item["field"] = navigation_field
    return [item]


def _schema_probe_candidate(mapping: MSourceMapping, source_step_ids: Sequence[str]) -> dict[str, Any] | None:
    source_type = str(mapping.source_type or "")
    connector_id = str(mapping.connector_id or "")
    if source_type not in _SCHEMA_PROBE_SOURCE_TYPES and not connector_id:
        return None
    strategy = "adapter"
    if connector_id == "local_file":
        strategy = "local_file"
    elif connector_id == "local_folder":
        strategy = "local_folder"
    elif source_type in {"sql", "odbc", "odata", "sharepoint", "salesforce"}:
        strategy = "connector_adapter"
    elif source_type == "query_reference":
        strategy = "query_graph"
    return {
        "status": "candidate",
        "strategy": strategy,
        "source_step_id": source_step_ids[0] if source_step_ids else None,
        "connector_id": connector_id or None,
        "requires_credentials": bool(mapping.credential_required),
    }


def _steps_by_id(raw_m: str) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    try:
        steps, _result_expression, _functions, _diagnostics = parse_m_query(raw_m)
    except Exception:
        return {}, {}
    return {str(getattr(step, "id", "") or ""): step for step in steps}, _step_dependency_map(steps)


def _binding_chain(step_ids: Sequence[str], steps_by_id: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step_id in step_ids:
        step = steps_by_id.get(step_id)
        if step is None:
            continue
        out.append({
            "step_id": step_id,
            "operation": str(getattr(step, "operation", "") or ""),
            "dependencies": list(getattr(step, "dependencies", []) or []),
        })
    return out


def _navigation_step_dicts(step_ids: Sequence[str], steps_by_id: Mapping[str, Any], dependents: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    nav_steps: list[Any] = []
    seen: set[str] = set()
    for step_id in step_ids:
        step = steps_by_id.get(step_id)
        if step is not None and str(getattr(step, "operation", "") or "") == "Navigation":
            nav_steps.append(step)
        nav_steps.extend(_navigation_steps_for_step(step_id, dependents))
    out: list[dict[str, Any]] = []
    for step in nav_steps:
        step_id = str(getattr(step, "id", "") or "")
        if not step_id or step_id in seen:
            continue
        seen.add(step_id)
        out.append({
            "step_id": step_id,
            "dependencies": list(getattr(step, "dependencies", []) or []),
            "navigation": _navigation_record_from_expression(str(getattr(step, "expression", "") or "")),
        })
    return out


def _source_binding_from_mapping(mapping: MSourceMapping, raw_m: str, index: int) -> MSourceBinding:
    step_ids = _binding_step_ids(mapping, raw_m)
    steps_by_id, dependents = _steps_by_id(raw_m)
    source_step_id = step_ids[0] if step_ids else None
    source_block = dict(mapping.source_block or {})
    credential_profile_id = source_block.get("credential_profile_id")
    if not isinstance(credential_profile_id, str) or not credential_profile_id:
        credential_profile_id = None
    binding_id_parts = [
        str(mapping.source_type or "unknown"),
        str(index + 1),
        str(source_step_id or mapping.raw_function or "source"),
    ]
    return MSourceBinding(
        binding_id=":".join(part.replace(" ", "_") for part in binding_id_parts),
        source_type=mapping.source_type,
        source_block=source_block,
        raw_function=mapping.raw_function,
        source_step_id=source_step_id,
        source_step_ids=step_ids,
        binding_chain=_binding_chain(step_ids, steps_by_id),
        navigation_steps=_navigation_step_dicts(step_ids, steps_by_id, dependents),
        connector_id=mapping.connector_id,
        credential_profile_id=credential_profile_id,
        privacy_level=mapping.privacy_level,
        privacy_partition=mapping.firewall_partition,
        firewall_partition=mapping.firewall_partition,
        navigation_chain=_navigation_chain_from_block(source_block),
        schema_probe_candidate=_schema_probe_candidate(mapping, step_ids),
        confidence=mapping.confidence,
        reason=mapping.reason,
        folding_status=mapping.folding_status,
    )


def _m_identifier_reference(expression: str) -> str | None:
    text = (expression or "").strip()
    if not text:
        return None
    if text.startswith('#"') and text.endswith('"'):
        value = text[2:-1].replace('""', '"').strip()
        return value or None
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", text) and text.lower() not in {"true", "false", "null", "each"}:
        return text
    return None


def _query_reference_bindings_from_m(raw_m: str, mapped_step_ids: set[str]) -> list[MSourceBinding]:
    try:
        steps, _result_expression, _functions, _diagnostics = parse_m_query(raw_m)
    except Exception:
        return []
    steps_by_id = {str(getattr(step, "id", "") or ""): step for step in steps}
    current_ids = {step_id.upper() for step_id in steps_by_id}
    dependents = _step_dependency_map(steps)
    out: list[MSourceBinding] = []
    for step in steps:
        step_id = str(getattr(step, "id", "") or "")
        if not step_id or step_id in mapped_step_ids:
            continue
        query_id = _m_identifier_reference(str(getattr(step, "expression", "") or ""))
        if not query_id or query_id.upper() in current_ids:
            continue
        block: dict[str, Any] = {
            "type": "query_reference",
            "query_id": query_id,
        }
        block.update(_navigation_record_for_step(step_id, dependents))
        nav_steps = _navigation_step_dicts([step_id], steps_by_id, dependents)
        source_step_ids = [step_id, *[str(item.get("step_id") or "") for item in nav_steps if item.get("step_id")]]
        source_step_ids = [item for item in dict.fromkeys(source_step_ids) if item]
        partition = f"query_reference:{query_id}"
        out.append(MSourceBinding(
            binding_id=f"query_reference:{len(out) + 1}:{step_id}",
            source_type="query_reference",
            source_block=block,
            raw_function="Query.Reference",
            source_step_id=step_id,
            source_step_ids=source_step_ids,
            binding_chain=_binding_chain(source_step_ids, steps_by_id),
            navigation_steps=nav_steps,
            query_references=[{"step_id": step_id, "query_id": query_id, "kind": "query_reference"}],
            connector_id="query_reference",
            privacy_level="inherited",
            privacy_partition=partition,
            firewall_partition=partition,
            navigation_chain=_navigation_chain_from_block(block),
            schema_probe_candidate={
                "status": "candidate",
                "strategy": "query_graph",
                "source_step_id": step_id,
                "connector_id": "query_reference",
                "requires_credentials": False,
            },
            confidence="high",
            reason="Mapped parser-backed external query reference and downstream navigation metadata when present.",
            folding_status="query_graph_resolution_required",
        ))
    return out


def _mapping(
    *,
    source_type: str,
    source_block: dict[str, Any],
    confidence: str,
    reason: str,
    raw_function: str,
) -> MSourceMapping:
    policy = _policy(source_type)
    block = dict(source_block)
    credential_required = bool(policy.get("credential_required")) or bool(block.pop("_credential_required", False))
    return MSourceMapping(
        source_type=source_type,
        source_block=block,
        confidence=confidence,
        reason=reason,
        raw_function=raw_function,
        connector_id=str(policy.get("connector_id") or ""),
        privacy_level=str(policy.get("privacy_level") or ""),
        credential_required=credential_required,
        pushdown_support=str(policy.get("pushdown_support") or ""),
        folding_status=str(policy.get("folding_status") or ""),
        firewall_partition=_firewall_partition(source_type, block, raw_function),
    )


def _file_type(path: str, raw_m: str) -> str:
    hints = [
        (r"\bCsv\.Document\b", "csv"),
        (r"\bExcel\.Workbook\b", "excel"),
        (r"\bJson\.Document\b", "json"),
        (r"\bXml\.Tables\b", "xml"),
        (r"\bParquet\.Document\b", "parquet"),
    ]
    for pattern, source_type in hints:
        if re.search(pattern, raw_m, re.IGNORECASE):
            return source_type
    return _EXT_TO_TYPE.get(os.path.splitext(path)[1].lower(), "file")


def map_sources_from_m(raw_m: str) -> list[MSourceMapping]:
    text = raw_m or ""
    if not text.strip():
        return []

    mappings: list[MSourceMapping] = []
    steps, _result_expression, _functions, _diagnostics = parse_m_query(text)
    dependents = _step_dependency_map(steps)

    for step in steps:
        expression = str(getattr(step, "expression", ""))
        function_name, args = "", []
        call = _direct_call(expression)
        if call:
            function_name, args = call
        function_upper = function_name.upper()

        if function_upper == "FILE.CONTENTS" and args:
            path = _m_string(args[0])
            if path:
                source_type, document_step = _file_type_for_step(path, str(getattr(step, "id", "")), dependents)
                block: dict[str, Any] = {"type": source_type, "path": path}
                document_expression = str(getattr(document_step, "expression", "")) if document_step is not None else ""
                if source_type == "csv" and (_TSV_DELIMITER_RE.search(document_expression) or _TSV_DELIMITER_RE.search(expression)):
                    block["delimiter"] = "\t"
                if source_type == "excel" and document_step is not None:
                    block.update(_navigation_record_for_step(str(getattr(document_step, "id", "")), dependents))
                mappings.append(_mapping(
                    source_type=source_type,
                    source_block=block,
                    confidence="high",
                    reason="Mapped static File.Contents path, dependent document function or extension, and simple workbook navigation when present.",
                    raw_function="File.Contents",
                ))
        else:
            for file_match in _iter_code_matches(_FILE_CONTENTS_RE, expression):
                path = file_match.group(1)
                source_type = _file_type(path, expression)
                block: dict[str, Any] = {"type": source_type, "path": path}
                if source_type == "csv" and _TSV_DELIMITER_RE.search(expression):
                    block["delimiter"] = "\t"
                if source_type == "excel":
                    block.update(_navigation_record_for_step(str(getattr(step, "id", "")), dependents))
                mappings.append(_mapping(
                    source_type=source_type,
                    source_block=block,
                    confidence="high",
                    reason="Mapped nested File.Contents path from a document-reader expression or file extension, with simple workbook navigation when present.",
                    raw_function="File.Contents",
                ))

        if function_upper in {"FOLDER.FILES", "FOLDER.CONTENTS"} and args:
            path = _m_string(args[0])
            if path:
                kind = function_name.split(".", 1)[1]
                raw_function = f"Folder.{kind}"
                mappings.append(_mapping(
                    source_type="folder",
                    source_block={
                        "type": "folder",
                        "path": path,
                        "mode": kind.lower(),
                        "recursive": kind.lower() == "files",
                        "include_folders": kind.lower() == "contents",
                    },
                    confidence="medium",
                    reason=f"Mapped {raw_function} path; combine-file helper queries must remain preserved.",
                    raw_function=raw_function,
                ))

        if function_upper == "SQL.DATABASE" and len(args) >= 2:
            connection = _m_string(args[0])
            database = _m_string(args[1])
            if connection and database:
                block = {"type": "sql", "connection_string": connection, "database": database}
                block.update(_sql_database_options(args[2] if len(args) > 2 else None))
                navigation = _sql_navigation_from_expression(expression)
                if not navigation:
                    navigation = _sql_navigation_for_step(str(getattr(step, "id", "")), dependents)
                if navigation and "native_query_sql" not in block:
                    block.update(navigation)
                mappings.append(_mapping(
                    source_type="sql",
                    source_block=block,
                    confidence="high" if navigation else "medium",
                    reason="Mapped Sql.Database server/database, parser-backed navigation item, and native Query option when present.",
                    raw_function="Sql.Database",
                ))
        else:
            for sql_match in _iter_code_matches(_SQL_DATABASE_RE, expression):
                block = {
                    "type": "sql",
                    "connection_string": sql_match.group(1),
                    "database": sql_match.group(2),
                }
                block.update(_sql_database_options(sql_match.group(3)))
                navigation = _sql_navigation_from_expression(expression)
                if navigation and "native_query_sql" not in block:
                    block.update(navigation)
                mappings.append(_mapping(
                    source_type="sql",
                    source_block=block,
                    confidence="high" if navigation else "medium",
                    reason="Mapped nested Sql.Database server/database and parser-backed navigation item when present.",
                    raw_function="Sql.Database",
                ))

        if function_upper == "ODBC.DATASOURCE" and args:
            value = _m_string(args[0])
            if value:
                block = {"type": "odbc", "connection_string": value}
                block.update(_navigation_record_from_expression(expression))
                block.update(_navigation_record_for_step(str(getattr(step, "id", "")), dependents))
                mappings.append(_mapping(
                    source_type="odbc",
                    source_block=block,
                    confidence="high" if len(block) > 2 else "medium",
                    reason="Mapped Odbc.DataSource connection string and simple navigation metadata when present.",
                    raw_function="Odbc.DataSource",
                ))
        else:
            for odbc_match in _iter_code_matches(_ODBC_RE, expression):
                block = {"type": "odbc", "connection_string": odbc_match.group(1)}
                block.update(_navigation_record_from_expression(expression))
                mappings.append(_mapping(
                    source_type="odbc",
                    source_block=block,
                    confidence="high" if len(block) > 2 else "medium",
                    reason="Mapped nested Odbc.DataSource connection string and simple navigation metadata when present.",
                    raw_function="Odbc.DataSource",
                ))
        if function_upper == "ODATA.FEED" and args:
            value = _m_string(args[0])
            if value:
                block = {"type": "odata", "url": value}
                block.update(_odata_navigation_record_from_expression(expression))
                block.update(_odata_navigation_record_for_step(str(getattr(step, "id", "")), dependents))
                mappings.append(_mapping(
                    source_type="odata",
                    source_block=block,
                    confidence="high",
                    reason="Mapped OData.Feed URL and simple entity navigation metadata when present.",
                    raw_function="OData.Feed",
                ))
        else:
            for odata_match in _iter_code_matches(_ODATA_RE, expression):
                block = {"type": "odata", "url": odata_match.group(1)}
                block.update(_odata_navigation_record_after_call(expression, odata_match.start()))
                mappings.append(_mapping(
                    source_type="odata",
                    source_block=block,
                    confidence="high",
                    reason="Mapped nested OData.Feed URL and simple entity navigation metadata when present.",
                    raw_function="OData.Feed",
                ))
        if function_upper == "WEB.CONTENTS" and args:
            value = _m_string(args[0])
            if value:
                block = {"type": "web", "url": value}
                block.update(_web_contents_options(expression, expression.find("(")))
                mappings.append(_mapping(
                    source_type="web",
                    source_block=block,
                    confidence="medium",
                    reason="Mapped Web.Contents URL and redacted option metadata; raw option values stay preserved only in raw M.",
                    raw_function="Web.Contents",
                ))
        else:
            for web_match in _iter_code_matches(_WEB_RE, expression):
                block = {"type": "web", "url": web_match.group(1)}
                block.update(_web_contents_options(expression, web_match.end()))
                mappings.append(_mapping(
                    source_type="web",
                    source_block=block,
                    confidence="medium",
                    reason="Mapped nested Web.Contents URL and redacted option metadata; raw option values stay preserved only in raw M.",
                    raw_function="Web.Contents",
                ))
        if function_upper in {"SHAREPOINT.FILES", "SHAREPOINT.TABLES"} and args:
            value = _m_string(args[0])
            if value:
                kind = function_name.split(".", 1)[1]
                block = {"type": "sharepoint", "url": value, "kind": kind.lower()}
                block.update(_navigation_record_from_expression(expression))
                block.update(_navigation_record_for_step(str(getattr(step, "id", "")), dependents))
                mappings.append(_mapping(
                    source_type="sharepoint",
                    source_block=block,
                    confidence="high" if len(block) > 3 else "medium",
                    reason="Mapped SharePoint resource URL and simple navigation metadata when present; authentication remains an explicit compatibility item.",
                    raw_function=f"SharePoint.{kind}",
                ))
        else:
            for sp_match in _iter_code_matches(_SHAREPOINT_RE, expression):
                block = {"type": "sharepoint", "url": sp_match.group(2), "kind": sp_match.group(1).lower()}
                block.update(_navigation_record_from_expression(expression))
                mappings.append(_mapping(
                    source_type="sharepoint",
                    source_block=block,
                    confidence="high" if len(block) > 3 else "medium",
                    reason="Mapped nested SharePoint resource URL and simple navigation metadata when present; authentication remains an explicit compatibility item.",
                    raw_function=f"SharePoint.{sp_match.group(1)}",
                ))

        generic_source = _GENERIC_SOURCE_FUNCTIONS.get(function_upper)
        if generic_source is not None:
            canonical_name, source_type = generic_source
            block = _generic_source_block(function_upper, canonical_name, source_type, args)
            block.update(_navigation_record_from_expression(expression))
            block.update(_navigation_record_for_step(str(getattr(step, "id", "")), dependents))
            mappings.append(_mapping(
                source_type=source_type,
                source_block=block,
                confidence="medium",
                reason=(
                    f"Preserved {canonical_name} connector metadata for the source-map lane; "
                    "adapter execution still requires connector credentials, privacy review, and folding capability checks."
                ),
                raw_function=canonical_name,
            ))

    return mappings


def map_source_from_m(raw_m: str) -> Optional[MSourceMapping]:
    sources = map_sources_from_m(raw_m)
    return sources[0] if sources else None


def map_source_bindings_from_m(raw_m: str) -> list[MSourceBinding]:
    bindings = [_source_binding_from_mapping(mapping, raw_m, idx) for idx, mapping in enumerate(map_sources_from_m(raw_m))]
    mapped_step_ids = {
        step_id
        for binding in bindings
        for step_id in binding.source_step_ids
    }
    bindings.extend(_query_reference_bindings_from_m(raw_m, mapped_step_ids))
    return bindings
