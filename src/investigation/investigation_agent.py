"""
src/investigation/investigation_agent.py
=========================================
InvestigationAgent with six explicit strategies.

Architecture: option (a) — a Strategy enum with six concrete InvestigationStrategy
classes, each implementing only generate_queries(). The investigate_event() workflow
loop lives exclusively in InvestigationAgent, never duplicated per-strategy.
This keeps each strategy's query logic cleanly testable in isolation while
eliminating the per-agent workflow duplication that was ~80% shared code.

Strategy → HypothesisType mapping:
  PromotionStrategy      -> PROMOTION
  CompetitorStrategy     -> COMPETITOR_RESPONSE
  ProductEventStrategy   -> PRODUCT_EVENT, MANUFACTURER_CHANGE
  NewsStrategy           -> MARKET_EVENT
  RetailerEventStrategy  -> SEASONAL_EVENT
  SupplyStrategy         -> INVENTORY_LIQUIDATION
  DATA_ISSUE             -> no investigation (skipped)
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.events.event_generator import ChangeEvent
from src.evidence.extractor import EvidenceExtractor
from src.models.evidence import Evidence
from src.models.hypothesis import Hypothesis, HypothesisType
from src.models.search import SearchQuery
from src.search.provider_interface import SearchProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities (module-level, used by multiple strategies)
# ---------------------------------------------------------------------------

def _qid(event_id: str, suffix: str) -> str:
    """Deterministic query ID from event_id and suffix."""
    raw = event_id + "|" + suffix
    return "q_" + hashlib.sha256(raw.encode()).hexdigest()[:10]


def _date_window(observed_at: str) -> str:
    """Return human-readable date window: 'August 2017'."""
    try:
        parts = observed_at[:10].split("-")
        dt = date(int(parts[0]), int(parts[1]), int(parts[2]))
        return dt.strftime("%B %Y")
    except Exception:
        return observed_at[:7]


# Alias for clarity
_month_year = _date_window


def _year(observed_at: str) -> str:
    """Return just the 4-digit year: '2017'."""
    try:
        return observed_at[:4]
    except Exception:
        return ""


def _brand_prefix(brand: str, product: str) -> str:
    """
    Return 'Brand ' prefix only when product name does not already start with brand.
    Prevents 'Apple Apple MacBook' duplication.
    """
    if brand and not product.lower().startswith(brand.lower()):
        return brand + " "
    return ""


def _best_identifier(event: ChangeEvent) -> Optional[str]:
    """
    Return the most specific available product identifier, or None.
    Preference order: manufacturer_number > ASIN > UPC.
    Never invents one.
    """
    if event.manufacturer_number and event.manufacturer_number.strip():
        return event.manufacturer_number.strip()
    if event.asins and event.asins.strip():
        return event.asins.strip()
    if event.upc and event.upc.strip():
        return event.upc.strip()
    return None


def _make_query(
    event: ChangeEvent,
    hypothesis: Hypothesis,
    suffix: str,
    text: str,
    purpose: str,
    priority: int,
    generated_by: str,
) -> SearchQuery:
    """Factory for SearchQuery with consistent fields."""
    dw = _date_window(event.observed_at)
    return SearchQuery(
        query_id=_qid(event.event_id, suffix),
        event_id=event.event_id,
        hypothesis_type=hypothesis.hypothesis_type.value,
        query_text=text,
        purpose=purpose,
        priority=priority,
        generated_by=generated_by,
        product_name=event.product_name,
        brand=event.brand,
        merchant=event.merchant,
        category=event.category,
        date_window=dw,
        asin=event.asins or None,
        upc=event.upc or None,
        manufacturer_number=event.manufacturer_number or None,
    )


# ---------------------------------------------------------------------------
# Strategy abstract base class
# ---------------------------------------------------------------------------

class InvestigationStrategy(ABC):
    """
    Abstract base for all investigation strategies.
    Each concrete subclass implements only generate_queries().
    The investigation workflow loop is owned by InvestigationAgent.
    """

    @abstractmethod
    def generate_queries(
        self, event: ChangeEvent, hypothesis: Hypothesis
    ) -> List[SearchQuery]:
        """Generate 3-5 targeted SearchQuery objects for this strategy."""
        ...

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Human-readable strategy identifier."""
        ...


# ---------------------------------------------------------------------------
# Six concrete strategy implementations
# ---------------------------------------------------------------------------

class PromotionStrategy(InvestigationStrategy):
    """
    Investigates PROMOTION hypotheses.

    Searches for product-specific discounts, coupons, and promotions at the
    specific merchant around the event date. Does NOT cover merchant-wide events
    (that is RetailerEventStrategy).

    Keywords: sale, discount, promo, promotion, deal, offer, coupon, off,
              markdown, clearance price
    """

    @property
    def strategy_name(self) -> str:
        return "PromotionStrategy"

    def generate_queries(self, event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        dw = _date_window(event.observed_at)
        product = event.product_name.strip()
        brand = event.brand.strip()
        merchant_short = event.merchant.replace(".com", "").replace(".co.uk", "").strip()

        def _q(suffix: str, text: str, purpose: str, priority: int) -> SearchQuery:
            return _make_query(event, hypothesis, suffix, text, purpose, priority, self.strategy_name)

        queries: List[SearchQuery] = []

        # Q1: Product + merchant + sale + date (most targeted)
        queries.append(_q(
            "promo_1",
            f"{product} {merchant_short} sale {dw}",
            f"Find product-specific promotional pricing at {event.merchant} around the event date",
            1,
        ))

        # Q2: Product + discount explicitly
        queries.append(_q(
            "promo_2",
            f"{product} discount coupon {dw}",
            "Find evidence of a discount or coupon on this specific product",
            1,
        ))

        # Q3: Brand + product + promotion (avoid brand duplication)
        brand_prefix = _brand_prefix(brand, product)
        queries.append(_q(
            "promo_3",
            brand_prefix + product + " promotion offer",
            "Find brand-specific promotional announcements for this product",
            2,
        ))

        # Q4 (conditional): model number specific
        if event.manufacturer_number and event.manufacturer_number.strip():
            queries.append(_q(
                "promo_4",
                f"{event.manufacturer_number.strip()} sale discount {dw}",
                f"Find promotions for specific model {event.manufacturer_number.strip()}",
                2,
            ))

        # Q5 (conditional): price-point specific
        if event.current_price:
            price_str = f"${event.current_price:.0f}" if event.current_price < 10000 else str(int(event.current_price))
            queries.append(_q(
                "promo_5",
                f"{product} {price_str} {dw}",
                f"Find evidence of product being sold at the observed price of {price_str}",
                2,
            ))

        return queries[:5]


class CompetitorStrategy(InvestigationStrategy):
    """
    Investigates COMPETITOR_RESPONSE hypotheses.

    Searches for evidence that a competing merchant changed price for the same
    product around the event date. Does NOT cover promotional events at THIS
    merchant (that is PromotionStrategy).

    Keywords: competitor, competition, rival, price war, match, undercut,
              price match, competitive pricing, market share
    """

    @property
    def strategy_name(self) -> str:
        return "CompetitorStrategy"

    def generate_queries(self, event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        dw = _date_window(event.observed_at)
        product = event.product_name.strip()
        brand = event.brand.strip()

        def _q(suffix: str, text: str, purpose: str, priority: int) -> SearchQuery:
            return _make_query(event, hypothesis, suffix, text, purpose, priority, self.strategy_name)

        queries: List[SearchQuery] = []

        # Q1: Generic competitor pricing discovery
        queries.append(_q(
            "comp_1",
            f"{product} competitor price {dw}",
            "Discover whether any competitor changed pricing for this product around the event date",
            1,
        ))

        # Q2: Directional price change (avoid brand duplication)
        direction_word = "price drop" if event.change_direction == "decrease" else "price change"
        prod_prefix = _brand_prefix(brand, product)
        queries.append(_q(
            "comp_2",
            prod_prefix + product + f" {direction_word} competitor {dw}",
            f"Find evidence of competitor {direction_word} for the same product",
            1,
        ))

        # Q3: Competitor retailer discount angle
        queries.append(_q(
            "comp_3",
            f"{product} retailer discount {dw}",
            "Find competitor retailer discounts that could have triggered a price response",
            2,
        ))

        # Q4: Phase 1 signal aware queries
        if event.competitors_changed_7d >= 1:
            direction_label = "price drop" if event.competitor_direction_7d < 0 else "price change"
            queries.append(_q(
                "comp_4",
                f"{product} {direction_label} retail {dw}",
                f"Find evidence of competitor {direction_label} matching Phase 1 signal "
                f"(competitors_changed_7d={event.competitors_changed_7d})",
                1,
            ))
        elif event.competitor_count > 0:
            queries.append(_q(
                "comp_4",
                f"{product} multiple retailers price {dw}",
                f"Find multiple retailer pricing evidence (competitor_count={event.competitor_count})",
                2,
            ))
        else:
            # Generic market-level competitive pressure
            prod_prefix4 = _brand_prefix(brand, product)
            queries.append(_q(
                "comp_4",
                prod_prefix4 + product + f" price competition retail {dw}",
                "Find evidence of broader competitive pricing pressure in the product category",
                2,
            ))

        # Q5 (conditional): price-comparison at the observed price
        if event.current_price:
            price_str = (
                "$" + str(int(event.current_price))
                if event.current_price < 10000
                else str(int(event.current_price))
            )
            queries.append(_q(
                "comp_5",
                f"{product} {price_str} retail price comparison {dw}",
                f"Find retail price comparison evidence at the observed price of {price_str}",
                3,
            ))

        return queries[:5]


class ProductEventStrategy(InvestigationStrategy):
    """
    Investigates PRODUCT_EVENT and MANUFACTURER_CHANGE hypotheses.

    Searches for external evidence of product lifecycle events such as launches,
    refreshes, discontinuations, successor announcements, or recalls.
    Does NOT establish causality — only collects evidence.

    Keywords: launch, new model, refresh, discontinu, successor, released,
              announced, updated, end of life, recall
    """

    @property
    def strategy_name(self) -> str:
        return "ProductEventStrategy"

    def generate_queries(self, event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        dw = _date_window(event.observed_at)
        product = event.product_name.strip()
        brand = event.brand.strip()
        manufacturer = (event.manufacturer or brand).strip()
        prefix = _brand_prefix(brand, product)
        identifier = _best_identifier(event)

        def _q(suffix: str, text: str, purpose: str, priority: int) -> SearchQuery:
            return _make_query(event, hypothesis, suffix, text, purpose, priority, self.strategy_name)

        queries: List[SearchQuery] = []

        # Q1: Discontinuation / end-of-life
        queries.append(_q(
            "pe_1",
            prefix + product + f" discontinued {dw}",
            (
                f"Find evidence that {product} was discontinued or reached "
                f"end-of-life around {dw}, which could explain a price reduction"
            ),
            1,
        ))

        # Q2: Successor / replacement model announcement
        queries.append(_q(
            "pe_2",
            prefix + product + f" successor replacement model {dw}",
            (
                f"Find evidence of a successor or replacement model for {product} "
                f"announced around {dw}, which would make the existing model less valuable"
            ),
            1,
        ))

        # Q3: Product launch / release
        queries.append(_q(
            "pe_3",
            prefix + product + f" new release launch {dw}",
            f"Find evidence of a new release or product launch related to {product} around {dw}",
            2,
        ))

        # Q4: Recall or safety notice
        queries.append(_q(
            "pe_4",
            prefix + product + f" recall announcement {dw}",
            (
                f"Find evidence of a product recall, safety notice, or major "
                f"quality announcement for {product} around {dw}"
            ),
            2,
        ))

        # Q5: Model-number specific (if identifier available), else lifecycle change
        if identifier:
            queries.append(_q(
                "pe_5",
                identifier + f" {brand} discontinued replaced {dw}",
                f"Find product lifecycle evidence for model {identifier} ({brand}) around {dw}",
                2,
            ))
        else:
            mfr_prefix = _brand_prefix(manufacturer, product)
            queries.append(_q(
                "pe_5",
                mfr_prefix + product + f" product lifecycle change {dw}",
                (
                    f"Find general product lifecycle or product line change information "
                    f"for {product} from {manufacturer} around {dw}"
                ),
                3,
            ))

        return queries[:5]


class NewsStrategy(InvestigationStrategy):
    """
    Investigates MARKET_EVENT hypotheses.

    Searches for industry-level and market-level news that could explain
    macro pricing trends affecting the product category.

    Keywords: market, industry, supply chain, tariff, inflation, demand,
              shortage, economic, trend
    """

    @property
    def strategy_name(self) -> str:
        return "NewsStrategy"

    def generate_queries(self, event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        dw = _date_window(event.observed_at)
        yr = _year(event.observed_at)
        product = event.product_name.strip()
        brand = event.brand.strip()
        category = event.category.strip()
        merchant = event.merchant.strip()

        def _q(suffix: str, text: str, purpose: str, priority: int) -> SearchQuery:
            return _make_query(event, hypothesis, suffix, text, purpose, priority, self.strategy_name)

        queries: List[SearchQuery] = []

        # Q1: Industry-level news for the category
        queries.append(_q(
            "news_1",
            f"{category} industry news {dw}",
            f"Find industry-level news in the {category} sector around the event date",
            1,
        ))

        # Q2: Brand + category market trends
        queries.append(_q(
            "news_2",
            f"{brand} {category} market trends {dw}",
            f"Find market trend analysis for {brand} in the {category} segment around {dw}",
            1,
        ))

        # Q3: Supply chain issues
        queries.append(_q(
            "news_3",
            f"{product} supply chain {dw}",
            f"Find supply chain issues affecting pricing for {product} around {dw}",
            2,
        ))

        # Q4: Merchant pricing strategy
        queries.append(_q(
            "news_4",
            f"{merchant} pricing strategy {yr}",
            f"Find {merchant} pricing strategy information in {yr}",
            2,
        ))

        # Q5: Macro pricing factors
        queries.append(_q(
            "news_5",
            f"{category} price inflation tariff {dw}",
            f"Find macro pricing factors (inflation, tariffs) affecting {category} around {dw}",
            3,
        ))

        return queries[:5]


class RetailerEventStrategy(InvestigationStrategy):
    """
    Investigates SEASONAL_EVENT hypotheses.

    Searches for merchant-wide and calendar-driven sales events at the retailer.
    IMPORTANT: These queries are merchant-and-calendar-anchored only.
    They MUST NOT include event.product_name to stay focused on retailer-level events.

    Keywords: back to school, holiday, black friday, cyber monday, seasonal,
              summer, winter, site-wide, storewide, event
    """

    @property
    def strategy_name(self) -> str:
        return "RetailerEventStrategy"

    def generate_queries(self, event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        dw = _date_window(event.observed_at)
        yr = _year(event.observed_at)
        merchant_short = event.merchant.replace(".com", "").replace(".co.uk", "").strip()

        def _q(suffix: str, text: str, purpose: str, priority: int) -> SearchQuery:
            return _make_query(event, hypothesis, suffix, text, purpose, priority, self.strategy_name)

        queries: List[SearchQuery] = []

        # Q1: Merchant sale event — NO product name
        queries.append(_q(
            "retail_1",
            f"{merchant_short} sale event {dw}",
            f"Find {event.merchant} sale events around the event date (retailer-level, not product-specific)",
            1,
        ))

        # Q2: Seasonal event — Black Friday — NO product name
        queries.append(_q(
            "retail_2",
            f"{merchant_short} Black Friday {yr}",
            f"Find {event.merchant} Black Friday or major seasonal sale event in {yr}",
            1,
        ))

        # Q3: Back to school — NO product name
        queries.append(_q(
            "retail_3",
            f"{merchant_short} back to school {dw}",
            f"Find {event.merchant} back-to-school promotional campaign around {dw}",
            2,
        ))

        # Q4: Site-wide discount — NO product name
        queries.append(_q(
            "retail_4",
            f"{merchant_short} site-wide discount {dw}",
            f"Find {event.merchant} site-wide or storewide discount event around {dw}",
            2,
        ))

        # Q5: Promotional campaign — NO product name
        queries.append(_q(
            "retail_5",
            f"{merchant_short} promotional campaign {yr}",
            f"Find {event.merchant} promotional campaign information in {yr}",
            3,
        ))

        return queries[:5]


class SupplyStrategy(InvestigationStrategy):
    """
    Investigates INVENTORY_LIQUIDATION and MANUFACTURER_CHANGE hypotheses.

    Searches for evidence of supply-side factors such as clearance, stock shortages,
    overstock situations, or supply chain disruptions.
    IMPORTANT: Must NOT claim inventory liquidation from price drop alone.
    If no external evidence found, VerificationAgent will assign INSUFFICIENT_EVIDENCE.

    Keywords: clearance, liquidation, overstock, excess inventory, end of line,
              discontinued stock, out of stock, shortage, backorder, while supplies last
    """

    @property
    def strategy_name(self) -> str:
        return "SupplyStrategy"

    def generate_queries(self, event: ChangeEvent, hypothesis: Hypothesis) -> List[SearchQuery]:
        dw = _date_window(event.observed_at)
        product = event.product_name.strip()
        brand = event.brand.strip()
        manufacturer = (event.manufacturer or brand).strip()

        def _q(suffix: str, text: str, purpose: str, priority: int) -> SearchQuery:
            return _make_query(event, hypothesis, suffix, text, purpose, priority, self.strategy_name)

        queries: List[SearchQuery] = []

        # Q1: Clearance language
        queries.append(_q(
            "supply_1",
            f"{product} discontinued clearance {dw}",
            f"Find clearance or discontinued-stock evidence for {product} around {dw}",
            1,
        ))

        # Q2: Supply shortage (avoid brand duplication if manufacturer == brand and product starts with brand)
        mfr_prefix = _brand_prefix(manufacturer, product)
        queries.append(_q(
            "supply_2",
            mfr_prefix + product + f" shortage supply {dw}",
            f"Find supply shortage or availability constraints affecting {product} around {dw}",
            1,
        ))

        # Q3: Stock / availability issues
        queries.append(_q(
            "supply_3",
            f"{product} out of stock availability {dw}",
            f"Find out-of-stock or availability evidence for {product} around {dw}",
            2,
        ))

        # Q4: Inventory liquidation / overstock
        queries.append(_q(
            "supply_4",
            f"{product} inventory liquidation overstocked {dw}",
            f"Find overstock or inventory liquidation evidence for {product} around {dw}",
            2,
        ))

        # Q5: End-of-life supply (avoid brand duplication)
        brand_prefix = _brand_prefix(brand, product)
        queries.append(_q(
            "supply_5",
            brand_prefix + product + f" end of life supply {dw}",
            f"Find end-of-life supply chain information for {product} from {brand} around {dw}",
            3,
        ))

        return queries[:5]


# ---------------------------------------------------------------------------
# Strategy → HypothesisType mapping
# ---------------------------------------------------------------------------

# Singleton strategy instances (stateless — safe to share)
_PROMOTION_STRATEGY = PromotionStrategy()
_COMPETITOR_STRATEGY = CompetitorStrategy()
_PRODUCT_EVENT_STRATEGY = ProductEventStrategy()
_NEWS_STRATEGY = NewsStrategy()
_RETAILER_EVENT_STRATEGY = RetailerEventStrategy()
_SUPPLY_STRATEGY = SupplyStrategy()

HYPOTHESIS_TO_STRATEGY: Dict[HypothesisType, Optional[InvestigationStrategy]] = {
    HypothesisType.PROMOTION: _PROMOTION_STRATEGY,
    HypothesisType.COMPETITOR_RESPONSE: _COMPETITOR_STRATEGY,
    HypothesisType.INVENTORY_LIQUIDATION: _SUPPLY_STRATEGY,
    HypothesisType.PRODUCT_EVENT: _PRODUCT_EVENT_STRATEGY,
    HypothesisType.SEASONAL_EVENT: _RETAILER_EVENT_STRATEGY,
    HypothesisType.MARKET_EVENT: _NEWS_STRATEGY,
    HypothesisType.MANUFACTURER_CHANGE: _PRODUCT_EVENT_STRATEGY,  # reuse ProductEventStrategy
    HypothesisType.DATA_ISSUE: None,  # no web investigation for data issues
}


# ---------------------------------------------------------------------------
# InvestigationAgent — the single agent class
# ---------------------------------------------------------------------------

class InvestigationAgent:
    """
    Single investigation agent that runs all applicable strategies for an event.

    Replaces the six-agent + AgentRegistry design. Each hypothesis type is handled
    by a corresponding InvestigationStrategy. The workflow loop (search, extract,
    tag) lives here only — strategies only generate_queries().

    No early-exit: all strategies run regardless of what earlier strategies find.
    """

    def __init__(
        self,
        search_provider: SearchProvider,
        min_relevance: float = 0.20,
    ) -> None:
        self.search_provider = search_provider
        self.extractor = EvidenceExtractor(min_relevance=min_relevance)
        self._last_queries_count: int = 0
        self._last_results_count: int = 0

    def investigate_event(
        self, event: ChangeEvent, hypotheses: List[Hypothesis]
    ) -> List[Evidence]:
        """
        Run ALL applicable strategies for the given event and hypotheses.
        Never short-circuits — every strategy runs.
        Returns: list of Evidence items with strategy and hypothesis tags set.
        """
        self._last_queries_count = 0
        self._last_results_count = 0

        all_evidence: List[Evidence] = []
        for hypothesis in hypotheses:
            strategy = HYPOTHESIS_TO_STRATEGY.get(hypothesis.hypothesis_type)
            if strategy is None:
                logger.debug(
                    "InvestigationAgent: no strategy for %s — skipping",
                    hypothesis.hypothesis_type.value,
                )
                continue
            evidence = self._investigate_with_strategy(event, hypothesis, strategy)
            all_evidence.extend(evidence)

        # Cross-strategy dedup: flag shared source URLs across hypotheses
        all_evidence = self._flag_shared_sources(all_evidence)
        return all_evidence

    def get_last_stats(self) -> Tuple[int, int]:
        """
        Returns (queries_generated, results_retrieved) from the last investigate_event call.
        """
        return self._last_queries_count, self._last_results_count

    def _investigate_with_strategy(
        self,
        event: ChangeEvent,
        hypothesis: Hypothesis,
        strategy: InvestigationStrategy,
    ) -> List[Evidence]:
        """Run one strategy: generate queries, search, extract evidence."""
        queries = strategy.generate_queries(event, hypothesis)[:5]
        all_evidence: List[Evidence] = []

        for query in queries:
            query.executed_at = datetime.now(timezone.utc).isoformat()
            self._last_queries_count += 1

            try:
                results = self.search_provider.search(query, num_results=5)
                query.execution_status = "completed"
                query.result_count = len(results)
                query.provider_used = self.search_provider.provider_name()
                self._last_results_count += len(results)
            except Exception as exc:
                logger.warning(
                    "Search failed for query %s: %s", query.query_id, exc
                )
                query.execution_status = "failed"
                query.provider_used = self.search_provider.provider_name()
                continue

            for result in results:
                try:
                    evidence_items = self.extractor.extract(
                        result=result,
                        hypothesis=hypothesis,
                        product_name=event.product_name,
                        brand=event.brand,
                        merchant=event.merchant,
                        event_date=event.observed_at,
                    )
                    # Tag each evidence item with the strategy name
                    for ev in evidence_items:
                        ev.strategy = strategy.strategy_name
                    all_evidence.extend(evidence_items)
                except Exception as exc:
                    logger.warning(
                        "Evidence extraction failed for %s: %s", result.url, exc
                    )

        logger.debug(
            "InvestigationAgent [%s/%s]: %d evidence items from %d queries",
            strategy.strategy_name,
            hypothesis.hypothesis_type.value,
            len(all_evidence),
            len(queries),
        )
        return all_evidence

    def _flag_shared_sources(self, evidence: List[Evidence]) -> List[Evidence]:
        """
        Flag evidence items that share a source URL across multiple hypotheses.
        Sets shared_source_hypotheses on each such item.
        """
        url_hypotheses: Dict[str, set] = defaultdict(set)
        for ev in evidence:
            url_hypotheses[ev.source_url].add(ev.hypothesis_type)

        for ev in evidence:
            shared = url_hypotheses[ev.source_url] - {ev.hypothesis_type}
            ev.shared_source_hypotheses = list(shared)

        return evidence
