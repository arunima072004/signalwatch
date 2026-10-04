"""
src/investigation/verification_agent.py

Evaluates whether collected evidence actually supports each hypothesis.
Uses 8 transparent assessment dimensions.
Preserves all component scores - nothing is hidden.

IMPORTANT:
- Causal keywords are SIGNALS only, not proof.
- Temporal co-occurrence is CONSISTENT_WITH, not SUPPORTS.
- Multiple hypotheses can be SUPPORTED simultaneously.
- Source independence is heuristic, not ground truth.
- The system uses conservative language throughout.
"""
from __future__ import annotations
import logging
import re
from typing import Dict, List, Tuple
from src.events.event_generator import ChangeEvent
from src.models.evidence import Evidence, EvidenceSpecificity, RelationshipType
from src.models.hypothesis import Hypothesis, HypothesisType
from src.models.verification import (
    ComponentScores, EvidenceVerification,
    HypothesisAssessment, SourceIndependenceClass, SupportLevel
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source Independence Detector (heuristic)
# ---------------------------------------------------------------------------

class SourceIndependenceDetector:
    """
    Classifies evidence sources as INDEPENDENT, DUPLICATED, SYNDICATED, etc.
    These are HEURISTIC classifications, not ground truth.
    Signals used: text similarity, same domain, attribution phrases.
    """

    _ATTRIBUTION_PHRASES = [
        "according to", "reported by", "as reported", "originally published",
        "citing", "via ", "source:", "republished",
    ]

    def analyze(self, evidence_list: List[Evidence]) -> Dict[str, SourceIndependenceClass]:
        """
        Returns {evidence_id: SourceIndependenceClass} for each item.
        """
        result: Dict[str, SourceIndependenceClass] = {}
        if not evidence_list:
            return result

        # Group by domain first
        by_domain: Dict[str, List[Evidence]] = {}
        for ev in evidence_list:
            by_domain.setdefault(ev.source_domain, []).append(ev)

        for ev in evidence_list:
            cls = self._classify_one(ev, evidence_list, by_domain)
            result[ev.evidence_id] = cls
        return result

    def _classify_one(self, ev: Evidence, all_ev: List[Evidence],
                      by_domain: Dict[str, List[Evidence]]) -> SourceIndependenceClass:
        text = ev.evidence_text.lower()

        # Shared source signal: same URL cited as evidence for multiple hypotheses
        # A source that supports multiple hypotheses simultaneously is not an
        # independent confirmation of any one of them.
        if ev.shared_source_hypotheses:
            return SourceIndependenceClass.SYNDICATED

        # Syndication signal: attribution phrases
        if any(ph in text for ph in self._ATTRIBUTION_PHRASES):
            return SourceIndependenceClass.SYNDICATED

        # Duplication signal: very similar text from different source
        for other in all_ev:
            if other.evidence_id == ev.evidence_id:
                continue
            if ev.source_domain == other.source_domain:
                continue  # same domain, skip
            sim = self._jaccard(ev.evidence_text, other.evidence_text)
            if sim > 0.75:
                return SourceIndependenceClass.DUPLICATED

        # Contradiction signal: check within same hypothesis
        for other in all_ev:
            if other.evidence_id == ev.evidence_id:
                continue
            if other.hypothesis_type != ev.hypothesis_type:
                continue
            if self._contradicts(ev.evidence_text, other.evidence_text):
                return SourceIndependenceClass.CONTRADICTING

        # Only classify as INDEPENDENT with positive evidence of independence.
        # Default to INDEPENDENCE_UNCERTAIN to avoid inflating independence counts.
        return SourceIndependenceClass.INDEPENDENCE_UNCERTAIN

    def _jaccard(self, a: str, b: str) -> float:
        """Token-level Jaccard similarity. Heuristic approximation."""
        ta = set(re.findall(r"\w+", a.lower()))
        tb = set(re.findall(r"\w+", b.lower()))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def _contradicts(self, a: str, b: str) -> bool:
        """
        Heuristic contradiction detection.
        Looks for negation patterns near shared key terms.
        This is approximate - human review may be needed for complex cases.
        """
        negations = ["no ", "not ", "never ", "no sale", "not discounted", "not reduced"]
        a_lower = a.lower()
        b_lower = b.lower()
        a_neg = any(n in a_lower for n in negations)
        b_neg = any(n in b_lower for n in negations)
        # One says something, the other negates it
        return a_neg != b_neg


# ---------------------------------------------------------------------------
# Verification Agent
# ---------------------------------------------------------------------------

class VerificationAgent:
    """
    Evaluates evidence quality for each hypothesis using 8 dimensions.
    Preserves all component scores for full explainability.
    Never forces a single hypothesis winner.
    """

    def __init__(self) -> None:
        self.independence_detector = SourceIndependenceDetector()

    def verify(self,
               evidence_list: List[Evidence],
               hypotheses: List[Hypothesis],
               event: ChangeEvent) -> Tuple[List[EvidenceVerification], List[HypothesisAssessment]]:
        """
        Main verification entry point.
        Returns per-evidence verifications and per-hypothesis assessments.
        """
        independence_map = self.independence_detector.analyze(evidence_list)
        ev_verifications: List[EvidenceVerification] = []

        for ev in evidence_list:
            hyp = self._find_hypothesis(ev.hypothesis_type, hypotheses)
            if hyp is None:
                continue
            ind_cls = independence_map.get(ev.evidence_id, SourceIndependenceClass.INDEPENDENCE_UNCERTAIN)
            scores, notes = self._score_evidence(ev, hyp, event, ind_cls)
            support = self._determine_support_level(ev, scores, ind_cls)
            ev_verifications.append(EvidenceVerification(
                evidence_id=ev.evidence_id,
                hypothesis_type=ev.hypothesis_type,
                support_level=support,
                independence_class=ind_cls,
                component_scores=scores,
                notes=notes,
            ))

        # Roll up to per-hypothesis assessments
        ha_list = self._assess_hypotheses(hypotheses, ev_verifications, evidence_list, independence_map)
        return ev_verifications, ha_list

    def _find_hypothesis(self, h_type_str: str, hypotheses: List[Hypothesis]):
        for h in hypotheses:
            if h.hypothesis_type.value == h_type_str:
                return h
        return None

    def _score_evidence(self,
                        ev: Evidence,
                        hyp: Hypothesis,
                        event: ChangeEvent,
                        ind_cls: SourceIndependenceClass
                        ) -> Tuple[ComponentScores, str]:
        """
        Score evidence across 8 dimensions.
        All scores kept separate - transparent aggregation only.
        """
        notes_parts: List[str] = []

        # 1. source_quality: inferred from domain characteristics
        sq = self._score_source_quality(ev.source_domain)
        notes_parts.append(f"source_quality={sq:.2f} (domain: {ev.source_domain})")

        # 2. temporal_alignment: evidence pub date vs event date
        ta = self._score_temporal(ev.publication_date, event.observed_at)
        notes_parts.append(f"temporal_alignment={ta:.2f}")

        # 3. product_match: does evidence text actually mention the product or brand?
        # NOTE: specificity can be DIRECT due to merchant mention alone, so we check
        # the text directly rather than relying on the specificity dimension.
        pm = self._score_product_match(ev.evidence_text, event.product_name, event.brand)
        notes_parts.append(f"product_match={pm:.2f} (text-based, product={event.product_name!r})")

        # 4. merchant_match: does evidence name the merchant?
        mm = self._score_merchant_match(ev.evidence_text, event.merchant)
        notes_parts.append(f"merchant_match={mm:.2f}")

        # 5. specificity: quantitative data, named entities, concrete claims
        spec = self._score_specificity(ev.evidence_text)
        notes_parts.append(f"specificity={spec:.2f}")

        # 6. source_independence
        si = {
            SourceIndependenceClass.INDEPENDENT: 1.0,
            SourceIndependenceClass.SYNDICATED: 0.3,
            SourceIndependenceClass.DUPLICATED: 0.2,
            SourceIndependenceClass.CONTRADICTING: 0.0,
            SourceIndependenceClass.INDEPENDENCE_UNCERTAIN: 0.5,
        }.get(ind_cls, 0.5)
        notes_parts.append(f"source_independence={si:.2f} ({ind_cls.value})")

        # 7. causal_strength: how strongly does evidence establish causality?
        # IMPORTANT: causal keywords alone are not proof.
        cs = self._score_causal_strength(ev)
        notes_parts.append(f"causal_strength={cs:.2f} (relationship={ev.relationship_type.value})")

        # 8. contradiction_penalty: does this evidence conflict with others?
        cp = 1.0 if ind_cls == SourceIndependenceClass.CONTRADICTING else 0.0
        notes_parts.append(f"contradiction_penalty={cp:.2f}")

        scores = ComponentScores(
            source_quality=round(sq, 3),
            temporal_alignment=round(ta, 3),
            product_match=round(pm, 3),
            merchant_match=round(mm, 3),
            specificity=round(spec, 3),
            source_independence=round(si, 3),
            causal_strength=round(cs, 3),
            contradiction_penalty=round(cp, 3),
        )
        return scores, "; ".join(notes_parts)

    def _determine_support_level(self,
                                  ev: Evidence,
                                  scores: ComponentScores,
                                  ind_cls: SourceIndependenceClass) -> SupportLevel:
        """
        Conservative support level assignment.

        Rules (all must hold for SUPPORTS):
          - evidence is DIRECT (specificity)
          - temporal alignment >= 0.5
          - product_match >= 0.8
          - NOT solely correlational
          - source is not CONTRADICTING

        Temporal co-occurrence alone => CONSISTENT_WITH, not SUPPORTS.
        Causal keywords without corroboration => PARTIALLY_SUPPORTS at most.
        """
        if ind_cls == SourceIndependenceClass.CONTRADICTING:
            return SupportLevel.CONTRADICTS

        if scores.product_match < 0.5 and scores.merchant_match < 0.3:
            return SupportLevel.INSUFFICIENT_EVIDENCE

        if scores.specificity < 0.2:
            return SupportLevel.INSUFFICIENT_EVIDENCE

        is_direct = ev.evidence_specificity == EvidenceSpecificity.DIRECT
        is_causal = ev.relationship_type == RelationshipType.CAUSAL
        is_descriptive = ev.relationship_type == RelationshipType.DESCRIPTIVE

        # Temporal alignment only, no substance => CONSISTENT_WITH
        if scores.temporal_alignment >= 0.5 and scores.causal_strength < 0.3 and not is_direct:
            return SupportLevel.CONSISTENT_WITH

        # Strong direct evidence with some causal grounding
        if (is_direct and (is_causal or is_descriptive) and
                scores.product_match >= 0.8 and
                scores.temporal_alignment >= 0.4 and
                scores.specificity >= 0.3):
            return SupportLevel.SUPPORTS

        # Direct evidence but weaker
        if is_direct and scores.product_match >= 0.6:
            return SupportLevel.PARTIALLY_SUPPORTS

        # Indirect with some alignment
        if scores.temporal_alignment >= 0.4 and scores.specificity >= 0.2:
            return SupportLevel.CONSISTENT_WITH

        return SupportLevel.INSUFFICIENT_EVIDENCE

    def _assess_hypotheses(self,
                            hypotheses: List[Hypothesis],
                            verifications: List[EvidenceVerification],
                            evidence_list: List[Evidence],
                            independence_map: Dict[str, SourceIndependenceClass]
                            ) -> List[HypothesisAssessment]:
        """
        Roll up per-evidence verifications into per-hypothesis assessments.
        Multiple hypotheses may be SUPPORTED simultaneously.
        """
        assessments: List[HypothesisAssessment] = []
        for hyp in hypotheses:
            h_type = hyp.hypothesis_type.value
            h_verifs = [v for v in verifications if v.hypothesis_type == h_type]
            h_ev = [e for e in evidence_list if e.hypothesis_type == h_type]

            if not h_verifs:
                assessments.append(HypothesisAssessment(
                    hypothesis_id=hyp.hypothesis_id,
                    hypothesis_type=h_type,
                    support_level=SupportLevel.INSUFFICIENT_EVIDENCE,
                    supporting_evidence_ids=[],
                    contradicting_evidence_ids=[],
                    independent_source_count=0,
                    duplicated_source_count=0,
                    component_scores=ComponentScores(),
                    explanation="No evidence was retrieved for this hypothesis.",
                ))
                continue

            support_ids = [v.evidence_id for v in h_verifs
                           if v.support_level in (SupportLevel.SUPPORTS, SupportLevel.PARTIALLY_SUPPORTS)]
            contra_ids = [v.evidence_id for v in h_verifs
                          if v.support_level == SupportLevel.CONTRADICTS]

            ind_count = sum(1 for e in h_ev
                            if independence_map.get(e.evidence_id) == SourceIndependenceClass.INDEPENDENT)
            dup_count = sum(1 for e in h_ev
                            if independence_map.get(e.evidence_id) in (
                                SourceIndependenceClass.DUPLICATED, SourceIndependenceClass.SYNDICATED))

            overall_level = self._roll_up_support(h_verifs)
            agg_scores = self._aggregate_scores([v.component_scores for v in h_verifs])
            explanation = self._explain(overall_level, h_type, support_ids, contra_ids, ind_count)

            assessments.append(HypothesisAssessment(
                hypothesis_id=hyp.hypothesis_id,
                hypothesis_type=h_type,
                support_level=overall_level,
                supporting_evidence_ids=support_ids,
                contradicting_evidence_ids=contra_ids,
                independent_source_count=ind_count,
                duplicated_source_count=dup_count,
                component_scores=agg_scores,
                explanation=explanation,
            ))
        return assessments

    def _roll_up_support(self, verifications: List[EvidenceVerification]) -> SupportLevel:
        """
        Aggregate multiple evidence verdicts into one hypothesis-level verdict.
        Uses the strongest level achieved by any evidence item,
        moderated by contradiction presence.
        """
        levels = [v.support_level for v in verifications]
        if SupportLevel.CONTRADICTS in levels:
            # Some support but also contradictions
            if SupportLevel.SUPPORTS in levels:
                return SupportLevel.PARTIALLY_SUPPORTS
            return SupportLevel.CONTRADICTS
        order = [
            SupportLevel.SUPPORTS,
            SupportLevel.PARTIALLY_SUPPORTS,
            SupportLevel.CONSISTENT_WITH,
            SupportLevel.INSUFFICIENT_EVIDENCE,
        ]
        for level in order:
            if level in levels:
                return level
        return SupportLevel.INSUFFICIENT_EVIDENCE

    def _aggregate_scores(self, score_list: List[ComponentScores]) -> ComponentScores:
        """Average component scores across all evidence for a hypothesis."""
        if not score_list:
            return ComponentScores()
        n = len(score_list)
        return ComponentScores(
            source_quality=round(sum(s.source_quality for s in score_list) / n, 3),
            temporal_alignment=round(sum(s.temporal_alignment for s in score_list) / n, 3),
            product_match=round(sum(s.product_match for s in score_list) / n, 3),
            merchant_match=round(sum(s.merchant_match for s in score_list) / n, 3),
            specificity=round(sum(s.specificity for s in score_list) / n, 3),
            source_independence=round(sum(s.source_independence for s in score_list) / n, 3),
            causal_strength=round(sum(s.causal_strength for s in score_list) / n, 3),
            contradiction_penalty=round(sum(s.contradiction_penalty for s in score_list) / n, 3),
        )

    def _explain(self, level: SupportLevel, h_type: str,
                 support_ids: List[str], contra_ids: List[str], ind_count: int) -> str:
        """Conservative, human-readable explanation."""
        n_sup = len(support_ids)
        n_con = len(contra_ids)
        verb = {
            SupportLevel.SUPPORTS: "Evidence supports",
            SupportLevel.PARTIALLY_SUPPORTS: "Evidence partially supports",
            SupportLevel.CONSISTENT_WITH: "Evidence is consistent with",
            SupportLevel.INSUFFICIENT_EVIDENCE: "Insufficient evidence to assess",
            SupportLevel.CONTRADICTS: "Evidence contradicts",
        }.get(level, "Assessment unclear for")
        parts = [f"{verb} the {h_type} hypothesis."]
        if n_sup:
            parts.append(f"{n_sup} supporting evidence item(s) found.")
        if n_con:
            parts.append(f"{n_con} contradicting evidence item(s) found.")
        if ind_count:
            parts.append(f"{ind_count} independent source(s) identified.")
        else:
            parts.append("Source independence could not be confirmed.")
        return " ".join(parts)

    # ---- Helper scorers ----

    _HIGH_QUALITY_DOMAINS = frozenset([
        "bestbuy.com", "amazon.com", "walmart.com", "target.com",
        "apple.com", "samsung.com", "sony.com",
        "techcrunch.com", "theverge.com", "cnet.com", "pcmag.com",
        "9to5mac.com", "macrumors.com", "engadget.com",
        "reuters.com", "bloomberg.com", "wsj.com", "ft.com",
    ])

    def _score_product_match(self, evidence_text: str, product_name: str, brand: str) -> float:
        """
        Score whether evidence_text mentions the specific product or brand.

        1.0 - full product name found in text
        0.6 - brand name found (but not full product name)
        0.0 - neither product name nor brand found

        This avoids the error of equating specificity=DIRECT (which can be triggered
        by a merchant mention alone) with actual product relevance.
        """
        t = evidence_text.lower()
        # Check for significant tokens from the product name (3+ chars)
        prod_tokens = [tok for tok in product_name.lower().split() if len(tok) >= 3]
        # Full product name: all significant tokens must appear
        if prod_tokens and all(tok in t for tok in prod_tokens):
            return 1.0
        # Brand name present
        if brand and len(brand) >= 3 and brand.lower() in t:
            return 0.6
        return 0.0

    def _score_source_quality(self, domain: str) -> float:
        if domain in self._HIGH_QUALITY_DOMAINS:
            return 0.85
        if domain.endswith(".gov") or domain.endswith(".edu"):
            return 0.90
        if any(domain.endswith(x) for x in [".com", ".co.uk", ".org"]):
            return 0.55
        return 0.35

    def _score_temporal(self, pub_date: str | None, event_date: str) -> float:
        """Score temporal proximity. Returns 0 if dates cannot be compared."""
        if not pub_date:
            return 0.4  # unknown date - moderate uncertainty
        try:
            from datetime import date
            def parse_date(s: str) -> date:
                return date.fromisoformat(s[:10])
            pd_dt = parse_date(pub_date)
            ev_dt = parse_date(event_date)
            delta = abs((pd_dt - ev_dt).days)
            if delta <= 3:   return 1.0
            if delta <= 14:  return 0.8
            if delta <= 30:  return 0.6
            if delta <= 90:  return 0.4
            return 0.2
        except Exception:
            return 0.4

    def _score_merchant_match(self, text: str, merchant: str) -> float:
        # Normalise merchant name: strip TLD and common suffixes
        m = merchant.lower()
        for suffix in [".com", ".co.uk", ".net", ".org", " inc", " llc", " ltd"]:
            m = m.replace(suffix, "")
        m = m.strip()
        t = text.lower()

        # Full normalised merchant name found — strong match
        if m in t:
            return 0.9

        # First significant word of the merchant name (>=4 chars) — partial match
        first_word = m.split()[0] if m.split() else m
        if len(first_word) >= 4 and first_word in t:
            return 0.6

        # Prefix heuristic: check progressively shorter prefixes (min 3 chars)
        # Handles cases like "bestbuy" matching where only "bestb" appears
        for length in range(max(3, len(m) - 3), len(m)):
            prefix = m[:length]
            if len(prefix) >= 3 and prefix in t:
                return 0.5

        return 0.0

    def _score_specificity(self, text: str) -> float:
        score = 0.0
        if re.search(r"\$[\d,]+|\d+%|£[\d,]+", text):
            score += 0.4
        if re.search(r"\b(sale|discount|promo|launch|discontinued|clearance)\b", text, re.I):
            score += 0.3
        if re.search(r"\b\d{4}-\d{2}-\d{2}|\b(january|february|march|april|may|june|july|august|september|october|november|december)\b", text, re.I):
            score += 0.2
        if len(text) > 100:
            score += 0.1
        return min(score, 1.0)

    def _score_causal_strength(self, ev: Evidence) -> float:
        """
        Estimate how strongly evidence establishes a causal relationship.
        Keywords are SIGNALS only - not definitive proof.
        CAUSAL relationship_type already flagged by extractor, but we
        also require the evidence to be specific and direct to score high.
        """
        if ev.relationship_type == RelationshipType.CAUSAL:
            # Has causal language, but specificity matters
            if ev.evidence_specificity == EvidenceSpecificity.DIRECT:
                return 0.70
            return 0.40
        if ev.relationship_type == RelationshipType.DESCRIPTIVE:
            if ev.evidence_specificity == EvidenceSpecificity.DIRECT:
                return 0.50
            return 0.25
        if ev.relationship_type == RelationshipType.CORRELATIONAL:
            return 0.20
        return 0.10
