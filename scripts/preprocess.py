"""
scripts/preprocess.py
======================
Run the preprocessing pipeline and save cleaned data to
data/processed/cleaned_data.csv.

Usage:
    python scripts/preprocess.py
    python scripts/preprocess.py --raw-path /path/to/file.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.loader import load_raw
from src.data.preprocessing import preprocess, save_cleaned

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(raw_path: str | None = None) -> None:
    logger.info("=== SignalWatch — Preprocessing ===")

    df_raw = load_raw(raw_path)
    logger.info("Raw data: %d rows × %d columns", len(df_raw), len(df_raw.columns))

    cleaned, log = preprocess(df_raw)

    print("\n" + log.summary())
    print(
        f"\nFinal cleaned dataset: {len(cleaned):,} rows × "
        f"{len(cleaned.columns)} columns\n"
    )

    out_path = _ROOT / "data" / "processed" / "cleaned_data.csv"
    save_cleaned(cleaned, out_path)
    logger.info("Done. Cleaned data: %s", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess raw dataset.")
    parser.add_argument("--raw-path", type=str, default=None)
    args = parser.parse_args()
    main(raw_path=args.raw_path)
