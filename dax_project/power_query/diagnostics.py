from __future__ import annotations

from typing import Any, Mapping

from .parser import parse_m_query
from .registry import classify_function_names
from .source_map import map_source_bindings_from_m, map_sources_from_m
from .source_policy import build_source_policy_report
from .transpiler import build_neutral_transform_plan


def _status_from_events(events: list[dict[str, Any]]) -> str:
    if any(str(event.get("severity") or "").lower() == "error" for event in events):
        return "error"
    if events:
        return "warning"
    return "ok"


def _event(*, phase: str, severity: str, message: str, code: str, step_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "phase": phase,
        "severity": severity,
        "code": code,
        "message": message,
    }
    if step_id:
        data["step_id"] = step_id
    return data


def build_power_query_diagnostics(
    *,
    query_id: str,
    raw_m: str,
    table_name: str | None = None,
    partition_name: str | None = None,
    source_sql: str = "",
    source_row_count: int | None = None,
    preview: Mapping[str, Any] | None = None,
    preview_error: str | None = None,
    timings_ms: Mapping[str, float] | None = None,
    draft: bool = False,
    target_step_id: str | None = None,
) -> dict[str, Any]:
    """Build a visible diagnostics report for Transform Studio.

    This is intentionally not a clone of Power Query's trace format. It is a
    Dummy BI diagnostic contract that reports the same important engineering
    facts: parse health, source mapping, foldability, preview execution,
    blockers, and stable timing buckets when the route has measured them.
    """

    steps, result_expression, functions, parse_diagnostics = parse_m_query(raw_m)
    function_status = classify_function_names(functions)
    source_mappings = map_sources_from_m(raw_m)
    source_mapping = source_mappings[0] if source_mappings else None
    source_mapping_dicts = [mapping.to_dict() for mapping in source_mappings]
    source_mapping_dict = source_mapping.to_dict() if source_mapping else None
    source_bindings = map_source_bindings_from_m(raw_m)
    source_binding_dicts = [binding.to_dict() for binding in source_bindings]
    source_policy = build_source_policy_report(raw_m)
    transform_plan = build_neutral_transform_plan(raw_m)
    events: list[dict[str, Any]] = []

    for diag in parse_diagnostics:
        events.append({
            "phase": "parse",
            "severity": diag.severity,
            "code": diag.code or "PQ_PARSE_DIAGNOSTIC",
            "message": diag.message,
            **({"step_id": diag.step_id} if diag.step_id else {}),
        })

    for name, status in function_status.items():
        execution = str(status.get("execution") or "")
        if execution in {"unsupported", "preserve_only"}:
            events.append(_event(
                phase="capability",
                severity="warning",
                code="PQ_UNSUPPORTED_FUNCTION",
                message=f"Function {name} is preserved but not executable in Dummy BI yet.",
            ))

    if source_mapping is None:
        events.append(_event(
            phase="source_mapping",
            severity="warning",
            code="PQ_SOURCE_UNMAPPED",
            message="No executable source mapping could be inferred from this M query.",
        ))
    for item in source_policy.get("events") or []:
        if not isinstance(item, Mapping):
            continue
        events.append(
            _event(
                phase="source_mapping",
                severity=str(item.get("severity") or "warning"),
                code=str(item.get("code") or "PQ_SOURCE_POLICY"),
                message=str(item.get("message") or "Source policy requires review."),
            )
        )

    for blocker in transform_plan.get("blockers") or []:
        if not isinstance(blocker, Mapping):
            continue
        events.append(_event(
            phase="folding",
            severity="warning",
            code="PQ_FOLDING_BLOCKED",
            message=str(blocker.get("reason") or "Step is not foldable yet."),
            step_id=str(blocker.get("step_id") or "") or None,
        ))

    preview_blockers: list[dict[str, Any]] = []
    if isinstance(preview, Mapping):
        for blocker in preview.get("blocked_steps") or []:
            if isinstance(blocker, Mapping):
                item = dict(blocker)
                preview_blockers.append(item)
                events.append(_event(
                    phase="preview",
                    severity="warning",
                    code="PQ_PREVIEW_STEP_BLOCKED",
                    message=str(item.get("reason") or "Preview step was blocked."),
                    step_id=str(item.get("step_id") or "") or None,
                ))
    if preview_error:
        events.append(_event(
            phase="preview",
            severity="warning",
            code="PQ_PREVIEW_UNAVAILABLE",
            message=preview_error,
        ))

    parse_events = [event for event in events if event.get("phase") == "parse"]
    capability_events = [event for event in events if event.get("phase") == "capability"]
    source_events = [event for event in events if event.get("phase") == "source_mapping"]
    folding_events = [event for event in events if event.get("phase") == "folding"]
    preview_events = [event for event in events if event.get("phase") == "preview"]

    plan_steps = [step for step in transform_plan.get("steps") or [] if isinstance(step, Mapping)]
    foldable_steps = [step for step in plan_steps if step.get("foldable")]
    source_status = "mapped" if source_mapping is not None else "unmapped"
    if preview is not None:
        preview_status = "executed_with_blockers" if preview_blockers else "executed"
    elif preview_error:
        preview_status = "unavailable"
    else:
        preview_status = "not_requested"

    return {
        "query_id": query_id,
        "table_name": table_name,
        "partition_name": partition_name,
        "draft": draft,
        "target_step_id": target_step_id,
        "result_expression": result_expression,
        "summary": {
            "status": _status_from_events(events),
            "step_count": len(steps),
            "function_count": len(functions),
            "event_count": len(events),
            "unsupported_function_count": len(capability_events),
            "foldable_step_count": len(foldable_steps),
            "blocked_step_count": len(transform_plan.get("blockers") or []) + len(preview_blockers),
            "execution_strategy": transform_plan.get("execution_strategy"),
            "parity_status": transform_plan.get("parity_status"),
            "schema_probe_required": bool(transform_plan.get("schema_probe_required")),
            "preview_row_count": int(preview.get("row_count") or 0) if isinstance(preview, Mapping) else None,
            "target_step_id": target_step_id,
        },
        "phases": [
            {
                "phase": "parse",
                "status": _status_from_events(parse_events),
                "step_count": len(steps),
                "diagnostic_count": len(parse_events),
            },
            {
                "phase": "capability",
                "status": _status_from_events(capability_events),
                "function_count": len(functions),
                "unsupported_function_count": len(capability_events),
            },
            {
                "phase": "source_mapping",
                "status": source_status if not source_events else "warning",
                "source_type": source_mapping.source_type if source_mapping else None,
                "confidence": source_mapping.confidence if source_mapping else None,
                "connector_id": source_mapping.connector_id if source_mapping else None,
                "privacy_level": source_mapping.privacy_level if source_mapping else None,
                "folding_status": source_mapping.folding_status if source_mapping else None,
                "firewall_status": source_policy.get("firewall_status"),
                "source_count": source_policy.get("source_count"),
                "source_binding_count": len(source_binding_dicts),
                "credential_required_count": source_policy.get("credential_required_count"),
                "source_row_count": source_row_count,
            },
            {
                "phase": "folding",
                "status": str(transform_plan.get("status") or "preserve_only"),
                "execution_strategy": transform_plan.get("execution_strategy"),
                "parity_status": transform_plan.get("parity_status"),
                "schema_probe_required": bool(transform_plan.get("schema_probe_required")),
                "local_evaluator_reason": transform_plan.get("local_evaluator_reason"),
                "step_count": len(plan_steps),
                "foldable_step_count": len(foldable_steps),
                "blocked_step_count": len(transform_plan.get("blockers") or []),
            },
            {
                "phase": "preview",
                "status": preview_status if not preview_events else "warning",
                "row_count": int(preview.get("row_count") or 0) if isinstance(preview, Mapping) else None,
                "applied_steps": list(preview.get("applied_steps") or []) if isinstance(preview, Mapping) else [],
                "blocked_step_count": len(preview_blockers),
            },
        ],
        "events": events,
        "source_mapping": source_mapping_dict,
        "source_mappings": source_mapping_dicts,
        "source_mapping_count": len(source_mapping_dicts),
        "source_bindings": source_binding_dicts,
        "source_binding_count": len(source_binding_dicts),
        "source_policy": source_policy,
        "transform_plan": transform_plan,
        "preview": {
            "columns": list(preview.get("columns") or []) if isinstance(preview, Mapping) else [],
            "row_count": int(preview.get("row_count") or 0) if isinstance(preview, Mapping) else None,
            "applied_steps": list(preview.get("applied_steps") or []) if isinstance(preview, Mapping) else [],
            "blocked_steps": preview_blockers,
            "error": preview_error,
            "source_sql": source_sql,
            "execution_scope": str(preview.get("execution_scope") or "") if isinstance(preview, Mapping) else "",
            "adapter_result": preview.get("adapter_result") if isinstance(preview, Mapping) and isinstance(preview.get("adapter_result"), Mapping) else None,
            "result_step_id": (str(preview.get("result_step_id") or "") or None) if isinstance(preview, Mapping) else None,
        },
        "timings_ms": dict(timings_ms or {}),
    }
