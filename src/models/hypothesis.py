"""
src/models/hypothesis.py
=========================
Hypothesis data model for Phase 2 investigation.

A Hypothesis is a plausible explanation for a detected ChangeEvent.
It is generated BEFORE any web search.  The signal_score reflects
how strongly the ChangeEvent signals support this hypothesis type —
it is NOT a verified confidence and does NOT imply the hypothesis is true.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class HypothesisType(str, Enum):
    PROMOTION = "PROMOTION"
    COMPETITOR_RESPONSE = "COMPETITOR_RESPONSE"
    INVENTORY_LIQUIDATION = "INVENTORY_LIQUIDATION"
    PRODUCT_EVENT = "PRODUCT_EVENT"
    SEASONAL_EVENT = "SEASONAL_EVENT"
    MARKET_EVENT = "MARKET_EVENT"
    MANUFACTURER_CHANGE = "MANUFACTURER_CHANGE"
    DATA_ISSUE = "DATA_ISSUE"


@dataclass
class Hypothesis:
    """
    A plausible explanation for a detected price change.

    signal_score: heuristic score [0.0, 1.0] based on ChangeEvent signals.
                  NOT a verified probability.  Do not call it "confidence".
    requires_external_evidence: True when the hypothesis cannot be inferred
                  from ChangeEvent attributes alone (e.g. INVENTORY_LIQUIDATION
                  needs web evidence; do NOT infer from availability field).
    """
    hypothesis_id: str
    event_id: str
    hypothesis_type: HypothesisType
    signal_score: float          # heuristic, NOT verified confidence
    rationale: str               # human-readable explanation of why generated
    signals_matched: List[str]   # which ChangeEvent signals triggered this
    assigned_agents: List[str]   # agent classes that should investigate
    requires_external_evidence: bool
    generated_at: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.signal_score <= 1.0:
            raise ValueError(
                f"signal_score must be in [0.0, 1.0], got {self.signal_score}"
            )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["hypothesis_type"] = self.hypothesis_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Hypothesis":
        data = dict(data)
        data["hypothesis_type"] = HypothesisType(data["hypothesis_type"])
        return cls(**data)


def make_hypothesis_id(event_id: str, hypothesis_type: HypothesisType) -> str:
    raw = f"{event_id}|{hypothesis_type.value}"
    return "hyp_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
