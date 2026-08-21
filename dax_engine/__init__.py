"""dax_engine package.

This package contains the DAX → DuckDB SQL compiler implementation.
The legacy public API remains available via the top-level dax_compiler.py wrapper.
"""

from .compiler import *  # noqa: F401,F403
