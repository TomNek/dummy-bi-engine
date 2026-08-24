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
EXCLUDED_IMPLEMENTATION_FILES = {
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
    "dax_project/tmdl_converter.py",
    "dax_engine/subscription_product.py",
    "dax_engine/threshold_scheduler.py",
}
PUBLIC_TESTS = {
    "tests/conftest.py",
    "tests/test_compiler_mapping_load.py",
    "tests/test_connectors.py",
    "tests/test_runtime_import_connectors.py",
    "tests/test_semantic_model_loader_duckdb.py",
    "tests/test_semantic_model_validation.py",
    "tests/test_open_core_mvp.py",
    "tests/test_open_core_frontend_e2e.py",
}
PUBLIC_TOOLS = {
    "tools/check_open_core_boundary.py",
    "tools/create_open_core_release_bundle.py",
    "tools/create_tauri_updater_manifest.py",
    "tools/publish_community_repo.py",
    "tools/publish_open_core_mvp.py",
    "tools/set_open_core_release_version.py",
    "tools/smoke_packaged_backend.ps1",
    "tools/smoke_windows_installer.ps1",
    "tools/validate_open_core_frontend_build.py",
    "tools/validate_open_core_mvp.py",
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
        if rel in EXCLUDED_IMPLEMENTATION_FILES or rel.startswith(EXCLUDED_IMPLEMENTATION_PREFIXES):
            continue
        if rel.startswith(FRONTEND_ROOT) and any(
            part in {"node_modules", "dist", "dist-open-core", "build"}
            for part in Path(rel).parts
        ):
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
        if rel.startswith(".github/workflows/") and rel != ".github/workflows/open-core-ci.yml":
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


def _write_excluded_feature_stubs(output_dir: Path) -> None:
    """Keep shared-shell imports buildable without publishing excluded implementations."""

    frontend_stubs = {
        "src/components/autogen/index.ts": """export function AutogenWizard() { return null }\n""",
        "src/components/autogen/EDUSubWizard.tsx": """
export type EDUConfig = Record<string, unknown>
export function EDUSubWizard(_props: Record<string, unknown>) { return null }
""",
        "src/components/stories/index.ts": """
export function StoryViewer(_props: Record<string, unknown>) { return null }
export function StoryEditor(_props: Record<string, unknown>) { return null }
""",
        "src/components/power-query/TransformStudio.tsx": """
export function TransformStudio() { return null }
""",
        "src/components/explanations/index.ts": """
export function EDUDiagram(_props: Record<string, unknown>) { return null }
export function MLAnalyticsPanel(_props: Record<string, unknown>) { return null }
""",
        "src/components/subscriptions/SubscriptionList.tsx": """
export function SubscriptionList(_props: Record<string, unknown>) { return null }
""",
        "src/components/model/PlaybookEditor.tsx": """
export function PlaybookEditor(_props: Record<string, unknown>) { return null }
""",
        "src/components/model/TmdlImportWizard.tsx": """
export function TmdlImportWizard(_props: Record<string, unknown>) { return null }
""",
        "src/components/model/ReportImportWizard.tsx": """
export function ReportImportWizard(_props: Record<string, unknown>) { return null }
""",
        "src/stores/autogen-store.ts": """
export interface AutogenState { setOpen: (open: boolean) => void }
const state: AutogenState = { setOpen: () => undefined }
export const useAutogenStore = Object.assign(
  <T>(selector: (value: AutogenState) => T): T => selector(state),
  { getState: () => state },
)
""",
        "src/stores/ml-store.ts": """
export type MLActivity = Record<string, unknown>
export interface MLState {
  loadRegimeChanges: (...args: unknown[]) => Promise<void>
  hasRegimeChanges: (...args: unknown[]) => boolean
}
const state: MLState = {
  loadRegimeChanges: async () => undefined,
  hasRegimeChanges: () => false,
}
export const useMLStore = <T>(selector: (value: MLState) => T): T => selector(state)
""",
        "src/stores/story-store.ts": """
export interface StoryState { presentingStoryId: string | null }
const state: StoryState = { presentingStoryId: null }
export const useStoryStore = <T>(selector: (value: StoryState) => T): T => selector(state)
""",
        "src/stores/subscription-store.ts": """
export type SubscriptionState = Record<string, never>
const state: SubscriptionState = {}
export const useSubscriptionStore = <T>(selector: (value: SubscriptionState) => T): T => selector(state)
""",
        "src/stores/server-store.ts": """
export type ServerState = Record<string, never>
const state: ServerState = {}
export const useServerStore = <T>(selector: (value: ServerState) => T): T => selector(state)
""",
        "src/hooks/useStories.ts": """
export type UseStoriesReturn = Record<string, never>
export function useStories(): UseStoriesReturn { return {} }
""",
    }
    frontend = output_dir / "dax_ui" / "frontend"
    for relative, content in frontend_stubs.items():
        target = frontend / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// Open-core compatibility stub.\n" + content.strip() + "\n", encoding="utf-8")

    server_stubs = {
        "dax_ui/server/_routes_story.py": "def register_story_routes(app):\n    return None\n",
        "dax_ui/server/_routes_tmdl.py": "def register_tmdl_converter_routes(app):\n    return None\n",
    }
    for relative, content in server_stubs.items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Open-core compatibility stub.\n" + content, encoding="utf-8")


def _strip_excluded_backend_exports(output_dir: Path) -> None:
    package_init = output_dir / "dax_project" / "__init__.py"
    text = package_init.read_text(encoding="utf-8")
    text, count = re.subn(
        r"\nfrom \.power_query import \(  # noqa: F401\n(?:    .*\n)+?\)\n",
        "\n",
        text,
        count=1,
    )
    if count != 1 and "from .power_query import" in text:
        raise ValueError("Could not remove Transform Studio exports from public dax_project package")
    excluded_names = {
        "MCompatibilityReport", "MDiagnostic", "MQuery", "MSourceMapping", "MStep",
        "build_power_query_metadata", "build_power_query_report", "map_source_from_m", "parse_m_query",
    }
    text = "\n".join(
        line for line in text.splitlines()
        if not any(f'"{name}"' in line for name in excluded_names)
    ) + "\n"
    package_init.write_text(text, encoding="utf-8")


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
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    vite = output_dir / "dax_ui" / "frontend" / "vite.open-core.config.ts"
    vite.write_text(vite.read_text(encoding="utf-8").replace("'dist-open-core'", "'dist'"), encoding="utf-8")


def _strip_excluded_sample_pages(output_dir: Path) -> None:
    pages_path = output_dir / "sample_project" / "reports" / "pages.yaml"
    if not pages_path.is_file():
        return
    payload = yaml.safe_load(pages_path.read_text(encoding="utf-8")) or {}
    pages = payload.get("pages", [])
    story_ids = {str(page.get("id")) for page in pages if page.get("page_type") == "story"}
    payload["pages"] = [page for page in pages if page.get("page_type") != "story"]
    pages_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

    visuals_dir = pages_path.parent / "visuals"
    for visual_path in visuals_dir.glob("*.json") if visuals_dir.is_dir() else []:
        try:
            visual = json.loads(visual_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(visual.get("page_id") or "") in story_ids:
            visual_path.unlink()


def _write_public_tauri_config(output_dir: Path) -> None:
    tauri_dir = output_dir / "src-tauri"
    source = tauri_dir / "tauri.open-core.conf.json"
    target = tauri_dir / "tauri.conf.json"
    if source.is_file():
        shutil.copy2(source, target)
        source.unlink()
    elif not target.is_file():
        raise FileNotFoundError("Open-core Tauri configuration was not published")
    config = json.loads(target.read_text(encoding="utf-8"))
    config.setdefault("build", {})["frontendDist"] = "../dax_ui/frontend/dist"
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _write_public_cargo_identity(output_dir: Path) -> None:
    cargo_toml = output_dir / "src-tauri" / "Cargo.toml"
    cargo_text = cargo_toml.read_text(encoding="utf-8")
    cargo_text, count = re.subn(
        r'(^\[package\][\s\S]*?^name\s*=\s*)"(?:semantic-migration-workbench|dummy-bi-engine)"',
        r'\g<1>"dummy-bi-engine"',
        cargo_text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1 and 'name = "dummy-bi-engine"' not in cargo_text:
        raise ValueError("Could not rewrite the public Cargo package name")
    # Keep the published package identity aligned with the desktop product.
    cargo_text = re.sub(
        r'^description\s*=\s*"[^"]*"',
        'description = "Dummy BI Engine — open-core desktop shell"',
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
    if not re.search(r'^repository\s*=', cargo_text, flags=re.MULTILINE):
        cargo_text = re.sub(
            r'(^description\s*=.*$)',
            r'\1\nrepository = "https://github.com/TomNek/dummy-bi-engine"',
            cargo_text,
            count=1,
            flags=re.MULTILINE,
        )
    if not re.search(r'^homepage\s*=', cargo_text, flags=re.MULTILINE):
        cargo_text = re.sub(
            r'(^repository\s*=.*$)',
            r'\1\nhomepage = "https://www.dummy-bi.com/engine"',
            cargo_text,
            count=1,
            flags=re.MULTILINE,
        )
    cargo_toml.write_text(cargo_text, encoding="utf-8")

    cargo_lock = output_dir / "src-tauri" / "Cargo.lock"
    lock_text = cargo_lock.read_text(encoding="utf-8")
    lock_text, count = re.subn(
        r'(\[\[package\]\]\r?\nname = )"(?:semantic-migration-workbench|dummy-bi-engine)"',
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
    shutil.copy2(readme_source, output_dir / "README.md")
    _write_filtered_visual_registry(output_dir)
    _write_excluded_feature_stubs(output_dir)
    _strip_excluded_backend_exports(output_dir)
    _strip_excluded_sample_pages(output_dir)
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
