"""
scripts/profile_dataset.py
============================
Run dataset profiling and save the report to data/processed/.

Usage:
    python scripts/profile_dataset.py
    python scripts/profile_dataset.py --raw-path /path/to/file.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make sure the project root is on sys.path when running as a script
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.loader import load_raw
from src.data.profiler import print_report, profile, save_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(raw_path: str | None = None) -> None:
    logger.info("=== SignalWatch — Dataset Profiling ===")

    # Load raw data
    df = load_raw(raw_path)

    # Profile
    report = profile(df)

    # Print to console
    print_report(report)

    # Save JSON report
    out_dir = _ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "dataset_profile.json"
    save_report(report, report_path)
    logger.info("Profile saved to: %s", report_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Profile the raw dataset.")
    parser.add_argument(
        "--raw-path",
        type=str,
        default=None,
        help="Path to the raw CSV file (optional — uses DATA_PATH.txt if omitted).",
    )
    args = parser.parse_args()
    main(raw_path=args.raw_path)
