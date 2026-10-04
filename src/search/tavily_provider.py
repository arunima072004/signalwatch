"""
src/search/tavily_provider.py
==============================
TavilySearchProvider — concrete SearchProvider implementation using the Tavily API.

Docs:     https://docs.tavily.com
Free tier: 1,000 credits/month (no credit card required)
Cost:      1 credit per basic search

Usage:
    export TAVILY_API_KEY=tvly-...
    provider = TavilySearchProvider()

Retry policy: up to 3 attempts with exponential backoff (1s, 2s, 4s)
on HTTP 429 (rate limit) and 503 (service unavailable).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from src.models.search import SearchQuery, SearchResult, make_result_id
from src.search.provider_interface import SearchProvider, SearchProviderError

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RESULTS = 5
_DEFAULT_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]   # sleep durations between retries

# Default domains to exclude from search results.
# These sites consistently return irrelevant results for product-pricing queries:
#   - job boards (indeed.com) match on brand names that are also company names
#   - local business directories (yelp.com, yellowpages.com, mapquest.com) match
#     on brand names that are also place names (e.g. "Sherwood")
#   - people-search / company-profile sites (rocketreach.co, linkedin.com,
#     glassdoor.com, zillow.com) add noise with no pricing evidence
_DEFAULT_EXCLUDE_DOMAINS: List[str] = [
    "yelp.com",
    "indeed.com",
    "mapquest.com",
    "rocketreach.co",
    "glassdoor.com",
    "linkedin.com",
    "zillow.com",
    "yellowpages.com",
]


class TavilySearchProvider(SearchProvider):
    """
    SearchProvider backed by the Tavily Search API.

    Requires:
        pip install tavily-python>=0.5.0
        TAVILY_API_KEY environment variable

    Parameters
    ----------
    api_key : str, optional
        Tavily API key.  Defaults to os.getenv("TAVILY_API_KEY").
    search_depth : str
        "basic"    — 1 credit/query, fast, sufficient for focused queries
        "advanced" — 2 credits/query, deeper coverage
    max_retries : int
        Number of retry attempts on 429/503.  Default: 3.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        search_depth: str = "basic",
        max_retries: int = _DEFAULT_MAX_RETRIES,
        exclude_domains: Optional[List[str]] = None,
    ) -> None:
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self._api_key:
            raise ValueError(
                "Tavily API key not found. "
                "Set the TAVILY_API_KEY environment variable or pass api_key= explicitly."
            )
        self._search_depth = search_depth
        self._max_retries = max_retries
        # Use caller-supplied list, or fall back to the module-level default.
        # Pass an empty list [] to disable exclusions entirely.
        self._exclude_domains: List[str] = (
            exclude_domains if exclude_domains is not None else _DEFAULT_EXCLUDE_DOMAINS
        )
        self._client = self._build_client()

    def _build_client(self):
        """Lazy-import tavily so the module can be imported without the package installed."""
        try:
            from tavily import TavilyClient  # type: ignore
            return TavilyClient(api_key=self._api_key)
        except ImportError:
            raise ImportError(
                "tavily-python is required for TavilySearchProvider. "
                "Install it with: pip install tavily-python>=0.5.0"
            )

    def provider_name(self) -> str:
        return "tavily"

    # ------------------------------------------------------------------
    # SearchProvider interface
    # ------------------------------------------------------------------

    def search(self, query: SearchQuery, num_results: int = _DEFAULT_MAX_RESULTS) -> List[SearchResult]:
        """
        Execute a search against the Tavily API.

        Retries up to self._max_retries times on rate-limit (429) or
        transient (503) errors, with exponential backoff.

        Returns an empty list (not an exception) if all retries fail,
        so the investigation pipeline can continue with other queries.
        """
        now = datetime.now(timezone.utc).isoformat()
        last_exc: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.search(
                    query=query.query_text,
                    max_results=num_results,
                    search_depth=self._search_depth,
                    exclude_domains=self._exclude_domains if self._exclude_domains else None,
                )
                return self._normalize_results(response, query, now)

            except Exception as exc:
                exc_str = str(exc).lower()
                is_rate_limit = "429" in exc_str or "rate limit" in exc_str or "too many" in exc_str
                is_transient  = "503" in exc_str or "service unavailable" in exc_str or "timeout" in exc_str

                if (is_rate_limit or is_transient) and attempt < self._max_retries:
                    sleep_s = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                    logger.warning(
                        "TavilySearchProvider: %s on attempt %d/%d for query %r — "
                        "retrying in %ds",
                        "rate limit (429)" if is_rate_limit else "transient error",
                        attempt + 1, self._max_retries + 1,
                        query.query_text[:60],
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    last_exc = exc
                    continue

                # Non-retryable error or final attempt — log and return empty
                logger.error(
                    "TavilySearchProvider: search failed for query %r: %s",
                    query.query_text[:60], exc,
                )
                last_exc = exc
                break

        # All retries exhausted — return empty rather than crashing the pipeline
        logger.warning(
            "TavilySearchProvider: returning 0 results for query %r after %d attempt(s). "
            "Last error: %s",
            query.query_text[:60], self._max_retries + 1, last_exc,
        )
        return []

    def get_page_content(self, url: str) -> Optional[str]:
        """
        Fetch full HTML/text content of a URL via Tavily Extract.
        Returns None on failure — never raises.
        """
        try:
            response = self._client.extract(urls=[url])
            results = response.get("results", [])
            if results:
                return results[0].get("raw_content") or results[0].get("content")
            return None
        except Exception as exc:
            logger.warning("TavilySearchProvider.get_page_content(%r) failed: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_results(
        self, response: dict, query: SearchQuery, retrieved_at: str
    ) -> List[SearchResult]:
        """Convert Tavily API response dict to List[SearchResult]."""
        results: List[SearchResult] = []
        raw_results = response.get("results", [])

        for item in raw_results:
            url = item.get("url", "")
            if not url:
                continue

            domain = urlparse(url).netloc or "unknown"
            result_id = make_result_id(query.query_id, url)

            results.append(SearchResult(
                result_id=result_id,
                query_id=query.query_id,
                event_id=query.event_id,
                title=item.get("title", ""),
                url=url,
                snippet=item.get("content", ""),
                source_domain=domain,
                retrieved_at=retrieved_at,
                provider=self.provider_name(),
                full_content=item.get("raw_content") or None,
                publication_date=item.get("published_date") or None,
            ))

        logger.debug(
            "TavilySearchProvider: query=%r depth=%s -> %d results",
            query.query_text[:60], self._search_depth, len(results),
        )
        return results
