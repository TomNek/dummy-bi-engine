"""Deployment scaling rules — auto-select optimal server configuration.

Defines tier-based deployment profiles derived from benchmark data:

  Tier   Users    Workers  Nodes  Cache TTL  Cache Max  Best for
  ─────  ───────  ───────  ─────  ─────────  ─────────  ─────────────────────
  small  1-10     1        1      300s       1000       Desktop / dev
  medium 10-50    4        1      300s       2000       Team / department
  large  50-200   4        2      600s       5000       Organization
  xl     200-500  8        2      900s       10000      Enterprise / public

Each tier is a frozen dataclass defining all tunable parameters.
The auto-selector picks the right tier based on ``--expected-users``.

Usage:
    from dax_ui.server._scaling import select_tier, ScalingTier

    tier = select_tier(expected_users=100)
    tier.workers   # 4
    tier.nodes     # 2
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScalingTier:
    """Immutable deployment profile."""

    name: str
    max_users: int          # upper bound of recommended user range
    workers: int            # uvicorn --workers N
    nodes: int              # independent server instances (behind LB)
    result_cache_ttl: float # seconds
    result_cache_max: int   # entries per worker
    sql_cache_ttl: float    # seconds
    sql_cache_max: int      # entries per worker
    batch_pool_size: int    # threads in the per-process render pool
    description: str


# ── Tier definitions (derived from benchmark data) ───────────

TIER_SMALL = ScalingTier(
    name="small",
    max_users=10,
    workers=1,
    nodes=1,
    result_cache_ttl=300.0,
    result_cache_max=1000,
    sql_cache_ttl=600.0,
    sql_cache_max=500,
    batch_pool_size=4,
    description="Desktop / dev — single process, caching enabled",
)

TIER_MEDIUM = ScalingTier(
    name="medium",
    max_users=50,
    workers=4,
    nodes=1,
    result_cache_ttl=300.0,
    result_cache_max=2000,
    sql_cache_ttl=600.0,
    sql_cache_max=1000,
    batch_pool_size=4,
    description="Team / department — multi-worker, single node",
)

TIER_LARGE = ScalingTier(
    name="large",
    max_users=200,
    workers=4,
    nodes=2,
    result_cache_ttl=600.0,
    result_cache_max=5000,
    sql_cache_ttl=900.0,
    sql_cache_max=2000,
    batch_pool_size=6,
    description="Organization — multi-worker + multi-node",
)

TIER_XL = ScalingTier(
    name="xl",
    max_users=500,
    workers=8,
    nodes=2,
    result_cache_ttl=900.0,
    result_cache_max=10000,
    sql_cache_ttl=1200.0,
    sql_cache_max=5000,
    batch_pool_size=8,
    description="Enterprise / public — max parallelism",
)

ALL_TIERS = [TIER_SMALL, TIER_MEDIUM, TIER_LARGE, TIER_XL]
TIERS_BY_NAME = {t.name: t for t in ALL_TIERS}


# ── Auto-selector ───────────────────────────────────────────

def select_tier(
    expected_users: int = 0,
    tier_name: Optional[str] = None,
) -> ScalingTier:
    """Pick the optimal scaling tier.

    Priority:
      1. Explicit tier name (``--scale-tier small``)
      2. ``DAX_SCALE_TIER`` env var
      3. ``DAX_EXPECTED_USERS`` env var
      4. ``expected_users`` argument
      5. Default: ``small``
    """
    # 1. Explicit name
    if tier_name:
        return TIERS_BY_NAME.get(tier_name.lower(), TIER_SMALL)

    # 2. Env var — tier name
    env_tier = os.environ.get("DAX_SCALE_TIER", "").strip().lower()
    if env_tier and env_tier in TIERS_BY_NAME:
        return TIERS_BY_NAME[env_tier]

    # 3. Env var — expected users
    env_users = os.environ.get("DAX_EXPECTED_USERS", "").strip()
    if env_users.isdigit():
        expected_users = int(env_users)

    # 4. Auto-select by user count
    if expected_users > 0:
        for tier in ALL_TIERS:
            if expected_users <= tier.max_users:
                return tier
        return TIER_XL  # above all tiers → use largest

    # 5. Default
    return TIER_SMALL


def apply_tier(tier: ScalingTier) -> None:
    """Apply a scaling tier's cache settings to the running process.

    Call this at server startup (before requests arrive) to configure
    the render cache and SQL plan cache with tier-appropriate limits.
    """
    from dax_ui.server._render_cache import result_cache, sql_cache

    result_cache._ttl = tier.result_cache_ttl
    result_cache._max_size = tier.result_cache_max
    sql_cache._ttl = tier.sql_cache_ttl
    sql_cache._max_size = tier.sql_cache_max

    # Store the active tier for /runtime/cache/stats
    os.environ["_DAX_ACTIVE_TIER"] = tier.name


def get_active_tier_name() -> str:
    """Return the name of the currently active scaling tier."""
    return os.environ.get("_DAX_ACTIVE_TIER", "small")


def format_tier_table() -> str:
    """Return a human-readable table of all available tiers."""
    lines = [
        "Available scaling tiers:",
        "",
        f"  {'Tier':<8} {'Users':<10} {'Workers':<9} {'Nodes':<7} "
        f"{'Cache TTL':<11} {'Cache Max':<11} {'Description'}",
        f"  {'─'*8} {'─'*10} {'─'*9} {'─'*7} {'─'*11} {'─'*11} {'─'*30}",
    ]
    for t in ALL_TIERS:
        lines.append(
            f"  {t.name:<8} ≤{t.max_users:<9} {t.workers:<9} {t.nodes:<7} "
            f"{t.result_cache_ttl:>6.0f}s     {t.result_cache_max:<11} {t.description}"
        )
    return "\n".join(lines)
