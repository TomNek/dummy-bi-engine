"""Single source of truth for product and build information."""

import os

__product_name__ = "Dummy BI Engine"
__version__ = "0.2.4"

# Overridable via env var at build time (e.g., git hash injected by CI)
__build__ = os.environ.get("DAX_BUILD_HASH", "dev")
