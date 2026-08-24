#!/usr/bin/env python3
"""Validate a generated open-core MVP artifact without modifying it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


REQUIRED = {
    "readme.md",
    "LICENSE",
    "open_core_mvp.yml",
    "dax_compiler.py",
    "semantic_model_loader.py",
    "dax_project/open_core_profile.py",
    "dax_project/visual_types.yaml",
    "dax_ui/open_core_app.py",
    "dax_ui/open_core_main.py",
    "dax_ui/frontend/open-core/index.html",
    "dax_ui/frontend/open-core/src/main.tsx",
    "dax_ui/frontend/src/App.tsx",
    "dax_ui/frontend/src/lib/edition.ts",
    "dax_ui/frontend/src/components/layout/VisualsPane.tsx",
    "dax_ui/frontend/src/components/updates/UpdateManager.tsx",
    "pyinstaller_open_core.spec",
    "src-tauri/Cargo.toml",
    "src-tauri/capabilities/default.json",
    "src-tauri/icons/icon.ico",
    "src-tauri/src/main.rs",
    "src-tauri/tauri.conf.json",
}
FORBIDDEN_PATH_PARTS = {
    "dax_ui/static",
    "dax_ui/templates",
    "routes_enterprise.py",
}
EXCLUDED_IMPLEMENTATION_PREFIXES = (
    "dax_ui/frontend/src/components/autogen/",
    "dax_ui/frontend/src/components/stories/",
    "dax_ui/frontend/src/components/power-query/",
    "dax_ui/frontend/src/components/explanations/",
    "dax_ui/frontend/src/components/subscriptions/",
    "dax_ui/frontend/src/components/server/",
    "dax_engine/autogen/",
    "dax_engine/explanations/",
    "dax_project/power_query/",
)
COMPATIBILITY_STUBS = {
    "dax_ui/frontend/src/components/autogen/index.ts",
    "dax_ui/frontend/src/components/autogen/EDUSubWizard.tsx",
    "dax_ui/frontend/src/components/stories/index.ts",
    "dax_ui/frontend/src/components/power-query/TransformStudio.tsx",
    "dax_ui/frontend/src/components/explanations/index.ts",
    "dax_ui/frontend/src/components/subscriptions/SubscriptionList.tsx",
    "dax_ui/frontend/src/components/model/PlaybookEditor.tsx",
    "dax_ui/frontend/src/components/model/TmdlImportWizard.tsx",
    "dax_ui/frontend/src/components/model/ReportImportWizard.tsx",
    "dax_ui/frontend/src/stores/autogen-store.ts",
    "dax_ui/frontend/src/stores/ml-store.ts",
    "dax_ui/frontend/src/stores/server-store.ts",
    "dax_ui/frontend/src/stores/story-store.ts",
    "dax_ui/frontend/src/stores/subscription-store.ts",
    "dax_ui/frontend/src/hooks/useStories.ts",
    "dax_ui/server/_routes_story.py",
    "dax_ui/server/_routes_tmdl.py",
}
REMOVED_IMPLEMENTATIONS = {
    "dax_project/tmdl_converter.py",
    "dax_engine/subscription_product.py",
    "dax_engine/threshold_scheduler.py",
}


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    if not root.is_dir():
        return [f"Artifact directory does not exist: {root}"]

    relative_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    for required in sorted(REQUIRED):
        if required not in relative_files:
            errors.append(f"Missing required file: {required}")
    for rel in sorted(relative_files):
        if any(part in rel for part in FORBIDDEN_PATH_PARTS):
            errors.append(f"Forbidden path in artifact: {rel}")
        if rel.startswith(EXCLUDED_IMPLEMENTATION_PREFIXES) and rel not in COMPATIBILITY_STUBS:
            errors.append(f"Excluded feature implementation in artifact: {rel}")
    for rel in sorted(COMPATIBILITY_STUBS & relative_files):
        content = (root / rel).read_text(encoding="utf-8", errors="ignore")
        if "Open-core compatibility stub." not in content or len(content) > 1500:
            errors.append(f"Excluded feature path is not a minimal compatibility stub: {rel}")
    for rel in sorted(REMOVED_IMPLEMENTATIONS & relative_files):
        errors.append(f"Excluded backend implementation in artifact: {rel}")

    manifest_path = root / "open_core_mvp.yml"
    registry_path = root / "dax_project" / "visual_types.yaml"
    if manifest_path.exists() and registry_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        expected_visuals = set(manifest["visuals"]["allowed"])
        actual_visuals = set(registry["visual_types"])
        if actual_visuals != expected_visuals:
            errors.append(f"Visual allowlist mismatch: expected {len(expected_visuals)}, found {len(actual_visuals)}")
        bad_renderers = {
            spec.get("renderer")
            for spec in registry["visual_types"].values()
            if spec.get("renderer") not in {"plotly_express", "graph_objects", "table"}
        }
        if bad_renderers:
            errors.append(f"Unsupported renderers remain: {sorted(bad_renderers)}")
        if len(actual_visuals) != 32 or "table" not in actual_visuals or "matrix" in actual_visuals:
            errors.append(f"Expected 31 Plotly visuals plus table, found {len(actual_visuals)}")
        if len(set(manifest["data_connections"]["allowed"])) != 17:
            errors.append("Expected all 17 connectors in the manifest")

    frontend = root / "dax_ui" / "frontend"
    edition_path = frontend / "src" / "lib" / "edition.ts"
    if edition_path.exists():
        edition = edition_path.read_text(encoding="utf-8")
        for gate in (
            "HAS_TRANSFORM_STUDIO", "HAS_STORIES", "HAS_EDU_RELATIONSHIPS",
            "HAS_ML_ANALYTICS", "HAS_REPORT_AUTOGENERATION", "HAS_SUBSCRIPTIONS",
            "HAS_POWER_BI_IMPORT",
        ):
            if gate not in edition:
                errors.append(f"Missing frontend edition gate: {gate}")
    project_init = root / "dax_project" / "__init__.py"
    if project_init.exists() and "from .power_query import" in project_init.read_text(encoding="utf-8"):
        errors.append("Public dax_project package still exports Transform Studio implementation")

    package_path = frontend / "package.json"
    if package_path.exists():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        if "open-core" not in scripts.get("dev", "") or "open-core" not in scripts.get("build", ""):
            errors.append("Public frontend default scripts do not target the open-core entry")
        dependencies = package.get("dependencies", {})
        for dependency in ("@tauri-apps/plugin-process", "@tauri-apps/plugin-updater"):
            if dependency not in dependencies:
                errors.append(f"Public frontend is missing updater dependency: {dependency}")

    tauri_path = root / "src-tauri" / "tauri.conf.json"
    if tauri_path.exists():
        tauri = json.loads(tauri_path.read_text(encoding="utf-8"))
        if tauri.get("productName") != "Semantic Migration Workbench":
            errors.append("Public Tauri product name is incorrect")
        if tauri.get("bundle", {}).get("externalBin") != ["binaries/dax_backend"]:
            errors.append("Public Tauri config does not bundle the backend sidecar")
        updater = tauri.get("plugins", {}).get("updater", {})
        if not updater.get("endpoints") or not updater.get("pubkey"):
            errors.append("Public Tauri updater is not configured")
    main_rs = root / "src-tauri" / "src" / "main.rs"
    if main_rs.exists():
        main_text = main_rs.read_text(encoding="utf-8")
        if "DAX_EMBEDDED_PRODUCT_PROFILE" not in main_text:
            errors.append("Public Tauri shell does not embed the open-core runtime profile")
        if "tauri_plugin_updater" not in main_text or "tauri_plugin_process" not in main_text:
            errors.append("Public Tauri shell does not register updater and restart plugins")
    cargo_toml = root / "src-tauri" / "Cargo.toml"
    if cargo_toml.exists():
        cargo_text = cargo_toml.read_text(encoding="utf-8")
        if 'name = "dax-to-sql-open-core"' not in cargo_text:
            errors.append("Public Cargo package name is incorrect")
        if "tauri-plugin-updater" not in cargo_text or "tauri-plugin-process" not in cargo_text:
            errors.append("Public Cargo package is missing updater and restart plugins")
    capability_path = root / "src-tauri" / "capabilities" / "default.json"
    if capability_path.exists():
        permissions = set(json.loads(capability_path.read_text(encoding="utf-8")).get("permissions", []))
        if not {"updater:default", "process:allow-restart"}.issubset(permissions):
            errors.append("Public Tauri capability does not permit signed updates and restart")
    launcher = root / "dax_ui" / "open_core_main.py"
    if launcher.exists() and "OPEN_CORE_PROFILE" not in launcher.read_text(encoding="utf-8"):
        errors.append("Public backend launcher does not enforce the open-core runtime profile")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", nargs="?", type=Path, default=Path("dist/open_core_mvp"))
    args = parser.parse_args()
    errors = validate(args.artifact.resolve())
    if errors:
        print("Open-core MVP validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Open-core MVP validation passed: shared shell, excluded implementations removed, 31 Plotly visuals plus table, updater configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
