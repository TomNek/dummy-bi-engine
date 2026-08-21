#!/usr/bin/env python3
"""Synchronize an open-core release version across Python, npm, and Tauri."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def set_version(root: Path, version: str) -> list[Path]:
    version = version.strip().removeprefix("v")
    if not VERSION_RE.fullmatch(version):
        raise ValueError("Version must look like 1.2.3, optionally with prerelease/build metadata")

    changed: list[Path] = []
    version_py = root / "dax_ui" / "version.py"
    text = version_py.read_text(encoding="utf-8")
    version_pattern = re.compile(r'^__version__\s*=\s*"[^"]+"', flags=re.MULTILINE)
    if version_pattern.search(text) is None:
        raise ValueError(f"Could not locate __version__ in {version_py}")
    updated = version_pattern.sub(f'__version__ = "{version}"', text, count=1)
    version_py.write_text(updated, encoding="utf-8")
    changed.append(version_py)

    for name in ("package.json", "package-lock.json"):
        path = root / "dax_ui" / "frontend" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = version
        if name == "package-lock.json" and isinstance(payload.get("packages", {}).get(""), dict):
            payload["packages"][""]["version"] = version
        _write_json(path, payload)
        changed.append(path)

    config_candidates = [
        root / "src-tauri" / "tauri.open-core.conf.json",
        root / "src-tauri" / "tauri.conf.json",
    ]
    config_path = next((path for path in config_candidates if path.is_file()), None)
    if config_path is None:
        raise FileNotFoundError("No open-core Tauri configuration found")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["version"] = version
    _write_json(config_path, config)
    changed.append(config_path)

    cargo_toml = root / "src-tauri" / "Cargo.toml"
    cargo_text = cargo_toml.read_text(encoding="utf-8")
    cargo_pattern = re.compile(
        r'(^\[package\][\s\S]*?^version\s*=\s*)"[^"]+"',
        flags=re.MULTILINE,
    )
    if cargo_pattern.search(cargo_text) is None:
        raise ValueError(f"Could not locate package version in {cargo_toml}")
    cargo_updated = cargo_pattern.sub(rf'\g<1>"{version}"', cargo_text, count=1)
    cargo_toml.write_text(cargo_updated, encoding="utf-8")
    changed.append(cargo_toml)

    cargo_lock = root / "src-tauri" / "Cargo.lock"
    lock_text = cargo_lock.read_text(encoding="utf-8")
    lock_pattern = re.compile(
        r'(\[\[package\]\]\r?\nname = "(?:semantic-migration-workbench|dax-to-sql-open-core|dummy-bi-engine)"\r?\nversion = )"[^"]+"',
    )
    if lock_pattern.search(lock_text) is None:
        raise ValueError(f"Could not locate root package version in {cargo_lock}")
    lock_updated = lock_pattern.sub(rf'\g<1>"{version}"', lock_text, count=1)
    cargo_lock.write_text(lock_updated, encoding="utf-8")
    changed.append(cargo_lock)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    for path in set_version(args.root.resolve(), args.version):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
