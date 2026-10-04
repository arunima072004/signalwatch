"""
src/evidence/extractor.py
Evidence extractor: turns SearchResults into Evidence with full provenance.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlparse
from src.models.evidence import Evidence, EvidenceSpecificity, RelationshipType, make_evidence_id
from src.models.search import SearchResult
from src.models.hypothesis import Hypothesis
from src.evidence.parser import SearchResultParser

logger = logging.getLogger(__name__)


class EvidenceExtractor:
    """
    Extracts relevant passages from search results and creates Evidence objects
    with complete provenance and two-dimensional classification.
    """

    def __init__(self, min_relevance: float = 0.20) -> None:
        self.min_relevance = min_relevance
        self.parser = SearchResultParser()

    def extract(self,
                result: SearchResult,
                hypothesis: Hypothesis,
                product_name: str,
                brand: str,
                merchant: str,
                event_date: str) -> List[Evidence]:
        """
        Extract Evidence items from a single SearchResult.
        Returns empty list if nothing relevant is found.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Use full content if available, else snippet
        raw_text = result.full_content or result.snippet
        if not raw_text:
            return []

        parsed = self.parser.parse(raw_text, result.url)
        source_title = parsed.source_title or result.title
        pub_date = parsed.publication_date or result.publication_date

        # Passages to score
        if parsed.extracted_text:
            passages = self.parser.segment_passages(parsed.extracted_text)
        else:
            # Fall back to snippet as single passage
            passages = [result.snippet] if result.snippet and len(result.snippet) > 30 else []

        if not passages:
            return []

        evidence_list: List[Evidence] = []
        for passage in passages:
            score = self._relevance_score(passage, hypothesis, product_name, brand, merchant)
            if score < self.min_relevance:
                continue
            spec = self._classify_specificity(passage, product_name, brand, merchant)
            rel = self._classify_relationship(passage)
            claim = self._extract_claim(passage, product_name, merchant)
            ev_id = make_evidence_id(result.result_id, passage)
            evidence_list.append(Evidence(
                evidence_id=ev_id,
                event_id=result.event_id,
                hypothesis_type=hypothesis.hypothesis_type.value,
                query_id=result.query_id,
                result_id=result.result_id,
                source_url=result.url,
                source_domain=result.source_domain,
                source_title=source_title,
                retrieved_at=now,
                claim=claim,
                evidence_text=passage[:800],
                evidence_specificity=spec,
                relationship_type=rel,
                relevance_score=round(score, 3),
                investigator=hypothesis.assigned_agents[0] if hypothesis.assigned_agents else "unknown",
                publication_date=pub_date,
            ))
        return evidence_list

    # ------------------------------------------------------------------
    # Scoring and classification helpers
    # ------------------------------------------------------------------

    def _relevance_score(self, passage: str, hypothesis: Hypothesis,
                         product_name: str, brand: str, merchant: str) -> float:
        """
        Weighted relevance score [0.0, 1.0].
        Components are kept separate and transparent.
        """
        p = passage.lower()

        # Entity match (0.40 weight)
        entity = 0.0
        if product_name.lower() in p:
            entity += 0.50
        if brand.lower() in p:
            entity += 0.30
        if merchant.lower().split(".")[0] in p:
            entity += 0.20
        entity = min(entity, 1.0)

        # Hypothesis keyword match (0.35 weight)
        kw_score = self._keyword_score(p, hypothesis.hypothesis_type.value)

        # Numeric signals - prices or percentages (0.15 weight)
        has_price = bool(re.search(r"\$[\d,]+|\d+%|£[\d,]+", passage))
        numeric = 0.8 if has_price else 0.0

        # Temporal signal (0.10 weight)
        has_date = bool(re.search(r"\b(20\d\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", p))
        temporal = 0.7 if has_date else 0.0

        score = 0.40 * entity + 0.35 * kw_score + 0.15 * numeric + 0.10 * temporal
        return round(min(score, 1.0), 3)

    _HYPOTHESIS_KEYWORDS = {
        "PROMOTION": ["sale","discount","promo","promotion","deal","offer","coupon","off","markdown","clearance price"],
        "COMPETITOR_RESPONSE": ["competitor","competition","rival","price war","match","undercut","price match","competitive pricing","market share"],
        "INVENTORY_LIQUIDATION": ["clearance","liquidation","overstock","excess inventory","end of line","discontinued stock"],
        "PRODUCT_EVENT": ["launch","new model","refresh","discontinu","successor","released","announced","updated"],
        "SEASONAL_EVENT": ["back to school","holiday","black friday","cyber monday","seasonal","summer","winter"],
        "MARKET_EVENT": ["market","industry","supply chain","tariff","inflation","demand","shortage"],
        "MANUFACTURER_CHANGE": ["msrp","manufacturer","list price","price change","official price"],
        "DATA_ISSUE": ["error","incorrect","wrong price","data","glitch"],
    }

    def _keyword_score(self, passage_lower: str, hypothesis_type: str) -> float:
        keywords = self._HYPOTHESIS_KEYWORDS.get(hypothesis_type, [])
        if not keywords:
            return 0.0
        hits = sum(1 for k in keywords if k in passage_lower)
        return min(hits / max(len(keywords) * 0.4, 1), 1.0)

    def _classify_specificity(self, passage: str, product_name: str,
                               brand: str, merchant: str) -> EvidenceSpecificity:
        """
        DIRECT: passage names the specific product or merchant.
        INDIRECT: passage discusses brand, category, or market.
        """
        p = passage.lower()
        if (product_name.lower() in p or
                merchant.lower().split(".")[0] in p):
            return EvidenceSpecificity.DIRECT
        return EvidenceSpecificity.INDIRECT

    def _classify_relationship(self, passage: str) -> RelationshipType:
        """
        Classify the relationship type based on text analysis.

        Priority order: CAUSAL > DESCRIPTIVE > CORRELATIONAL > UNKNOWN
        Rationale:
          - CAUSAL is checked first because explicit causal language ("because",
            "due to", "caused by") is the strongest signal when present, and
            should not be overridden by weaker patterns.
          - DESCRIPTIVE is checked next: factual statements about a price or
            availability are meaningful even without causal framing.
          - CORRELATIONAL is for temporal co-occurrence language with no stated
            cause or description.
          - UNKNOWN is the safe default when no pattern matches.

        IMPORTANT: causal keywords are SIGNALS only — the verifier layer
        determines whether causality is actually established after examining
        source quality, specificity, and corroboration.
        NOTE: causal keywords are SIGNALS only — the verifier determines actual causality.
        The verifier still determines whether causality is genuinely established.
        """
        p = passage.lower()
        causal_phrases = [
            "because", "due to", "caused by", "resulted from",
            "as a result of", "in response to", "triggered by",
        ]
        correlational_phrases = [
            "at the same time", "coinciding", "also", "during the same",
            "around the same period", "while",
        ]
        descriptive_phrases = [
            "is available", "is priced", "costs", "the price is",
            "is on sale", "is discounted", "is reduced",
        ]
        # Causal language detected - flag as potential CAUSAL (verifier must confirm)
        if any(ph in p for ph in causal_phrases):
            return RelationshipType.CAUSAL
        if any(ph in p for ph in descriptive_phrases):
            return RelationshipType.DESCRIPTIVE
        if any(ph in p for ph in correlational_phrases):
            return RelationshipType.CORRELATIONAL
        return RelationshipType.UNKNOWN

    def _extract_claim(self, passage: str, product_name: str, merchant: str) -> str:
        """Short summary claim extracted from the passage."""
        # First sentence that mentions the product or merchant
        sentences = re.split(r"(?<=[.!?])\s+", passage)
        p_lower = product_name.lower()
        m_lower = merchant.lower().split(".")[0]
        for s in sentences:
            if p_lower in s.lower() or m_lower in s.lower():
                return s[:200]
        # Fallback: first sentence
        return sentences[0][:200] if sentences else passage[:200]
