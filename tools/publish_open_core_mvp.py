#!/usr/bin/env python3
"""Create the small, auditable open-core MVP source artifact.

This command only writes to the requested local output directory. It does not
commit, push, upload, or publish anything to an external service.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path
import re

import yaml

try:
    from tools.publish_community_repo import ROOT, _load_boundary, _matches_any_pattern, _should_skip_file
except ModuleNotFoundError:  # Direct execution: python tools/publish_open_core_mvp.py
    from publish_community_repo import ROOT, _load_boundary, _matches_any_pattern, _should_skip_file

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dax_project.open_core_profile import OPEN_CORE_VISUAL_TYPES


DEFAULT_OUTPUT = ROOT / "dist" / "open_core_mvp"
FRONTEND_ROOT = "dax_ui/frontend/"
PUBLIC_FRONTEND_FILES = {
    "dax_ui/frontend/package.json",
    "dax_ui/frontend/package-lock.json",
    "dax_ui/frontend/tsconfig.open-core.json",
    "dax_ui/frontend/vite.open-core.config.ts",
    "dax_ui/frontend/open-core/index.html",
    "dax_ui/frontend/open-core/src/main.tsx",
    "dax_ui/frontend/src/open-core/OpenCoreApp.tsx",
    "dax_ui/frontend/src/open-core/api.ts",
    "dax_ui/frontend/src/open-core/charts.ts",
    "dax_ui/frontend/src/open-core/open-core.css",
    "dax_ui/frontend/src/lib/utils.ts",
    "dax_ui/frontend/src/components/ui/button.tsx",
    "dax_ui/frontend/src/components/ui/input.tsx",
    "dax_ui/frontend/src/components/ui/select.tsx",
    "dax_ui/frontend/src/components/ui/switch.tsx",
    "dax_ui/frontend/src/components/ui/textarea.tsx",
}
PUBLIC_TESTS = {
    "tests/conftest.py",
    "tests/test_compiler_mapping_load.py",
    "tests/test_connectors.py",
    "tests/test_runtime_import_connectors.py",
    "tests/test_semantic_model_loader_duckdb.py",
    "tests/test_semantic_model_validation.py",
    "tests/test_open_core_mvp.py",
}
PUBLIC_TOOLS = {
    "tools/check_open_core_boundary.py",
    "tools/create_open_core_release_bundle.py",
    "tools/publish_community_repo.py",
    "tools/publish_open_core_mvp.py",
    "tools/set_open_core_release_version.py",
    "tools/smoke_packaged_backend.ps1",
    "tools/smoke_windows_installer.ps1",
    "tools/validate_open_core_mvp.py",
}
PUBLIC_WORKFLOWS = {
    ".github/workflows/codeql.yml",
    ".github/workflows/open-core-ci.yml",
}
PUBLIC_FRONTEND_DEPENDENCIES = {
    "@radix-ui/react-select",
    "@radix-ui/react-slot",
    "buffer",
    "class-variance-authority",
    "clsx",
    "lucide-react",
    "plotly.js-dist-min",
    "react",
    "react-dom",
    "react-plotly.js",
    "tailwind-merge",
}
PUBLIC_FRONTEND_DEV_DEPENDENCIES = {
    "@tailwindcss/vite",
    "@types/node",
    "@types/react",
    "@types/react-dom",
    "@types/react-plotly.js",
    "@vitejs/plugin-react",
    "tailwindcss",
    "typescript",
    "vite",
}


def _is_public_sample_file(rel: str) -> bool:
    if any(part in {".git", ".report_server", ".dax_engine_cache"} for part in Path(rel).parts):
        return False
    if not rel.startswith("sample_project/reports/"):
        return True
    if rel == "sample_project/reports/pages.yaml":
        return True
    if not rel.startswith("sample_project/reports/visuals/") or not rel.endswith(".json"):
        return False
    try:
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return str(payload.get("visual_type") or "") in OPEN_CORE_VISUAL_TYPES


def collect_open_core_files() -> list[str]:
    community_patterns, excluded_patterns = _load_boundary()
    community_files: set[str] = set()
    for pattern in community_patterns:
        if pattern.endswith("/**"):
            base = ROOT / pattern[:-3]
            candidates = base.rglob("*") if base.is_dir() else []
        else:
            candidate = ROOT / pattern
            candidates = [candidate] if candidate.is_file() else ROOT.glob(pattern)
        for path in candidates:
            if not path.is_file() or _should_skip_file(path.name):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if not _matches_any_pattern(rel, excluded_patterns):
                community_files.add(rel)
    # A published snapshot has already renamed the dedicated open-core config
    # to Tauri's conventional filename. Keeping the publisher idempotent lets
    # contributors run the same boundary tests in the public repository.
    if not (ROOT / "src-tauri" / "tauri.open-core.conf.json").is_file():
        public_tauri = ROOT / "src-tauri" / "tauri.conf.json"
        if public_tauri.is_file():
            community_files.add("src-tauri/tauri.conf.json")
    selected: list[str] = []
    for rel in community_files:
        if rel.startswith(FRONTEND_ROOT) and rel not in PUBLIC_FRONTEND_FILES:
            continue
        if rel.startswith("dax_ui/static/") or rel.startswith("dax_ui/templates/"):
            continue
        if rel == "dax_ui/__main__.py":
            continue
        if rel.startswith("tests/") and rel not in PUBLIC_TESTS:
            continue
        if rel.startswith("scripts/"):
            continue
        if rel.startswith("tools/") and rel not in PUBLIC_TOOLS:
            continue
        if "__pycache__" in Path(rel).parts:
            continue
        if rel.startswith("sample_project/") and not _is_public_sample_file(rel):
            continue
        if rel == "README_community.md":
            continue
        if rel.startswith(".github/workflows/") and rel not in PUBLIC_WORKFLOWS:
            continue
        selected.append(rel)
    return sorted(set(selected))


def _write_filtered_visual_registry(output_dir: Path) -> None:
    target = output_dir / "dax_project" / "visual_types.yaml"
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    visual_types = payload.get("visual_types", {})
    payload["visual_types"] = {
        key: spec for key, spec in visual_types.items() if key in OPEN_CORE_VISUAL_TYPES
    }
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _prune_npm_lock(lock: dict) -> None:
    """Keep only packages reachable from the public lockfile root."""

    packages = lock.get("packages")
    root_package = packages.get("") if isinstance(packages, dict) else None
    if not isinstance(packages, dict) or not isinstance(root_package, dict):
        raise ValueError("Public frontend lockfile has no package graph")

    def resolve_dependency(package_path: str, name: str) -> str | None:
        cursor = package_path
        while cursor:
            candidate = f"{cursor}/node_modules/{name}"
            if candidate in packages:
                return candidate
            marker = "/node_modules/"
            if marker in cursor:
                cursor = cursor.rsplit(marker, 1)[0]
            else:
                cursor = ""
        candidate = f"node_modules/{name}"
        return candidate if candidate in packages else None

    reachable = {""}
    pending = [""]
    while pending:
        package_path = pending.pop()
        entry = packages[package_path]
        dependency_names: set[str] = set()
        for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            values = entry.get(field, {})
            if isinstance(values, dict):
                dependency_names.update(str(name) for name in values)
        for name in dependency_names:
            resolved = resolve_dependency(package_path, name)
            if resolved is not None and resolved not in reachable:
                reachable.add(resolved)
                pending.append(resolved)
    lock["packages"] = {path: entry for path, entry in packages.items() if path in reachable}


def _write_public_package(output_dir: Path) -> None:
    target = output_dir / "dax_ui" / "frontend" / "package.json"
    package = json.loads(target.read_text(encoding="utf-8"))
    package["name"] = "dummy-bi-engine-ui"
    package["private"] = False
    package["license"] = "AGPL-3.0-only"
    package["homepage"] = "https://www.dummy-bi.com/engine"
    package["repository"] = {
        "type": "git",
        "url": "https://github.com/TomNek/dummy-bi-engine.git",
    }
    package["dependencies"] = {
        name: version
        for name, version in package.get("dependencies", {}).items()
        if name in PUBLIC_FRONTEND_DEPENDENCIES
    }
    package["devDependencies"] = {
        name: version
        for name, version in package.get("devDependencies", {}).items()
        if name in PUBLIC_FRONTEND_DEV_DEPENDENCIES
    }
    package["scripts"] = {
        "dev": "vite --config vite.open-core.config.ts",
        "build": "tsc -p tsconfig.open-core.json && vite build --config vite.open-core.config.ts",
        "preview": "vite preview --config vite.open-core.config.ts",
    }
    target.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    lock_path = output_dir / "dax_ui" / "frontend" / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    root_package = lock.get("packages", {}).get("")
    if not isinstance(root_package, dict):
        raise ValueError("Public frontend lockfile has no root package")
    root_package["name"] = package["name"]
    root_package["dependencies"] = package["dependencies"]
    root_package["devDependencies"] = package["devDependencies"]
    lock["name"] = package["name"]
    _prune_npm_lock(lock)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    vite = output_dir / "dax_ui" / "frontend" / "vite.open-core.config.ts"
    vite.write_text(vite.read_text(encoding="utf-8").replace("'dist-open-core'", "'dist'"), encoding="utf-8")


def _write_public_tauri_config(output_dir: Path) -> None:
    tauri_dir = output_dir / "src-tauri"
    source = tauri_dir / "tauri.open-core.conf.json"
    target = tauri_dir / "tauri.conf.json"
    if source.is_file():
        shutil.copy2(source, target)
        source.unlink()
    elif not target.is_file():
        raise FileNotFoundError("Open-core Tauri configuration was not published")


def _write_public_cargo_identity(output_dir: Path) -> None:
    cargo_toml = output_dir / "src-tauri" / "Cargo.toml"
    cargo_text = cargo_toml.read_text(encoding="utf-8")
    cargo_text, count = re.subn(
        r'(^\[package\][\s\S]*?^name\s*=\s*)"semantic-migration-workbench"',
        r'\g<1>"dummy-bi-engine"',
        cargo_text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1 and 'name = "dummy-bi-engine"' not in cargo_text:
        raise ValueError("Could not rewrite the public Cargo package name")
    cargo_text = re.sub(
        r'^description\s*=\s*"[^"]*"',
        'description = "Dummy BI Engine — desktop shell"',
        cargo_text,
        count=1,
        flags=re.MULTILINE,
    )
    cargo_text = re.sub(
        r'^license\s*=\s*"[^"]*"',
        'license = "AGPL-3.0-only"',
        cargo_text,
        count=1,
        flags=re.MULTILINE,
    )
    if not re.search(r'^homepage\s*=', cargo_text, flags=re.MULTILINE):
        cargo_text = re.sub(
            r'(^description\s*=.*$)',
            r'\1\nhomepage = "https://www.dummy-bi.com/engine"\nrepository = "https://github.com/TomNek/dummy-bi-engine"',
            cargo_text,
            count=1,
            flags=re.MULTILINE,
        )
    cargo_toml.write_text(cargo_text, encoding="utf-8")

    cargo_lock = output_dir / "src-tauri" / "Cargo.lock"
    lock_text = cargo_lock.read_text(encoding="utf-8")
    lock_text, count = re.subn(
        r'(\[\[package\]\]\r?\nname = )"semantic-migration-workbench"',
        r'\g<1>"dummy-bi-engine"',
        lock_text,
        count=1,
    )
    if count != 1 and 'name = "dummy-bi-engine"' not in lock_text:
        raise ValueError("Could not rewrite the public Cargo.lock package name")
    cargo_lock.write_text(lock_text, encoding="utf-8")


def publish(output_dir: Path, *, dry_run: bool = False) -> bool:
    files = collect_open_core_files()
    print(f"Open-core MVP files: {len(files)}")
    print(f"Output: {output_dir}")
    if dry_run:
        for rel in files:
            print(rel)
        return True

    resolved_output = output_dir.resolve()
    resolved_dist = (ROOT / "dist").resolve()
    if resolved_output == ROOT.resolve() or resolved_output == resolved_dist:
        raise ValueError("Refusing to overwrite the repository root or the whole dist directory")
    if output_dir.exists():
        def remove_readonly(function, path, _excinfo):
            os.chmod(path, stat.S_IWRITE)
            function(path)

        shutil.rmtree(output_dir, onexc=remove_readonly)
    output_dir.mkdir(parents=True, exist_ok=True)

    for rel in files:
        source = ROOT / rel
        destination = output_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    readme_source = ROOT / "README_OPEN_CORE.md"
    if not readme_source.is_file():
        readme_source = ROOT / "readme.md"
    shutil.copy2(readme_source, output_dir / "readme.md")
    _write_filtered_visual_registry(output_dir)
    _write_public_package(output_dir)
    _write_public_tauri_config(output_dir)
    _write_public_cargo_identity(output_dir)
    print(f"Created open-core MVP artifact at {output_dir}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return 0 if publish(args.output, dry_run=args.dry_run) else 1


if __name__ == "__main__":
    raise SystemExit(main())
