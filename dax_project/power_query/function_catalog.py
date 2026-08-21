from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from .adapters import build_runtime_adapter_descriptor
from .expression_sql import _FUNCTION_RENDERERS
from .registry import (
    C0_PRESERVED,
    C2_MAPPED,
    C3_EXECUTABLE,
    _CONSTRUCTOR_FUNCTIONS,
    _EVALUATOR_FUNCTIONS,
    _FOLDABLE_TABLE_FUNCTIONS,
    _NATIVE_QUERY_FUNCTIONS,
    _PRESERVE_ONLY_FUNCTIONS,
    _SOURCE_FUNCTIONS,
    get_function_metadata,
)


_OFFICIAL_INVENTORY_PATH = Path(__file__).with_name("official_function_inventory.json")

_LOCAL_FILE_SOURCE_SQL = {
    "Csv.Document": "DuckDB CSV scan lane when fed by static File.Contents/Folder binary content.",
    "Excel.Workbook": "Local workbook preview lane; DuckDB SQL pushdown is not the primary execution path.",
    "File.Contents": "Source binary/path binding; downstream document reader chooses the execution lane.",
    "Folder.Contents": "Local folder inventory lane; SQL pushdown is not used for file inventory itself.",
    "Folder.Files": "Local folder inventory lane; downstream file helpers may preview locally.",
    "Json.Document": "DuckDB JSON scan lane for static JSON file sources, local evaluator for binary/list/record payloads.",
    "Parquet.Document": "DuckDB parquet scan lane when path/options are static.",
    "Xml.Tables": "Local XML table-shaping evaluator; connector SQL pushdown is not applicable.",
}

_CONNECTOR_SOURCE_SQL = {
    "Sql.Database": "Connector-native SQL/source adapter lane; DuckDB may coordinate local DirectQuery views but does not translate this source call by itself.",
    "Odbc.DataSource": "Connector-native ODBC adapter lane; execution requires credential/profile binding.",
    "OData.Feed": "Connector-native OData adapter lane; query folding depends on service capabilities.",
    "Web.Contents": "Connector/source request lane with credential/privacy review; downstream document reader determines preview shape.",
    "SharePoint.Files": "Connector-native SharePoint adapter lane; folder/file metadata can be preserved before adapter execution.",
    "SharePoint.Tables": "Connector-native SharePoint adapter lane; table navigation metadata is preserved before adapter execution.",
}

_LOCAL_DOCUMENT_SUPPORT = {
    "File.Contents",
    "Folder.Contents",
    "Folder.Files",
    "Csv.Document",
    "Excel.CurrentWorkbook",
    "Excel.Workbook",
    "Json.Document",
    "Parquet.Document",
    "Pdf.Tables",
    "RData.FromBinary",
}

_RELATIONAL_CONNECTOR_SUPPORT = {
    "Access.Database",
    "AdoDotNet.DataSource",
    "DB2.Database",
    "Informix.Database",
    "MySQL.Database",
    "Odbc.DataSource",
    "OleDb.DataSource",
    "Oracle.Database",
    "PostgreSQL.Database",
    "SapHana.Database",
    "Sql.Database",
    "Sql.Databases",
    "Sybase.Database",
    "Teradata.Database",
}

_CLOUD_STORAGE_LAKE_SUPPORT = {
    "AzureStorage.BlobContents",
    "AzureStorage.Blobs",
    "AzureStorage.DataLake",
    "AzureStorage.DataLakeContents",
    "AzureStorage.Tables",
    "Cdm.Contents",
    "DeltaLake.Metadata",
    "DeltaLake.Table",
    "Hdfs.Contents",
    "Hdfs.Files",
    "HdInsight.Containers",
    "HdInsight.Contents",
    "HdInsight.Files",
}

_WEB_SAAS_API_SUPPORT = {
    "ActiveDirectory.Domains",
    "AdobeAnalytics.Cubes",
    "Exchange.Contents",
    "GoogleAnalytics.Accounts",
    "OData.Feed",
    "Salesforce.Data",
    "Salesforce.Reports",
    "SharePoint.Contents",
    "SharePoint.Files",
    "SharePoint.Tables",
    "Soda.Feed",
    "Web.BrowserContents",
    "Web.Contents",
    "Web.Page",
    "WebAction.Request",
}

_SEMANTIC_CUBE_SUPPORT = {
    "AnalysisServices.Database",
    "AnalysisServices.Databases",
    "Essbase.Cubes",
    "SapBusinessWarehouse.Cubes",
    "Cube.AddAndExpandDimensionColumn",
    "Cube.AddMeasureColumn",
    "Cube.ApplyParameter",
    "Cube.AttributeMemberId",
    "Cube.AttributeMemberProperty",
    "Cube.CollapseAndRemoveColumns",
    "Cube.Dimensions",
    "Cube.DisplayFolders",
    "Cube.MeasureProperties",
    "Cube.MeasureProperty",
    "Cube.Measures",
    "Cube.Parameters",
    "Cube.Properties",
    "Cube.PropertyKey",
    "Cube.ReplaceDimensions",
    "Cube.Transform",
    "FabricAI.Prompt",
    "PowerBI.Dataflows",
}

_SUPPORT_TRACK_REQUIREMENTS = {
    "local_document": [
        "complete option parsing",
        "source navigation binding",
        "preview/load execution",
        "refresh integration",
        "binary/content and culture/encoding fixtures",
    ],
    "relational_connector": [
        "credential/profile binding",
        "table/schema navigation",
        "column inference",
        "preview/load execution via DuckDB extension or Python adapter",
        "DirectQuery source views and folding flags",
    ],
    "cloud_storage_lake": [
        "auth-mode binding",
        "path/container navigation",
        "file/table listing",
        "format inference",
        "local/direct refresh with privacy partitions",
    ],
    "web_saas_api": [
        "HTTP/client adapter",
        "auth redaction",
        "paging and rate-limit handling",
        "navigation tables",
        "stable no-secret diagnostics",
    ],
    "native_query": [
        "approval state",
        "target credential binding",
        "safe parameter binding",
        "execution audit record",
        "preview/load path with blocked state when unapproved",
    ],
    "semantic_cube": [
        "semantic-source adapter",
        "cube navigation model",
        "measure/dimension materialization",
        "Cube.Transform operation evaluator",
        "XMLA/semantic execution with preserve-only fallback",
    ],
}

_SUPPORT_TRACK_STATUSES = {
    "local_document": "partial_local",
    "relational_connector": "adapter_pending",
    "cloud_storage_lake": "adapter_pending",
    "web_saas_api": "adapter_pending",
    "native_query": "native_review_pending",
    "semantic_cube": "semantic_adapter_pending",
}

_TABLE_TRANSFORM_SQL = {
    "Table.AddColumn": "SELECT *, <row expression> AS <column> when the row expression is lowerable.",
    "Table.AddIndexColumn": "ROW_NUMBER-style index projection in the DuckDB preview emitter.",
    "Table.AggregateTableColumn": "GROUP/aggregate-after-merge SQL candidate for supported nested-join aggregate shapes.",
    "Table.Combine": "UNION ALL BY NAME for compatible branch relations.",
    "Table.Distinct": "SELECT DISTINCT over the current relation.",
    "Table.DuplicateColumn": "Projection with repeated source expression under a new column name.",
    "Table.ExpandListColumn": "UNNEST-style expansion for known-projection list columns.",
    "Table.ExpandRecordColumn": "Projection of known record fields.",
    "Table.ExpandTableColumn": "Join/expand projection for supported nested-join relations.",
    "Table.FillDown": "Window LAST_VALUE IGNORE NULLS-style SQL candidate when ordering and source shape are safe.",
    "Table.FillUp": "Reverse window fill candidate when ordering and source shape are safe.",
    "Table.FirstN": "LIMIT when count predicate is static.",
    "Table.Group": "GROUP BY plus supported List/Table aggregators.",
    "Table.Join": "INNER/OUTER/ANTI JOIN for supported key lists and join kinds.",
    "Table.LastN": "Local evaluator by default; SQL needs deterministic ordering.",
    "Table.NestedJoin": "Join relation plus nested-column metadata; expanded forms can emit SQL.",
    "Table.Pivot": "Conditional aggregate projection for supported value/aggregate shapes.",
    "Table.RemoveColumns": "Projection excluding known columns.",
    "Table.RemoveFirstN": "OFFSET when count predicate is static.",
    "Table.RemoveLastN": "Local evaluator by default; SQL needs deterministic ordering.",
    "Table.RenameColumns": "Projection aliases.",
    "Table.ReorderColumns": "Projection ordering.",
    "Table.ReplaceValue": "CASE/replace expression for supported replacer shapes.",
    "Table.SelectColumns": "Projection of known columns.",
    "Table.SelectRows": "WHERE clause when predicate is row-expression lowerable.",
    "Table.Sort": "ORDER BY for supported sort specs.",
    "Table.TransformColumnNames": "Projection alias rewrite when current projection is known.",
    "Table.TransformColumns": "Projection with supported row-expression transformers.",
    "Table.TransformColumnTypes": "CAST projection with culture metadata preserved.",
    "Table.Unpivot": "UNPIVOT-style reshape for explicit columns.",
    "Table.UnpivotOtherColumns": "UNPIVOT-style reshape for known non-key columns.",
}


def _support_track(name: str) -> str | None:
    if name in _NATIVE_QUERY_FUNCTIONS:
        return "native_query"
    if name in _SEMANTIC_CUBE_SUPPORT:
        return "semantic_cube"
    if name in _LOCAL_DOCUMENT_SUPPORT:
        return "local_document"
    if name in _RELATIONAL_CONNECTOR_SUPPORT:
        return "relational_connector"
    if name in _CLOUD_STORAGE_LAKE_SUPPORT:
        return "cloud_storage_lake"
    if name in _WEB_SAAS_API_SUPPORT:
        return "web_saas_api"
    return None


def _support_plan(name: str) -> dict[str, Any]:
    track = _support_track(name)
    if track is None:
        return {
            "support_status": "supported",
            "support_track": "supported",
            "required_to_support": [],
            "first_acceptance_test": "",
        }
    if _compatibility_level(name) == C3_EXECUTABLE:
        return {
            "support_status": "supported",
            "support_track": track,
            "required_to_support": [],
            "first_acceptance_test": f"test_power_query_supports_{_test_slug(name)}",
        }
    return {
        "support_status": _SUPPORT_TRACK_STATUSES[track],
        "support_track": track,
        "required_to_support": list(_SUPPORT_TRACK_REQUIREMENTS[track]),
        "first_acceptance_test": f"test_power_query_supports_{_test_slug(name)}",
    }


def _test_slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or "")).strip("_")


def _all_catalog_function_names() -> list[str]:
    names = (
        set(_SOURCE_FUNCTIONS)
        | set(_FOLDABLE_TABLE_FUNCTIONS)
        | set(_CONSTRUCTOR_FUNCTIONS)
        | set(_EVALUATOR_FUNCTIONS)
        | set(_NATIVE_QUERY_FUNCTIONS)
        | set(_PRESERVE_ONLY_FUNCTIONS)
        | {item["name"] for item in official_function_inventory()}
    )
    return sorted(names, key=str.upper)


@lru_cache(maxsize=1)
def official_function_inventory() -> tuple[dict[str, Any], ...]:
    if not _OFFICIAL_INVENTORY_PATH.exists():
        return ()
    try:
        raw = json.loads(_OFFICIAL_INVENTORY_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return ()
    functions = raw.get("functions") if isinstance(raw, dict) else None
    if not isinstance(functions, list):
        return ()
    out: list[dict[str, Any]] = []
    for item in functions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "category": str(item.get("category") or "").strip() or name.split(".", 1)[0],
                "description": str(item.get("description") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "source_slug": str(item.get("source_slug") or "").strip(),
            }
        )
    return tuple(sorted(out, key=lambda item: item["name"].upper()))


@lru_cache(maxsize=1)
def _official_by_name() -> dict[str, dict[str, Any]]:
    return {item["name"].upper(): item for item in official_function_inventory()}


def _compatibility_level(name: str) -> str:
    c3_names = (
        set(_FOLDABLE_TABLE_FUNCTIONS)
        | set(_CONSTRUCTOR_FUNCTIONS)
        | set(_EVALUATOR_FUNCTIONS)
        | set(_SOURCE_FUNCTIONS)
        | set(_NATIVE_QUERY_FUNCTIONS)
        | set(_PRESERVE_ONLY_FUNCTIONS)
    )
    if name in c3_names:
        return C3_EXECUTABLE
    meta = get_function_metadata(name)
    return meta.compatibility_level if meta is not None else C0_PRESERVED


def _execution_lane(name: str) -> str:
    if name in _PRESERVE_ONLY_FUNCTIONS:
        return "preserve_only"
    if name in _NATIVE_QUERY_FUNCTIONS:
        return "native_query_review"
    if name in _CONSTRUCTOR_FUNCTIONS:
        return "literal_constructor"
    if name in _EVALUATOR_FUNCTIONS:
        return "local_evaluator"
    if name in _FOLDABLE_TABLE_FUNCTIONS:
        return "neutral_transform_ast"
    if name in _SOURCE_FUNCTIONS:
        return "source_map"
    if name.upper() in _official_by_name():
        return "unimplemented_official"
    return "unsupported"


def _missing_official_duckdb_policy(name: str, category: str) -> str:
    upper_name = name.upper()
    if category == "Accessing data":
        return "Connector/source adapter lane; not a generic DuckDB scalar translation. Local DuckDB may coordinate only after adapter credentials/navigation are implemented."
    if name.startswith("Cube.") or name.startswith("AnalysisServices.") or name.startswith("PowerBI."):
        return "Semantic-source adapter lane for cube/dataflow metadata and measures; preserve until adapter execution is implemented."
    if name.startswith("Table."):
        if "Fuzzy" in name:
            return "Local evaluator first; optional future DuckDB fuzzy matching extension only after Power Query threshold/culture semantics are proven."
        if name in {"Table.View", "Table.ViewError", "Table.ViewFunction", "Table.WithErrorContext"}:
            return "Functional handler/view runtime lane; no generic SQL equivalent."
        if name in {"Table.FirstValue", "Table.ApproximateRowCount", "Table.HasColumns", "Table.IsDistinct", "Table.MatchesAllRows"}:
            return "Local evaluator first; SQL equivalent possible for specific source/schema shapes."
        return "Table-transform AST lane candidate; DuckDB equivalent must be expressed as relational algebra, not one scalar function."
    if name.startswith("List."):
        return "Local evaluator first; SQL equivalent only when embedded in a foldable aggregate/window/list-literal pattern."
    if category in {"Text", "Number", "Date", "DateTime", "DateTimeZone", "Duration", "Time", "Logical", "Uri", "Lines", "Binary"}:
        return "Local evaluator first; DuckDB row-expression renderer possible for deterministic culture/timezone/encoding-safe overloads."
    if category in {"Combiner", "Comparer", "Replacer", "Splitter"}:
        return "Function-value helper lane used by table/list transforms; lower only when passed to a supported transform shape."
    if category in {"Record", "Value", "Type", "Expression", "Function values", "Error"}:
        return "Local M runtime/meta/type/error lane; SQL equivalent only for narrow patterns, otherwise not a relational operation."
    if upper_name.startswith("ITEMEXPRESSION.") or upper_name.startswith("ROWEXPRESSION."):
        return "Expression AST helper lane; preserve/interpret for folding analysis, not direct DuckDB SQL."
    return "No mapped DuckDB policy yet; classify before implementation."


def _duckdb_sql_equivalent(name: str) -> str:
    official = _official_by_name().get(name.upper())
    category = str((official or {}).get("category") or "").strip()
    if name in _FUNCTION_RENDERERS:
        return "DuckDB row-expression renderer implemented for supported argument shapes."
    if name in _TABLE_TRANSFORM_SQL:
        return _TABLE_TRANSFORM_SQL[name]
    if name in _FOLDABLE_TABLE_FUNCTIONS:
        return "Neutral table-transform AST candidate; DuckDB emission depends on argument/schema support."
    if name in _LOCAL_FILE_SOURCE_SQL:
        return _LOCAL_FILE_SOURCE_SQL[name]
    if name in _CONNECTOR_SOURCE_SQL:
        return _CONNECTOR_SOURCE_SQL[name]
    if name in _NATIVE_QUERY_FUNCTIONS:
        return "Native SQL is preserved/reviewed; not generated from M and not auto-rewritten to DuckDB SQL."
    if name in _PRESERVE_ONLY_FUNCTIONS:
        return "No generic DuckDB SQL equivalent; requires connector/semantic-source adapter."
    if name in _CONSTRUCTOR_FUNCTIONS:
        return "Literal/local value constructor; may feed source-less table SQL when the constructed value is tabular."
    if name in _EVALUATOR_FUNCTIONS:
        return "Local evaluator implementation; SQL pushdown is not guaranteed unless a separate row/table renderer exists."
    if official is not None:
        return _missing_official_duckdb_policy(name, category)
    return "No mapped DuckDB equivalent yet."


def _risk_note(name: str) -> str:
    official = _official_by_name().get(name.upper())
    category = str((official or {}).get("category") or "").strip()
    if name in _PRESERVE_ONLY_FUNCTIONS:
        return "Preserve raw M and surface adapter requirement; do not fake execution."
    if name in _NATIVE_QUERY_FUNCTIONS:
        return "Requires credential binding, parameter safety, and native-query approval workflow."
    if name in _SOURCE_FUNCTIONS and name not in _LOCAL_FILE_SOURCE_SQL:
        return "Connector semantics, privacy partitions, credentials, and folding capability must be validated per adapter."
    if name in _FOLDABLE_TABLE_FUNCTIONS and name not in _TABLE_TRANSFORM_SQL:
        return "Recognized as a transform, but exact SQL foldability is argument/schema dependent."
    if name in _FUNCTION_RENDERERS:
        return "Foldable for deterministic row-expression forms; culture/comparer/timezone variants need golden fixtures."
    if name in _EVALUATOR_FUNCTIONS:
        return "Covered for deterministic local-preview semantics; broader overloads still need official-function fixtures."
    if official is not None:
        if category == "Accessing data":
            return "Missing connector adapter; preserve source metadata and block execution until credentials/privacy/folding are implemented."
        if name.startswith("Table."):
            return "Missing table-transform/evaluator coverage; implement with local output fixtures before SQL folding."
        if category in {"Text", "Number", "Date", "DateTime", "DateTimeZone", "Duration", "Time", "Binary"}:
            return "Missing deterministic local fixtures; culture/timezone/encoding overloads must be classified before pushdown."
        return "Official function not implemented in Dummy BI yet; preserve raw M and report explicit unsupported status."
    return "Tracked but needs explicit implementation evidence."


def function_catalog_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    official_by_name = _official_by_name()
    for name in _all_catalog_function_names():
        meta = get_function_metadata(name)
        official = official_by_name.get(name.upper())
        registered = (
            name in _SOURCE_FUNCTIONS
            or name in _FOLDABLE_TABLE_FUNCTIONS
            or name in _CONSTRUCTOR_FUNCTIONS
            or name in _EVALUATOR_FUNCTIONS
            or name in _NATIVE_QUERY_FUNCTIONS
            or name in _PRESERVE_ONLY_FUNCTIONS
        )
        status = "implemented_or_mapped" if registered else "missing_official" if official is not None else "repo_only"
        support_plan = _support_plan(name)
        row = {
            "function": name,
            "category": meta.category if meta is not None else str((official or {}).get("category") or name.split(".", 1)[0]),
            "implementation_status": status,
            "compatibility_level": _compatibility_level(name),
            "execution_lane": _execution_lane(name),
            "registry_execution": meta.execution if meta is not None else "unsupported",
            "official_reference": official is not None,
            "official_description": str((official or {}).get("description") or ""),
            "official_url": str((official or {}).get("url") or ""),
            "source_mapping": name in _SOURCE_FUNCTIONS,
            "foldable_table_transform": name in _FOLDABLE_TABLE_FUNCTIONS,
            "local_evaluator": name in _EVALUATOR_FUNCTIONS or name in _CONSTRUCTOR_FUNCTIONS,
            "literal_constructor": name in _CONSTRUCTOR_FUNCTIONS,
            "duckdb_row_expression": name in _FUNCTION_RENDERERS,
            "native_query_review": name in _NATIVE_QUERY_FUNCTIONS,
            "preserve_only": name in _PRESERVE_ONLY_FUNCTIONS,
            "duckdb_sql_equivalent": _duckdb_sql_equivalent(name),
            "risk": _risk_note(name),
            "notes": meta.notes if meta is not None else "Function is not registered yet.",
            **support_plan,
        }
        row["runtime_adapter"] = build_runtime_adapter_descriptor(row)
        rows.append(row)
    return rows


def function_catalog_summary() -> dict[str, Any]:
    rows = function_catalog_rows()
    official_names = {item["name"].upper() for item in official_function_inventory()}
    registered_names = {
        name.upper()
        for name in (
            set(_SOURCE_FUNCTIONS)
            | set(_FOLDABLE_TABLE_FUNCTIONS)
            | set(_CONSTRUCTOR_FUNCTIONS)
            | set(_EVALUATOR_FUNCTIONS)
            | set(_NATIVE_QUERY_FUNCTIONS)
            | set(_PRESERVE_ONLY_FUNCTIONS)
        )
    }
    levels = Counter(row["compatibility_level"] for row in rows)
    lanes = Counter(row["execution_lane"] for row in rows)
    live_states = Counter(str((row.get("runtime_adapter") or {}).get("live_certification_state") or "not_started") for row in rows)
    live_families = Counter(str(((row.get("runtime_adapter") or {}).get("live_certification") or {}).get("family") or "unknown") for row in rows)
    non_c3_rows = [row for row in rows if row["compatibility_level"] != C3_EXECUTABLE]
    c3_names = {str(row["function"]) for row in rows if row["compatibility_level"] == C3_EXECUTABLE}
    local_evaluator_names = (set(_EVALUATOR_FUNCTIONS) - set(_NATIVE_QUERY_FUNCTIONS)) | set(_CONSTRUCTOR_FUNCTIONS)
    return {
        "official_reference_functions": len(official_names),
        "official_implemented_or_mapped_functions": len(official_names & registered_names),
        "official_missing_functions": len(official_names - registered_names),
        "repo_known_functions": len(registered_names),
        "total_catalog_functions": len(rows),
        "mapped_but_not_fully_supported_functions": len(non_c3_rows),
        "c3_executable_unique": len(c3_names),
        "c2_mapped_or_review_unique": levels.get(C2_MAPPED, 0),
        "c0_preserve_only_unique": levels.get(C0_PRESERVED, 0),
        "local_evaluator_registry_entries": len(_EVALUATOR_FUNCTIONS),
        "local_evaluator_unique": len(local_evaluator_names),
        "foldable_table_functions": len(_FOLDABLE_TABLE_FUNCTIONS),
        "source_mapping_functions": len(_SOURCE_FUNCTIONS),
        "constructor_functions": len(_CONSTRUCTOR_FUNCTIONS),
        "duckdb_row_expression_functions": len(_FUNCTION_RENDERERS),
        "native_query_review_functions": len(_NATIVE_QUERY_FUNCTIONS),
        "preserve_only_functions": len(_PRESERVE_ONLY_FUNCTIONS),
        "by_compatibility_level": dict(sorted(levels.items())),
        "by_execution_lane": dict(sorted(lanes.items())),
        "by_live_certification_state": dict(sorted(live_states.items())),
        "by_live_connector_family": dict(sorted(live_families.items())),
    }


def build_function_coverage_catalog() -> dict[str, Any]:
    return {
        "version": "power_query_function_catalog.v1",
        "summary": function_catalog_summary(),
        "functions": function_catalog_rows(),
    }
