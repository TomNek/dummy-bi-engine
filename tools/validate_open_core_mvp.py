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
    "dax_ui/frontend/src/open-core/OpenCoreApp.tsx",
    "dax_ui/frontend/src/open-core/charts.ts",
    "pyinstaller_open_core.spec",
    "src-tauri/Cargo.toml",
    "src-tauri/icons/icon.ico",
    "src-tauri/src/main.rs",
    "src-tauri/tauri.conf.json",
}
FORBIDDEN_PATH_PARTS = {
    "src/components/visuals/ibcs",
    "src/components/layout",
    "src/components/autogen",
    "src/stores/ml-store.ts",
    "src/App.tsx",
    "dax_ui/static",
    "dax_ui/templates",
    "routes_enterprise.py",
}
FORBIDDEN_FRONTEND_TOKENS = ("ibcs", "tableau", "customsvg", "custom svg")


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
            if spec.get("renderer") not in {"plotly_express", "graph_objects"}
        }
        if bad_renderers:
            errors.append(f"Non-Plotly renderers remain: {sorted(bad_renderers)}")
        if len(actual_visuals) != 31:
            errors.append(f"Expected all 31 Plotly visuals, found {len(actual_visuals)}")
        if len(set(manifest["data_connections"]["allowed"])) != 17:
            errors.append("Expected all 17 connectors in the manifest")

    frontend = root / "dax_ui" / "frontend"
    for path in frontend.rglob("*") if frontend.exists() else []:
        if path.suffix.lower() not in {".ts", ".tsx", ".css", ".html", ".json"} or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN_FRONTEND_TOKENS:
            if token in content:
                errors.append(f"Forbidden frontend token {token!r}: {path.relative_to(root).as_posix()}")

    package_path = frontend / "package.json"
    if package_path.exists():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        if "open-core" not in scripts.get("dev", "") or "open-core" not in scripts.get("build", ""):
            errors.append("Public frontend default scripts do not target the open-core entry")

    tauri_path = root / "src-tauri" / "tauri.conf.json"
    if tauri_path.exists():
        tauri = json.loads(tauri_path.read_text(encoding="utf-8"))
        if tauri.get("productName") != "Dummy BI Engine":
            errors.append("Public Tauri product name is incorrect")
        if tauri.get("identifier") != "com.dummy-bi.engine":
            errors.append("Public Tauri identifier is incorrect")
        if tauri.get("bundle", {}).get("externalBin") != ["binaries/dax_backend"]:
            errors.append("Public Tauri config does not bundle the backend sidecar")
    main_rs = root / "src-tauri" / "src" / "main.rs"
    if main_rs.exists() and "DAX_EMBEDDED_PRODUCT_PROFILE" not in main_rs.read_text(encoding="utf-8"):
        errors.append("Public Tauri shell does not embed the open-core runtime profile")
    cargo_toml = root / "src-tauri" / "Cargo.toml"
    if cargo_toml.exists() and 'name = "dummy-bi-engine"' not in cargo_toml.read_text(encoding="utf-8"):
        errors.append("Public Cargo package name is incorrect")
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
    print("Open-core MVP validation passed: 31 Plotly visuals, 17 connectors, no private visual UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
