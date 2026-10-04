"""
scripts/generate_events.py
============================
Merge BOCPD results with features, apply event filters, generate
ChangeEvent objects with weak supervision labels, and save outputs.

Output files:
    data/events/change_events.csv
    data/events/change_events.json

Usage:
    python scripts/generate_events.py
    python scripts/generate_events.py --min-pct 2.0 --dedup-hours 24
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from src.events.event_generator import (
    EventConfig,
    generate_events,
    save_events_csv,
    save_events_json,
)
from src.features.competitive_features import load_competitive_features
from src.weak_supervision.label_generator import WeakLabelConfig, generate_weak_labels

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(
    min_pct_change: float = 2.0,
    min_cp_probability: float = 0.30,
    dedup_hours: float = 24.0,
) -> None:
    logger.info("=== SignalWatch — Event Generation ===")

    # Load BOCPD results
    bocpd_path = _ROOT / "data" / "events" / "bocpd_results.csv"
    if not bocpd_path.exists():
        logger.error(
            "BOCPD results not found at %s. Run scripts/run_bocpd.py first.",
            bocpd_path,
        )
        sys.exit(1)

    bocpd_df = pd.read_csv(bocpd_path)
    bocpd_df["observed_at"] = pd.to_datetime(
        bocpd_df["observed_at"], errors="coerce", utc=True
    )
    logger.info(
        "BOCPD results loaded: %d rows, %d change-point flags",
        len(bocpd_df),
        int(bocpd_df.get("is_change_point", pd.Series(dtype=bool)).sum()),
    )

    # Load features
    feat_path = _ROOT / "data" / "features" / "competitive_features.csv"
    if not feat_path.exists():
        logger.error("Features not found at %s.", feat_path)
        sys.exit(1)

    features_df = load_competitive_features(feat_path)
    logger.info("Features loaded: %d rows", len(features_df))

    # Generate events
    event_config = EventConfig(
        min_pct_change=min_pct_change,
        dedup_window_hours=dedup_hours,
        min_cp_probability=min_cp_probability,
    )
    events = generate_events(bocpd_df, features_df, config=event_config)

    if not events:
        logger.warning("No events generated. Try lowering --min-pct or --threshold.")
        sys.exit(0)

    logger.info("Generated %d change events.", len(events))

    # Weak labels
    label_config = WeakLabelConfig()
    labelled_events = generate_weak_labels(events, features_df=features_df, config=label_config)

    # Count labels
    from collections import Counter
    label_counter: Counter = Counter()
    for le in labelled_events:
        for lbl in le.labels:
            label_counter[lbl] += 1

    print(f"\n{'='*50}")
    print("  Change Event Summary")
    print(f"{'='*50}")
    print(f"  Total events generated     : {len(events):>6,}")
    for label, count in sorted(label_counter.items()):
        print(f"  {label:<30s}: {count:>6,}")
    print()

    # Save events (without labels) to CSV and JSON
    events_dir = _ROOT / "data" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    save_events_csv(events, events_dir / "change_events.csv")
    save_events_json(events, events_dir / "change_events.json")

    # Save labelled events to JSON
    labelled_dicts = [le.to_dict() for le in labelled_events]
    labelled_path = events_dir / "labelled_events.json"
    with open(labelled_path, "w", encoding="utf-8") as fh:
        json.dump(labelled_dicts, fh, indent=2, default=str)
    logger.info("Labelled events saved: %s", labelled_path)

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate change events.")
    parser.add_argument("--min-pct", type=float, default=2.0,
                        help="Minimum absolute % price change (default: 2.0).")
    parser.add_argument("--min-cp", type=float, default=0.30,
                        help="Minimum BOCPD CP probability (default: 0.30).")
    parser.add_argument("--dedup-hours", type=float, default=24.0,
                        help="Deduplication window in hours (default: 24).")
    args = parser.parse_args()
    main(
        min_pct_change=args.min_pct,
        min_cp_probability=args.min_cp,
        dedup_hours=args.dedup_hours,
    )
