#!/usr/bin/env python3
"""
Publish Community Repo

Copies only the community-allowed paths from the current repository
into a clean `dist/community_repo/` folder, suitable for publishing
as the noncommercial source-available edition.

Usage:
    python tools/publish_community_repo.py [--output dist/community_repo]
    python tools/publish_community_repo.py --dry-run

This script:
1. Reads open_core_boundary.yml for community paths and excluded patterns.
2. Copies matching files into the output directory.
3. Skips enterprise-only files and excluded patterns.
4. Reports what was copied and what was skipped.

NOTE: This is a copy-only tool. It does NOT push to any remote repository.
"""

import argparse
import fnmatch
import os
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
BOUNDARY_FILE = ROOT / "open_core_boundary.yml"
DEFAULT_OUTPUT = ROOT / "dist" / "community_repo"

# Always skip these regardless of boundary config
ALWAYS_SKIP_DIRS = {
    ".git", ".venv", "__pycache__", "node_modules", "build", "dist",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "src-tauri",
    # Build artifacts / reports
    "reports",
    # Debug artifacts
    "debug",
    # Enterprise sample projects
    "accounting_project", "ibcs_project", "perf_project",
    # Enterprise placeholder
    "enterprise",
    # QA sample projects (dev-only)
    "sample_project_qa_di_a1", "sample_project_qa_di_a2", "sample_project_qa_di_a3",
    "sample_project_qa_edu_a2",
    "sample_project_qa_full_a1", "sample_project_qa_full_a2", "sample_project_qa_full_a3",
    "sample_project_qa_full_a4", "sample_project_qa_full_a5", "sample_project_qa_full_a6",
    "sample_project_qa_full_a6_overlay",
    "sample_project_qa_nf_a1", "sample_project_qa_nf_a2", "sample_project_qa_nf_a3",
    "sample_project_qa_nf_a4", "sample_project_qa_nf_a5", "sample_project_qa_nf_a6",
    "sample_project_qa_nf_a7", "sample_project_qa_nf_a8", "sample_project_qa_nf_a9",
    "sample_project_qa_phase18_holdout_overlay_a1",
    "sample_project_qa_test",
    "sample_project_qa_ut1", "sample_project_qa_ut2", "sample_project_qa_ut3",
}

ALWAYS_SKIP_FILES = {
    ".duckdb", ".duckdb.wal",
}

ALWAYS_SKIP_PREFIXES = [
    "_debug", "_tmp_", "_test_",
]

ALWAYS_SKIP_EXTENSIONS = {
    ".log",
}


def _load_boundary():
    """Load community paths and excluded patterns from boundary YAML."""
    if yaml is not None:
        with open(BOUNDARY_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = data.get("edition_rules", {})
        community = rules.get("community", {})
        return community.get("paths", []), community.get("excluded_patterns", [])
    else:
        # Fallback regex parser
        community_paths = []
        community_excluded = []
        current_section = None
        current_list = None
        with open(BOUNDARY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "community:" in stripped and "excluded" not in stripped:
                    current_section = "community"
                    continue
                if "enterprise:" in stripped:
                    current_section = "enterprise"
                    continue
                if "excluded_patterns:" in stripped:
                    current_list = "excluded"
                    continue
                if "paths:" in stripped:
                    current_list = "paths"
                    continue
                if stripped.startswith("- ") and current_section == "community" and current_list:
                    path = stripped[2:].strip()
                    if current_list == "paths":
                        community_paths.append(path)
                    elif current_list == "excluded":
                        community_excluded.append(path)
        return community_paths, community_excluded


def _matches_any_pattern(rel_path: str, patterns: list) -> bool:
    """Check if a relative path matches any glob pattern."""
    rel_posix = rel_path.replace("\\", "/")
    for pattern in patterns:
        if fnmatch.fnmatch(rel_posix, pattern):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if rel_posix.startswith(prefix + "/") or rel_posix == prefix:
                return True
    return False


def _should_skip_dir(dirname: str) -> bool:
    """Check if directory should always be skipped."""
    return dirname in ALWAYS_SKIP_DIRS


def _should_skip_file(filename: str) -> bool:
    """Check if file should always be skipped."""
    if filename in ALWAYS_SKIP_FILES:
        return True
    for prefix in ALWAYS_SKIP_PREFIXES:
        if filename.startswith(prefix):
            return True
    ext = os.path.splitext(filename)[1]
    if ext in ALWAYS_SKIP_EXTENSIONS:
        return True
    return False


def collect_community_files():
    """Collect all files that belong to the community edition."""
    community_paths, excluded_patterns = _load_boundary()
    community_files = []
    skipped_files = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Filter out always-skip dirs
        dirnames[:] = sorted(d for d in dirnames if not _should_skip_dir(d))

        for fname in filenames:
            if _should_skip_file(fname):
                continue

            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")

            # Check if excluded (enterprise component in community path)
            if _matches_any_pattern(rel, excluded_patterns):
                skipped_files.append((rel, "excluded (enterprise component)"))
                continue

            # Check if in community paths
            if _matches_any_pattern(rel, community_paths):
                community_files.append(rel)
            else:
                skipped_files.append((rel, "not in community paths"))

    return sorted(community_files), sorted(skipped_files, key=lambda x: x[0])


def publish(output_dir: Path, dry_run: bool = False):
    """Copy community files to output directory."""
    community_files, skipped_files = collect_community_files()

    print(f"Community files: {len(community_files)}")
    print(f"Skipped files:   {len(skipped_files)}")
    print(f"Output:          {output_dir}")
    print()

    if dry_run:
        print("=== DRY RUN — no files will be copied ===\n")
        print("Would copy:")
        for f in community_files[:30]:
            print(f"  ✅ {f}")
        if len(community_files) > 30:
            print(f"  ... and {len(community_files) - 30} more")

        print("\nWould skip:")
        for f, reason in skipped_files[:20]:
            print(f"  ⏭️  {f} ({reason})")
        if len(skipped_files) > 20:
            print(f"  ... and {len(skipped_files) - 20} more")
        return True

    # Clean output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    errors = 0
    for rel in community_files:
        src = ROOT / rel
        # Rename README_community.md → readme.md in the artifact
        if rel == "README_community.md":
            dst = output_dir / "readme.md"
        else:
            dst = output_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        except Exception as e:
            print(f"  ❌ Error copying {rel}: {e}")
            errors += 1

    print(f"\n✅ Copied {copied} files to {output_dir}")
    if errors:
        print(f"❌ {errors} errors occurred")
        return False

    # Verify the output has key community files
    key_files = [
        "LICENSE",
        "readme.md",
        "requirements.txt",
        "dax_engine/compiler.py",
        "dax_engine/ir.py",
        "semantic_model_loader.py",
    ]
    missing_key = [f for f in key_files if not (output_dir / f).exists()]
    if missing_key:
        print(f"\n⚠️  Missing key community files in output:")
        for f in missing_key:
            print(f"   - {f}")
    else:
        print("✅ All key community files present in output.")

    return errors == 0


def main():
    parser = argparse.ArgumentParser(description="Publish Community Repo")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be copied without copying")
    args = parser.parse_args()

    print("=" * 60)
    print("Publish Community Repo")
    print("=" * 60)

    ok = publish(args.output, dry_run=args.dry_run)

    print("\n" + "=" * 60)
    if ok:
        print("✅ Community repo published successfully.")
    else:
        print("❌ Errors occurred during publish.")
    print("=" * 60)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
