"""Compatibility wrapper.

The compiler implementation lives in dax_engine/*.
This module re-exports the public API to keep existing imports working.
"""

from dax_engine.compiler import *  # noqa: F401,F403
from dax_engine.registry import *  # noqa: F401,F403
from dax_engine.relationships import *  # noqa: F401,F403
from dax_engine.context import *  # noqa: F401,F403
from dax_engine.ir import *  # noqa: F401,F403
