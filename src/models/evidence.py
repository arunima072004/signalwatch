"""
src/models/evidence.py
=======================
Evidence data model with two independent classification dimensions.

evidence_specificity: how directly the source relates to this product/merchant
  DIRECT   - explicitly mentions the specific product or merchant
  INDIRECT - discusses the category, brand, or market more broadly

relationship_type: the nature of the claimed relationship
  CAUSAL        - source explicitly states a cause (strong claim)
  CORRELATIONAL - events co-occurred but no causation stated
  DESCRIPTIVE   - source describes a fact without causal framing
  UNKNOWN       - cannot be determined from available text

These are SEPARATE dimensions.  An evidence item may be DIRECT + CAUSAL,
or DIRECT + DESCRIPTIVE, or INDIRECT + CORRELATIONAL, etc.

Provenance chain:
  ChangeEvent -> Hypothesis -> SearchQuery(query_id) -> SearchResult(result_id) -> Evidence(evidence_id)
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceSpecificity(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"


class RelationshipType(str, Enum):
    CAUSAL = "CAUSAL"
    CORRELATIONAL = "CORRELATIONAL"
    DESCRIPTIVE = "DESCRIPTIVE"
    UNKNOWN = "UNKNOWN"


@dataclass
class Evidence:
    evidence_id: str
    event_id: str
    hypothesis_type: str
    query_id: str
    result_id: str
    source_url: str
    source_domain: str
    source_title: str
    retrieved_at: str
    claim: str
    evidence_text: str
    evidence_specificity: EvidenceSpecificity
    relationship_type: RelationshipType
    relevance_score: float
    investigator: str
    publication_date: Optional[str] = None
    strategy: str = ""   # which strategy found this evidence (e.g. "PROMOTION", "COMPETITOR_RESPONSE")
    shared_source_hypotheses: List[str] = field(default_factory=list)  # other hypotheses sharing this source URL

    def __post_init__(self) -> None:
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError(f"relevance_score must be in [0.0, 1.0], got {self.relevance_score}")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence_specificity"] = self.evidence_specificity.value
        d["relationship_type"] = self.relationship_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        data = dict(data)
        data["evidence_specificity"] = EvidenceSpecificity(data["evidence_specificity"])
        data["relationship_type"] = RelationshipType(data["relationship_type"])
        # Handle missing new fields for backward compatibility with older serialized data
        data.setdefault("strategy", "")
        data.setdefault("shared_source_hypotheses", [])
        return cls(**data)


def make_evidence_id(result_id: str, passage: str) -> str:
    raw = f"{result_id}|{passage[:80]}"
    return "evd_" + hashlib.sha256(raw.encode()).hexdigest()[:12]