"""
src/models/verification.py
===========================
Verification result models.

The verifier preserves ALL component scores so the final assessment
is always explainable.  No opaque formulas.

SupportLevel vocabulary (conservative):
  SUPPORTS              - strong, specific, direct evidence with corroboration
  PARTIALLY_SUPPORTS    - some relevant evidence but incomplete
  CONSISTENT_WITH       - temporal/topical alignment, no causation established
  INSUFFICIENT_EVIDENCE - too little or too vague to assess
  CONTRADICTS           - evidence conflicts with the hypothesis
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SupportLevel(str, Enum):
    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    CONSISTENT_WITH = "CONSISTENT_WITH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRADICTS = "CONTRADICTS"


class SourceIndependenceClass(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    DUPLICATED = "DUPLICATED"
    SYNDICATED = "SYNDICATED"
    CONTRADICTING = "CONTRADICTING"
    INDEPENDENCE_UNCERTAIN = "INDEPENDENCE_UNCERTAIN"


@dataclass
class ComponentScores:
    """
    Eight explainable verification dimensions.
    Each score in [0.0, 1.0].  All are preserved; none are hidden.
    """
    source_quality: float = 0.0
    temporal_alignment: float = 0.0
    product_match: float = 0.0
    merchant_match: float = 0.0
    specificity: float = 0.0
    source_independence: float = 0.0
    causal_strength: float = 0.0
    contradiction_penalty: float = 0.0   # 0 = no contradiction, 1 = strong contradiction

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "ComponentScores":
        return cls(**data)


@dataclass
class EvidenceVerification:
    """Verification result for one Evidence item against one hypothesis."""
    evidence_id: str
    hypothesis_type: str
    support_level: SupportLevel
    independence_class: SourceIndependenceClass
    component_scores: ComponentScores
    notes: str                        # human-readable explanation

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["support_level"] = self.support_level.value
        d["independence_class"] = self.independence_class.value
        d["component_scores"] = self.component_scores.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceVerification":
        data = dict(data)
        data["support_level"] = SupportLevel(data["support_level"])
        data["independence_class"] = SourceIndependenceClass(data["independence_class"])
        data["component_scores"] = ComponentScores.from_dict(data["component_scores"])
        return cls(**data)


@dataclass
class HypothesisAssessment:
    """
    Rolled-up assessment for one hypothesis after all evidence is verified.

    Multiple hypotheses in the same EventAssessment may all be SUPPORTED.
    The system does NOT force a single winner.
    """
    hypothesis_id: str
    hypothesis_type: str
    support_level: SupportLevel
    supporting_evidence_ids: List[str]
    contradicting_evidence_ids: List[str]
    independent_source_count: int
    duplicated_source_count: int
    component_scores: ComponentScores  # aggregate across all evidence
    explanation: str                   # conservative, human-readable summary

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["support_level"] = self.support_level.value
        d["component_scores"] = self.component_scores.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HypothesisAssessment":
        data = dict(data)
        data["support_level"] = SupportLevel(data["support_level"])
        data["component_scores"] = ComponentScores.from_dict(data["component_scores"])
        return cls(**data)