"""
src/investigation/hypothesis_generator.py
Generates plausible hypotheses from a ChangeEvent.

signal_score is a HEURISTIC score based on ChangeEvent attributes.
It is NOT a verified confidence and does NOT claim the hypothesis is true.
Actual evidentiary support is determined by the verification layer.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import List, Tuple
from src.events.event_generator import ChangeEvent
from src.models.hypothesis import Hypothesis, HypothesisType, make_hypothesis_id

logger = logging.getLogger(__name__)

# Hypothesis type -> (requires_external_evidence, assigned_agents)
_META = {
    HypothesisType.PROMOTION:            (False, ["PromotionAgent", "RetailerEventAgent"]),
    HypothesisType.COMPETITOR_RESPONSE:  (False, ["CompetitorAgent"]),
    HypothesisType.INVENTORY_LIQUIDATION:(True,  ["SupplyAgent"]),
    HypothesisType.PRODUCT_EVENT:        (True,  ["ProductEventAgent"]),
    HypothesisType.SEASONAL_EVENT:       (False, ["NewsAgent", "RetailerEventAgent"]),
    HypothesisType.MARKET_EVENT:         (True,  ["NewsAgent"]),
    HypothesisType.MANUFACTURER_CHANGE:  (True,  ["ProductEventAgent", "SupplyAgent"]),
    HypothesisType.DATA_ISSUE:           (False, []),
}

# ---------------------------------------------------------------------------
# Signal weights — heuristic weights for each ChangeEvent signal type.
# These drive signal_score calculation in HypothesisGenerator.generate().
# They can be inspected and overridden in tests without changing logic.
# ---------------------------------------------------------------------------
_SIGNAL_WEIGHTS = {
    # PROMOTION signals
    "is_sale": 0.75,
    "price_decrease_10pct": 0.55,
    "offer_url": 0.45,
    # COMPETITOR_RESPONSE signals
    "competitor_count_2": 0.45,
    "competitors_changed_7d": 0.55,
    "competitor_direction": 0.35,
    # INVENTORY_LIQUIDATION signals
    "large_decrease_20pct": 0.40,
    # PRODUCT_EVENT signals
    "extreme_change_25pct": 0.40,
    "short_run_length": 0.35,
    # SEASONAL_EVENT signals
    "seasonal_aug_sep": 0.40,
    "seasonal_nov_dec": 0.50,
    "seasonal_jun_jul": 0.30,
    # MANUFACTURER_CHANGE signals
    "msrp_change_signal": 0.35,
    # DATA_ISSUE signals
    "data_issue_60pct": 0.45,
}


def _combine_signals(weights: List[float]) -> float:
    """
    Combine independent signal weights into a single score.
    Uses complement probability: 1 - product(1 - w).
    Capped at 0.92 to avoid implying near-certainty.
    """
    if not weights:
        return 0.0
    p_absent = 1.0
    for w in weights:
        p_absent *= (1.0 - w)
    return min(round(1.0 - p_absent, 3), 0.92)


class HypothesisGenerator:
    """
    Generates plausible hypotheses from ChangeEvent signals.
    Multiple non-exclusive hypotheses may be generated.
    """

    def generate(self, event: ChangeEvent) -> List[Hypothesis]:
        """
        Analyse ChangeEvent signals and return a list of Hypothesis objects.
        At least 2 hypotheses are always returned.
        """
        candidates: List[Tuple[HypothesisType, float, List[str]]] = []
        pct = event.percentage_change or 0.0
        direction = event.change_direction

        # --- PROMOTION ---
        promo_weights, promo_signals = [], []
        if event.is_sale:
            promo_weights.append(_SIGNAL_WEIGHTS["is_sale"])
            promo_signals.append("is_sale=True")
        if direction == "decrease" and abs(pct) >= 10:
            promo_weights.append(_SIGNAL_WEIGHTS["price_decrease_10pct"])
            promo_signals.append(f"price decrease {pct:.1f}%")
        if event.offer:
            promo_weights.append(_SIGNAL_WEIGHTS["offer_url"])
            promo_signals.append("offer URL present")
        if promo_weights:
            candidates.append((HypothesisType.PROMOTION, _combine_signals(promo_weights), promo_signals))

        # --- COMPETITOR_RESPONSE ---
        comp_weights, comp_signals = [], []
        if event.competitor_count >= 2:
            comp_weights.append(_SIGNAL_WEIGHTS["competitor_count_2"])
            comp_signals.append(f"competitor_count={event.competitor_count}")
        if event.competitors_changed_7d >= 1:
            comp_weights.append(_SIGNAL_WEIGHTS["competitors_changed_7d"])
            comp_signals.append(f"competitors_changed_7d={event.competitors_changed_7d}")
        if event.competitor_direction_7d != 0:
            comp_weights.append(_SIGNAL_WEIGHTS["competitor_direction"])
            comp_signals.append(f"competitor_direction_7d={event.competitor_direction_7d}")
        if comp_weights:
            candidates.append((HypothesisType.COMPETITOR_RESPONSE, _combine_signals(comp_weights), comp_signals))

        # --- INVENTORY_LIQUIDATION ---
        # NOTE: availability field alone is NOT sufficient.
        # A large drop is a signal but external evidence is required.
        inv_weights, inv_signals = [], []
        if direction == "decrease" and abs(pct) >= 20:
            inv_weights.append(_SIGNAL_WEIGHTS["large_decrease_20pct"])
            inv_signals.append(f"large price decrease {pct:.1f}%")
        if inv_weights:
            candidates.append((HypothesisType.INVENTORY_LIQUIDATION, _combine_signals(inv_weights), inv_signals))

        # --- PRODUCT_EVENT ---
        prod_weights, prod_signals = [], []
        if abs(pct) >= 25:
            prod_weights.append(_SIGNAL_WEIGHTS["extreme_change_25pct"])
            prod_signals.append(f"extreme price change {pct:.1f}%")
        if event.map_run_length <= 2:
            prod_weights.append(_SIGNAL_WEIGHTS["short_run_length"])
            prod_signals.append(f"short run length ({event.map_run_length}) suggests new regime")
        if prod_weights:
            candidates.append((HypothesisType.PRODUCT_EVENT, _combine_signals(prod_weights), prod_signals))

        # --- SEASONAL_EVENT ---
        seas_weights, seas_signals = [], []
        try:
            month = int(event.observed_at[5:7])
            if month in (8, 9):  # back to school
                seas_weights.append(_SIGNAL_WEIGHTS["seasonal_aug_sep"])
                seas_signals.append(f"event in August/September (back-to-school period)")
            elif month in (11, 12):  # holiday
                seas_weights.append(_SIGNAL_WEIGHTS["seasonal_nov_dec"])
                seas_signals.append(f"event in Nov/Dec (holiday season)")
            elif month in (6, 7):  # summer sales
                seas_weights.append(_SIGNAL_WEIGHTS["seasonal_jun_jul"])
                seas_signals.append(f"event in summer sale period")
        except (IndexError, ValueError):
            pass
        if seas_weights and direction == "decrease":
            candidates.append((HypothesisType.SEASONAL_EVENT, _combine_signals(seas_weights), seas_signals))

        # --- MANUFACTURER_CHANGE ---
        mfr_weights, mfr_signals = [], []
        if abs(pct) >= 15 and event.competitor_count >= 3:
            mfr_weights.append(_SIGNAL_WEIGHTS["msrp_change_signal"])
            mfr_signals.append(f"large change with multiple competitors - possible MSRP change")
        if mfr_weights:
            candidates.append((HypothesisType.MANUFACTURER_CHANGE, _combine_signals(mfr_weights), mfr_signals))

        # --- DATA_ISSUE ---
        data_weights, data_signals = [], []
        if abs(pct) >= 60:
            data_weights.append(_SIGNAL_WEIGHTS["data_issue_60pct"])
            data_signals.append(f"extreme change magnitude ({pct:.1f}%) may indicate data issue")
        if data_weights:
            candidates.append((HypothesisType.DATA_ISSUE, _combine_signals(data_weights), data_signals))

        # Guarantee at least 2 hypotheses
        if len(candidates) < 2:
            for default_type in [HypothesisType.PROMOTION, HypothesisType.COMPETITOR_RESPONSE]:
                if not any(c[0] == default_type for c in candidates):
                    candidates.append((default_type, 0.20, ["default hypothesis - insufficient signals"]))
                if len(candidates) >= 2:
                    break

        now = datetime.now(timezone.utc).isoformat()
        hypotheses: List[Hypothesis] = []
        for h_type, score, signals in candidates:
            requires_ext, agents = _META[h_type]
            h_id = make_hypothesis_id(event.event_id, h_type)
            hypotheses.append(Hypothesis(
                hypothesis_id=h_id,
                event_id=event.event_id,
                hypothesis_type=h_type,
                signal_score=score,
                rationale=self._rationale(h_type, signals, pct, direction),
                signals_matched=signals,
                assigned_agents=agents,
                requires_external_evidence=requires_ext,
                generated_at=now,
            ))

        # Sort by signal_score descending for readability
        hypotheses.sort(key=lambda h: h.signal_score, reverse=True)
        logger.info("Generated %d hypotheses for event %s", len(hypotheses), event.event_id)
        return hypotheses

    def _rationale(self, h_type: HypothesisType, signals: List[str], pct: float, direction: str) -> str:
        base = "Hypothesis type {} generated from signals: {}.".format(h_type.value, "; ".join(signals))
        if h_type == HypothesisType.INVENTORY_LIQUIDATION:
            base += " Note: requires external web evidence; availability field alone is insufficient."
        return base
