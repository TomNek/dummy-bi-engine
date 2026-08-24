#!/usr/bin/env python3
"""Reject incomplete or non-portable open-core frontend build artifacts."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REQUIRED_CSS_TOKENS = (
    ".flex{",
    ".h-screen{",
    ".w-full{",
    ".bg-background{",
    ".text-xs{",
    ".border-b{",
)


def validate(build_dir: Path) -> list[str]:
    build_dir = build_dir.resolve()
    errors: list[str] = []
    index_path = build_dir / "index.html"
    if not index_path.is_file():
        return [f"Missing frontend entry point: {index_path}"]

    html = index_path.read_text(encoding="utf-8")
    if "<title>Dummy BI Engine</title>" not in html:
        errors.append("Compiled frontend title is not Dummy BI Engine")
    refs = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html)
    local_refs = [ref for ref in refs if not re.match(r"^[a-z]+:", ref, re.IGNORECASE)]
    for ref in local_refs:
        if not ref.startswith("/"):
            errors.append(f"Compiled frontend asset is not rooted at the backend origin: {ref}")
        target = build_dir / ref.lstrip("./")
        if not target.is_file():
            errors.append(f"Compiled frontend references a missing asset: {ref}")

    stylesheets = [build_dir / ref.lstrip("./") for ref in local_refs if ref.endswith(".css")]
    if not stylesheets:
        errors.append("Compiled frontend does not reference a stylesheet")
    else:
        css = "\n".join(path.read_text(encoding="utf-8") for path in stylesheets if path.is_file())
        if len(css.encode("utf-8")) < 50_000:
            errors.append("Compiled stylesheet is unexpectedly small; shared Tailwind sources were likely skipped")
        for token in REQUIRED_CSS_TOKENS:
            if token not in css:
                errors.append(f"Compiled stylesheet is missing required utility: {token[:-1]}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    errors = validate(args.build_dir)
    if errors:
        print("Open-core frontend build validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Open-core frontend build validated: {args.build_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
