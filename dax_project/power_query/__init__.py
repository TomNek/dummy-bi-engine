"""Power Query M import compatibility helpers.

This package is the backend foundation for Transform Studio.  The first slice
is intentionally conservative: preserve raw M, parse a step inventory, map
common sources, and produce explicit compatibility reports without pretending
unsupported M can execute.
"""

from .model import (
    MCompatibilityReport,
    MDiagnostic,
    MQuery,
    MSourceBinding,
    MSourceMapping,
    MStep,
)
from .adapters import (
    ADAPTER_CAPABILITY_KEYS,
    ADAPTER_RESULT_CONTRACT,
    LIVE_CERTIFICATION_STATES,
    LIVE_PROFILE_ENV_VARS,
    PowerQueryAdapterContext,
    PowerQueryAdapterResult,
    build_adapter_result,
    build_fixture_adapter_context,
    build_live_certification_descriptor,
    build_runtime_adapter_descriptor,
    execute_power_query_adapter,
    get_power_query_adapter,
)
from .credentials import (
    PROFILE_METADATA_KEYS,
    PROFILE_CERTIFICATION_KEYS,
    credential_profiles_path,
    delete_credential_profile,
    get_credential_profile,
    get_credential_secrets,
    list_credential_profiles,
    redact_secret_value,
    redact_text,
    upsert_credential_profile,
)
from .live_setup import (
    build_live_connector_setup_manifest,
    certify_live_connector_profile,
    complete_live_connector_oauth,
    start_live_connector_oauth,
)
from .parser import (
    add_m_step_expression,
    delete_m_step_expression,
    parse_m_query,
    rename_m_step_expression,
    reorder_m_step_expression,
    replace_m_parameter_value_expression,
    replace_m_step_expression,
)
from .parity_gap_report import build_power_query_parity_gap_report
from .step_editing import build_power_query_applied_step_edit_preview
from .evaluator import PreviewEvaluationResult, evaluate_preview_table
from .graph import build_power_query_graph
from .ir import PQTransformIRNode
from .sql_ast import build_relational_query_ast
from .duckdb_emitter import emit_duckdb_sql
from .connector_folding import build_connector_native_plan
from .authoring import build_power_query_intellisense
from .diagnostics import build_power_query_diagnostics
from .function_catalog import build_function_coverage_catalog, function_catalog_rows, function_catalog_summary
from .profiling import build_data_profile
from .registry import (
    C0_PRESERVED,
    C1_PARSED,
    C2_MAPPED,
    C3_EXECUTABLE,
    MFunctionMetadata,
    classify_function_names,
    get_function_metadata,
    list_function_metadata,
)
from .source_map import map_source_bindings_from_m, map_source_from_m, map_sources_from_m
from .source_policy import build_source_policy_report
from .schema_probe import build_power_query_schema_probe
from .transpiler import build_neutral_transform_plan
from .validation import build_power_query_metadata, build_power_query_report

__all__ = [
    "C0_PRESERVED",
    "C1_PARSED",
    "C2_MAPPED",
    "C3_EXECUTABLE",
    "MCompatibilityReport",
    "MDiagnostic",
    "MFunctionMetadata",
    "MQuery",
    "MSourceBinding",
    "MSourceMapping",
    "MStep",
    "ADAPTER_CAPABILITY_KEYS",
    "ADAPTER_RESULT_CONTRACT",
    "LIVE_CERTIFICATION_STATES",
    "LIVE_PROFILE_ENV_VARS",
    "PreviewEvaluationResult",
    "PowerQueryAdapterContext",
    "PowerQueryAdapterResult",
    "PQTransformIRNode",
    "PROFILE_METADATA_KEYS",
    "PROFILE_CERTIFICATION_KEYS",
    "build_adapter_result",
    "build_fixture_adapter_context",
    "build_live_certification_descriptor",
    "build_live_connector_setup_manifest",
    "build_connector_native_plan",
    "build_power_query_metadata",
    "build_power_query_graph",
    "build_power_query_intellisense",
    "build_power_query_parity_gap_report",
    "build_power_query_applied_step_edit_preview",
    "build_relational_query_ast",
    "build_power_query_report",
    "build_power_query_diagnostics",
    "build_power_query_schema_probe",
    "build_data_profile",
    "build_function_coverage_catalog",
    "build_neutral_transform_plan",
    "build_runtime_adapter_descriptor",
    "build_source_policy_report",
    "certify_live_connector_profile",
    "complete_live_connector_oauth",
    "execute_power_query_adapter",
    "evaluate_preview_table",
    "emit_duckdb_sql",
    "function_catalog_rows",
    "function_catalog_summary",
    "credential_profiles_path",
    "delete_credential_profile",
    "get_credential_profile",
    "get_credential_secrets",
    "get_power_query_adapter",
    "list_credential_profiles",
    "redact_secret_value",
    "redact_text",
    "classify_function_names",
    "get_function_metadata",
    "list_function_metadata",
    "map_source_from_m",
    "map_source_bindings_from_m",
    "map_sources_from_m",
    "parse_m_query",
    "add_m_step_expression",
    "delete_m_step_expression",
    "rename_m_step_expression",
    "reorder_m_step_expression",
    "replace_m_parameter_value_expression",
    "replace_m_step_expression",
    "start_live_connector_oauth",
    "upsert_credential_profile",
]
