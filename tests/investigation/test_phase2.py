"""tests/investigation/test_phase2.py
Phase 2 vertical slice tests. All tests use MockSearchProvider.
No API keys or network access required.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.events.event_generator import ChangeEvent
from src.models.hypothesis import HypothesisType
from src.models.evidence import EvidenceSpecificity, RelationshipType
from src.models.verification import SupportLevel, SourceIndependenceClass
from src.investigation.hypothesis_generator import HypothesisGenerator
from src.investigation.investigation_agent import InvestigationAgent, PromotionStrategy
from src.investigation.verification_agent import VerificationAgent, SourceIndependenceDetector
from src.investigation.orchestrator import InvestigationOrchestrator
from src.search.mock_provider import MockSearchProvider
from src.evidence.extractor import EvidenceExtractor
from src.evidence.parser import SearchResultParser


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
def mock_provider() -> MockSearchProvider:
    return MockSearchProvider()


@pytest.fixture
def extractor() -> EvidenceExtractor:
    return EvidenceExtractor(min_relevance=0.10)


# ---------------------------------------------------------------------------
# Hypothesis Generator Tests
# ---------------------------------------------------------------------------

class TestHypothesisGenerator:
    def test_generates_at_least_two_hypotheses(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        assert len(hyps) >= 2

    def test_uses_signal_score_not_confidence(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        for h in hyps:
            assert hasattr(h, "signal_score")
            assert not hasattr(h, "confidence")
            assert 0.0 <= h.signal_score <= 1.0

    def test_promotion_hypothesis_generated_for_decrease(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        types = {h.hypothesis_type for h in hyps}
        # 26.7% decrease should trigger PROMOTION or PRODUCT_EVENT
        assert HypothesisType.PROMOTION in types or HypothesisType.PRODUCT_EVENT in types

    def test_inventory_liquidation_flagged_as_requiring_external_evidence(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        for h in hyps:
            if h.hypothesis_type == HypothesisType.INVENTORY_LIQUIDATION:
                assert h.requires_external_evidence is True

    def test_all_hypotheses_have_rationale(self, macbook_event):
        gen = HypothesisGenerator()
        for h in gen.generate(macbook_event):
            assert h.rationale
            assert h.event_id == macbook_event.event_id

    def test_hypotheses_sorted_by_signal_score(self, macbook_event):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        scores = [h.signal_score for h in hyps]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# SearchQuery / PromotionStrategy Tests (formerly PromotionAgent)
# ---------------------------------------------------------------------------

class TestPromotionAgent:
    def test_can_investigate_promotion(self, macbook_event, mock_provider, extractor):
        agent = InvestigationAgent(mock_provider)
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        promo = next(h for h in hyps if h.hypothesis_type == HypothesisType.PROMOTION)
        # PromotionStrategy handles PROMOTION — evidence must be collected
        strategy = PromotionStrategy()
        queries = strategy.generate_queries(macbook_event, promo)
        assert len(queries) >= 3

    def test_generates_structured_query_objects(self, macbook_event, mock_provider, extractor):
        strategy = PromotionStrategy()
        gen = HypothesisGenerator()
        promo = next(h for h in gen.generate(macbook_event) if h.hypothesis_type == HypothesisType.PROMOTION)
        queries = strategy.generate_queries(macbook_event, promo)
        assert len(queries) >= 3
        for q in queries:
            assert q.query_id
            assert q.event_id == macbook_event.event_id
            assert q.product_name == macbook_event.product_name
            assert q.merchant == macbook_event.merchant
            assert q.generated_by == "PromotionStrategy"
            assert q.date_window
            assert q.query_text
            assert q.purpose

    def test_query_text_contains_product_or_brand(self, macbook_event, mock_provider, extractor):
        strategy = PromotionStrategy()
        gen = HypothesisGenerator()
        promo = next(h for h in gen.generate(macbook_event) if h.hypothesis_type == HypothesisType.PROMOTION)
        queries = strategy.generate_queries(macbook_event, promo)
        texts = " ".join(q.query_text.lower() for q in queries)
        assert "apple" in texts or "macbook" in texts


# ---------------------------------------------------------------------------
# MockSearchProvider Tests
# ---------------------------------------------------------------------------

class TestMockSearchProvider:
    def test_returns_results_for_sale_keyword(self, macbook_event, mock_provider, extractor):
        from src.models.search import SearchQuery
        q = SearchQuery(
            query_id="test_q1", event_id=macbook_event.event_id,
            hypothesis_type="PROMOTION", query_text="macbook sale August 2017",
            purpose="test", priority=1, generated_by="test",
            product_name="MacBook", brand="Apple", merchant="Bestbuy.com",
            category="Electronics", date_window="August 2017",
        )
        results = mock_provider.search(q)
        assert isinstance(results, list)
        for r in results:
            assert r.query_id == "test_q1"
            assert r.url
            assert r.source_domain

    def test_empty_scenario_returns_no_results(self, macbook_event):
        provider = MockSearchProvider(scenario="empty")
        from src.models.search import SearchQuery
        q = SearchQuery(
            query_id="test_empty", event_id="e1",
            hypothesis_type="PROMOTION", query_text="sale",
            purpose="test", priority=1, generated_by="test",
            product_name="X", brand="Y", merchant="Z",
            category="C", date_window="Jan 2017",
        )
        assert provider.search(q) == []

    def test_failure_scenario_raises(self, macbook_event):
        from src.search.provider_interface import SearchProviderError
        provider = MockSearchProvider(scenario="failure")
        from src.models.search import SearchQuery
        q = SearchQuery(
            query_id="test_fail", event_id="e1",
            hypothesis_type="PROMOTION", query_text="sale",
            purpose="test", priority=1, generated_by="test",
            product_name="X", brand="Y", merchant="Z",
            category="C", date_window="Jan 2017",
        )
        with pytest.raises(SearchProviderError):
            provider.search(q)


# ---------------------------------------------------------------------------
# Evidence Extractor Tests
# ---------------------------------------------------------------------------

class TestEvidenceExtractor:
    def _get_promo_evidence(self, macbook_event, mock_provider, extractor):
        """Helper: get evidence for PROMOTION hypothesis via InvestigationAgent."""
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        promo = next(h for h in hyps if h.hypothesis_type == HypothesisType.PROMOTION)
        agent = InvestigationAgent(mock_provider, min_relevance=0.10)
        evidence = agent.investigate_event(macbook_event, [promo])
        return [ev for ev in evidence if ev.hypothesis_type == "PROMOTION"]

    def test_evidence_has_two_independent_dimensions(self, macbook_event, mock_provider, extractor):
        evidence = self._get_promo_evidence(macbook_event, mock_provider, extractor)
        for ev in evidence:
            assert hasattr(ev, "evidence_specificity")
            assert hasattr(ev, "relationship_type")
            assert isinstance(ev.evidence_specificity, EvidenceSpecificity)
            assert isinstance(ev.relationship_type, RelationshipType)

    def test_evidence_has_complete_provenance(self, macbook_event, mock_provider, extractor):
        evidence = self._get_promo_evidence(macbook_event, mock_provider, extractor)
        for ev in evidence:
            assert ev.evidence_id
            assert ev.event_id == macbook_event.event_id
            assert ev.query_id
            assert ev.result_id
            assert ev.source_url
            assert ev.source_domain
            assert ev.retrieved_at
            assert ev.investigator

    def test_relevance_score_in_valid_range(self, macbook_event, mock_provider, extractor):
        evidence = self._get_promo_evidence(macbook_event, mock_provider, extractor)
        for ev in evidence:
            assert 0.0 <= ev.relevance_score <= 1.0


# ---------------------------------------------------------------------------
# Verification Agent Tests
# ---------------------------------------------------------------------------

class TestVerificationAgent:
    def _get_promo_evidence(self, macbook_event, mock_provider):
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        promo = next(h for h in hyps if h.hypothesis_type == HypothesisType.PROMOTION)
        agent = InvestigationAgent(mock_provider, min_relevance=0.10)
        return agent.investigate_event(macbook_event, [promo]), hyps

    def test_returns_component_scores_not_opaque_number(self, macbook_event, mock_provider, extractor):
        evidence, hyps = self._get_promo_evidence(macbook_event, mock_provider)
        verifier = VerificationAgent()
        ev_verifs, ha_list = verifier.verify(evidence, hyps, macbook_event)
        for ev_v in ev_verifs:
            scores = ev_v.component_scores
            assert hasattr(scores, "source_quality")
            assert hasattr(scores, "temporal_alignment")
            assert hasattr(scores, "product_match")
            assert hasattr(scores, "merchant_match")
            assert hasattr(scores, "specificity")
            assert hasattr(scores, "source_independence")
            assert hasattr(scores, "causal_strength")
            assert hasattr(scores, "contradiction_penalty")

    def test_multiple_hypotheses_can_be_supported(self, macbook_event, mock_provider, extractor):
        evidence, hyps = self._get_promo_evidence(macbook_event, mock_provider)
        verifier = VerificationAgent()
        _, ha_list = verifier.verify(evidence, hyps, macbook_event)
        # System must not force a single winner
        assert ha_list  # at least one assessment exists
        # All support levels must be valid enum values
        for ha in ha_list:
            assert isinstance(ha.support_level, SupportLevel)

    def test_causal_keywords_alone_do_not_force_supports(self, macbook_event):
        """Causal keywords in text are signals, not proof."""
        from src.models.evidence import Evidence
        ev_with_causal = Evidence(
            evidence_id="test_causal",
            event_id=macbook_event.event_id,
            hypothesis_type="PROMOTION",
            query_id="q1", result_id="r1",
            source_url="https://example.com/article",
            source_domain="example.com",
            source_title="Article",
            retrieved_at="2017-08-19T00:00:00+00:00",
            claim="Price dropped because of a promotion",
            evidence_text="The price dropped because of a summer promotion.",
            evidence_specificity=EvidenceSpecificity.INDIRECT,  # not direct!
            relationship_type=RelationshipType.CAUSAL,
            relevance_score=0.4,
            investigator="PromotionStrategy",
        )
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, _ = verifier.verify([ev_with_causal], hyps, macbook_event)
        if ev_verifs:
            # INDIRECT + CAUSAL should not be SUPPORTS - only PARTIALLY_SUPPORTS at best
            assert ev_verifs[0].support_level != SupportLevel.SUPPORTS


# ---------------------------------------------------------------------------
# Source Independence Tests
# ---------------------------------------------------------------------------

class TestSourceIndependence:
    def test_classifies_identical_text_as_duplicated(self, macbook_event):
        from src.models.evidence import Evidence
        text = "Best Buy offers 30% off Apple MacBook during summer sale"
        def make_ev(eid, domain):
            return Evidence(
                evidence_id=eid, event_id="e1", hypothesis_type="PROMOTION",
                query_id="q1", result_id="r1",
                source_url=f"https://{domain}/article",
                source_domain=domain, source_title="Title", retrieved_at="2017-08-19T00:00:00",
                claim=text, evidence_text=text,
                evidence_specificity=EvidenceSpecificity.DIRECT,
                relationship_type=RelationshipType.DESCRIPTIVE,
                relevance_score=0.8, investigator="PromotionAgent",
            )
        ev1 = make_ev("evd_001", "site1.com")
        ev2 = make_ev("evd_002", "site2.com")
        detector = SourceIndependenceDetector()
        result = detector.analyze([ev1, ev2])
        # At least one should be flagged as non-independent
        values = list(result.values())
        assert SourceIndependenceClass.INDEPENDENT not in values or len(values) < 2

    def test_independent_sources_classified_correctly(self, macbook_event):
        from src.models.evidence import Evidence
        def make_ev(eid, domain, text):
            return Evidence(
                evidence_id=eid, event_id="e1", hypothesis_type="PROMOTION",
                query_id="q1", result_id="r1",
                source_url=f"https://{domain}/article",
                source_domain=domain, source_title="Title", retrieved_at="2017-08-19T00:00:00",
                claim=text, evidence_text=text,
                evidence_specificity=EvidenceSpecificity.DIRECT,
                relationship_type=RelationshipType.DESCRIPTIVE,
                relevance_score=0.8, investigator="PromotionAgent",
            )
        ev1 = make_ev("evd_001", "bestbuy.com", "Best Buy MacBook sale August 2017 up to 30 percent off")
        ev2 = make_ev("evd_002", "9to5mac.com", "9to5mac reports laptop price cuts for back to school season")
        detector = SourceIndependenceDetector()
        result = detector.analyze([ev1, ev2])
        # Fix 1: sources with no positive independence signal default to INDEPENDENCE_UNCERTAIN,
        # not INDEPENDENT. Verify neither is flagged as DUPLICATED, SYNDICATED, or CONTRADICTING.
        for cls in result.values():
            assert cls not in (
                SourceIndependenceClass.DUPLICATED,
                SourceIndependenceClass.SYNDICATED,
                SourceIndependenceClass.CONTRADICTING,
            ), f"Unexpected negative classification {cls} for dissimilar sources"


# ---------------------------------------------------------------------------
# Full Orchestration Test
# ---------------------------------------------------------------------------

class TestOrchestrator:
    def test_full_vertical_slice(self, macbook_event, mock_provider, tmp_path):
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

    def test_assessment_serializes_to_json(self, macbook_event, mock_provider, tmp_path):
        orchestrator = InvestigationOrchestrator(
            search_provider=mock_provider,
            output_dir=tmp_path,
        )
        assessment = orchestrator.investigate(macbook_event)
        out_path = orchestrator.save(assessment)
        assert out_path.exists()
        import json
        with open(out_path) as f:
            data = json.load(f)
        assert data["event_id"] == macbook_event.event_id
        assert "hypothesis_assessments" in data
        assert "evidence" in data

    def test_provenance_chain_intact(self, macbook_event, mock_provider, tmp_path):
        """Every evidence item must trace back to event -> query -> result."""
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

    def test_agent_failure_does_not_crash_pipeline(self, macbook_event, tmp_path):
        """A failing search provider should not crash the orchestrator."""
        failing_provider = MockSearchProvider(scenario="failure")
        orchestrator = InvestigationOrchestrator(
            search_provider=failing_provider,
            output_dir=tmp_path,
        )
        # Should complete without raising
        assessment = orchestrator.investigate(macbook_event)
        assert assessment is not None
        assert assessment.event_id == macbook_event.event_id
