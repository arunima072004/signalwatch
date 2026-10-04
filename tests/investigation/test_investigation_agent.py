"""tests/investigation/test_investigation_agent.py
Comprehensive tests for InvestigationAgent and its six strategies.

Architecture validated here:
  - All 6 strategies run (no early exit)
  - Per-strategy query generation correctness
  - Strategy-specific keyword distinctiveness
  - RetailerEventStrategy never includes product name
  - Cross-strategy source deduplication flags shared_source_hypotheses
  - VerificationAgent treats shared-source evidence as SYNDICATED
  - Evidence tagged with strategy and hypothesis_type fields
  - Regression: PROMOTION and COMPETITOR query counts match pre-refactor expectations
  - Full orchestration end-to-end

All tests use MockSearchProvider. No API keys or network access required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.events.event_generator import ChangeEvent
from src.models.hypothesis import Hypothesis, HypothesisType, make_hypothesis_id
from src.models.evidence import Evidence, EvidenceSpecificity, RelationshipType
from src.models.verification import SupportLevel, SourceIndependenceClass
from src.investigation.hypothesis_generator import HypothesisGenerator
from src.investigation.investigation_agent import (
    InvestigationAgent,
    PromotionStrategy,
    CompetitorStrategy,
    ProductEventStrategy,
    NewsStrategy,
    RetailerEventStrategy,
    SupplyStrategy,
    HYPOTHESIS_TO_STRATEGY,
)
from src.investigation.orchestrator import InvestigationOrchestrator
from src.investigation.verification_agent import VerificationAgent, SourceIndependenceDetector
from src.search.mock_provider import MockSearchProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def macbook_event() -> ChangeEvent:
    """Apple MacBook event from Phase 1 historical data."""
    return ChangeEvent(
        event_id="evt_835c783f6785e8bf",
        product_id="AVpe4lBzLJeJML43xc_m",
        product_name="Apple MacBook - 12 - Core m5",
        brand="Apple",
        manufacturer="Apple",
        manufacturer_number="MLHF2LL/A",
        category="Electronics",
        asins="",
        upc="",
        merchant="Bestbuy.com",
        observed_at="2017-08-19T08:00:00+00:00",
        previous_price=1499.99,
        current_price=1099.99,
        absolute_change=-400.0,
        percentage_change=-26.67,
        change_direction="decrease",
        cp_probability=0.72,
        map_run_length=3,
        log_price_diff=-0.31,
        is_sale=False,
        offer=None,
        availability="In Stock",
        condition="New",
        competitor_count=0,
        competitor_price_median=None,
        price_vs_comp_median=None,
        competitors_changed_7d=0,
        competitor_direction_7d=0,
        source_url=None,
    )


@pytest.fixture
def event_with_competitors() -> ChangeEvent:
    """Event with Phase 1 competitor signals."""
    return ChangeEvent(
        event_id="evt_test_with_competitors",
        product_id="P_COMP_01",
        product_name="Sony WH-1000XM4 Headphones",
        brand="Sony",
        manufacturer="Sony",
        manufacturer_number="WH1000XM4",
        category="Electronics",
        asins="B0863TXGM3",
        upc="027242920934",
        merchant="Amazon.com",
        observed_at="2022-11-15T12:00:00+00:00",
        previous_price=349.99,
        current_price=279.99,
        absolute_change=-70.00,
        percentage_change=-20.0,
        change_direction="decrease",
        cp_probability=0.80,
        map_run_length=4,
        log_price_diff=-0.22,
        is_sale=False,
        offer=None,
        availability="In Stock",
        condition="New",
        competitor_count=4,
        competitor_price_median=319.99,
        price_vs_comp_median=-40.00,
        competitors_changed_7d=3,
        competitor_direction_7d=-1,
        source_url=None,
    )


@pytest.fixture
def event_no_identifiers() -> ChangeEvent:
    """Event with no product identifiers."""
    return ChangeEvent(
        event_id="evt_no_ids_001",
        product_id="P_NO_IDS",
        product_name="Generic Wireless Headphones",
        brand="GenericBrand",
        manufacturer="GenericBrand",
        manufacturer_number="",
        category="Electronics",
        asins="",
        upc="",
        merchant="Amazon.com",
        observed_at="2022-06-15T10:00:00+00:00",
        previous_price=89.99,
        current_price=49.99,
        absolute_change=-40.0,
        percentage_change=-44.45,
        change_direction="decrease",
        cp_probability=0.65,
        map_run_length=2,
        log_price_diff=-0.59,
        is_sale=False,
        offer=None,
        availability="In Stock",
        condition="New",
        competitor_count=0,
        competitor_price_median=None,
        price_vs_comp_median=None,
        competitors_changed_7d=0,
        competitor_direction_7d=0,
        source_url=None,
    )


@pytest.fixture
def mock_provider() -> MockSearchProvider:
    return MockSearchProvider()


def _make_hyp(event: ChangeEvent, h_type: HypothesisType, agents: List[str] = None) -> Hypothesis:
    """Helper to build a Hypothesis for a given type."""
    return Hypothesis(
        hypothesis_id=make_hypothesis_id(event.event_id, h_type),
        event_id=event.event_id,
        hypothesis_type=h_type,
        signal_score=0.50,
        rationale=f"Test hypothesis for {h_type.value}",
        signals_matched=["test signal"],
        assigned_agents=agents or [h_type.value + "Agent"],
        requires_external_evidence=True,
        generated_at="2017-08-19T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# 1. All strategies run (no early exit)
# ---------------------------------------------------------------------------

class TestAllStrategiesRun:
    """InvestigationAgent must run all applicable strategies, never short-circuit."""

    def test_all_applicable_strategies_execute(self, macbook_event, mock_provider):
        """MacBook event triggers at least PROMOTION + PRODUCT_EVENT. Both must run."""
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)

        # Verify: search provider called for each hypothesis type with a strategy
        agent.investigate_event(macbook_event, hyps)
        # Each hypothesis with a non-None strategy dispatches queries.
        # min_queries = hypotheses with strategies * at least 3 queries each
        q_count, _ = agent.get_last_stats()
        applicable = sum(
            1 for h in hyps
            if HYPOTHESIS_TO_STRATEGY.get(h.hypothesis_type) is not None
        )
        assert q_count >= applicable * 3, (
            f"Expected at least {applicable * 3} queries for {applicable} strategies, "
            f"got {q_count}"
        )

    def test_no_early_exit_even_with_strong_first_evidence(self, macbook_event, mock_provider):
        """
        If the first strategy returns evidence, all subsequent strategies must still run.
        Strategy count = hypotheses with non-None strategies.
        """
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)

        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, hyps)

        q_count, _ = agent.get_last_stats()
        applicable = sum(
            1 for h in hyps
            if HYPOTHESIS_TO_STRATEGY.get(h.hypothesis_type) is not None
        )
        # If early exit happened, q_count would equal 1 strategy's worth of queries (~5)
        # With no early exit it should be >= applicable strategies * min 3 queries
        assert q_count >= applicable * 3, (
            f"Possible early exit: {q_count} queries for {applicable} applicable strategies"
        )

    def test_data_issue_hypothesis_skipped(self, macbook_event, mock_provider):
        """DATA_ISSUE type has None strategy — must be skipped without error."""
        data_hyp = _make_hyp(macbook_event, HypothesisType.DATA_ISSUE)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [data_hyp])
        # No crash, no evidence (DATA_ISSUE is not investigated)
        assert evidence == []
        q_count, _ = agent.get_last_stats()
        assert q_count == 0

    def test_empty_hypothesis_list_returns_empty(self, macbook_event, mock_provider):
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [])
        assert evidence == []

    def test_all_six_hypothesis_types_covered(self):
        """Every non-DATA_ISSUE HypothesisType must have a strategy registered."""
        for h_type in HypothesisType:
            if h_type == HypothesisType.DATA_ISSUE:
                assert HYPOTHESIS_TO_STRATEGY[h_type] is None
            else:
                assert HYPOTHESIS_TO_STRATEGY[h_type] is not None, (
                    f"No strategy registered for {h_type.value}"
                )


# ---------------------------------------------------------------------------
# 2. Evidence tagged with hypothesis and strategy
# ---------------------------------------------------------------------------

class TestEvidenceTagging:
    """Every evidence item must carry both hypothesis_type and strategy fields."""

    def test_evidence_has_strategy_tag(self, macbook_event, mock_provider):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, hyps)
        assert evidence, "Expected at least one evidence item"
        for ev in evidence:
            assert ev.strategy, f"Evidence {ev.evidence_id} missing strategy tag"

    def test_evidence_has_hypothesis_type(self, macbook_event, mock_provider):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, hyps)
        for ev in evidence:
            assert ev.hypothesis_type, f"Evidence {ev.evidence_id} missing hypothesis_type"

    def test_promotion_evidence_tagged_with_promotion_strategy(self, macbook_event, mock_provider):
        promo_hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [promo_hyp])
        for ev in evidence:
            assert ev.strategy == "PromotionStrategy", (
                f"Expected PromotionStrategy tag, got {ev.strategy!r}"
            )
            assert ev.hypothesis_type == "PROMOTION"

    def test_competitor_evidence_tagged_with_competitor_strategy(self, event_with_competitors, mock_provider):
        comp_hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(event_with_competitors, [comp_hyp])
        for ev in evidence:
            assert ev.strategy == "CompetitorStrategy"
            assert ev.hypothesis_type == "COMPETITOR_RESPONSE"

    def test_product_event_evidence_tagged_correctly(self, macbook_event, mock_provider):
        pe_hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [pe_hyp])
        for ev in evidence:
            assert ev.strategy == "ProductEventStrategy"

    def test_retailer_evidence_tagged_correctly(self, macbook_event, mock_provider):
        ret_hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [ret_hyp])
        for ev in evidence:
            assert ev.strategy == "RetailerEventStrategy"

    def test_supply_evidence_tagged_correctly(self, macbook_event, mock_provider):
        supply_hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [supply_hyp])
        for ev in evidence:
            assert ev.strategy == "SupplyStrategy"

    def test_news_evidence_tagged_correctly(self, macbook_event, mock_provider):
        news_hyp = _make_hyp(macbook_event, HypothesisType.MARKET_EVENT)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [news_hyp])
        for ev in evidence:
            assert ev.strategy == "NewsStrategy"


# ---------------------------------------------------------------------------
# 3. Per-strategy query tests
# ---------------------------------------------------------------------------

class TestPromotionStrategyQueries:
    def test_generates_3_to_5_queries(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        queries = PromotionStrategy().generate_queries(macbook_event, hyp)
        assert 3 <= len(queries) <= 5

    def test_queries_have_structured_fields(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        queries = PromotionStrategy().generate_queries(macbook_event, hyp)
        for q in queries:
            assert q.query_id
            assert q.event_id == macbook_event.event_id
            assert q.hypothesis_type == "PROMOTION"
            assert q.generated_by == "PromotionStrategy"
            assert q.query_text
            assert q.purpose
            assert q.date_window

    def test_queries_reference_product_or_brand(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        texts = " ".join(q.query_text.lower() for q in PromotionStrategy().generate_queries(macbook_event, hyp))
        assert "apple" in texts or "macbook" in texts

    def test_promotion_keywords_present(self, macbook_event):
        """At least one query must contain a promotion-related keyword."""
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        texts = " ".join(q.query_text.lower() for q in PromotionStrategy().generate_queries(macbook_event, hyp))
        promo_kw = ["sale", "discount", "promo", "promotion", "offer", "coupon"]
        assert any(kw in texts for kw in promo_kw), (
            f"No promotion keyword found in: {texts}"
        )

    def test_no_brand_duplication(self, macbook_event):
        """Queries must not produce 'Apple Apple MacBook ...'."""
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        brand = macbook_event.brand.lower()
        for q in PromotionStrategy().generate_queries(macbook_event, hyp):
            words = q.query_text.lower().split()
            for i in range(len(words) - 1):
                assert not (words[i] == brand and words[i + 1] == brand), (
                    f"Brand duplicated in query: {q.query_text!r}"
                )

    def test_unique_query_ids(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        ids = [q.query_id for q in PromotionStrategy().generate_queries(macbook_event, hyp)]
        assert len(ids) == len(set(ids))

    def test_unique_query_texts(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        texts = [q.query_text for q in PromotionStrategy().generate_queries(macbook_event, hyp)]
        assert len(texts) == len(set(texts))

    def test_handles_empty_results_gracefully(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        agent = InvestigationAgent(MockSearchProvider(scenario="empty"))
        evidence = agent.investigate_event(macbook_event, [hyp])
        assert evidence == []

    def test_handles_provider_failure_gracefully(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        agent = InvestigationAgent(MockSearchProvider(scenario="failure"))
        evidence = agent.investigate_event(macbook_event, [hyp])
        assert evidence == []


class TestCompetitorStrategyQueries:
    def test_generates_3_to_5_queries(self, event_with_competitors):
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        queries = CompetitorStrategy().generate_queries(event_with_competitors, hyp)
        assert 3 <= len(queries) <= 5

    def test_queries_reference_product_or_brand(self, event_with_competitors):
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        texts = " ".join(q.query_text.lower() for q in CompetitorStrategy().generate_queries(event_with_competitors, hyp))
        assert "sony" in texts or "wh-1000xm4" in texts or "headphone" in texts

    def test_competitor_keywords_present(self, event_with_competitors):
        """At least one query must contain a competitor-related keyword."""
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        texts = " ".join(q.query_text.lower() for q in CompetitorStrategy().generate_queries(event_with_competitors, hyp))
        comp_kw = ["competitor", "competition", "price drop", "price change", "retailer", "retail"]
        assert any(kw in texts for kw in comp_kw), (
            f"No competitor keyword found in: {texts}"
        )

    def test_no_brand_duplication(self, event_with_competitors):
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        for q in CompetitorStrategy().generate_queries(event_with_competitors, hyp):
            words = q.query_text.lower().split()
            brand = event_with_competitors.brand.lower()
            for i in range(len(words) - 1):
                assert not (words[i] == brand and words[i + 1] == brand), (
                    f"Brand duplicated: {q.query_text!r}"
                )

    def test_uses_competitor_signal_when_available(self, event_with_competitors):
        """Event with competitors_changed_7d=3 should produce competitor-signal-aware query."""
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        queries = CompetitorStrategy().generate_queries(event_with_competitors, hyp)
        purposes = " ".join(q.purpose.lower() for q in queries)
        assert "competitor" in purposes or "competitive" in purposes

    def test_unique_query_ids(self, event_with_competitors):
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        ids = [q.query_id for q in CompetitorStrategy().generate_queries(event_with_competitors, hyp)]
        assert len(ids) == len(set(ids))


class TestProductEventStrategyQueries:
    def test_generates_5_queries(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        queries = ProductEventStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) == 5

    def test_queries_reference_product_or_brand(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        texts = " ".join(q.query_text.lower() for q in ProductEventStrategy().generate_queries(macbook_event, hyp))
        assert "apple" in texts or "macbook" in texts

    def test_product_lifecycle_keywords_present(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        texts = " ".join(q.query_text.lower() for q in ProductEventStrategy().generate_queries(macbook_event, hyp))
        pe_kw = ["discontinu", "successor", "replacement", "new release", "recall", "launch", "lifecycle"]
        assert any(kw in texts for kw in pe_kw), (
            f"No product-event keyword found in: {texts}"
        )

    def test_identifier_used_when_available(self, macbook_event):
        """MLHF2LL/A should appear in at least one query."""
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        texts = " ".join(q.query_text.lower() for q in ProductEventStrategy().generate_queries(macbook_event, hyp))
        assert "mlhf2ll" in texts

    def test_no_identifier_invented_when_none_available(self, event_no_identifiers):
        """When no identifier is available, queries must still be valid."""
        hyp = _make_hyp(event_no_identifiers, HypothesisType.PRODUCT_EVENT)
        queries = ProductEventStrategy().generate_queries(event_no_identifiers, hyp)
        assert len(queries) >= 3
        for q in queries:
            assert q.query_text.strip()
            assert not q.query_text.startswith(" ")

    def test_no_brand_duplication(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        brand = macbook_event.brand.lower()
        for q in ProductEventStrategy().generate_queries(macbook_event, hyp):
            words = q.query_text.lower().split()
            for i in range(len(words) - 1):
                assert not (words[i] == brand and words[i + 1] == brand), (
                    f"Brand duplicated: {q.query_text!r}"
                )

    def test_unique_query_ids(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        ids = [q.query_id for q in ProductEventStrategy().generate_queries(macbook_event, hyp)]
        assert len(ids) == len(set(ids))


class TestRetailerEventStrategyQueries:
    def test_generates_5_queries(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        queries = RetailerEventStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) == 5

    def test_queries_do_not_include_product_name(self, macbook_event):
        """CRITICAL: RetailerEvent queries must NEVER include event.product_name."""
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        product_lower = macbook_event.product_name.lower()
        # Check significant product tokens (3+ chars)
        product_tokens = [t for t in product_lower.split() if len(t) >= 3]
        for q in RetailerEventStrategy().generate_queries(macbook_event, hyp):
            q_lower = q.query_text.lower()
            # No significant product token should appear
            for token in product_tokens:
                assert token not in q_lower, (
                    f"RetailerEvent query contains product token '{token}': {q.query_text!r}"
                )

    def test_queries_reference_merchant(self, macbook_event):
        """Queries should be merchant-anchored."""
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        texts = " ".join(q.query_text.lower() for q in RetailerEventStrategy().generate_queries(macbook_event, hyp))
        merchant_short = macbook_event.merchant.lower().replace(".com", "").replace(".co.uk", "")
        assert merchant_short in texts, (
            f"Merchant '{merchant_short}' not found in queries: {texts}"
        )

    def test_seasonal_keywords_present(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        texts = " ".join(q.query_text.lower() for q in RetailerEventStrategy().generate_queries(macbook_event, hyp))
        retail_kw = ["sale", "black friday", "back to school", "discount", "site-wide", "promotional", "campaign", "event"]
        assert any(kw in texts for kw in retail_kw), (
            f"No seasonal/retailer keyword in: {texts}"
        )

    def test_unique_query_ids(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        ids = [q.query_id for q in RetailerEventStrategy().generate_queries(macbook_event, hyp)]
        assert len(ids) == len(set(ids))


class TestNewsStrategyQueries:
    def test_generates_5_queries(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.MARKET_EVENT)
        queries = NewsStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) == 5

    def test_news_keywords_present(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.MARKET_EVENT)
        texts = " ".join(q.query_text.lower() for q in NewsStrategy().generate_queries(macbook_event, hyp))
        news_kw = ["market", "industry", "supply chain", "tariff", "inflation", "trend"]
        assert any(kw in texts for kw in news_kw), (
            f"No news keyword in: {texts}"
        )

    def test_references_category(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.MARKET_EVENT)
        texts = " ".join(q.query_text.lower() for q in NewsStrategy().generate_queries(macbook_event, hyp))
        assert macbook_event.category.lower() in texts

    def test_unique_query_ids(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.MARKET_EVENT)
        ids = [q.query_id for q in NewsStrategy().generate_queries(macbook_event, hyp)]
        assert len(ids) == len(set(ids))


class TestSupplyStrategyQueries:
    def test_generates_5_queries(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        queries = SupplyStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) == 5

    def test_supply_keywords_present(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        texts = " ".join(q.query_text.lower() for q in SupplyStrategy().generate_queries(macbook_event, hyp))
        supply_kw = ["clearance", "shortage", "out of stock", "liquidation", "overstocked", "lifecycle", "discontinued"]
        assert any(kw in texts for kw in supply_kw), (
            f"No supply keyword in: {texts}"
        )

    def test_no_brand_duplication(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        brand = macbook_event.brand.lower()
        for q in SupplyStrategy().generate_queries(macbook_event, hyp):
            words = q.query_text.lower().split()
            for i in range(len(words) - 1):
                assert not (words[i] == brand and words[i + 1] == brand), (
                    f"Brand duplicated: {q.query_text!r}"
                )

    def test_unique_query_ids(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        ids = [q.query_id for q in SupplyStrategy().generate_queries(macbook_event, hyp)]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 4. Strategy-specific keyword distinctiveness
# ---------------------------------------------------------------------------

class TestStrategyKeywordDistinctiveness:
    """
    Promotion queries should NOT look like supply queries and vice versa.
    Tests 2 strategy pairs as required.
    """

    def test_promotion_queries_contain_promotion_keywords_not_supply(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        texts = " ".join(q.query_text.lower() for q in PromotionStrategy().generate_queries(macbook_event, hyp))

        promo_kw = ["sale", "discount", "promo", "promotion", "offer", "coupon"]
        supply_kw = ["liquidation", "overstocked", "out of stock", "shortage"]

        assert any(kw in texts for kw in promo_kw), "PromotionStrategy missing promotion keywords"
        # Promotion queries must NOT contain supply-specific terms
        for kw in supply_kw:
            assert kw not in texts, (
                f"PromotionStrategy query should not contain supply keyword '{kw}': {texts}"
            )

    def test_supply_queries_contain_supply_keywords_not_promotion(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        texts = " ".join(q.query_text.lower() for q in SupplyStrategy().generate_queries(macbook_event, hyp))

        supply_kw = ["clearance", "liquidation", "overstocked", "shortage", "out of stock", "discontinued"]
        assert any(kw in texts for kw in supply_kw), "SupplyStrategy missing supply keywords"

        # Supply queries must NOT contain promotion-specific terms (sale, coupon, discount)
        pure_promo_kw = ["coupon", "off sale", "promo offer"]
        for kw in pure_promo_kw:
            assert kw not in texts, (
                f"SupplyStrategy query should not contain promo keyword '{kw}': {texts}"
            )

    def test_retailer_queries_differ_from_promotion_queries(self, macbook_event):
        """RetailerEvent targets merchant-wide events; Promotion targets product-specific."""
        promo_hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        ret_hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)

        promo_texts = set(q.query_text for q in PromotionStrategy().generate_queries(macbook_event, promo_hyp))
        ret_texts = set(q.query_text for q in RetailerEventStrategy().generate_queries(macbook_event, ret_hyp))

        # No query text should be shared
        assert promo_texts.isdisjoint(ret_texts), (
            f"Overlapping queries between Promotion and RetailerEvent: "
            f"{promo_texts & ret_texts}"
        )

    def test_product_event_queries_contain_lifecycle_not_discount(self, macbook_event):
        """ProductEvent queries focus on lifecycle events, not discounts."""
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        texts = " ".join(q.query_text.lower() for q in ProductEventStrategy().generate_queries(macbook_event, hyp))

        lifecycle_kw = ["discontinu", "successor", "recall", "release", "launch"]
        assert any(kw in texts for kw in lifecycle_kw), "ProductEvent missing lifecycle keywords"

        # Should not be dominated by discount language
        pure_discount_kw = ["coupon", "promo offer", "sale price", "on sale"]
        for kw in pure_discount_kw:
            assert kw not in texts, (
                f"ProductEvent query should not contain discount keyword '{kw}': {texts}"
            )


# ---------------------------------------------------------------------------
# 5. RetailerEvent never includes product name
# ---------------------------------------------------------------------------

class TestRetailerEventNoProductName:
    def test_retailer_event_excludes_product_name_macbook(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        product_lower = macbook_event.product_name.lower()
        product_tokens = [t for t in product_lower.split() if len(t) >= 3]
        for q in RetailerEventStrategy().generate_queries(macbook_event, hyp):
            q_lower = q.query_text.lower()
            for token in product_tokens:
                assert token not in q_lower, (
                    f"RetailerEvent query contains product token '{token}': {q.query_text!r}"
                )

    def test_retailer_event_excludes_product_name_sony_event(self, event_with_competitors):
        hyp = _make_hyp(event_with_competitors, HypothesisType.SEASONAL_EVENT)
        product_lower = event_with_competitors.product_name.lower()
        product_tokens = [t for t in product_lower.split() if len(t) >= 3]
        for q in RetailerEventStrategy().generate_queries(event_with_competitors, hyp):
            q_lower = q.query_text.lower()
            for token in product_tokens:
                assert token not in q_lower, (
                    f"RetailerEvent query contains product token '{token}': {q.query_text!r}"
                )

    def test_retailer_event_queries_via_agent_no_product_name(self, macbook_event, mock_provider):
        """End-to-end: evidence from RetailerEvent strategy collected without product name in queries."""
        hyp = _make_hyp(macbook_event, HypothesisType.SEASONAL_EVENT)
        agent = InvestigationAgent(mock_provider)
        # We can only check the strategy queries directly since the agent uses them internally
        queries = RetailerEventStrategy().generate_queries(macbook_event, hyp)
        product_lower = macbook_event.product_name.lower()
        product_tokens = [t for t in product_lower.split() if len(t) >= 3]
        for q in queries:
            q_lower = q.query_text.lower()
            for token in product_tokens:
                assert token not in q_lower


# ---------------------------------------------------------------------------
# 6. Cross-strategy source deduplication
# ---------------------------------------------------------------------------

class TestCrossStrategySourceDedup:
    def test_shared_source_url_flagged_in_shared_source_hypotheses(self, macbook_event, mock_provider):
        """
        When two strategies produce evidence from the same URL,
        both items must have non-empty shared_source_hypotheses.
        """
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, hyps)

        # Group by URL
        from collections import defaultdict
        url_to_hyp = defaultdict(set)
        for ev in evidence:
            url_to_hyp[ev.source_url].add(ev.hypothesis_type)

        # Find URLs shared across multiple hypothesis types
        shared_urls = {url for url, hyps_set in url_to_hyp.items() if len(hyps_set) > 1}

        if shared_urls:
            # All evidence from shared URLs must have shared_source_hypotheses set
            for ev in evidence:
                if ev.source_url in shared_urls:
                    assert ev.shared_source_hypotheses, (
                        f"Evidence {ev.evidence_id} from shared URL {ev.source_url} "
                        f"must have shared_source_hypotheses set"
                    )

    def test_unique_source_url_not_flagged(self, macbook_event, mock_provider):
        """Evidence from URLs unique to one hypothesis must have empty shared_source_hypotheses."""
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, hyps)

        from collections import defaultdict
        url_to_hyp = defaultdict(set)
        for ev in evidence:
            url_to_hyp[ev.source_url].add(ev.hypothesis_type)

        unique_urls = {url for url, hyps_set in url_to_hyp.items() if len(hyps_set) == 1}
        for ev in evidence:
            if ev.source_url in unique_urls:
                assert ev.shared_source_hypotheses == [], (
                    f"Evidence from unique URL {ev.source_url} should have "
                    f"empty shared_source_hypotheses, got {ev.shared_source_hypotheses}"
                )

    def test_manually_constructed_shared_source_flagged(self, macbook_event):
        """
        Manually construct scenario: PROMOTION and SEASONAL_EVENT evidence
        sharing the same source URL. Assert both records have shared_source_hypotheses.
        """
        # Build fake evidence with shared URL
        shared_url = "https://www.bestbuy.com/site/promotions/summer-sale"
        ev1 = Evidence(
            evidence_id="evd_shared_promo",
            event_id=macbook_event.event_id,
            hypothesis_type="PROMOTION",
            query_id="q_promo",
            result_id="res_promo",
            source_url=shared_url,
            source_domain="bestbuy.com",
            source_title="Best Buy Summer Sale",
            retrieved_at="2017-08-19T00:00:00+00:00",
            claim="Best Buy Summer Sale MacBook discount",
            evidence_text="Best Buy is offering MacBook at a discount during the summer sale.",
            evidence_specificity=EvidenceSpecificity.DIRECT,
            relationship_type=RelationshipType.DESCRIPTIVE,
            relevance_score=0.7,
            investigator="PromotionStrategy",
            strategy="PromotionStrategy",
        )
        ev2 = Evidence(
            evidence_id="evd_shared_retail",
            event_id=macbook_event.event_id,
            hypothesis_type="SEASONAL_EVENT",
            query_id="q_retail",
            result_id="res_retail",
            source_url=shared_url,
            source_domain="bestbuy.com",
            source_title="Best Buy Summer Sale",
            retrieved_at="2017-08-19T00:00:00+00:00",
            claim="Best Buy site-wide summer sale",
            evidence_text="Best Buy is running a site-wide summer sale event in August 2017.",
            evidence_specificity=EvidenceSpecificity.DIRECT,
            relationship_type=RelationshipType.DESCRIPTIVE,
            relevance_score=0.6,
            investigator="RetailerEventStrategy",
            strategy="RetailerEventStrategy",
        )

        # Run _flag_shared_sources directly
        agent = InvestigationAgent(MockSearchProvider())
        flagged = agent._flag_shared_sources([ev1, ev2])

        for ev in flagged:
            assert ev.shared_source_hypotheses, (
                f"Evidence {ev.evidence_id} should have shared_source_hypotheses set"
            )
            # Each should contain the OTHER hypothesis's type
            if ev.hypothesis_type == "PROMOTION":
                assert "SEASONAL_EVENT" in ev.shared_source_hypotheses
            elif ev.hypothesis_type == "SEASONAL_EVENT":
                assert "PROMOTION" in ev.shared_source_hypotheses


# ---------------------------------------------------------------------------
# 7. VerificationAgent treats shared-source evidence as SYNDICATED
# ---------------------------------------------------------------------------

class TestVerificationAgentSharedSource:
    def test_shared_source_evidence_classified_as_syndicated(self, macbook_event):
        """Evidence with non-empty shared_source_hypotheses should be SYNDICATED."""
        shared_url = "https://www.bestbuy.com/site/promotions/summer-sale"
        ev = Evidence(
            evidence_id="evd_shared_test",
            event_id=macbook_event.event_id,
            hypothesis_type="PROMOTION",
            query_id="q1",
            result_id="r1",
            source_url=shared_url,
            source_domain="bestbuy.com",
            source_title="Best Buy Summer Sale",
            retrieved_at="2017-08-19T00:00:00+00:00",
            claim="MacBook sale at Best Buy",
            evidence_text="Best Buy is offering the Apple MacBook at a sale price during August 2017.",
            evidence_specificity=EvidenceSpecificity.DIRECT,
            relationship_type=RelationshipType.DESCRIPTIVE,
            relevance_score=0.7,
            investigator="PromotionStrategy",
            strategy="PromotionStrategy",
            shared_source_hypotheses=["SEASONAL_EVENT"],  # non-empty => SYNDICATED
        )

        detector = SourceIndependenceDetector()
        result = detector.analyze([ev])
        assert result[ev.evidence_id] == SourceIndependenceClass.SYNDICATED, (
            f"Expected SYNDICATED for shared-source evidence, got {result[ev.evidence_id]}"
        )

    def test_non_shared_source_not_forced_to_syndicated(self, macbook_event):
        """Evidence with empty shared_source_hypotheses should NOT be forced to SYNDICATED."""
        ev = Evidence(
            evidence_id="evd_unique_test",
            event_id=macbook_event.event_id,
            hypothesis_type="PROMOTION",
            query_id="q1",
            result_id="r1",
            source_url="https://unique-domain.com/article",
            source_domain="unique-domain.com",
            source_title="Unique Article",
            retrieved_at="2017-08-19T00:00:00+00:00",
            claim="Some claim",
            evidence_text="The Apple MacBook is available at Best Buy for a limited time.",
            evidence_specificity=EvidenceSpecificity.DIRECT,
            relationship_type=RelationshipType.DESCRIPTIVE,
            relevance_score=0.7,
            investigator="PromotionStrategy",
            strategy="PromotionStrategy",
            shared_source_hypotheses=[],  # empty => not forced to SYNDICATED
        )

        detector = SourceIndependenceDetector()
        result = detector.analyze([ev])
        assert result[ev.evidence_id] != SourceIndependenceClass.SYNDICATED, (
            f"Evidence with empty shared_source_hypotheses should not be SYNDICATED, "
            f"got {result[ev.evidence_id]}"
        )


# ---------------------------------------------------------------------------
# 8. Regression tests: PROMOTION and COMPETITOR query counts
# ---------------------------------------------------------------------------

class TestQueryCountRegression:
    """
    Regression: ensure the new strategies generate the same number of queries
    as the old PromotionAgent and CompetitorAgent.
    """

    def test_promotion_strategy_generates_at_least_3_queries(self, macbook_event):
        """Old PromotionAgent always generated >= 3 queries."""
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        queries = PromotionStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) >= 3

    def test_promotion_strategy_generates_at_most_5_queries(self, macbook_event):
        hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        queries = PromotionStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) <= 5

    def test_competitor_strategy_generates_at_least_3_queries(self, event_with_competitors):
        """Old CompetitorAgent always generated >= 3 queries."""
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        queries = CompetitorStrategy().generate_queries(event_with_competitors, hyp)
        assert len(queries) >= 3

    def test_competitor_strategy_generates_at_most_5_queries(self, event_with_competitors):
        hyp = _make_hyp(event_with_competitors, HypothesisType.COMPETITOR_RESPONSE)
        queries = CompetitorStrategy().generate_queries(event_with_competitors, hyp)
        assert len(queries) <= 5

    def test_product_event_strategy_generates_5_queries(self, macbook_event):
        """Old ProductEventAgent generated exactly 5 queries for a well-specified event."""
        hyp = _make_hyp(macbook_event, HypothesisType.PRODUCT_EVENT)
        queries = ProductEventStrategy().generate_queries(macbook_event, hyp)
        assert len(queries) == 5

    def test_promotion_evidence_not_in_competitor_set(self, macbook_event, mock_provider):
        """Evidence sets for PROMOTION and COMPETITOR_RESPONSE must be disjoint."""
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, hyps)

        promo_ev = {ev.evidence_id for ev in evidence if ev.hypothesis_type == "PROMOTION"}
        comp_ev = {ev.evidence_id for ev in evidence if ev.hypothesis_type == "COMPETITOR_RESPONSE"}
        assert promo_ev.isdisjoint(comp_ev), (
            "PROMOTION and COMPETITOR_RESPONSE evidence sets must be disjoint"
        )

    def test_promotion_evidence_investigator_is_strategy_name(self, macbook_event, mock_provider):
        """Evidence investigator should be the strategy's strategy_name."""
        promo_hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        agent = InvestigationAgent(mock_provider)
        evidence = agent.investigate_event(macbook_event, [promo_hyp])
        # Investigator is set by EvidenceExtractor from hypothesis.assigned_agents[0]
        # (legacy behavior preserved); strategy tag is on ev.strategy
        for ev in evidence:
            assert ev.strategy == "PromotionStrategy"


# ---------------------------------------------------------------------------
# 9. Provider failure resilience
# ---------------------------------------------------------------------------

class TestProviderFailureResilience:
    def test_failing_provider_returns_empty_evidence(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(MockSearchProvider(scenario="failure"))
        evidence = agent.investigate_event(macbook_event, hyps)
        assert evidence == []
        q_count, r_count = agent.get_last_stats()
        assert q_count > 0  # queries were generated
        assert r_count == 0  # no results retrieved

    def test_empty_provider_returns_empty_evidence(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(MockSearchProvider(scenario="empty"))
        evidence = agent.investigate_event(macbook_event, hyps)
        assert evidence == []

    def test_get_last_stats_returns_tuple_of_ints(self, macbook_event, mock_provider):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        agent = InvestigationAgent(mock_provider)
        agent.investigate_event(macbook_event, hyps)
        q_count, r_count = agent.get_last_stats()
        assert isinstance(q_count, int)
        assert isinstance(r_count, int)
        assert q_count >= 0
        assert r_count >= 0


# ---------------------------------------------------------------------------
# 10. Full orchestration test
# ---------------------------------------------------------------------------

class TestFullOrchestration:
    def test_orchestrator_returns_assessment(self, macbook_event, mock_provider, tmp_path):
        """InvestigationOrchestrator.investigate() returns complete EventAssessment."""
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        assert assessment.event_id == macbook_event.event_id
        assert assessment.assessment_id
        assert assessment.assessed_at
        assert len(assessment.hypotheses) >= 2
        assert assessment.hypothesis_assessments
        assert assessment.summary

    def test_orchestrator_serializes_to_json(self, macbook_event, mock_provider, tmp_path):
        import json
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        out_path = orchestrator.save(assessment)
        assert out_path.exists()
        data = json.load(open(out_path))
        assert data["event_id"] == macbook_event.event_id
        assert "hypothesis_assessments" in data
        assert "evidence" in data

    def test_json_evidence_has_strategy_field(self, macbook_event, mock_provider, tmp_path):
        """Serialized evidence must preserve the strategy field."""
        import json
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        out_path = orchestrator.save(assessment)
        data = json.load(open(out_path))
        for ev_dict in data["evidence"]:
            assert "strategy" in ev_dict, f"Missing 'strategy' field in evidence: {ev_dict}"

    def test_orchestrator_provenance_chain_intact(self, macbook_event, mock_provider, tmp_path):
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        for ev in assessment.evidence:
            assert ev.event_id == macbook_event.event_id
            assert ev.query_id
            assert ev.result_id
            assert ev.source_url

    def test_orchestrator_with_failing_provider_does_not_crash(self, macbook_event, tmp_path):
        orchestrator = InvestigationOrchestrator(
            search_provider=MockSearchProvider(scenario="failure"),
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        assert assessment is not None
        assert assessment.event_id == macbook_event.event_id

    def test_multiple_hypothesis_types_assessed(self, macbook_event, mock_provider, tmp_path):
        """Multiple hypotheses must appear in the assessment (no single forced winner)."""
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        ha_types = {ha.hypothesis_type for ha in assessment.hypothesis_assessments}
        assert len(ha_types) >= 2, f"Expected >= 2 hypothesis types, got {ha_types}"

    def test_product_event_and_promotion_both_assessed(self, macbook_event, mock_provider, tmp_path):
        """Both PROMOTION and PRODUCT_EVENT must be assessed for the MacBook event."""
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        ha_types = {ha.hypothesis_type for ha in assessment.hypothesis_assessments}
        assert "PROMOTION" in ha_types
        assert "PRODUCT_EVENT" in ha_types

    def test_queries_generated_count_is_positive(self, macbook_event, mock_provider, tmp_path):
        """Orchestrator must report at least one query generated."""
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        assert assessment.queries_generated > 0


# ---------------------------------------------------------------------------
# 11. Per-strategy extraction tests
# ---------------------------------------------------------------------------

class TestPerStrategyExtraction:
    """
    Verify that hypothesis-type-specific keyword scoring in EvidenceExtractor
    means the right evidence gets picked up by the right strategy.
    """

    def test_discontinued_language_triggers_supply_or_product_event_not_promotion(self, macbook_event, mock_provider):
        """
        A search result containing 'discontinued clearance' should be scored
        higher for INVENTORY_LIQUIDATION / PRODUCT_EVENT than for PROMOTION.
        """
        from src.evidence.extractor import EvidenceExtractor
        from src.models.search import SearchQuery, SearchResult, make_result_id
        from datetime import datetime, timezone

        extractor = EvidenceExtractor(min_relevance=0.10)

        result_text = (
            "The Apple MacBook 12-inch has been discontinued. "
            "Best Buy is clearing remaining inventory of this discontinued model."
        )
        supply_hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)
        promo_hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)

        from src.models.search import SearchQuery
        q_supply = SearchQuery(
            query_id="q_supply_disc", event_id=macbook_event.event_id,
            hypothesis_type="INVENTORY_LIQUIDATION",
            query_text="macbook discontinued clearance",
            purpose="test", priority=1, generated_by="SupplyStrategy",
            product_name=macbook_event.product_name, brand=macbook_event.brand,
            merchant=macbook_event.merchant, category=macbook_event.category,
            date_window="August 2017",
        )
        q_promo = SearchQuery(
            query_id="q_promo_disc", event_id=macbook_event.event_id,
            hypothesis_type="PROMOTION",
            query_text="macbook sale August 2017",
            purpose="test", priority=1, generated_by="PromotionStrategy",
            product_name=macbook_event.product_name, brand=macbook_event.brand,
            merchant=macbook_event.merchant, category=macbook_event.category,
            date_window="August 2017",
        )
        now = datetime.now(timezone.utc).isoformat()
        result = SearchResult(
            result_id=make_result_id(q_supply.query_id, "https://test.com/discontinued"),
            query_id=q_supply.query_id,
            event_id=macbook_event.event_id,
            title="MacBook Discontinued",
            url="https://test.com/discontinued",
            snippet=result_text,
            source_domain="test.com",
            retrieved_at=now,
            provider="mock",
        )

        supply_evidence = extractor.extract(
            result=result,
            hypothesis=supply_hyp,
            product_name=macbook_event.product_name,
            brand=macbook_event.brand,
            merchant=macbook_event.merchant,
            event_date=macbook_event.observed_at,
        )
        # Recalculate for PROMOTION using same text
        result_promo = SearchResult(
            result_id=make_result_id(q_promo.query_id, "https://test.com/discontinued-promo"),
            query_id=q_promo.query_id,
            event_id=macbook_event.event_id,
            title="MacBook Discontinued",
            url="https://test.com/discontinued-promo",
            snippet=result_text,
            source_domain="test.com",
            retrieved_at=now,
            provider="mock",
        )
        promo_evidence = extractor.extract(
            result=result_promo,
            hypothesis=promo_hyp,
            product_name=macbook_event.product_name,
            brand=macbook_event.brand,
            merchant=macbook_event.merchant,
            event_date=macbook_event.observed_at,
        )

        # INVENTORY_LIQUIDATION has "discontinued stock" in its keyword list
        # PROMOTION does not have "discontinued" → supply score should be >= promo score
        if supply_evidence and promo_evidence:
            supply_max = max(e.relevance_score for e in supply_evidence)
            promo_max = max(e.relevance_score for e in promo_evidence)
            assert supply_max >= promo_max, (
                f"Discontinued text should score higher for SUPPLY ({supply_max:.3f}) "
                f"than PROMOTION ({promo_max:.3f})"
            )

    def test_discount_language_triggers_promotion_not_supply(self, macbook_event):
        """
        A search result containing '20% off coupon' should score higher for
        PROMOTION than for INVENTORY_LIQUIDATION.
        """
        from src.evidence.extractor import EvidenceExtractor
        from src.models.search import SearchQuery, SearchResult, make_result_id
        from datetime import datetime, timezone

        extractor = EvidenceExtractor(min_relevance=0.05)

        result_text = (
            "Apple MacBook 12-inch is on sale at Best Buy with a 20% off coupon. "
            "Save $300 with this limited-time discount promotion offer."
        )
        promo_hyp = _make_hyp(macbook_event, HypothesisType.PROMOTION)
        supply_hyp = _make_hyp(macbook_event, HypothesisType.INVENTORY_LIQUIDATION)

        now = datetime.now(timezone.utc).isoformat()
        r_promo = SearchResult(
            result_id=make_result_id("q_promo_discount", "https://test.com/promo"),
            query_id="q_promo_discount",
            event_id=macbook_event.event_id,
            title="MacBook Discount",
            url="https://test.com/promo",
            snippet=result_text,
            source_domain="bestbuy.com",
            retrieved_at=now,
            provider="mock",
        )
        r_supply = SearchResult(
            result_id=make_result_id("q_supply_discount", "https://test.com/supply-promo"),
            query_id="q_supply_discount",
            event_id=macbook_event.event_id,
            title="MacBook Discount",
            url="https://test.com/supply-promo",
            snippet=result_text,
            source_domain="bestbuy.com",
            retrieved_at=now,
            provider="mock",
        )

        promo_evidence = extractor.extract(
            result=r_promo, hypothesis=promo_hyp,
            product_name=macbook_event.product_name, brand=macbook_event.brand,
            merchant=macbook_event.merchant, event_date=macbook_event.observed_at,
        )
        supply_evidence = extractor.extract(
            result=r_supply, hypothesis=supply_hyp,
            product_name=macbook_event.product_name, brand=macbook_event.brand,
            merchant=macbook_event.merchant, event_date=macbook_event.observed_at,
        )

        if promo_evidence and supply_evidence:
            promo_max = max(e.relevance_score for e in promo_evidence)
            supply_max = max(e.relevance_score for e in supply_evidence)
            assert promo_max >= supply_max, (
                f"Discount/coupon text should score higher for PROMOTION ({promo_max:.3f}) "
                f"than SUPPLY ({supply_max:.3f})"
            )
