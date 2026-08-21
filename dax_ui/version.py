"""Single source of truth for product and build information."""

import os

__product_name__ = "Semantic Migration Workbench"
__version__ = "0.1.0"

# Overridable via env var at build time (e.g., git hash injected by CI)
__build__ = os.environ.get("DAX_BUILD_HASH", "dev")
