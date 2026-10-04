"""
src/search/mock_provider.py
============================
MockSearchProvider - a deterministic test double for SearchProvider.

Returns canned results based on keyword patterns in the query text.
No network calls, no API keys, no internet required.

Usage:
    provider = MockSearchProvider()
    results = provider.search(query)

    # Custom scenarios:
    provider = MockSearchProvider(scenario="empty")   # always empty
    provider = MockSearchProvider(scenario="failure") # always raises
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from src.models.search import SearchQuery, SearchResult, make_result_id
from src.search.provider_interface import SearchProvider, SearchProviderError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canned result library — realistic-looking mock data
# ---------------------------------------------------------------------------

_MOCK_RESULTS: Dict[str, List[Dict]] = {
    "sale": [
        {
            "title": "Best Buy Summer Sale: Up to 30% off Apple MacBooks",
            "url": "https://www.bestbuy.com/site/promotions/summer-sale",
            "snippet": "Best Buy is offering up to 30% off select MacBook models during the Summer 2017 sale event running August 13-20.",
            "domain": "bestbuy.com",
            "pub_date": "2017-08-13",
        },
        {
            "title": "Apple MacBook Deals August 2017 - Best Buy",
            "url": "https://www.bestbuy.com/site/apple/macbook/deals",
            "snippet": "Save on the Apple MacBook 12-inch. Price reduced from $1499.99 to $1099.99 for a limited time.",
            "domain": "bestbuy.com",
            "pub_date": "2017-08-14",
        },
    ],
    "promotion": [
        {
            "title": "Best Buy Back to School Promotions 2017",
            "url": "https://www.bestbuy.com/back-to-school-2017",
            "snippet": "Best Buy launches back-to-school promotions with discounts on laptops and tablets through August 2017.",
            "domain": "bestbuy.com",
            "pub_date": "2017-08-01",
        },
    ],
    "discount": [
        {
            "title": "Apple MacBook 12 Discounted at Best Buy",
            "url": "https://9to5mac.com/2017/08/macbook-discount-bestbuy",
            "snippet": "Best Buy is discounting the Apple MacBook 12-inch (MLHF2LL/A) by $400, bringing the price to $1099.99.",
            "domain": "9to5mac.com",
            "pub_date": "2017-08-15",
        },
    ],
    "macbook": [
        {
            "title": "Apple MacBook 12-inch Review 2017",
            "url": "https://www.theverge.com/2017/apple-macbook-12-review",
            "snippet": "The Apple MacBook 12-inch remains a compelling ultraportable, though pricing is a point of debate.",
            "domain": "theverge.com",
            "pub_date": "2017-05-10",
        },
    ],
    "back to school": [
        {
            "title": "Back to School Tech Deals 2017",
            "url": "https://www.cnet.com/news/back-to-school-tech-deals-2017",
            "snippet": "Retailers including Best Buy and Amazon are offering back-to-school discounts on laptops and tablets during August 2017.",
            "domain": "cnet.com",
            "pub_date": "2017-08-05",
        },
    ],
    "competitor": [
        {
            "title": "Laptop Price Wars: Best Buy vs Amazon vs Costco",
            "url": "https://www.pcmag.com/news/laptop-price-competition-2017",
            "snippet": "Major retailers are competing on laptop pricing as the back-to-school season heats up.",
            "domain": "pcmag.com",
            "pub_date": "2017-08-10",
        },
    ],


    "price drop": [
        {
            "title": "Apple MacBook Price Drop at Amazon August 2017",
            "url": "https://www.amazon.com/dp/B01EIUGCN6/macbook-deal",
            "snippet": "Amazon has reduced the Apple MacBook 12-inch Core m5 price to 1199 dollars in August 2017.",
            "domain": "amazon.com",
            "pub_date": "2017-08-17",
        },
    ],
    "price comparison": [
        {
            "title": "Apple MacBook 12 Prices Compared: Best Buy, Amazon, Walmart",
            "url": "https://www.rtings.com/laptops/apple-macbook-2017-price",
            "snippet": "Best Buy lists the MacBook at 1099 dollars, Amazon at 1199 dollars, Walmart at 1149 during August 2017.",
            "domain": "rtings.com",
            "pub_date": "2017-08-18",
        },
    ],
    "price competition": [
        {
            "title": "Retailer Price Competition MacBook August 2017",
            "url": "https://www.anandtech.com/show/retailer-competition-2017",
            "snippet": "Multiple retailers including Amazon and Best Buy are competing on MacBook pricing during August 2017.",
            "domain": "anandtech.com",
            "pub_date": "2017-08-14",
        },
    ],
    "discontinued": [
        {
            "title": "Apple MacBook 12-inch Discontinued by Apple",
            "url": "https://www.macrumors.com/2019/07/09/apple-discontinues-12-inch-macbook/",
            "snippet": "Apple has discontinued the 12-inch MacBook from its lineup. The product page has been removed from Apple's website.",
            "domain": "macrumors.com",
            "pub_date": "2019-07-09",
        },
        {
            "title": "MacBook 12 Discontinued Stock Clearance at Best Buy",
            "url": "https://9to5mac.com/2019/07/10/macbook-12-discontinued-clearance",
            "snippet": "Following Apple's discontinuation of the MacBook 12-inch, Best Buy is clearing remaining inventory at reduced prices.",
            "domain": "9to5mac.com",
            "pub_date": "2019-07-10",
        },
    ],
    "successor": [
        {
            "title": "Apple MacBook Air Successor Announced at WWDC",
            "url": "https://www.theverge.com/2018/10/30/18044962/apple-macbook-air-2018-announced",
            "snippet": "Apple announced the new MacBook Air as the successor to the MacBook 12-inch, replacing the older model in the lineup.",
            "domain": "theverge.com",
            "pub_date": "2018-10-30",
        },
    ],
    "replacement model": [
        {
            "title": "Apple MacBook 12 Replacement Model Review",
            "url": "https://www.pcmag.com/reviews/apple-macbook-air-2018",
            "snippet": "The 2018 MacBook Air is effectively the replacement model for the discontinued MacBook 12-inch, offering better performance.",
            "domain": "pcmag.com",
            "pub_date": "2018-11-01",
        },
    ],
    "new release": [
        {
            "title": "Apple New MacBook Release Date and Price",
            "url": "https://9to5mac.com/2017/06/apple-macbook-new-release-2017",
            "snippet": "Apple's new MacBook release in 2017 features a refreshed processor lineup. The 12-inch model is available in three configurations.",
            "domain": "9to5mac.com",
            "pub_date": "2017-06-05",
        },
    ],
    "recall": [
        {
            "title": "Apple Recall Notice for MacBook Battery",
            "url": "https://www.apple.com/support/macbook-battery-recall",
            "snippet": "Apple issued a voluntary recall for certain MacBook batteries that may pose a fire safety risk. Affected models include select 2015-2017 units.",
            "domain": "apple.com",
            "pub_date": "2017-09-20",
        },
    ],
    "product lifecycle": [
        {
            "title": "Apple MacBook Product Lifecycle and Roadmap 2017",
            "url": "https://www.macrumors.com/guide/macbook-lifecycle-2017",
            "snippet": "Analysis of Apple MacBook product lifecycle indicates the 12-inch model is approaching end-of-life as Apple focuses on MacBook Pro and Air.",
            "domain": "macrumors.com",
            "pub_date": "2017-08-01",
        },
    ],
    "shortage": [
        {
            "title": "MacBook Supply Shortage Due to Component Issues",
            "url": "https://www.bloomberg.com/news/articles/macbook-supply-chain-shortage-2017",
            "snippet": "Apple is experiencing a supply shortage for certain MacBook components, causing limited availability at some retailers.",
            "domain": "bloomberg.com",
            "pub_date": "2017-07-15",
        },
    ],
    "clearance": [
        {
            "title": "Best Buy MacBook Clearance Sale August 2017",
            "url": "https://www.bestbuy.com/site/clearance/macbook",
            "snippet": "Best Buy is running a clearance event on MacBook models, with select configurations marked down to clear existing inventory.",
            "domain": "bestbuy.com",
            "pub_date": "2017-08-12",
        },
    ],
    "out of stock": [
        {
            "title": "Apple MacBook 12 Out of Stock at Major Retailers",
            "url": "https://www.cnet.com/news/apple-macbook-12-out-of-stock-2017",
            "snippet": "The Apple MacBook 12-inch is currently out of stock at Best Buy and Amazon, suggesting supply constraints or discontinuation.",
            "domain": "cnet.com",
            "pub_date": "2017-08-05",
        },
    ],
    "retailer": [
        {
            "title": "Best Buy Retailer Promotions Back to School 2017",
            "url": "https://www.bestbuy.com/site/promotions/back-to-school-2017",
            "snippet": "Best Buy is running retailer-wide back-to-school promotions with discounts across laptops, tablets, and accessories in August 2017.",
            "domain": "bestbuy.com",
            "pub_date": "2017-08-01",
        },
    ],
    "site-wide": [
        {
            "title": "Best Buy Site-Wide Summer Sale Event 2017",
            "url": "https://www.bestbuy.com/promotions/summer-sale-2017",
            "snippet": "Best Buy is hosting a site-wide summer sale event with storewide discounts from August 10-20, 2017.",
            "domain": "bestbuy.com",
            "pub_date": "2017-08-10",
        },
    ],
    "industry": [
        {
            "title": "Consumer Electronics Industry Report Q3 2017",
            "url": "https://www.idc.com/getdoc.jsp?containerId=prUS42894417",
            "snippet": "The consumer electronics industry saw shifting demand in Q3 2017, with laptop prices declining amid tablet and smartphone competition.",
            "domain": "idc.com",
            "pub_date": "2017-08-28",
        },
    ],
    "market trends": [
        {
            "title": "Laptop Market Trends and Price Outlook 2017",
            "url": "https://www.gartner.com/en/newsroom/pc-market-2017",
            "snippet": "Gartner reports that laptop market trends show declining average selling prices as vendors compete for back-to-school consumers in 2017.",
            "domain": "gartner.com",
            "pub_date": "2017-08-20",
        },
    ],
    "supply chain": [
        {
            "title": "Apple Supply Chain Updates Affect MacBook Pricing",
            "url": "https://www.reuters.com/article/apple-supply-chain-2017",
            "snippet": "Changes in Apple's supply chain for the MacBook 12-inch are reflected in recent retail pricing adjustments by major retailers.",
            "domain": "reuters.com",
            "pub_date": "2017-08-11",
        },
    ],
    "tariff": [
        {
            "title": "Electronics Tariffs Impact on Laptop Prices 2017",
            "url": "https://www.wsj.com/articles/tariff-impact-electronics-2017",
            "snippet": "Trade tariff considerations are affecting the consumer electronics market, with some laptop manufacturers adjusting pricing strategies.",
            "domain": "wsj.com",
            "pub_date": "2017-08-08",
        },
    ],
    "inflation": [
        {
            "title": "Consumer Electronics Price Inflation Trends 2017",
            "url": "https://www.bloomberg.com/news/articles/consumer-electronics-inflation",
            "snippet": "Consumer electronics prices are showing mixed signals in 2017, with some segments experiencing deflation while others face inflationary pressure.",
            "domain": "bloomberg.com",
            "pub_date": "2017-08-03",
        },
    ],
    "back to school": [
        {
            "title": "Back to School Tech Deals 2017",
            "url": "https://www.cnet.com/news/back-to-school-tech-deals-2017",
            "snippet": "Retailers including Best Buy and Amazon are offering back-to-school discounts on laptops and tablets during August 2017.",
            "domain": "cnet.com",
            "pub_date": "2017-08-05",
        },
    ],
}
_DEFAULT_RESULT = {
    "title": "No specific results found",
    "url": "https://example.com/no-results",
    "snippet": "No closely matching content found for this query.",
    "domain": "example.com",
    "pub_date": None,
}


class MockSearchProvider(SearchProvider):
    """
    Deterministic test double.  No network calls.

    Scenarios:
      "normal"  (default) - returns canned results based on keyword matching
      "empty"             - always returns []
      "failure"           - always raises SearchProviderError
    """

    def __init__(self, scenario: str = "normal") -> None:
        self.scenario = scenario
        self.call_count = 0
        self.query_history: List[str] = []

    def provider_name(self) -> str:
        return "mock"

    def search(self, query: SearchQuery, num_results: int = 5) -> List[SearchResult]:
        self.call_count += 1
        self.query_history.append(query.query_text)
        now = datetime.now(timezone.utc).isoformat()

        if self.scenario == "failure":
            raise SearchProviderError("Mock provider configured to fail")

        if self.scenario == "empty":
            logger.debug("MockSearchProvider: returning empty results (empty scenario)")
            return []

        # Pattern match against canned results
        q_lower = query.query_text.lower()
        matched: List[Dict] = []

        for keyword, results in _MOCK_RESULTS.items():
            if keyword in q_lower:
                for r in results:
                    if r not in matched:
                        matched.append(r)

        if not matched:
            matched = [_DEFAULT_RESULT]

        out: List[SearchResult] = []
        for raw in matched[:num_results]:
            result_id = make_result_id(query.query_id, raw["url"])
            out.append(SearchResult(
                result_id=result_id,
                query_id=query.query_id,
                event_id=query.event_id,
                title=raw["title"],
                url=raw["url"],
                snippet=raw["snippet"],
                source_domain=raw["domain"],
                retrieved_at=now,
                provider=self.provider_name(),
                full_content=None,
                publication_date=raw.get("pub_date"),
            ))

        logger.debug(
            "MockSearchProvider: query=%r returned %d results",
            query.query_text, len(out)
        )
        return out

    def get_page_content(self, url: str) -> Optional[str]:
        if self.scenario == "failure":
            return None
        domain = urlparse(url).netloc
        return f"<html><body><p>Mock page content for {domain}. This is a simulated web page.</p></body></html>"