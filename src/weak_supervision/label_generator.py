"""
src/weak_supervision/label_generator.py
=========================================
Generates weak supervision labels for each ChangeEvent.

IMPORTANT DISCLAIMER
---------------------
These labels are heuristic signals derived from observable dataset fields.
They are NOT verified causes of the price change.
They are NOT ground truth.
They represent plausible hypotheses that should be investigated by the
web-search agent layer.

A label merely means: "The dataset contains a signal that is CONSISTENT
WITH this type of event."  It does not confirm that the event occurred.

Label taxonomy
--------------
promotion_related
    Dataset signals:
    - is_sale == True at or near the change point
    - Offer field is non-empty at or near the change point
    - Price direction is decrease (discounts usually reduce price)

competitive_related
    Dataset signals:
    - Multiple competitors changed price in a 7-day window around the event
    - competitor_direction_7d is non-zero (competitors moving)
    - price_vs_comp_median changed significantly
    - The focal merchant became cheapest or most expensive

availability_related
    Dataset signals:
    - Availability value changes between the previous and current observation
    - Availability is blank or unusual at the time of the event

unknown
    None of the above signals are present.

Multiple labels are allowed.  The system always appends at minimum one
label per event.

Window conventions
------------------
Because we have only one snapshot per change-point observation (not a
sliding window of the features DataFrame), all context is drawn from the
event row itself plus nearby observations fetched from features_df.
The lookback_days parameter controls how many days before/after the
event we search for supporting signals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from ..events.event_generator import ChangeEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label constants
# ---------------------------------------------------------------------------

LABEL_PROMOTION = "promotion_related"
LABEL_COMPETITIVE = "competitive_related"
LABEL_AVAILABILITY = "availability_related"
LABEL_UNKNOWN = "unknown"

ALL_LABELS = [
    LABEL_PROMOTION,
    LABEL_COMPETITIVE,
    LABEL_AVAILABILITY,
    LABEL_UNKNOWN,
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WeakLabelConfig:
    """
    Thresholds for weak-label heuristics.

    Parameters
    ----------
    lookback_days : float
        Window around the event to search for supporting signals in
        adjacent observations.  Default: 14 days.
    min_competitors_for_competitive : int
        Minimum number of competitors that must have changed price in
        the 7-day window for the competitive label to fire.  Default: 1.
    min_price_vs_comp_change : float
        Minimum |price_vs_comp_median| for competitive positioning to
        be considered significant.  Default: 5.0 (USD).
    """
    lookback_days: float = 14.0
    min_competitors_for_competitive: int = 1
    min_price_vs_comp_change: float = 5.0


# ---------------------------------------------------------------------------
# Labelled event
# ---------------------------------------------------------------------------

@dataclass
class LabelledEvent:
    """A ChangeEvent augmented with weak supervision labels."""
    event: ChangeEvent
    labels: list[str] = field(default_factory=list)
    label_evidence: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = self.event.to_dict()
        d["weak_labels"] = self.labels
        d["label_evidence"] = self.label_evidence
        return d


# ---------------------------------------------------------------------------
# Label generation helpers
# ---------------------------------------------------------------------------

def _check_promotion(
    event: ChangeEvent,
    nearby_df: Optional[pd.DataFrame],
    config: WeakLabelConfig,
) -> tuple[bool, list[str]]:
    """
    Return (triggered, evidence_strings) for the promotion label.
    """
    evidence: list[str] = []

    # Signal 1: isSale flag active at the event observation
    if event.is_sale:
        evidence.append("is_sale=True at change point")

    # Signal 2: offer field is non-empty at the event
    if event.offer:
        evidence.append(f"offer field present: {event.offer[:80]}")

    # Signal 3: price decrease (consistent with promotion)
    if event.change_direction == "decrease":
        evidence.append(
            f"price decreased {event.percentage_change:.2f}% "
            f"(${event.previous_price} → ${event.current_price})"
            if event.percentage_change is not None and event.previous_price is not None
            else "price direction: decrease"
        )

    # Signal 4: nearby observations (within lookback_days) with is_sale=True
    if nearby_df is not None and not nearby_df.empty:
        if "is_sale" in nearby_df.columns:
            nearby_sales = nearby_df["is_sale"].astype(str).str.upper().isin(
                ["TRUE", "1"]
            )
            if nearby_sales.any():
                evidence.append(
                    f"is_sale=True found in {int(nearby_sales.sum())} "
                    f"nearby observations (within {config.lookback_days} days)"
                )

        if "offer" in nearby_df.columns:
            nearby_offers = nearby_df["offer"].dropna().astype(str).str.strip()
            non_empty = nearby_offers[nearby_offers.ne("")]
            if not non_empty.empty:
                evidence.append(
                    f"offer field non-empty in {len(non_empty)} "
                    "nearby observations"
                )

    triggered = len(evidence) > 0
    return triggered, evidence


def _check_competitive(
    event: ChangeEvent,
    nearby_df: Optional[pd.DataFrame],
    config: WeakLabelConfig,
) -> tuple[bool, list[str]]:
    """
    Return (triggered, evidence_strings) for the competitive label.
    """
    evidence: list[str] = []

    # Signal 1: competitors changed price in 7-day window
    if event.competitors_changed_7d >= config.min_competitors_for_competitive:
        direction_str = (
            "upward" if event.competitor_direction_7d > 0
            else "downward" if event.competitor_direction_7d < 0
            else "mixed"
        )
        evidence.append(
            f"{event.competitors_changed_7d} competitor(s) changed price "
            f"in past 7 days (net direction: {direction_str})"
        )

    # Signal 2: significant deviation from competitor median
    if (
        event.price_vs_comp_median is not None
        and abs(event.price_vs_comp_median) >= config.min_price_vs_comp_change
    ):
        evidence.append(
            f"price vs competitor median: "
            f"${event.price_vs_comp_median:+.2f}"
        )

    # Signal 3: became cheapest or most expensive
    if nearby_df is not None and not nearby_df.empty:
        if "is_cheapest" in nearby_df.columns:
            cheapest_rows = nearby_df["is_cheapest"].astype(str).str.upper()
            if "TRUE" in cheapest_rows.values:
                evidence.append("product is cheapest among competitors at event time")
        if "is_most_expensive" in nearby_df.columns:
            expensive_rows = nearby_df["is_most_expensive"].astype(str).str.upper()
            if "TRUE" in expensive_rows.values:
                evidence.append(
                    "product is most expensive among competitors at event time"
                )

    # Signal 4: competitor_count > 0 (at least some competitive context exists)
    if event.competitor_count > 0 and not evidence:
        # Only a weak signal if nothing else triggered
        evidence.append(
            f"{event.competitor_count} competitor price(s) observed near event"
        )

    triggered = len(evidence) > 0
    return triggered, evidence


def _check_availability(
    event: ChangeEvent,
    nearby_df: Optional[pd.DataFrame],
    config: WeakLabelConfig,
) -> tuple[bool, list[str]]:
    """
    Return (triggered, evidence_strings) for the availability label.
    """
    evidence: list[str] = []

    # Signal 1: availability value at the event is unusual
    avail = (event.availability or "").strip().lower()
    unusual_availability = avail in [
        "", "preorder", "pre-order", "sold out", "out of stock",
        "discontinued", "limited availability", "backorder",
    ]
    if unusual_availability and avail != "":
        evidence.append(
            f"availability at event time: '{event.availability}'"
        )

    # Signal 2: availability changed in nearby observations
    if nearby_df is not None and not nearby_df.empty and "availability" in nearby_df.columns:
        avail_values = (
            nearby_df["availability"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.lower()
            .unique()
        )
        if len(avail_values) > 1:
            evidence.append(
                f"availability changed in nearby observations: "
                f"{list(avail_values)}"
            )
        elif "out of stock" in avail_values or "sold out" in avail_values:
            evidence.append(
                "product was out of stock in nearby observations"
            )

    triggered = len(evidence) > 0
    return triggered, evidence


def _get_nearby_observations(
    event: ChangeEvent,
    features_df: Optional[pd.DataFrame],
    lookback_days: float,
) -> Optional[pd.DataFrame]:
    """
    Return observations for the same (product_id, merchant) within
    ±lookback_days of the event timestamp.

    Uses only the features_df if provided; otherwise returns None.
    No future data is required here — we are building context for a
    post-detection labelling pass, not an online signal.
    """
    if features_df is None or features_df.empty:
        return None

    ts = pd.to_datetime(event.observed_at, errors="coerce", utc=True)
    if pd.isna(ts):
        return None

    window = pd.Timedelta(days=lookback_days)
    mask = (
        (features_df["product_id"] == event.product_id) &
        (features_df["merchant"] == event.merchant) &
        (features_df["observed_at"] >= ts - window) &
        (features_df["observed_at"] <= ts + window)
    )
    result = features_df[mask].copy()
    return result if not result.empty else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_weak_labels(
    events: list[ChangeEvent],
    features_df: Optional[pd.DataFrame] = None,
    config: Optional[WeakLabelConfig] = None,
) -> list[LabelledEvent]:
    """
    Assign weak supervision labels to each ChangeEvent.

    Parameters
    ----------
    events:
        List of ChangeEvent objects from event_generator.generate_events().
    features_df:
        Full features DataFrame.  Used to fetch nearby observations for
        richer context.  If None, only the event-level fields are used.
    config:
        WeakLabelConfig.  If None, defaults are used.

    Returns
    -------
    list[LabelledEvent]
        Each event annotated with weak labels and evidence strings.

    Notes
    -----
    Labels are HEURISTIC SIGNALS, not verified causes.
    Multiple labels can be assigned per event.
    If no signals fire, the event receives the LABEL_UNKNOWN label.
    """
    if config is None:
        config = WeakLabelConfig()

    labelled: list[LabelledEvent] = []
    label_counts: dict[str, int] = {k: 0 for k in ALL_LABELS}

    for event in events:
        nearby_df = _get_nearby_observations(
            event, features_df, config.lookback_days
        )

        labels: list[str] = []
        evidence: dict[str, list[str]] = {}

        # Check each label category
        promo_triggered, promo_ev = _check_promotion(event, nearby_df, config)
        comp_triggered, comp_ev = _check_competitive(event, nearby_df, config)
        avail_triggered, avail_ev = _check_availability(event, nearby_df, config)

        if promo_triggered:
            labels.append(LABEL_PROMOTION)
            evidence[LABEL_PROMOTION] = promo_ev
            label_counts[LABEL_PROMOTION] += 1

        if comp_triggered:
            labels.append(LABEL_COMPETITIVE)
            evidence[LABEL_COMPETITIVE] = comp_ev
            label_counts[LABEL_COMPETITIVE] += 1

        if avail_triggered:
            labels.append(LABEL_AVAILABILITY)
            evidence[LABEL_AVAILABILITY] = avail_ev
            label_counts[LABEL_AVAILABILITY] += 1

        if not labels:
            labels.append(LABEL_UNKNOWN)
            evidence[LABEL_UNKNOWN] = [
                "No dataset signals matched any label category. "
                "External investigation required."
            ]
            label_counts[LABEL_UNKNOWN] += 1

        labelled.append(
            LabelledEvent(event=event, labels=labels, label_evidence=evidence)
        )

    total = len(labelled)
    logger.info(
        "Weak labels generated for %d events: "
        "promotion=%d, competitive=%d, availability=%d, unknown=%d",
        total,
        label_counts[LABEL_PROMOTION],
        label_counts[LABEL_COMPETITIVE],
        label_counts[LABEL_AVAILABILITY],
        label_counts[LABEL_UNKNOWN],
    )
    logger.info(
        "REMINDER: Weak labels are heuristic signals, NOT verified causes."
    )
    return labelled
