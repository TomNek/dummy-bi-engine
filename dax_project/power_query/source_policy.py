from __future__ import annotations

import re
from typing import Any, Mapping

from .ir import build_ir_args
from .parser import parse_m_query
from .source_map import map_sources_from_m


_PRIVACY_RANK = {
    "public": 1,
    "organizational": 2,
    "private": 3,
    "unknown": 4,
}


def _looks_like_combine_file_invocation(expression: str) -> bool:
    text = expression or ""
    if not re.search(r"\[\s*Content\s*\]", text, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(r"#?\"?Transform\s+File", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:Csv|Json)\.Document\s*\(", text, flags=re.IGNORECASE)
    )


def _looks_like_sample_file_navigation(expression: str) -> bool:
    text = expression or ""
    return bool(re.search(r"\{(?:\s*-?\d+\s*|\s*\[[^\]]+\]\s*)\}\s*\[\s*Content\s*\]", text, flags=re.IGNORECASE | re.DOTALL))


def _firewall_status(levels: set[str], source_count: int) -> str:
    if source_count <= 1:
        return "single_partition"
    if "unknown" in levels:
        return "privacy_review_required"
    ranks = {_PRIVACY_RANK.get(level, 4) for level in levels}
    if len(ranks) <= 1:
        return "compatible_partitions"
    if _PRIVACY_RANK["private"] in ranks:
        return "privacy_review_required"
    return "compatible_partitions"


def build_source_policy_report(raw_m: str) -> dict[str, Any]:
    """Return connector, credential, and privacy metadata for a raw M query.

    This is a conservative metadata model. It does not execute connectors or
    bypass privacy rules; it exposes the source facts that a future credential
    binder, firewall partitioner, and connector-native folding lane need.
    """

    sources = [source.to_dict() for source in map_sources_from_m(raw_m)]
    native_queries: list[dict[str, Any]] = []
    combine_file_patterns: list[dict[str, Any]] = []
    sample_file_navigations: list[dict[str, Any]] = []
    try:
        steps, _result, _functions, _diagnostics = parse_m_query(raw_m)
        for step in steps:
            if str(step.operation or "").strip().upper() == "VALUE.NATIVEQUERY":
                args = build_ir_args("native_query", step.expression)
                native_queries.append(
                    {
                        "step_id": step.id,
                        "target_ref": args.get("target_ref"),
                        "sql": args.get("sql"),
                        "parameters": args.get("parameters") or {"kind": "none", "count": 0},
                        "options": args.get("options") or {},
                    }
                )
            if str(step.operation or "").strip().upper() == "TABLE.ADDCOLUMN" and _looks_like_combine_file_invocation(step.expression):
                combine_file_patterns.append(
                    {
                        "step_id": step.id,
                        "operation": step.operation,
                        "reason": "Potential combine-files helper invocation over [Content]; simple CSV/JSON helpers and imported helper functions can preview locally, while complex generated helper patterns remain preserved until full executable parity lands.",
                    }
                )
            if str(step.operation or "").strip().upper() == "NAVIGATION" and _looks_like_sample_file_navigation(step.expression):
                sample_file_navigations.append(
                    {
                        "step_id": step.id,
                        "operation": step.operation,
                        "reason": "Sample-file navigation over folder [Content] can preview locally when the selected file row is available; connector-native folding and complex binary transforms remain blocked.",
                    }
                )
    except Exception:
        native_queries = []
        combine_file_patterns = []
        sample_file_navigations = []
    for source in sources:
        block = source.get("source_block") if isinstance(source, Mapping) else None
        if not isinstance(block, Mapping) or not block.get("native_query_sql"):
            continue
        native_queries.append(
            {
                "step_id": "",
                "target_ref": "Sql.Database",
                "sql": str(block.get("native_query_sql") or ""),
                "parameters": {"kind": "none", "count": 0},
                "options": {"EnableFolding": block.get("enable_folding")} if "enable_folding" in block else {},
                "source": "Sql.Database option Query",
            }
        )
    levels = {str(source.get("privacy_level") or "unknown") for source in sources}
    partitions = sorted({str(source.get("firewall_partition") or "") for source in sources if source.get("firewall_partition")})
    credential_sources = [source for source in sources if source.get("credential_required")]
    pushdown_ready = [
        source
        for source in sources
        if str(source.get("pushdown_support") or "") == "duckdb_sql_preview"
    ]
    adapter_pending = [
        source
        for source in sources
        if str(source.get("folding_status") or "") in {"connector_adapter_pending", "credential_binding_required"}
    ]
    folder_sources = [
        source
        for source in sources
        if str(source.get("source_type") or "") == "folder"
    ]
    firewall_status = _firewall_status(levels, len(sources))
    events: list[dict[str, Any]] = []
    if credential_sources:
        events.append(
            {
                "code": "PQ_CREDENTIAL_BINDING_REQUIRED",
                "severity": "warning",
                "message": f"{len(credential_sources)} source(s) need connector credentials before native refresh or folding can execute.",
            }
        )
    if adapter_pending:
        events.append(
            {
                "code": "PQ_CONNECTOR_ADAPTER_PENDING",
                "severity": "warning",
                "message": f"{len(adapter_pending)} source(s) are mapped but still need connector/native folding adapters.",
            }
        )
    if firewall_status == "privacy_review_required":
        events.append(
            {
                "code": "PQ_PRIVACY_PARTITIONS",
                "severity": "warning",
                "message": "The query combines different privacy partitions and needs a firewall review before connector-native folding.",
            }
        )
    if native_queries:
        events.append(
            {
                "code": "PQ_NATIVE_QUERY_REVIEW",
                "severity": "warning",
                "message": f"{len(native_queries)} native SQL query step(s) are preserved but require approved connector execution and safe parameter binding before refresh.",
            }
        )
    if folder_sources:
        events.append(
            {
                "code": "PQ_FOLDER_INVENTORY_PREVIEW",
                "severity": "info",
                "message": f"{len(folder_sources)} folder source(s) can preview file inventory locally; combine-file helper execution is tracked separately.",
            }
        )
    if combine_file_patterns:
        events.append(
            {
                "code": "PQ_COMBINE_FILES_HELPER_PRESERVED",
                "severity": "warning",
                "message": f"{len(combine_file_patterns)} potential combine-file helper invocation step(s) are preserved; simple CSV/JSON and imported helper-function previews can execute locally, while complex helper patterns remain explicit gaps.",
            }
        )
    if sample_file_navigations:
        events.append(
            {
                "code": "PQ_SAMPLE_FILE_NAVIGATION_PREVIEW",
                "severity": "info",
                "message": f"{len(sample_file_navigations)} sample-file navigation step(s) over folder content can preview locally when the source inventory is available.",
            }
        )
    return {
        "source_count": len(sources),
        "sources": sources,
        "native_query_count": len(native_queries),
        "native_queries": native_queries,
        "folder_source_count": len(folder_sources),
        "combine_file_pattern_count": len(combine_file_patterns),
        "combine_file_patterns": combine_file_patterns,
        "sample_file_navigation_count": len(sample_file_navigations),
        "sample_file_navigations": sample_file_navigations,
        "privacy_levels": sorted(levels),
        "privacy_partitions": partitions,
        "firewall_status": firewall_status,
        "credential_required_count": len(credential_sources),
        "duckdb_pushdown_ready_count": len(pushdown_ready),
        "adapter_pending_count": len(adapter_pending),
        "events": events,
    }
