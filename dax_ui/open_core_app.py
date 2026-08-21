"""ASGI entry point for the deliberately small open-core MVP.

Run with::

    uvicorn dax_ui.open_core_app:app --host 127.0.0.1 --port 8000

Setting the profile before importing the server makes the public allowlists
effective even when callers invoke endpoints directly instead of using the UI.
"""

from __future__ import annotations

import os

from dax_project.open_core_profile import OPEN_CORE_PROFILE, PROFILE_ENV_VAR

os.environ.setdefault(PROFILE_ENV_VAR, OPEN_CORE_PROFILE)

from dax_ui.server import app  # noqa: E402  (profile must be set first)

__all__ = ["app"]
