from __future__ import annotations

from typing import Any, Optional

from .model import MCompatibilityReport, MDiagnostic, MQuery, MStep
from .parser import parse_m_query
from .registry import C0_PRESERVED, C1_PARSED, C2_MAPPED, C3_EXECUTABLE, classify_function_names
from .source_map import map_source_bindings_from_m, map_source_from_m, map_sources_from_m
from .source_policy import build_source_policy_report


def _step_level(step: MStep, function_status: dict[str, dict[str, Any]]) -> str:
    if not step.functions:
        return C1_PARSED
    levels = [str(function_status.get(fn, {}).get("compatibility_level") or C0_PRESERVED) for fn in step.functions]
    if any(level == C0_PRESERVED for level in levels):
        return C0_PRESERVED
    if any(level == C1_PARSED for level in levels):
        return C1_PARSED
    if any(level == C2_MAPPED for level in levels):
        return C2_MAPPED
    return C3_EXECUTABLE


def build_power_query_report(query: MQuery) -> MCompatibilityReport:
    function_status = classify_function_names(query.functions)
    unsupported = [
        name
        for name, meta in function_status.items()
        if str(meta.get("execution") or "").lower() in {"unsupported", "preserve_only"}
    ]
    return MCompatibilityReport(
        query_id=query.query_id,
        compatibility_level=query.compatibility_level,
        execution_status=query.execution_status,
        unsupported_functions=unsupported,
        diagnostics=query.diagnostics,
        function_status=function_status,
    )


def build_power_query_metadata(
    *,
    query_id: str,
    raw_m: str,
    table_name: Optional[str] = None,
    partition_name: Optional[str] = None,
    mode: Optional[str] = None,
) -> dict[str, Any]:
    query = build_power_query_model(
        query_id=query_id,
        raw_m=raw_m,
        table_name=table_name,
        partition_name=partition_name,
        mode=mode,
    )
    data = query.to_dict()
    data["compatibility_report"] = build_power_query_report(query).to_dict()
    return data


def build_power_query_model(
    *,
    query_id: str,
    raw_m: str,
    table_name: Optional[str] = None,
    partition_name: Optional[str] = None,
    mode: Optional[str] = None,
) -> MQuery:
    diagnostics: list[MDiagnostic] = []
    steps, result_expression, functions, parse_diagnostics = parse_m_query(raw_m)
    diagnostics.extend(parse_diagnostics)
    source_mappings = map_sources_from_m(raw_m)
    source_mapping = source_mappings[0] if source_mappings else map_source_from_m(raw_m)
    source_bindings = map_source_bindings_from_m(raw_m)
    source_policy = build_source_policy_report(raw_m)
    function_status = classify_function_names(functions)

    leveled_steps: list[MStep] = []
    for step in steps:
        leveled_steps.append(
            MStep(
                id=step.id,
                expression=step.expression,
                operation=step.operation,
                dependencies=step.dependencies,
                functions=step.functions,
                compatibility_level=_step_level(step, function_status),
                source_span=step.source_span,
            )
        )

    unsupported = [
        name
        for name, meta in function_status.items()
        if str(meta.get("execution") or "").lower() in {"unsupported", "preserve_only"}
    ]
    for fn in unsupported:
        diagnostics.append(
            MDiagnostic(
                "warning",
                f"Power Query function {fn!r} is preserved but not executable in Dummy BI yet.",
                code="PQ_UNSUPPORTED_FUNCTION",
            )
        )

    if not raw_m.strip():
        level = C0_PRESERVED
        status = "preserved"
    elif source_mapping is not None:
        level = C3_EXECUTABLE
        status = "mapped"
    elif steps:
        level = C1_PARSED
        status = "parsed"
    else:
        level = C0_PRESERVED
        status = "preserved"

    return MQuery(
        query_id=query_id,
        raw_m=raw_m,
        table_name=table_name,
        partition_name=partition_name,
        mode=mode,
        result_expression=result_expression,
        steps=leveled_steps,
        functions=functions,
        source_mapping=source_mapping,
        source_mappings=source_mappings,
        source_bindings=source_bindings,
        source_policy=source_policy,
        diagnostics=diagnostics,
        compatibility_level=level,
        execution_status=status,
    )
