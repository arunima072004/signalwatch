"""
scripts/build_timeseries.py
=============================
Build product-merchant price time series and compute price + competitive
features.  Saves output to data/features/.

Usage:
    python scripts/build_timeseries.py
    python scripts/build_timeseries.py --min-obs 5 --skip-competitive
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.preprocessing import load_cleaned
from src.features.competitive_features import (
    compute_competitive_features,
    save_competitive_features,
)
from src.features.price_features import compute_all_price_features, save_price_features
from src.timeseries.builder import build_time_series, save_series

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(min_obs: int = 5, skip_competitive: bool = False) -> None:
    logger.info("=== SignalWatch — Build Time Series & Features ===")

    # Load cleaned data
    cleaned_path = _ROOT / "data" / "processed" / "cleaned_data.csv"
    if not cleaned_path.exists():
        logger.error(
            "Cleaned data not found at %s. Run scripts/preprocess.py first.",
            cleaned_path,
        )
        sys.exit(1)

    cleaned = load_cleaned(cleaned_path)
    logger.info("Cleaned data loaded: %d rows", len(cleaned))

    # Build time series
    catalogue = build_time_series(cleaned, min_observations=min_obs)

    series_dir = _ROOT / "data" / "processed"
    save_series(catalogue, series_dir)

    summary = catalogue.summary
    usable = catalogue.usable_pairs
    logger.info(
        "Time series: %d total PM pairs | %d usable (≥%d obs)",
        len(summary),
        len(usable),
        min_obs,
    )

    # Price features
    logger.info("Computing price features …")
    price_feat = compute_all_price_features(catalogue.series_df)
    price_feat_path = _ROOT / "data" / "features" / "price_features.csv"
    save_price_features(price_feat, price_feat_path)
    logger.info("Price features: %d rows, %d columns", len(price_feat), len(price_feat.columns))

    # Competitive features
    if skip_competitive:
        logger.info("Skipping competitive features (--skip-competitive flag).")
        # Still save the price features as competitive_features (no comp cols)
        comp_feat_path = _ROOT / "data" / "features" / "competitive_features.csv"
        save_competitive_features(price_feat, comp_feat_path)
    else:
        logger.info(
            "Computing competitive features (this may take several minutes for "
            "large datasets) …"
        )
        comp_feat = compute_competitive_features(price_feat)
        comp_feat_path = _ROOT / "data" / "features" / "competitive_features.csv"
        save_competitive_features(comp_feat, comp_feat_path)
        logger.info(
            "Competitive features: %d rows, %d columns",
            len(comp_feat),
            len(comp_feat.columns),
        )

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build time series and features.")
    parser.add_argument(
        "--min-obs",
        type=int,
        default=5,
        help="Minimum observations for a PM pair to be marked usable (default: 5).",
    )
    parser.add_argument(
        "--skip-competitive",
        action="store_true",
        help="Skip competitive feature computation (faster, for testing).",
    )
    args = parser.parse_args()
    main(min_obs=args.min_obs, skip_competitive=args.skip_competitive)
