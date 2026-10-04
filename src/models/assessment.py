"""
src/models/assessment.py
=========================
EventAssessment - the final intelligence object for an investigated event.

The assessment collects:
  - all hypotheses that were investigated
  - all evidence collected
  - per-hypothesis assessments (support levels + component scores)
  - overall uncertainty factors

Multiple hypotheses may be SUPPORTED simultaneously.
The system never forces a single winner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.models.evidence import Evidence
from src.models.hypothesis import Hypothesis
from src.models.verification import EvidenceVerification, HypothesisAssessment


@dataclass
class EventAssessment:
    assessment_id: str
    event_id: str
    assessed_at: str          # ISO-8601 UTC

    # --- inputs ---
    hypotheses: List[Hypothesis]
    queries_generated: int
    results_retrieved: int

    # --- collected evidence ---
    evidence: List[Evidence]
    evidence_verifications: List[EvidenceVerification]

    # --- per-hypothesis outcomes ---
    hypothesis_assessments: List[HypothesisAssessment]

    # --- overall ---
    independent_source_count: int
    duplicated_source_count: int
    uncertainty_factors: List[str]   # human-readable list of uncertainty reasons
    summary: str                     # conservative human-readable summary

    # --- event snapshot (extracted from ChangeEvent at assessment time) ---
    event_summary: Dict[str, Any]    # structured snapshot; see _build_event_summary()

    # --- bookkeeping ---
    agent_failures: List[str] = field(default_factory=list)   # any agents that failed
    search_failures: List[str] = field(default_factory=list)  # any queries that failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "event_id": self.event_id,
            "assessed_at": self.assessed_at,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "queries_generated": self.queries_generated,
            "results_retrieved": self.results_retrieved,
            "evidence": [e.to_dict() for e in self.evidence],
            "evidence_verifications": [ev.to_dict() for ev in self.evidence_verifications],
            "hypothesis_assessments": [ha.to_dict() for ha in self.hypothesis_assessments],
            "independent_source_count": self.independent_source_count,
            "duplicated_source_count": self.duplicated_source_count,
            "uncertainty_factors": self.uncertainty_factors,
            "summary": self.summary,
            "event_summary": self.event_summary,
            "agent_failures": self.agent_failures,
            "search_failures": self.search_failures,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventAssessment":
        """Reconstruct an EventAssessment from its serialised dict representation."""
        return cls(
            assessment_id=data["assessment_id"],
            event_id=data["event_id"],
            assessed_at=data["assessed_at"],
            hypotheses=[Hypothesis.from_dict(h) for h in data.get("hypotheses", [])],
            queries_generated=data["queries_generated"],
            results_retrieved=data["results_retrieved"],
            evidence=[Evidence.from_dict(e) for e in data.get("evidence", [])],
            evidence_verifications=[
                EvidenceVerification.from_dict(ev)
                for ev in data.get("evidence_verifications", [])
            ],
            hypothesis_assessments=[
                HypothesisAssessment.from_dict(ha)
                for ha in data.get("hypothesis_assessments", [])
            ],
            independent_source_count=data["independent_source_count"],
            duplicated_source_count=data["duplicated_source_count"],
            uncertainty_factors=data.get("uncertainty_factors", []),
            summary=data.get("summary", ""),
            event_summary=data.get("event_summary", {}),
            agent_failures=data.get("agent_failures", []),
            search_failures=data.get("search_failures", []),
        )
