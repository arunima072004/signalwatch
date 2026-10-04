"""
src/search/provider_interface.py
=================================
Abstract SearchProvider interface.

Investigators generate SearchQuery objects.
The SearchProvider executes them against the web (or mock).
These are SEPARATE responsibilities.

This interface abstracts over Google, SerpAPI, Tavily, Brave, etc.
Do NOT hard-code any provider here.
API keys must come from environment variables, never from source code.

NOT Channel3 - Channel3 is a future Phase 1 pricing-data source.
NOT RAG - no embeddings, no vector search.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from src.models.search import SearchQuery, SearchResult


class SearchProviderError(Exception):
    """Raised when a search provider fails after retries."""
    pass


class SearchProvider(ABC):
    """
    Abstract base for all web search providers.

    Implementations: MockSearchProvider, SerpAPIProvider, etc.
    """

    @abstractmethod
    def search(self, query: SearchQuery, num_results: int = 5) -> List[SearchResult]:
        """
        Execute a web search and return structured results.

        Args:
            query: Structured SearchQuery object (never a plain string)
            num_results: max results to return

        Returns:
            List of SearchResult objects, may be empty.

        Raises:
            SearchProviderError: on unrecoverable failure.
        """
        ...

    @abstractmethod
    def get_page_content(self, url: str) -> Optional[str]:
        """
        Fetch full HTML/text content of a URL.

        Returns None on failure — never raises.
        """
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Identifier string used in provenance tracking."""
        ...