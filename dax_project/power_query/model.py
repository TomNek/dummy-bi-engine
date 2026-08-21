from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None and v != [] and v != {}}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


@dataclass(frozen=True)
class MDiagnostic:
    severity: str
    message: str
    code: Optional[str] = None
    step_id: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class MStep:
    id: str
    expression: str
    operation: str = "unknown"
    dependencies: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    compatibility_level: str = "C1"
    source_span: Optional[dict[str, int]] = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class MSourceMapping:
    source_type: str
    source_block: dict[str, Any]
    confidence: str = "medium"
    reason: str = ""
    raw_function: Optional[str] = None
    connector_id: Optional[str] = None
    privacy_level: Optional[str] = None
    credential_required: Optional[bool] = None
    pushdown_support: Optional[str] = None
    folding_status: Optional[str] = None
    firewall_partition: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class MSourceBinding:
    binding_id: str
    source_type: str
    source_block: dict[str, Any]
    raw_function: Optional[str] = None
    source_step_id: Optional[str] = None
    source_step_ids: list[str] = field(default_factory=list)
    binding_chain: list[dict[str, Any]] = field(default_factory=list)
    navigation_steps: list[dict[str, Any]] = field(default_factory=list)
    query_references: list[dict[str, Any]] = field(default_factory=list)
    connector_id: Optional[str] = None
    credential_profile_id: Optional[str] = None
    privacy_level: Optional[str] = None
    privacy_partition: Optional[str] = None
    firewall_partition: Optional[str] = None
    navigation_chain: list[dict[str, Any]] = field(default_factory=list)
    schema_probe_candidate: Optional[dict[str, Any]] = None
    confidence: str = "medium"
    reason: str = ""
    folding_status: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass(frozen=True)
class MQuery:
    query_id: str
    raw_m: str
    table_name: Optional[str] = None
    partition_name: Optional[str] = None
    mode: Optional[str] = None
    result_expression: Optional[str] = None
    steps: list[MStep] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    source_mapping: Optional[MSourceMapping] = None
    source_mappings: list[MSourceMapping] = field(default_factory=list)
    source_bindings: list[MSourceBinding] = field(default_factory=list)
    source_policy: Optional[dict[str, Any]] = None
    diagnostics: list[MDiagnostic] = field(default_factory=list)
    compatibility_level: str = "C0"
    execution_status: str = "preserved"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        data["diagnostics"] = [diag.to_dict() for diag in self.diagnostics]
        data["source_mapping"] = self.source_mapping.to_dict() if self.source_mapping else None
        data["source_mappings"] = [mapping.to_dict() for mapping in self.source_mappings]
        data["source_bindings"] = [binding.to_dict() for binding in self.source_bindings]
        return _clean(data)


@dataclass(frozen=True)
class MCompatibilityReport:
    query_id: str
    compatibility_level: str
    execution_status: str
    unsupported_functions: list[str] = field(default_factory=list)
    unsupported_constructs: list[str] = field(default_factory=list)
    diagnostics: list[MDiagnostic] = field(default_factory=list)
    function_status: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["diagnostics"] = [diag.to_dict() for diag in self.diagnostics]
        return _clean(data)
