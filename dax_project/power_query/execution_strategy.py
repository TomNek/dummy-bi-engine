from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


FOLDED_SQL = "folded_sql"
CONNECTOR_FOLDED = "connector_folded"
HYBRID_SCHEMA_PROBE = "hybrid_schema_probe"
LOCAL_EXACT = "local_exact"
BLOCKED_MISSING_CAPABILITY = "blocked_missing_capability"


_CONNECTOR_CAPABILITIES: dict[str, list[str]] = {
    "source_sql": ["schema", "projection", "filter", "sort", "top", "group_by", "native_query", "culture_cast"],
    "source_odbc": ["schema", "projection", "filter", "sort", "top", "group_by", "native_query", "culture_cast"],
    "source_odata": ["schema", "projection", "filter", "sort", "top", "paging"],
    "source_web": ["schema", "paging"],
    "source_sharepoint": ["schema", "projection", "filter", "paging"],
}

_FUZZY_OPERATIONS = {
    "fuzzy_join",
    "fuzzy_nested_join",
    "fuzzy_group",
    "fuzzy_cluster",
}

_LOCAL_EXACT_OPERATIONS = {
    "fill_down",
    "fill_up",
    "limit_last",
    "remove_last",
    "fold_barrier",
    "native_query",
    "select_rows_with_errors",
}

_SCHEMA_PROBE_OPERATIONS = {
    "transform_column_names",
    "select_columns",
    "remove_columns",
    "rename_columns",
    "expand_table_column",
    "expand_record_column",
    "expand_list_column",
    "demote_headers",
}

_SCHEMA_MARKERS = (
    "known projection",
    "unknown-source projection",
    "schema probe",
    "schema-probe",
    "source schema",
    "containing the list column",
    "projection is unknown",
    "requires a schema",
)

_LOCAL_EXACT_MARKERS = (
    "fuzzy",
    "helper definition",
    "helper requires local evaluator",
    "generated helper",
    "folder-combine",
    "transform file",
    "sample file",
    "local evaluator",
    "intentionally stops sql pushdown",
    "nativequery",
    "native query",
    "culture",
    "timezone",
    "comparer",
    "error provenance",
    "sql folding only supports errors introduced",
    "not currently foldable",
)

_ERROR_OPERATIONS = {
    "replace_errors",
    "remove_rows_with_errors",
    "select_rows_with_errors",
}


def connector_capabilities_for_operation(operation: str | None) -> list[str]:
    return list(_CONNECTOR_CAPABILITIES.get(str(operation or ""), []))


def detect_helper_blockers(
    *,
    operation: str,
    functions: Sequence[str],
    expression: str,
    pure_helpers: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return local-evaluator blocker text for user/helper functions.

    The parser reports both built-in M calls and user-defined helper calls as
    function names. For this tranche we only flag obvious custom helpers:
    unqualified calls and generated folder-combine helper names. Built-ins keep
    flowing through the existing catalog and relational lowering paths.
    """

    blockers: list[str] = []
    pure_helper_names = set(pure_helpers or {})
    helper_names = [
        name for name in functions
        if name and "." not in name and not name.startswith("#") and name not in {"let", "in"} and name not in pure_helper_names
    ]
    helper_names.extend(
        candidate.strip()
        for candidate in re.findall(r'(?<![#\w.])(#"[^"]+"|[A-Za-z_]\w*)\s*\(', expression)
        if candidate
        and "." not in candidate
        and candidate.strip('#"') not in pure_helper_names
        and candidate not in {"each", "if", "try", "error"}
        and candidate.lower() not in {"#table", "#date", "#time", "#datetime", "#datetimezone", "#duration"}
    )
    generated_helper_markers = [
        marker
        for marker in ('#"Transform File"', '#"Transform Sample File"', '#"Sample File"', "Transform File", "Sample File")
        if marker in expression
    ]
    if operation == "expression" and "=>" in expression:
        blockers.append("Helper definition requires pure-helper analysis before SQL folding.")
    if helper_names:
        helpers = ", ".join(sorted(set(helper_names)))
        blockers.append(f"Helper requires local evaluator until classified as pure deterministic helper: {helpers}")
    elif generated_helper_markers:
        blockers.append("Generated folder-combine helper requires local evaluator unless a homogeneous finite union can be proven.")
    return blockers


def _status_for_strategy(strategy: str) -> str:
    if strategy == FOLDED_SQL:
        return "folded"
    if strategy == CONNECTOR_FOLDED:
        return "connector_folded"
    if strategy == HYBRID_SCHEMA_PROBE:
        return "needs_schema_probe"
    if strategy == LOCAL_EXACT:
        return "exact_local"
    return "missing_capability"


def _combined_blocker_text(step: Mapping[str, Any], extra_blockers: Sequence[str]) -> str:
    values: list[str] = []
    for key in ("blockers", "relational_blockers", "duckdb_blockers"):
        values.extend(str(item) for item in step.get(key) or [] if str(item))
    values.extend(str(item) for item in extra_blockers if str(item))
    return " | ".join(dict.fromkeys(values))


def classify_step_execution_strategy(
    step: Mapping[str, Any],
    *,
    extra_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    operation = str(step.get("operation") or "")
    blocker_text = _combined_blocker_text(step, extra_blockers)
    blocker_lower = blocker_text.lower()
    capabilities = connector_capabilities_for_operation(operation)
    evidence: list[dict[str, Any]] = []
    local_reason = ""
    schema_probe_required = False

    if capabilities:
        evidence.extend(
            {
                "capability": capability,
                "status": "required",
                "source": operation,
                "reason": "Connector adapter must declare and test this capability before pushdown.",
            }
            for capability in capabilities
        )
        if step.get("foldable") and not blocker_text:
            strategy = CONNECTOR_FOLDED
        else:
            strategy = BLOCKED_MISSING_CAPABILITY
        return {
            "execution_strategy": strategy,
            "parity_status": _status_for_strategy(strategy),
            "schema_probe_required": "schema" in capabilities and strategy == BLOCKED_MISSING_CAPABILITY,
            "capability_evidence": evidence,
            "local_evaluator_reason": None,
        }

    if step.get("foldable") and not blocker_text:
        strategy = FOLDED_SQL
        return {
            "execution_strategy": strategy,
            "parity_status": _status_for_strategy(strategy),
            "schema_probe_required": False,
            "capability_evidence": [],
            "local_evaluator_reason": None,
        }

    if operation in _FUZZY_OPERATIONS:
        evidence.append({
            "capability": "fuzzy_matching",
            "status": "local_exact",
            "reason": "Fuzzy matching uses the deterministic local evaluator unless an adapter registers tested fuzzy support.",
        })
        local_reason = "Fuzzy matching executes locally for exact Power Query semantics."
        strategy = LOCAL_EXACT
    elif operation in _ERROR_OPERATIONS and (
        operation == "select_rows_with_errors" or "sql folding only supports errors introduced" in blocker_lower
    ):
        evidence.append({
            "capability": "error_provenance",
            "status": "local_exact",
            "reason": "Non-cast-origin cell errors require M error provenance tracking.",
        })
        local_reason = "Error row/value handling executes locally unless error flags can be proven equivalent in SQL."
        strategy = LOCAL_EXACT
    elif operation in _LOCAL_EXACT_OPERATIONS or any(marker in blocker_lower for marker in _LOCAL_EXACT_MARKERS):
        local_reason = blocker_text or "Operation is exact in the local evaluator and not proven foldable yet."
        strategy = LOCAL_EXACT
    elif operation in _SCHEMA_PROBE_OPERATIONS or any(marker in blocker_lower for marker in _SCHEMA_MARKERS):
        schema_probe_required = True
        evidence.append({
            "capability": "schema",
            "status": "required",
            "reason": "A source schema probe can resolve known projections before SQL lowering.",
        })
        strategy = HYBRID_SCHEMA_PROBE
    elif blocker_text:
        strategy = BLOCKED_MISSING_CAPABILITY
        evidence.append({
            "capability": "sql_lowering",
            "status": "missing",
            "reason": blocker_text,
        })
    else:
        strategy = BLOCKED_MISSING_CAPABILITY
        evidence.append({
            "capability": "sql_lowering",
            "status": "missing",
            "reason": "Step is not currently foldable.",
        })

    return {
        "execution_strategy": strategy,
        "parity_status": _status_for_strategy(strategy),
        "schema_probe_required": schema_probe_required,
        "capability_evidence": evidence,
        "local_evaluator_reason": local_reason or None,
    }


def summarize_plan_execution_strategy(plan_steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not plan_steps:
        return {
            "execution_strategy": BLOCKED_MISSING_CAPABILITY,
            "parity_status": "no_steps",
            "schema_probe_required": False,
            "capability_evidence": [],
            "local_evaluator_reason": None,
        }

    first_non_folded: Mapping[str, Any] | None = None
    for step in plan_steps:
        if step.get("execution_strategy") != FOLDED_SQL:
            first_non_folded = step
            break
    if first_non_folded is None:
        strategy = FOLDED_SQL
        parity_status = _status_for_strategy(strategy)
        local_reason = None
    else:
        strategy = str(first_non_folded.get("execution_strategy") or BLOCKED_MISSING_CAPABILITY)
        parity_status = str(first_non_folded.get("parity_status") or _status_for_strategy(strategy))
        local_reason = first_non_folded.get("local_evaluator_reason")

    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for step in plan_steps:
        for item in step.get("capability_evidence") or []:
            if not isinstance(item, Mapping):
                continue
            key = (
                str(item.get("capability") or ""),
                str(item.get("status") or ""),
                str(item.get("source") or item.get("reason") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            evidence.append(dict(item))
    return {
        "execution_strategy": strategy,
        "parity_status": parity_status,
        "schema_probe_required": any(bool(step.get("schema_probe_required")) for step in plan_steps),
        "capability_evidence": evidence[:12],
        "local_evaluator_reason": local_reason,
    }


def build_schema_probe_summary(plan_steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for step in plan_steps:
        evidence = [
            item for item in step.get("capability_evidence") or []
            if isinstance(item, Mapping) and str(item.get("capability") or "") == "schema"
        ]
        if not step.get("schema_probe_required") and not evidence:
            continue
        candidates.append({
            "step_id": step.get("id"),
            "operation": step.get("operation"),
            "status": "required" if step.get("schema_probe_required") else "available",
            "evidence": [dict(item) for item in evidence],
        })
    required = any(str(item.get("status") or "") == "required" for item in candidates)
    return {
        "required": required,
        "status": "required" if required else "not_required",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
