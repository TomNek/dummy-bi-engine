#!/usr/bin/env python3
"""Create a Tauri v2 static updater manifest for a signed Windows installer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote


def create_manifest(
    installer: Path,
    signature: Path,
    *,
    version: str,
    repository: str,
    tag: str,
    output: Path,
    notes: str = "A new Semantic Migration Workbench version is available.",
) -> Path:
    if not installer.is_file():
        raise FileNotFoundError(installer)
    if not signature.is_file():
        raise FileNotFoundError(signature)
    if repository.count("/") != 1:
        raise ValueError("repository must be owner/name")

    payload = {
        "version": version,
        "notes": notes,
        "platforms": {
            "windows-x86_64": {
                "signature": signature.read_text(encoding="utf-8").strip(),
                "url": (
                    f"https://github.com/{repository}/releases/download/"
                    f"{quote(tag, safe='')}/{quote(installer.name, safe='')}"
                ),
            }
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--notes", default="A new Semantic Migration Workbench version is available.")
    args = parser.parse_args()
    print(create_manifest(
        args.installer,
        args.signature,
        version=args.version,
        repository=args.repository,
        tag=args.tag,
        output=args.output,
        notes=args.notes,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
