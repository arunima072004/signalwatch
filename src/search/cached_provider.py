"""
src/search/cached_provider.py
==============================
CachedSearchProvider — wraps any SearchProvider with a disk-backed cache.

Cache layout:
    data/search_cache/<sha256_of_query_text>.json

Behaviour:
    - On a cache HIT  : deserialize and return cached SearchResult list immediately
    - On a cache MISS : call the underlying provider, write the result, return it
    - --force flag    : skip cache on miss check (handled by passing force=True to search())

This allows one real-API run to populate the cache; all subsequent runs
(CI, demo, grading) run without touching the API.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from src.models.search import SearchQuery, SearchResult
from src.search.provider_interface import SearchProvider

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path("data/search_cache")


class CachedSearchProvider(SearchProvider):
    """
    Transparent caching wrapper around any SearchProvider.

    Parameters
    ----------
    underlying : SearchProvider
        The real provider to call on a cache miss (e.g. TavilySearchProvider).
        May be None — if so, cache misses return [] instead of hitting the API.
        This lets you run in offline mode with a pre-populated cache.
    cache_dir : Path, optional
        Directory for cache JSON files. Defaults to data/search_cache/.
    force : bool
        If True, bypass cache reads and always call the underlying provider.
        Useful for refreshing specific queries.
    """

    def __init__(
        self,
        underlying: Optional[SearchProvider] = None,
        cache_dir: Optional[Path] = None,
        force: bool = False,
    ) -> None:
        self._underlying = underlying
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._force = force
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    def provider_name(self) -> str:
        under = self._underlying.provider_name() if self._underlying else "none"
        return f"cached({under})"

    # ------------------------------------------------------------------
    # Cache key
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(query_text: str) -> str:
        """Deterministic cache key: SHA-256 of lowercased query text."""
        return hashlib.sha256(query_text.strip().lower().encode()).hexdigest()

    def _cache_path(self, query_text: str) -> Path:
        return self._cache_dir / (self._cache_key(query_text) + ".json")

    # ------------------------------------------------------------------
    # SearchProvider interface
    # ------------------------------------------------------------------

    def search(self, query: SearchQuery, num_results: int = 5) -> List[SearchResult]:
        cache_path = self._cache_path(query.query_text)

        # Cache read
        if not self._force and cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                results = [SearchResult.from_dict(r) for r in raw]
                # Patch query_id and event_id in case query context changed
                for r in results:
                    r.query_id = query.query_id
                    r.event_id = query.event_id
                self._hits += 1
                logger.debug(
                    "CachedSearchProvider: HIT  %s -> %d results",
                    cache_path.name[:16], len(results),
                )
                return results
            except Exception as exc:
                logger.warning("Cache read failed for %s: %s — refetching", cache_path, exc)

        # Cache miss — call underlying provider
        self._misses += 1
        logger.debug("CachedSearchProvider: MISS %s", cache_path.name[:16])

        if self._underlying is None:
            logger.warning(
                "CachedSearchProvider: no underlying provider and cache miss "
                "for %r — returning []", query.query_text[:60],
            )
            return []

        results = self._underlying.search(query, num_results=num_results)

        # Write to cache
        try:
            cache_path.write_text(
                json.dumps([r.to_dict() for r in results], indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Cache write failed for %s: %s", cache_path, exc)

        return results

    def get_page_content(self, url: str) -> Optional[str]:
        """Pass through to underlying provider — page content is not cached."""
        if self._underlying:
            return self._underlying.get_page_content(url)
        return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def cache_stats(self) -> dict:
        """Return hit/miss counts for the current session."""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
            "cache_dir": str(self._cache_dir),
            "cache_files": len(list(self._cache_dir.glob("*.json"))),
        }
