"""
src/events/event_generator.py
==============================
Converts BOCPD change-point flags into structured ChangeEvent objects
enriched with price, product, merchant, and competitive context from
the features DataFrame.

What counts as an event
------------------------
A BOCPD change-point flag (is_change_point=True) is a necessary but not
sufficient condition for creating an investigation event.  The rule is:

  An observation is treated as an investigation event if:
    1. BOCPD reports is_change_point = True  (cp_probability >= threshold), AND
    2. The absolute percentage price change |percentage_change| >= min_pct_change

Condition 2 filters out statistical regime shifts in the log-price-diff
series that are not accompanied by a meaningful price movement (e.g. a
long stable period ending with a tiny tick).

Both thresholds are configurable.

Deduplication
-------------
If BOCPD fires on consecutive observations for the same PM pair, only the
observation with the highest cp_probability is kept (within a
dedup_window_hours window).  This prevents a single regime shift from
generating many identical events.

Event schema
------------
{
  "event_id":             str  (deterministic hash of product_id+merchant+timestamp)
  "product_id":           str
  "product_name":         str
  "brand":                str
  "manufacturer":         str
  "manufacturer_number":  str
  "category":             str
  "asins":                str
  "upc":                  str
  "merchant":             str
  "observed_at":          str  (ISO-8601)
  "previous_price":       float | None
  "current_price":        float
  "absolute_change":      float | None
  "percentage_change":    float | None
  "change_direction":     "increase" | "decrease" | "no_change" | "unknown"
  "cp_probability":       float
  "map_run_length":       int
  "log_price_diff":       float | None
  "is_sale":              bool
  "offer":                str | None
  "availability":         str | None
  "condition":            str | None
  "competitor_count":     int
  "competitor_price_median": float | None
  "price_vs_comp_median": float | None
  "competitors_changed_7d": int
  "competitor_direction_7d": int
  "source_url":           str | None
  "event_type":           "pricing_regime_change"
  "detection_method":     "BOCPD"
}
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EventConfig:
    """
    Configurable rules for deciding when a BOCPD flag becomes an event.

    Parameters
    ----------
    min_pct_change : float
        Minimum absolute percentage price change required alongside a
        BOCPD flag.  Default: 2.0%.  Prevents trivial movements from
        generating events.
    dedup_window_hours : float
        Within this many hours of the same PM pair, only the highest-
        probability change point is retained.  Default: 24 hours.
    min_cp_probability : float
        Additional guard: only flags with cp_probability >= this value
        are converted to events.  Normally equals BOCPDConfig.cp_threshold,
        but can be set higher here for further filtering.
        Default: 0.3 (matches BOCPD default threshold).
    """
    min_pct_change: float = 2.0
    dedup_window_hours: float = 24.0
    min_cp_probability: float = 0.30


# ---------------------------------------------------------------------------
# Event data class
# ---------------------------------------------------------------------------

@dataclass
class ChangeEvent:
    event_id: str
    product_id: str
    product_name: str
    brand: str
    manufacturer: str
    manufacturer_number: str
    category: str
    asins: str
    upc: str
    merchant: str
    observed_at: str           # ISO-8601
    previous_price: Optional[float]
    current_price: float
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    change_direction: str      # "increase" | "decrease" | "no_change" | "unknown"
    cp_probability: float
    map_run_length: int
    log_price_diff: Optional[float]
    is_sale: bool
    offer: Optional[str]
    availability: Optional[str]
    condition: Optional[str]
    competitor_count: int
    competitor_price_median: Optional[float]
    price_vs_comp_median: Optional[float]
    competitors_changed_7d: int
    competitor_direction_7d: int
    source_url: Optional[str]
    event_type: str = "pricing_regime_change"
    detection_method: str = "BOCPD"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _make_event_id(product_id: str, merchant: str, observed_at: str) -> str:
    """Deterministic SHA-256-based event ID (first 16 hex chars)."""
    raw = f"{product_id}|{merchant}|{observed_at}"
    return "evt_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _safe_float(val: Any) -> Optional[float]:
    try:
        v = float(val)
        return None if pd.isna(v) else round(v, 6)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int:
    try:
        v = int(val)
        return 0 if pd.isna(float(val)) else v
    except (TypeError, ValueError):
        return 0


def _safe_str(val: Any) -> str:
    if pd.isna(val) if not isinstance(val, str) else False:
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "") else s


def _change_direction(pct: Optional[float]) -> str:
    if pct is None or pd.isna(pct):
        return "unknown"
    if pct > 0.001:
        return "increase"
    if pct < -0.001:
        return "decrease"
    return "no_change"


# ---------------------------------------------------------------------------
# Core merge: join BOCPD results onto features
# ---------------------------------------------------------------------------

def _merge_bocpd_with_features(
    bocpd_df: pd.DataFrame,
    features_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Join BOCPD results with the full features DataFrame on
    (product_id, merchant, observed_at).

    Only rows where is_change_point=True are carried forward.
    """
    # Keep only change-point rows from BOCPD
    cp_df = bocpd_df[bocpd_df["is_change_point"] == True].copy()

    if cp_df.empty:
        logger.warning("No change-point rows found in BOCPD results.")
        return pd.DataFrame()

    # Normalise timestamp columns for joining
    for df, name in [(cp_df, "bocpd_df"), (features_df, "features_df")]:
        if "observed_at" in df.columns:
            df["observed_at"] = pd.to_datetime(
                df["observed_at"], errors="coerce", utc=True
            )

    # The BOCPD df has: product_id, merchant, observed_at, cp_probability,
    # map_run_length, is_change_point, observation_value
    bocpd_cols = [
        "product_id", "merchant", "observed_at",
        "cp_probability", "map_run_length", "is_change_point",
    ]
    bocpd_cols = [c for c in bocpd_cols if c in cp_df.columns]

    merged = pd.merge(
        cp_df[bocpd_cols],
        features_df,
        on=["product_id", "merchant", "observed_at"],
        how="left",
    )
    logger.info(
        "Merged %d BOCPD change-point flags with features → %d rows",
        len(cp_df),
        len(merged),
    )
    return merged


# ---------------------------------------------------------------------------
# Event generation
# ---------------------------------------------------------------------------

def generate_events(
    bocpd_df: pd.DataFrame,
    features_df: pd.DataFrame,
    config: Optional[EventConfig] = None,
) -> list[ChangeEvent]:
    """
    Generate structured ChangeEvent objects from BOCPD results.

    Parameters
    ----------
    bocpd_df:
        Output of run_bocpd_on_catalogue().
    features_df:
        Full features DataFrame (price + competitive features).
    config:
        EventConfig.  If None, defaults are used.

    Returns
    -------
    list[ChangeEvent]
        One event per qualifying (product_id, merchant, timestamp) flag.
    """
    if config is None:
        config = EventConfig()

    merged = _merge_bocpd_with_features(bocpd_df, features_df)
    if merged.empty:
        return []

    # Filter 1: minimum cp_probability
    before = len(merged)
    merged = merged[
        merged["cp_probability"] >= config.min_cp_probability
    ]
    logger.info(
        "After cp_probability >= %.2f filter: %d → %d rows",
        config.min_cp_probability, before, len(merged),
    )

    # Filter 2: minimum percentage change
    if "percentage_change" in merged.columns:
        before = len(merged)
        merged = merged[
            merged["percentage_change"].isna() |
            (merged["percentage_change"].abs() >= config.min_pct_change)
        ]
        logger.info(
            "After |pct_change| >= %.1f%% filter: %d → %d rows",
            config.min_pct_change, before, len(merged),
        )

    if merged.empty:
        logger.warning("No events remain after filtering.")
        return []

    # Deduplication: within each PM pair, within dedup_window_hours,
    # keep only the row with the highest cp_probability.
    events: list[ChangeEvent] = []

    for (pid, merch), group in merged.groupby(
        ["product_id", "merchant"], sort=False
    ):
        g = group.sort_values("observed_at").reset_index(drop=True)
        dedup_window = pd.Timedelta(hours=config.dedup_window_hours)

        # Greedy dedup: keep a flag, suppress near-duplicates
        kept_times: list[pd.Timestamp] = []

        for _, row in g.iterrows():
            ts = row["observed_at"]

            # Check if this is too close to an already-kept event
            too_close = any(
                abs((ts - kt).total_seconds()) < dedup_window.total_seconds()
                for kt in kept_times
            )
            if too_close:
                continue

            kept_times.append(ts)

            ts_str = ts.isoformat() if pd.notna(ts) else ""
            event_id = _make_event_id(str(pid), str(merch), ts_str)

            pct_change = _safe_float(row.get("percentage_change"))

            event = ChangeEvent(
                event_id=event_id,
                product_id=str(pid),
                product_name=_safe_str(row.get("product_name")),
                brand=_safe_str(row.get("brand")),
                manufacturer=_safe_str(row.get("manufacturer")),
                manufacturer_number=_safe_str(row.get("manufacturer_number")),
                category=_safe_str(row.get("category")),
                asins=_safe_str(row.get("asins")),
                upc=_safe_str(row.get("upc")),
                merchant=str(merch),
                observed_at=ts_str,
                previous_price=_safe_float(row.get("previous_price")),
                current_price=_safe_float(row.get("price")) or 0.0,
                absolute_change=_safe_float(row.get("absolute_change")),
                percentage_change=pct_change,
                change_direction=_change_direction(pct_change),
                cp_probability=float(row.get("cp_probability", 0.0)),
                map_run_length=_safe_int(row.get("map_run_length", 0)),
                log_price_diff=_safe_float(row.get("log_price_diff")),
                is_sale=bool(row.get("is_sale", False)),
                offer=_safe_str(row.get("offer")) or None,
                availability=_safe_str(row.get("availability")) or None,
                condition=_safe_str(row.get("condition")) or None,
                competitor_count=_safe_int(row.get("competitor_count", 0)),
                competitor_price_median=_safe_float(
                    row.get("competitor_price_median")
                ),
                price_vs_comp_median=_safe_float(
                    row.get("price_vs_comp_median")
                ),
                competitors_changed_7d=_safe_int(
                    row.get("competitors_changed_7d", 0)
                ),
                competitor_direction_7d=_safe_int(
                    row.get("competitor_direction_7d", 0)
                ),
                source_url=_safe_str(row.get("source_url")) or None,
            )
            events.append(event)

    logger.info(
        "Generated %d ChangeEvent objects from %d qualified BOCPD flags",
        len(events),
        len(merged),
    )
    return events


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def events_to_dataframe(events: list[ChangeEvent]) -> pd.DataFrame:
    """Convert a list of ChangeEvent objects to a flat DataFrame."""
    if not events:
        return pd.DataFrame()
    return pd.DataFrame([e.to_dict() for e in events])


def save_events_csv(events: list[ChangeEvent], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = events_to_dataframe(events)
    df.to_csv(output_path, index=False)
    logger.info("Events saved to CSV: %s (%d events)", output_path, len(events))


def save_events_json(events: list[ChangeEvent], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [e.to_dict() for e in events]
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    logger.info("Events saved to JSON: %s (%d events)", output_path, len(events))


def load_events_json(input_path: str | Path) -> list[dict[str, Any]]:
    with open(input_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
