"""tests/investigation/test_fixes.py
Tests for the 15 pre-approved Phase 2 fixes.
Covers parser edge cases (Fix 12) and verification edge cases (Fix 13).
All tests use direct object construction — no API keys, no network access.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.events.event_generator import ChangeEvent
from src.models.evidence import Evidence, EvidenceSpecificity, RelationshipType
from src.models.hypothesis import Hypothesis, HypothesisType, make_hypothesis_id
from src.models.verification import SupportLevel, SourceIndependenceClass
from src.investigation.verification_agent import VerificationAgent, SourceIndependenceDetector
from src.evidence.parser import SearchResultParser
from src.investigation.hypothesis_generator import HypothesisGenerator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def macbook_event() -> ChangeEvent:
    """Apple MacBook event reused from test_phase2."""
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


def _make_evidence(
    eid: str,
    event_id: str,
    hypothesis_type: str,
    text: str,
    domain: str,
    specificity: EvidenceSpecificity,
    relationship: RelationshipType,
    relevance: float = 0.6,
) -> Evidence:
    return Evidence(
        evidence_id=eid,
        event_id=event_id,
        hypothesis_type=hypothesis_type,
        query_id="q_test",
        result_id="res_test",
        source_url=f"https://{domain}/article",
        source_domain=domain,
        source_title="Test Article",
        retrieved_at="2017-08-19T00:00:00+00:00",
        claim=text[:200],
        evidence_text=text,
        evidence_specificity=specificity,
        relationship_type=relationship,
        relevance_score=relevance,
        investigator="PromotionAgent",
        publication_date="2017-08-15",
    )


def _promo_hypothesis(event: ChangeEvent) -> Hypothesis:
    gen = HypothesisGenerator()
    hyps = gen.generate(event)
    return next(h for h in hyps if h.hypothesis_type == HypothesisType.PROMOTION)


def _comp_hypothesis(event: ChangeEvent) -> Hypothesis:
    """Construct a COMPETITOR_RESPONSE hypothesis directly (macbook event has no competitor signals)."""
    return Hypothesis(
        hypothesis_id=make_hypothesis_id(event.event_id, HypothesisType.COMPETITOR_RESPONSE),
        event_id=event.event_id,
        hypothesis_type=HypothesisType.COMPETITOR_RESPONSE,
        signal_score=0.50,
        rationale="Manually constructed for test",
        signals_matched=["test"],
        assigned_agents=["CompetitorAgent"],
        requires_external_evidence=False,
        generated_at="2017-08-19T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# FIX 12: Parser Exercise Tests
# ---------------------------------------------------------------------------

class TestParserFix12:
    """Parser exercise tests — Test A (valid HTML) and Test B (CAPTCHA block)."""

    def test_parser_test_a_valid_html_with_promotion(self):
        """
        Test A: HTML with <title>, <meta> publication date, and <p> tags
        containing promotional language. Verifies title, paragraphs, parse_success=True.
        """
        html = """<html>
<head>
  <title>Best Buy Summer Sale 2017</title>
  <meta property="article:published_time" content="2017-08-13" />
</head>
<body>
  <p>Best Buy is running a summer sale with up to 30% off MacBook laptops through August 2017.</p>
  <p>The Apple MacBook 12-inch Core m5 is now available for $1099.99, discounted from $1499.99.</p>
  <p>This promotion runs from August 13 to August 20, 2017 at all Best Buy locations.</p>
</body>
</html>"""
        parser = SearchResultParser()
        result = parser.parse(html, url="https://bestbuy.com/summer-sale")

        assert result.parse_success is True
        assert result.source_title == "Best Buy Summer Sale 2017"
        # paragraphs should be extracted into extracted_text
        assert len(result.extracted_text) > 0
        assert "sale" in result.extracted_text.lower() or "discount" in result.extracted_text.lower()

    def test_parser_test_a_publication_date_extracted(self):
        """Meta publication date is extracted from the HTML."""
        html = """<html>
<head>
  <title>MacBook Promotion</title>
  <meta property="article:published_time" content="2017-08-13" />
</head>
<body>
  <p>MacBook is on promotion at Best Buy during August 2017 with significant discounts available.</p>
</body>
</html>"""
        parser = SearchResultParser()
        result = parser.parse(html, url="https://bestbuy.com/promo")

        assert result.parse_success is True
        assert result.publication_date == "2017-08-13"

    def test_parser_test_b_captcha_blocked(self):
        """
        Test B: HTML containing CAPTCHA language.
        Verifies parse_success=False, extracted_text=''.
        """
        captcha_html = """<html>
<head><title>Access Denied</title></head>
<body>
  <p>Please complete the CAPTCHA to verify you are human.</p>
  <p>If you believe this is an error, contact support.</p>
</body>
</html>"""
        parser = SearchResultParser()
        result = parser.parse(captcha_html, url="https://example.com/blocked")

        assert result.parse_success is False
        assert result.extracted_text == ""

    def test_parser_test_b_robot_check_blocked(self):
        """Variant: 'robot check' phrasing also triggers the CAPTCHA guard."""
        html = "<html><body><p>Please complete our robot check before continuing.</p></body></html>"
        parser = SearchResultParser()
        result = parser.parse(html, url="https://example.com/bot-check")

        assert result.parse_success is False
        assert result.extracted_text == ""


# ---------------------------------------------------------------------------
# FIX 13: Edge Case Verification Tests
# ---------------------------------------------------------------------------

class TestVerificationEdgeCases:

    # A. Wrong product — correct merchant, wrong product
    def test_verification_wrong_product(self, macbook_event):
        """Evidence mentions Bestbuy but not MacBook. product_match should be low."""
        text = "Best Buy is having a sale on Samsung TVs and appliances this August."
        ev = _make_evidence(
            "evd_wp_01", macbook_event.event_id, "PROMOTION",
            text, "bestbuy.com",
            EvidenceSpecificity.DIRECT,   # DIRECT because merchant found
            RelationshipType.DESCRIPTIVE,
        )
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, _ = verifier.verify([ev], hyps, macbook_event)
        # With wrong product, product_match=0.0 so the score will be very low
        assert ev_verifs, "Expected at least one verification result"
        # product_match should be 0.0: neither 'apple macbook' nor 'apple' tokens present
        vr = ev_verifs[0]
        assert vr.component_scores.product_match < 0.5, (
            f"Expected low product_match, got {vr.component_scores.product_match}"
        )

    # B. Wrong merchant — correct product, wrong merchant
    def test_verification_wrong_merchant(self, macbook_event):
        """Evidence mentions Apple MacBook but a different merchant. merchant_match should be low."""
        text = "Apple MacBook 12-inch Core m5 is on sale at Amazon for $1099 this August."
        ev = _make_evidence(
            "evd_wm_01", macbook_event.event_id, "PROMOTION",
            text, "amazon.com",
            EvidenceSpecificity.DIRECT,
            RelationshipType.DESCRIPTIVE,
        )
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, _ = verifier.verify([ev], hyps, macbook_event)
        assert ev_verifs
        vr = ev_verifs[0]
        # merchant is Bestbuy.com; evidence only mentions amazon — merchant_match should be low
        assert vr.component_scores.merchant_match < 0.5, (
            f"Expected low merchant_match for wrong merchant, got {vr.component_scores.merchant_match}"
        )

    # C. Generic article — mentions neither product nor merchant
    def test_verification_generic_no_product_no_merchant(self, macbook_event):
        """Generic market article mentioning neither product nor merchant -> INSUFFICIENT_EVIDENCE."""
        text = (
            "The laptop market is experiencing a slowdown in 2017 as consumer spending shifts "
            "towards tablets and smartphones. Industry analysts expect price pressure."
        )
        ev = _make_evidence(
            "evd_gen_01", macbook_event.event_id, "PROMOTION",
            text, "marketwatch.com",
            EvidenceSpecificity.INDIRECT,
            RelationshipType.CORRELATIONAL,
        )
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, _ = verifier.verify([ev], hyps, macbook_event)
        assert ev_verifs
        assert ev_verifs[0].support_level == SupportLevel.INSUFFICIENT_EVIDENCE, (
            f"Expected INSUFFICIENT_EVIDENCE, got {ev_verifs[0].support_level}"
        )

    # D. Contradictory evidence — one says on sale, other says not on sale
    def test_verification_contradictory_evidence(self, macbook_event):
        """Two evidence items with conflicting claims. Contradiction should be detected."""
        ev_sale = _make_evidence(
            "evd_contra_a", macbook_event.event_id, "PROMOTION",
            "Best Buy Apple MacBook is on sale at a discounted price in August 2017.",
            "bestbuy.com",
            EvidenceSpecificity.DIRECT, RelationshipType.DESCRIPTIVE,
        )
        ev_no_sale = _make_evidence(
            "evd_contra_b", macbook_event.event_id, "PROMOTION",
            "Best Buy Apple MacBook is not discounted. The price has not been reduced.",
            "techblog.com",
            EvidenceSpecificity.DIRECT, RelationshipType.DESCRIPTIVE,
        )
        detector = SourceIndependenceDetector()
        result = detector.analyze([ev_sale, ev_no_sale])
        # At least one item should be flagged as CONTRADICTING
        assert SourceIndependenceClass.CONTRADICTING in result.values(), (
            f"Expected CONTRADICTING in {result}"
        )

    # E. Syndicated source — attribution phrase present
    def test_source_independence_syndicated(self):
        """Evidence with 'according to Reuters' should be classified as SYNDICATED."""
        text = (
            "According to Reuters, Best Buy is running a summer promotion on MacBook laptops "
            "with prices reduced by up to $400 during August 2017."
        )
        ev = _make_evidence(
            "evd_synd_01", "e1", "PROMOTION",
            text, "technews.com",
            EvidenceSpecificity.DIRECT, RelationshipType.DESCRIPTIVE,
        )
        detector = SourceIndependenceDetector()
        result = detector.analyze([ev])
        assert result[ev.evidence_id] == SourceIndependenceClass.SYNDICATED, (
            f"Expected SYNDICATED, got {result[ev.evidence_id]}"
        )

    # F. INDEPENDENCE_UNCERTAIN as default (FIX 1 validation)
    def test_source_independence_uncertain_is_default(self):
        """
        Evidence with no duplication/syndication signal and no positive independence
        signal should default to INDEPENDENCE_UNCERTAIN (not INDEPENDENT).
        Fix 1: the fallback was incorrectly INDEPENDENT before this fix.
        """
        text = (
            "The Apple MacBook Core m5 model MLHF2LL/A showed a significant price reduction "
            "at Best Buy in August 2017, dropping from $1499 to $1099."
        )
        ev = _make_evidence(
            "evd_unc_01", "e1", "PROMOTION",
            text, "uniquesite-xyz.com",   # obscure domain, no attribution phrases, no near-duplicate
            EvidenceSpecificity.DIRECT, RelationshipType.DESCRIPTIVE,
        )
        detector = SourceIndependenceDetector()
        result = detector.analyze([ev])
        # With Fix 1 in place, single item with no positive independence signal -> INDEPENDENCE_UNCERTAIN
        assert result[ev.evidence_id] == SourceIndependenceClass.INDEPENDENCE_UNCERTAIN, (
            f"Expected INDEPENDENCE_UNCERTAIN (Fix 1), got {result[ev.evidence_id]}"
        )

    # G. Two hypotheses simultaneously supported
    def test_two_hypotheses_simultaneously_supported(self, macbook_event):
        """
        One set of DIRECT+CAUSAL evidence for PROMOTION and one for COMPETITOR_RESPONSE.
        Both should receive at least PARTIALLY_SUPPORTS — system must not force a single winner.
        """
        promo_hyp = _promo_hypothesis(macbook_event)
        comp_hyp = _comp_hypothesis(macbook_event)

        ev_promo = _make_evidence(
            "evd_sim_promo", macbook_event.event_id, "PROMOTION",
            "Best Buy Apple MacBook is on sale with a $400 discount due to a summer promotion in August 2017.",
            "bestbuy.com",
            EvidenceSpecificity.DIRECT, RelationshipType.CAUSAL,
        )
        ev_comp = _make_evidence(
            "evd_sim_comp", macbook_event.event_id, "COMPETITOR_RESPONSE",
            "Best Buy reduced Apple MacBook pricing by $400 due to competitive pressure from rival retailers in August 2017.",
            "pcmag.com",
            EvidenceSpecificity.DIRECT, RelationshipType.CAUSAL,
        )

        verifier = VerificationAgent()
        _, ha_list = verifier.verify([ev_promo, ev_comp], [promo_hyp, comp_hyp], macbook_event)

        ha_map = {ha.hypothesis_type: ha.support_level for ha in ha_list}
        acceptable = {SupportLevel.SUPPORTS, SupportLevel.PARTIALLY_SUPPORTS}
        assert ha_map.get("PROMOTION") in acceptable, (
            f"PROMOTION should be at least PARTIALLY_SUPPORTS, got {ha_map.get('PROMOTION')}"
        )
        assert ha_map.get("COMPETITOR_RESPONSE") in acceptable, (
            f"COMPETITOR_RESPONSE should be at least PARTIALLY_SUPPORTS, got {ha_map.get('COMPETITOR_RESPONSE')}"
        )

    # H. DIRECT + CAUSAL -> should produce SUPPORTS (strongest case)
    def test_explicit_causal_evidence_with_direct_specificity(self, macbook_event):
        """DIRECT + CAUSAL with product match and temporal alignment should produce SUPPORTS."""
        text = (
            "Best Buy reduced the Apple MacBook Core m5 price by $400 because of "
            "their annual back-to-school promotion running August 2017."
        )
        ev = _make_evidence(
            "evd_direct_causal_01", macbook_event.event_id, "PROMOTION",
            text, "bestbuy.com",
            EvidenceSpecificity.DIRECT, RelationshipType.CAUSAL,
        )
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, _ = verifier.verify([ev], hyps, macbook_event)
        assert ev_verifs
        # Strongest case: expect SUPPORTS
        assert ev_verifs[0].support_level == SupportLevel.SUPPORTS, (
            f"Expected SUPPORTS for DIRECT+CAUSAL evidence, got {ev_verifs[0].support_level}"
        )

    # I. INDIRECT + CORRELATIONAL -> CONSISTENT_WITH at best
    def test_correlational_only_evidence(self, macbook_event):
        """INDIRECT + CORRELATIONAL evidence cannot establish causality -> CONSISTENT_WITH at best."""
        text = (
            "While Best Buy was running summer promotions, laptop prices across the industry "
            "also declined during the same period in August 2017."
        )
        ev = _make_evidence(
            "evd_corr_01", macbook_event.event_id, "PROMOTION",
            text, "techanalytics.com",
            EvidenceSpecificity.INDIRECT, RelationshipType.CORRELATIONAL,
        )
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, _ = verifier.verify([ev], hyps, macbook_event)
        assert ev_verifs
        # Should not be SUPPORTS; CONSISTENT_WITH or weaker
        assert ev_verifs[0].support_level in (
            SupportLevel.CONSISTENT_WITH,
            SupportLevel.INSUFFICIENT_EVIDENCE,
            SupportLevel.PARTIALLY_SUPPORTS,
        ), (
            f"Expected at most CONSISTENT_WITH for INDIRECT+CORRELATIONAL, "
            f"got {ev_verifs[0].support_level}"
        )
        assert ev_verifs[0].support_level != SupportLevel.SUPPORTS, (
            "INDIRECT+CORRELATIONAL evidence must not produce SUPPORTS"
        )

    # J. Empty evidence list -> all hypotheses get INSUFFICIENT_EVIDENCE
    def test_insufficient_evidence_when_no_evidence_retrieved(self, macbook_event):
        """verify() with empty evidence list gives all hypotheses INSUFFICIENT_EVIDENCE."""
        gen = HypothesisGenerator()
        hyps = gen.generate(macbook_event)
        verifier = VerificationAgent()
        ev_verifs, ha_list = verifier.verify([], hyps, macbook_event)

        assert ev_verifs == []
        assert ha_list  # assessments still produced, one per hypothesis
        for ha in ha_list:
            assert ha.support_level == SupportLevel.INSUFFICIENT_EVIDENCE, (
                f"Hypothesis {ha.hypothesis_type}: expected INSUFFICIENT_EVIDENCE, "
                f"got {ha.support_level}"
            )
