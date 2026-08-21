"""Render result + SQL plan caches for the visual render pipeline.

Tier 2: Result cache — caches full render results so identical requests
        (same visual, role, filters, params) return instantly.
Tier 4: SQL plan cache — caches the DAX→SQL compilation output so
        `_ENGINE_LOCK` is skipped for repeated visual structures.

Both caches are TTL-based with bounded size.  They are process-local
(each uvicorn worker has its own cache), which is the correct behavior
for multi-worker deployments.

Thread safety: both caches are protected by their own `threading.Lock`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────

RESULT_CACHE_TTL: float = 300.0   # 5 minutes
RESULT_CACHE_MAX: int = 1000      # max entries per worker

SQL_CACHE_TTL: float = 600.0      # 10 minutes (plans change less often)
SQL_CACHE_MAX: int = 500           # max entries per worker


# ── Cache key helpers ────────────────────────────────────────

def _stable_hash(*parts: str) -> str:
    """SHA-256 of pipe-joined parts — deterministic cache key."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_fingerprint(obj: Any) -> str:
    """MD5 of canonical JSON — fast deterministic fingerprint for dicts/lists."""
    try:
        raw = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = repr(obj)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _filters_fingerprint(runtime_filters: list) -> str:
    """Fingerprint the runtime_filters list.

    ScopedFilter is a frozen dataclass; its repr is deterministic for
    identical field values.
    """
    if not runtime_filters:
        return "nofilters"
    parts = sorted(repr(f) for f in runtime_filters)
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


# ── Result Cache (Tier 2) ───────────────────────────────────

@dataclass
class _CacheEntry:
    expiry: float
    value: Any


class RenderResultCache:
    """TTL-bounded LRU cache for full visual render results.

    On hit, the entire render pipeline is skipped — instant response.
    """

    def __init__(self, ttl: float = RESULT_CACHE_TTL, max_size: int = RESULT_CACHE_MAX):
        self._ttl = ttl
        self._max_size = max_size
        self._store: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def build_key(
        self,
        *,
        visual_id: str,
        project_path: str,
        role: Optional[str],
        runtime_filters: list,
        visual_json: dict,
        engine_sig: tuple,
        drill_level: Optional[int] = None,
        drill_filters: Optional[list] = None,
    ) -> str:
        return _stable_hash(
            visual_id,
            project_path,
            role or "",
            _filters_fingerprint(runtime_filters),
            _json_fingerprint(visual_json),
            str(engine_sig),
            str(drill_level),
            _json_fingerprint(drill_filters) if drill_filters else "",
        )

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.monotonic() > entry.expiry:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            # Evict expired entries if at capacity
            if len(self._store) >= self._max_size:
                self._evict_expired()
            # If still at capacity, evict oldest 25%
            if len(self._store) >= self._max_size:
                to_remove = sorted(
                    self._store.keys(),
                    key=lambda k: self._store[k].expiry,
                )[:self._max_size // 4]
                for k in to_remove:
                    del self._store[k]
            self._store[key] = _CacheEntry(
                expiry=time.monotonic() + self._ttl,
                value=value,
            )

    def invalidate_all(self) -> None:
        """Clear the entire cache (e.g., on Save All / project reload)."""
        with self._lock:
            self._store.clear()

    def invalidate_project(self, project_path: str) -> None:
        """Clear cache entries for a specific project."""
        # Since project_path is embedded in the key hash, we can't easily
        # filter.  Just clear everything — safe and rare.
        self.invalidate_all()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if now > v.expiry]
        for k in expired:
            del self._store[k]

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
                "hit_rate": (
                    round(self._hits / (self._hits + self._misses) * 100, 1)
                    if (self._hits + self._misses) > 0 else 0
                ),
            }


# ── SQL Plan Cache (Tier 4) ─────────────────────────────────

@dataclass
class SQLPlanEntry:
    """Cached DAX→SQL compilation result."""
    sql: str
    table_ir: Any
    applied_filters_meta: list
    plan_ms: float  # original plan time (for reporting)


class SQLPlanCache:
    """TTL-bounded cache for compiled SQL plans.

    On hit, `_ENGINE_LOCK` is skipped — the cached SQL is executed
    directly against DuckDB.  This eliminates the main scalability
    bottleneck (serial DAX compilation).
    """

    def __init__(self, ttl: float = SQL_CACHE_TTL, max_size: int = SQL_CACHE_MAX):
        self._ttl = ttl
        self._max_size = max_size
        self._store: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def build_key(
        self,
        *,
        visual_id: str,
        project_path: str,
        role: Optional[str],
        runtime_filters: list,
        visual_json: dict,
        engine_sig: tuple,
        drill_level: Optional[int] = None,
        drill_filters: Optional[list] = None,
    ) -> str:
        """Same inputs as the result cache — if any input changes, SQL may differ."""
        return _stable_hash(
            "sql",
            visual_id,
            project_path,
            role or "",
            _filters_fingerprint(runtime_filters),
            _json_fingerprint(visual_json),
            str(engine_sig),
            str(drill_level),
            _json_fingerprint(drill_filters) if drill_filters else "",
        )

    def get(self, key: str) -> Optional[SQLPlanEntry]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.monotonic() > entry.expiry:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def put(self, key: str, entry: SQLPlanEntry) -> None:
        with self._lock:
            if len(self._store) >= self._max_size:
                self._evict_expired()
            if len(self._store) >= self._max_size:
                to_remove = sorted(
                    self._store.keys(),
                    key=lambda k: self._store[k].expiry,
                )[:self._max_size // 4]
                for k in to_remove:
                    del self._store[k]
            self._store[key] = _CacheEntry(
                expiry=time.monotonic() + self._ttl,
                value=entry,
            )

    def invalidate_all(self) -> None:
        with self._lock:
            self._store.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if now > v.expiry]
        for k in expired:
            del self._store[k]

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._store),
                "hit_rate": (
                    round(self._hits / (self._hits + self._misses) * 100, 1)
                    if (self._hits + self._misses) > 0 else 0
                ),
            }


# ── Module-level singletons ─────────────────────────────────

result_cache = RenderResultCache()
sql_cache = SQLPlanCache()


def get_cache_stats() -> dict[str, Any]:
    """Return combined cache statistics (exposed via /runtime/cache/stats)."""
    from dax_ui.server._scaling import get_active_tier_name

    return {
        "active_tier": get_active_tier_name(),
        "result_cache": result_cache.stats,
        "sql_cache": sql_cache.stats,
    }


def invalidate_all_caches() -> None:
    """Clear all caches (call on Save All, project switch, etc.)."""
    result_cache.invalidate_all()
    sql_cache.invalidate_all()
    logger.info("All render caches invalidated")
