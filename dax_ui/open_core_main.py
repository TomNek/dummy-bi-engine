"""Desktop/server launcher for the public open-core application."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import sys

from dax_project.open_core_profile import OPEN_CORE_PROFILE, PROFILE_ENV_VAR


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((host, 0))
        return int(server.getsockname()[1])


def _configure_project(workspace: str) -> None:
    if workspace:
        os.environ["DAX_PROJECT_PATH"] = workspace
        return
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    sample = bundle_root / "sample_project"
    if sample.is_dir():
        os.environ.setdefault("DAX_PROJECT_PATH", str(sample))


def main() -> int:
    parser = argparse.ArgumentParser(description="DAX to SQL Open Core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--auth-token", default="")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--mode", default="author", choices=["author", "server"])
    parser.add_argument("--log-level", default="warning")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    os.environ[PROFILE_ENV_VAR] = OPEN_CORE_PROFILE
    os.environ["DAX_SERVER_MODE"] = args.mode
    if args.auth_token:
        os.environ["DAX_DESKTOP_TOKEN"] = args.auth_token
    _configure_project(args.workspace)

    from dax_ui.open_core_app import app

    if args.self_test:
        import duckdb  # noqa: F401
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401

        assert app is not None
        print("[self-test] PASS - open-core imports and app are ready")
        return 0

    port = args.port or _find_free_port(args.host)
    print(f"PORT={port}", flush=True)
    import uvicorn

    uvicorn.run(app, host=args.host, port=port, log_level=args.log_level, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
