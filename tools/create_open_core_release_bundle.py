#!/usr/bin/env python3
"""Create a deterministic, checksummed open-core Windows release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dax_ui.version import __version__


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def create_bundle(installer: Path, output_dir: Path, version: str = __version__) -> tuple[Path, Path]:
    installer = installer.resolve()
    if not installer.is_file():
        raise FileNotFoundError(installer)
    output_dir.mkdir(parents=True, exist_ok=True)
    installer_bytes = installer.read_bytes()
    manifest = {
        "artifact": installer.name,
        "bytes": len(installer_bytes),
        "platform": "windows-x64",
        "product": "DAX to SQL Open Core",
        "profile": "open-core-mvp",
        "sha256": _sha256(installer_bytes),
        "source_date_epoch": int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")),
        "version": version,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    sums = (
        f"{manifest['sha256']}  {installer.name}\n"
        f"{_sha256(manifest_bytes)}  release-manifest.json\n"
    ).encode("ascii")
    safe_version = version.replace("+", "-")
    bundle = output_dir / f"DAX-to-SQL-Open-Core-{safe_version}-windows-x64.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(
            {installer.name: installer_bytes, "release-manifest.json": manifest_bytes, "SHA256SUMS.txt": sums}.items()
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    checksum = bundle.with_suffix(bundle.suffix + ".sha256")
    checksum.write_text(f"{_sha256(bundle.read_bytes())}  {bundle.name}\n", encoding="ascii", newline="\n")
    return bundle, checksum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist" / "open-core-release")
    parser.add_argument("--version", default=__version__)
    args = parser.parse_args()
    bundle, checksum = create_bundle(args.installer, args.output_dir, args.version)
    print(bundle)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
