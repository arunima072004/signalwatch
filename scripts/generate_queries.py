"""
scripts/generate_queries.py
=============================
Load labelled change events and generate targeted investigation queries.
This is the FINAL STAGE of the current implementation.

Output file:
    data/events/investigation_queries.json

STOP HERE — no web search is performed.

Usage:
    python scripts/generate_queries.py
    python scripts/generate_queries.py --max-per-agent 6
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

from src.events.event_generator import ChangeEvent
from src.query_generation.query_generator import QueryGenerator, save_queries
from src.weak_supervision.label_generator import LabelledEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_labelled_events(path: Path) -> list[LabelledEvent]:
    """Reconstruct LabelledEvent objects from the saved JSON."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    labelled: list[LabelledEvent] = []
    for d in data:
        # Reconstruct ChangeEvent — pick only the ChangeEvent fields
        ce_fields = {
            k: v for k, v in d.items()
            if k not in ("weak_labels", "label_evidence")
        }
        try:
            event = ChangeEvent(**ce_fields)
        except TypeError as exc:
            logger.warning("Skipping malformed event record: %s", exc)
            continue
        le = LabelledEvent(
            event=event,
            labels=d.get("weak_labels", []),
            label_evidence=d.get("label_evidence", {}),
        )
        labelled.append(le)
    return labelled


def main(max_per_agent: int = 6) -> None:
    logger.info("=== SignalWatch — Query Generation ===")
    logger.info("NOTE: No web search is performed. Queries are for future agents only.")

    labelled_path = _ROOT / "data" / "events" / "labelled_events.json"
    if not labelled_path.exists():
        logger.error(
            "Labelled events not found at %s. "
            "Run scripts/generate_events.py first.",
            labelled_path,
        )
        sys.exit(1)

    labelled_events = _load_labelled_events(labelled_path)
    logger.info("Loaded %d labelled events.", len(labelled_events))

    if not labelled_events:
        logger.warning("No labelled events to process.")
        sys.exit(0)

    # Generate queries
    qg = QueryGenerator()
    query_results = qg.generate_all_queries(labelled_events, max_per_agent=max_per_agent)

    # Save
    out_path = _ROOT / "data" / "events" / "investigation_queries.json"
    save_queries(query_results, out_path)

    # Print a sample for verification
    print(f"\n{'='*60}")
    print("  SIGNALWATCH — SAMPLE INVESTIGATION QUERIES")
    print(f"{'='*60}")
    print(
        "\n  IMPLEMENTATION BOUNDARY: Generation of targeted search\n"
        "  queries for future web-search agents.\n"
        "  No internet search is performed here.\n"
    )

    for qr in query_results[:3]:
        tgt = qr["investigation_target"]
        print(f"\n  Event ID : {qr['event_id']}")
        print(f"  Product  : {tgt.get('product_name', '')[:60]}")
        print(f"  Merchant : {tgt.get('merchant', '')}")
        print(f"  Change   : {tgt.get('change_direction', '')} "
              f"({tgt.get('percentage_change', 'n/a'):.1f}% "
              f"if isinstance(tgt.get('percentage_change'), float) else '')") if False else None
        pct = tgt.get('percentage_change')
        pct_str = f"{pct:.1f}%" if isinstance(pct, (int, float)) and pct is not None else "n/a"
        print(f"  Change   : {tgt.get('change_direction', '')} ({pct_str})")
        print(f"  Labels   : {tgt.get('weak_labels', [])}")
        print(f"  Date     : {tgt.get('observed_at', '')[:10]}")
        for agent, queries in qr["queries"].items():
            print(f"\n  [{agent}]")
            for q in queries[:3]:
                print(f"    • {q}")

    # Summary stats
    total_queries = sum(
        sum(len(v) for v in r["queries"].values()) for r in query_results
    )
    agents_used = set()
    for r in query_results:
        agents_used.update(r["queries"].keys())

    print(f"\n{'='*60}")
    print(f"  Total events with queries : {len(query_results):,}")
    print(f"  Total queries generated   : {total_queries:,}")
    print(f"  Agent types used          : {sorted(agents_used)}")
    print(f"  Output file               : {out_path}")
    print(f"\n  ✓ PIPELINE COMPLETE — Queries ready for web-search agents.")
    print(f"{'='*60}\n")

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate investigation queries.")
    parser.add_argument(
        "--max-per-agent",
        type=int,
        default=6,
        help="Maximum queries per agent group (default: 6).",
    )
    args = parser.parse_args()
    main(max_per_agent=args.max_per_agent)
