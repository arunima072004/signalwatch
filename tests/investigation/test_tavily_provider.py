"""tests/investigation/test_tavily_provider.py
Unit tests for TavilySearchProvider.
All tests mock the Tavily HTTP layer — no API key or network required.
Key test: 429 rate-limit retry/backoff behaviour.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch, call

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.search import SearchQuery, SearchResult
from src.models.hypothesis import HypothesisType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_query(text: str = "apple macbook sale August 2017") -> SearchQuery:
    return SearchQuery(
        query_id="q_test_001",
        event_id="evt_test",
        hypothesis_type=HypothesisType.PROMOTION.value,
        query_text=text,
        purpose="test",
        priority=1,
        generated_by="test",
        product_name="Apple MacBook",
        brand="Apple",
        merchant="Bestbuy.com",
        category="Electronics",
        date_window="August 2017",
    )


def _mock_tavily_response(title: str = "Test Result", url: str = "https://example.com/test"):
    """Fake Tavily API response dict."""
    return {
        "results": [
            {
                "title": title,
                "url": url,
                "content": "This is the snippet content for testing purposes.",
                "raw_content": None,
                "published_date": "2017-08-15",
            }
        ]
    }


# ---------------------------------------------------------------------------
# TavilySearchProvider construction
# ---------------------------------------------------------------------------

class TestTavilyProviderConstruction:

    def test_raises_without_api_key(self):
        """Constructor must raise if no API key is found."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.getenv", return_value=None):
                with pytest.raises(ValueError, match="TAVILY_API_KEY"):
                    from src.search.tavily_provider import TavilySearchProvider
                    TavilySearchProvider(api_key=None)

    def test_accepts_explicit_api_key(self):
        """Constructor succeeds when api_key is passed explicitly."""
        mock_client = MagicMock()
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key")
            assert provider.provider_name() == "tavily"

    def test_provider_name(self):
        mock_client = MagicMock()
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key")
            assert provider.provider_name() == "tavily"


# ---------------------------------------------------------------------------
# Normal search
# ---------------------------------------------------------------------------

class TestTavilyProviderSearch:

    def _make_provider(self):
        mock_client = MagicMock()
        mock_client.search.return_value = _mock_tavily_response()
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key")
            provider._client = mock_client
            return provider

    def test_search_returns_list_of_search_results(self):
        provider = self._make_provider()
        results = provider.search(_make_query(), num_results=5)
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_result_fields_populated(self):
        provider = self._make_provider()
        results = provider.search(_make_query(), num_results=5)
        r = results[0]
        assert r.url == "https://example.com/test"
        assert r.title == "Test Result"
        assert r.snippet == "This is the snippet content for testing purposes."
        assert r.source_domain == "example.com"
        assert r.provider == "tavily"
        assert r.query_id == "q_test_001"
        assert r.event_id == "evt_test"
        assert r.publication_date == "2017-08-15"

    def test_search_passes_query_text_to_client(self):
        provider = self._make_provider()
        q = _make_query("macbook discount August 2017")
        provider.search(q, num_results=5)
        provider._client.search.assert_called_once()
        call_kwargs = provider._client.search.call_args
        assert "macbook discount august 2017" in call_kwargs[1].get("query", "").lower() or                "macbook discount august 2017" in str(call_kwargs).lower()

    def test_empty_results_returns_empty_list(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key")
            provider._client = mock_client
            results = provider.search(_make_query(), num_results=5)
            assert results == []

    def test_search_depth_basic_used_by_default(self):
        mock_client = MagicMock()
        mock_client.search.return_value = _mock_tavily_response()
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key", search_depth="basic")
            provider._client = mock_client
            provider.search(_make_query(), num_results=5)
            call_kwargs = provider._client.search.call_args[1]
            assert call_kwargs.get("search_depth") == "basic"


# ---------------------------------------------------------------------------
# 429 rate-limit retry / backoff (the key real-world failure test)
# ---------------------------------------------------------------------------

class TestTavilyProvider429Retry:

    def test_429_retries_and_succeeds_on_third_attempt(self):
        """
        CRITICAL: 429 rate-limit on first 2 attempts, success on 3rd.
        Assert: returns results, does NOT raise, calls sleep twice.
        """
        mock_client = MagicMock()
        rate_limit_exc = Exception("429 Too Many Requests — rate limit exceeded")
        mock_client.search.side_effect = [
            rate_limit_exc,
            rate_limit_exc,
            _mock_tavily_response(),  # 3rd attempt succeeds
        ]

        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            with patch("src.search.tavily_provider.time.sleep") as mock_sleep:
                provider = TavilySearchProvider(api_key="tvly-test-key", max_retries=3)
                provider._client = mock_client
                results = provider.search(_make_query())

        # Must have returned results, not raised
        assert len(results) == 1
        assert results[0].url == "https://example.com/test"

        # Must have slept between retries (1s then 2s)
        assert mock_sleep.call_count == 2
        sleep_args = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_args[0] == 1   # first backoff
        assert sleep_args[1] == 2   # second backoff

        # Must have called the API 3 times
        assert mock_client.search.call_count == 3

    def test_429_all_retries_exhausted_returns_empty_not_raises(self):
        """
        If every attempt hits 429, must return [] silently rather than raising.
        The investigation pipeline must be able to continue with other queries.
        """
        mock_client = MagicMock()
        rate_limit_exc = Exception("429 Too Many Requests")
        mock_client.search.side_effect = [rate_limit_exc] * 4  # all fail

        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            with patch("src.search.tavily_provider.time.sleep"):
                provider = TavilySearchProvider(api_key="tvly-test-key", max_retries=3)
                provider._client = mock_client
                results = provider.search(_make_query())

        assert results == [], "Must return empty list, not raise"

    def test_503_transient_error_also_retries(self):
        """503 Service Unavailable should trigger the same retry logic as 429."""
        mock_client = MagicMock()
        transient_exc = Exception("503 Service Unavailable")
        mock_client.search.side_effect = [transient_exc, _mock_tavily_response()]

        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            with patch("src.search.tavily_provider.time.sleep") as mock_sleep:
                provider = TavilySearchProvider(api_key="tvly-test-key", max_retries=3)
                provider._client = mock_client
                results = provider.search(_make_query())

        assert len(results) == 1
        assert mock_sleep.call_count == 1  # one sleep between attempts

    def test_non_retryable_error_returns_empty_immediately(self):
        """A generic (non-429/503) exception returns [] without sleeping."""
        mock_client = MagicMock()
        mock_client.search.side_effect = ValueError("Unexpected error from API")

        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            with patch("src.search.tavily_provider.time.sleep") as mock_sleep:
                provider = TavilySearchProvider(api_key="tvly-test-key", max_retries=3)
                provider._client = mock_client
                results = provider.search(_make_query())

        assert results == []
        assert mock_sleep.call_count == 0  # no backoff for non-retryable errors
        assert mock_client.search.call_count == 1  # only one attempt


# ---------------------------------------------------------------------------
# get_page_content
# ---------------------------------------------------------------------------

class TestTavilyProviderPageContent:

    def test_get_page_content_returns_text(self):
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [{"raw_content": "<html>Real page content</html>", "content": "page text"}]
        }
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key")
            provider._client = mock_client
            content = provider.get_page_content("https://example.com/article")
            assert content is not None
            assert len(content) > 0

    def test_get_page_content_returns_none_on_failure(self):
        mock_client = MagicMock()
        mock_client.extract.side_effect = Exception("network error")
        with patch("src.search.tavily_provider.TavilySearchProvider._build_client", return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            provider = TavilySearchProvider(api_key="tvly-test-key")
            provider._client = mock_client
            content = provider.get_page_content("https://example.com/article")
            assert content is None


# ---------------------------------------------------------------------------
# exclude_domains configuration
# ---------------------------------------------------------------------------

class TestTavilyProviderExcludeDomains:

    def _make_provider(self, exclude_domains=None):
        mock_client = MagicMock()
        mock_client.search.return_value = {'results': []}
        with patch('src.search.tavily_provider.TavilySearchProvider._build_client', return_value=mock_client):
            from src.search.tavily_provider import TavilySearchProvider
            kwargs = {'api_key': 'tvly-test-key'}
            if exclude_domains is not None:
                kwargs['exclude_domains'] = exclude_domains
            provider = TavilySearchProvider(**kwargs)
            provider._client = mock_client
            return provider

    def test_default_exclude_list_contains_expected_domains(self):
        """Module-level default must include the eight noise domains."""
        from src.search.tavily_provider import _DEFAULT_EXCLUDE_DOMAINS
        expected = [
            'yelp.com', 'indeed.com', 'mapquest.com', 'rocketreach.co',
            'glassdoor.com', 'linkedin.com', 'zillow.com', 'yellowpages.com',
        ]
        for domain in expected:
            assert domain in _DEFAULT_EXCLUDE_DOMAINS, (
                f'{domain} missing from _DEFAULT_EXCLUDE_DOMAINS'
            )

    def test_exclude_domains_passed_to_client_by_default(self):
        """exclude_domains must be forwarded to TavilyClient.search() on every call."""
        provider = self._make_provider()
        provider.search(_make_query(), num_results=5)
        call_kwargs = provider._client.search.call_args[1]
        assert 'exclude_domains' in call_kwargs, (
            'exclude_domains not passed to TavilyClient.search()'
        )
        passed = call_kwargs['exclude_domains']
        assert passed is not None
        assert 'yelp.com' in passed
        assert 'indeed.com' in passed
        assert 'mapquest.com' in passed
        assert 'rocketreach.co' in passed

    def test_custom_exclude_list_overrides_default(self):
        """Caller-supplied list replaces the default entirely."""
        provider = self._make_provider(exclude_domains=['example.com', 'test.org'])
        provider.search(_make_query(), num_results=5)
        passed = provider._client.search.call_args[1]['exclude_domains']
        assert passed == ['example.com', 'test.org']
        assert 'yelp.com' not in passed  # default should NOT be present

    def test_empty_list_disables_exclusions(self):
        """Passing exclude_domains=[] should send None to the API (no exclusions)."""
        provider = self._make_provider(exclude_domains=[])
        provider.search(_make_query(), num_results=5)
        passed = provider._client.search.call_args[1].get('exclude_domains')
        assert passed is None, (
            'Empty exclude_domains list should result in None being passed to API'
        )

    def test_yelp_domain_excluded_sherwood_scenario(self):
        """
        Regression: Sherwood A/V receiver event pulled in yelp.com local-business
        listings because 'Sherwood' is also a place name.
        Assert yelp.com is in the default exclusion list so this cannot recur.
        """
        from src.search.tavily_provider import _DEFAULT_EXCLUDE_DOMAINS
        assert 'yelp.com' in _DEFAULT_EXCLUDE_DOMAINS, (
            'yelp.com must be excluded: Sherwood event pulled in Al Garden & Home, Sherwood OR'
        )

    def test_indeed_domain_excluded_sherwood_scenario(self):
        """
        Regression: Sherwood event pulled in indeed.com job listings for
        'Sherwood Food Distributors' — a completely unrelated company.
        """
        from src.search.tavily_provider import _DEFAULT_EXCLUDE_DOMAINS
        assert 'indeed.com' in _DEFAULT_EXCLUDE_DOMAINS, (
            'indeed.com must be excluded: Sherwood event pulled in job listings'
        )

    def test_mapquest_domain_excluded(self):
        """
        Regression: Sherwood event returned mapquest.com pharmacy directory pages
        because 'discount' in the query matched pharmacy discount listings.
        """
        from src.search.tavily_provider import _DEFAULT_EXCLUDE_DOMAINS
        assert 'mapquest.com' in _DEFAULT_EXCLUDE_DOMAINS
