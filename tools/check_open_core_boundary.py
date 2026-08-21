#!/usr/bin/env python3
"""
Open-Core Boundary Checker

Validates that:
1. Every tracked file is classified as COMMUNITY or ENTERPRISE in open_core_boundary.yml.
2. Community code does not import from Enterprise paths.

Usage:
    python tools/check_open_core_boundary.py [--strict]

Exit codes:
    0 — all checks pass
    1 — boundary violations found
"""

import argparse
import ast
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    # Fallback: parse the YAML manually for the paths we need
    yaml = None


ROOT = Path(__file__).resolve().parent.parent
BOUNDARY_FILE = ROOT / "open_core_boundary.yml"

# Enterprise import patterns to detect in community code
ENTERPRISE_IMPORT_PATTERNS = [
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.decision\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.explanations\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.autogen\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.licensing\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.licensing_keygen\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.licensing_trial\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.catalog_folders\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.catalog_git\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.catalog_index\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.deployment\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.attachment_renderer\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.financial\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.auth\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.report_server\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.report_definition\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.server_security\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.viewer\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.subscription_product\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.threshold_scheduler\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_engine\.demo\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_ui\.phase14_routes\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+dax_ui\.api_models\b", re.MULTILINE),
    re.compile(r"^[ \t]*(?:from|import)\s+enterprise\b", re.MULTILINE),
    re.compile(r"['\"/]enterprise/", re.MULTILINE),
]

# Directories and files to skip entirely
SKIP_DIRS = {
    ".git", ".venv", "__pycache__", "node_modules", "build", "dist",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "src-tauri",
    # Build reports / dev-only artifacts
    "reports", "debug", ".vscode",
    # QA sample projects (dev-only, not shipped)
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
SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".duckdb", ".duckdb.wal",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
    ".ttf", ".eot", ".map", ".lock", ".log",
}

SKIP_FILE_PREFIXES = ["_tmp_", "_debug", "_test_", ".tmp_"]


def _load_boundary_paths():
    """Load community, enterprise, and internal path lists from boundary YAML."""
    if yaml is not None:
        with open(BOUNDARY_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = data.get("edition_rules", {})
        community_paths = rules.get("community", {}).get("paths", [])
        community_excluded = rules.get("community", {}).get("excluded_patterns", [])
        enterprise_paths = rules.get("enterprise", {}).get("paths", [])
        internal_paths = rules.get("internal", {}).get("paths", [])
        return community_paths, community_excluded, enterprise_paths, internal_paths
    else:
        # Simple regex-based YAML parser for our specific format
        community_paths = []
        community_excluded = []
        enterprise_paths = []
        internal_paths = []
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
                if "internal:" in stripped:
                    current_section = "internal"
                    continue
                if "excluded_patterns:" in stripped:
                    current_list = "excluded"
                    continue
                if "paths:" in stripped:
                    current_list = "paths"
                    continue
                if stripped.startswith("- ") and current_list:
                    path = stripped[2:].strip()
                    if current_section == "community" and current_list == "paths":
                        community_paths.append(path)
                    elif current_section == "community" and current_list == "excluded":
                        community_excluded.append(path)
                    elif current_section == "enterprise" and current_list == "paths":
                        enterprise_paths.append(path)
                    elif current_section == "internal" and current_list == "paths":
                        internal_paths.append(path)

        return community_paths, community_excluded, enterprise_paths, internal_paths


def _matches_any_pattern(rel_path: str, patterns: list) -> bool:
    """Check if a relative path matches any glob pattern."""
    rel_posix = rel_path.replace("\\", "/")
    for pattern in patterns:
        if fnmatch.fnmatch(rel_posix, pattern):
            return True
        # Also check if the path starts with a directory pattern (e.g., "dax_parser/**")
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if rel_posix.startswith(prefix + "/") or rel_posix == prefix:
                return True
    return False


def _get_tracked_files():
    """Get tracked and non-ignored untracked source files in the worktree.

    Including untracked files keeps the pre-commit release gate honest: a new
    source file must be classified before it can quietly enter a release.
    """
    source_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json", ".md"}
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    files = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        rel = raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        path = Path(rel)
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in source_extensions:
            continue
        if any(path.name.startswith(prefix) for prefix in SKIP_FILE_PREFIXES):
            continue
        files.append(rel)
    return sorted(files)


def check_classification(strict: bool = False):
    """Check that all tracked files are classified."""
    community_paths, community_excluded, enterprise_paths, internal_paths = _load_boundary_paths()
    tracked = _get_tracked_files()

    unclassified = []
    conflicts = []
    counts = {"community": 0, "enterprise": 0, "internal": 0}
    for f in tracked:
        # Determine which tiers match
        in_community = _matches_any_pattern(f, community_paths) and not _matches_any_pattern(f, community_excluded)
        in_enterprise = (
            _matches_any_pattern(f, enterprise_paths)
            or (_matches_any_pattern(f, community_paths) and _matches_any_pattern(f, community_excluded))
        )
        in_internal = _matches_any_pattern(f, internal_paths)

        matched_tiers = []
        if in_community:
            matched_tiers.append("community")
        if in_enterprise:
            matched_tiers.append("enterprise")
        if in_internal:
            matched_tiers.append("internal")

        if len(matched_tiers) > 1:
            conflicts.append((f, matched_tiers))
            counts[matched_tiers[0]] += 1  # count first match for stats
        elif len(matched_tiers) == 1:
            counts[matched_tiers[0]] += 1
        else:
            unclassified.append(f)

    print(f"   Community:  {counts['community']}")
    print(f"   Enterprise: {counts['enterprise']}")
    print(f"   Internal:   {counts['internal']}")

    ok = True

    if conflicts:
        print(f"\n[FAIL] CONFLICT: {len(conflicts)} file(s) match multiple tiers:")
        print("   Each file must belong to exactly ONE tier.\n")
        for f, tiers in conflicts[:30]:
            print(f"   - {f}  ->  {', '.join(tiers)}")
        if len(conflicts) > 30:
            print(f"   ... and {len(conflicts) - 30} more")
        ok = False

    if unclassified:
        print(f"\n[FAIL] UNCLASSIFIED FILES ({len(unclassified)}):")
        print("   These files are not listed in open_core_boundary.yml.")
        print("   Each must be classified as COMMUNITY, ENTERPRISE, or INTERNAL.\n")
        for f in unclassified[:200]:  # Cap output
            print(f"   - {f}")
        if len(unclassified) > 200:
            print(f"   ... and {len(unclassified) - 200} more")
        ok = False

    if ok:
        print(f"[PASS] All {len(tracked)} tracked source files are classified (no conflicts).")
    return ok


def _get_guarded_import_lines(content: str) -> set[int]:
    """Return 1-based line numbers of imports guarded by try/except that catches ImportError.

    Uses the ``ast`` module to find all ``Try`` nodes whose handlers catch
    ``ImportError``, ``ModuleNotFoundError``, ``Exception``, or bare ``except:``.
    Any import/from-import statement inside the ``try`` body of such a node is
    considered guarded.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()

    _CAUGHT_NAMES = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}

    guarded: set[int] = set()

    def _catches_import_error(node: ast.Try) -> bool:
        for handler in node.handlers:
            if handler.type is None:
                # bare ``except:`` — catches everything
                return True
            if isinstance(handler.type, ast.Name) and handler.type.id in _CAUGHT_NAMES:
                return True
            if isinstance(handler.type, ast.Tuple):
                if any(
                    isinstance(elt, ast.Name) and elt.id in _CAUGHT_NAMES
                    for elt in handler.type.elts
                ):
                    return True
        return False

    def _collect_import_lines(stmts: list[ast.stmt], guarded_set: set[int]):
        """Recursively collect line numbers of import statements in *stmts*."""
        for stmt in stmts:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                # Multi-line imports span lineno..end_lineno
                end = stmt.end_lineno or stmt.lineno
                for ln in range(stmt.lineno, end + 1):
                    guarded_set.add(ln)
            # Recurse into nested blocks (if/for/with/try inside the try body)
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.stmt):
                    _collect_import_lines([child], guarded_set)
                elif isinstance(child, list):
                    _collect_import_lines(
                        [c for c in child if isinstance(c, ast.stmt)], guarded_set
                    )

    def _walk_for_try(node: ast.AST):
        """Walk the full AST looking for Try nodes that guard imports."""
        for child in ast.walk(node):
            if isinstance(child, ast.Try) and _catches_import_error(child):
                _collect_import_lines(child.body, guarded)

    _walk_for_try(tree)
    return guarded


def check_imports():
    """Check that community code does not import enterprise modules."""
    community_paths, community_excluded, enterprise_paths, internal_paths = _load_boundary_paths()

    violations = []

    for rel in _get_tracked_files():
        if not rel.endswith(".py"):
            continue
        full = ROOT / rel

        # Only check community files
        if not _matches_any_pattern(rel, community_paths):
            continue
        # Skip files that are in the excluded list (enterprise components in community paths)
        if _matches_any_pattern(rel, community_excluded):
            continue

        try:
            content = open(full, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            continue

        guarded_lines = _get_guarded_import_lines(content)

        for pattern in ENTERPRISE_IMPORT_PATTERNS:
            for match in pattern.finditer(content):
                line_num = content[:match.start()].count("\n") + 1
                if line_num in guarded_lines:
                    continue
                violations.append((rel, match.group().strip()))

    if violations:
        print(f"\n[FAIL] ENTERPRISE IMPORT VIOLATIONS ({len(violations)}):")
        print("   Community code must NOT import from enterprise modules.\n")
        for filepath, imp in violations[:30]:
            print(f"   {filepath}: {imp}")
        if len(violations) > 30:
            print(f"   ... and {len(violations) - 30} more")
        return False
    else:
        print("[PASS] No enterprise imports found in community code.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Open-Core Boundary Checker")
    parser.add_argument("--strict", action="store_true",
                        help="Treat unclassified files as errors (exit 1)")
    args = parser.parse_args()

    print("=" * 60)
    print("Open-Core Boundary Check")
    print("=" * 60)

    ok = True
    ok = check_classification(strict=args.strict) and ok
    ok = check_imports() and ok

    print("\n" + "=" * 60)
    if ok:
        print("[PASS] All boundary checks passed.")
    else:
        print("[FAIL] Boundary violations found. See above.")
    print("=" * 60)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
