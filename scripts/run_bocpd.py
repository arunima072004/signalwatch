"""
scripts/run_bocpd.py
=====================
Run BOCPD + baseline detectors on the feature data and save results.

Output files:
    data/events/bocpd_results.csv
    data/features/competitive_features.csv  (with baseline flags appended)

Usage:
    python scripts/run_bocpd.py
    python scripts/run_bocpd.py --lambda 100 --threshold 0.3 --min-obs 5
    python scripts/run_bocpd.py --no-baseline
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.bocpd.config import BOCPDConfig, HazardConfig, NormalGammaConfig
from src.bocpd.detector import run_baseline_on_catalogue, run_bocpd_on_catalogue
from src.features.competitive_features import load_competitive_features

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(
    hazard_lambda: float = 100.0,
    cp_threshold: float = 0.30,
    min_obs: int = 5,
    run_baseline: bool = True,
    pct_threshold: float = 10.0,
    zscore_window: int = 5,
    zscore_threshold: float = 2.5,
) -> None:
    logger.info("=== SignalWatch — BOCPD Detection ===")

    feat_path = _ROOT / "data" / "features" / "competitive_features.csv"
    if not feat_path.exists():
        logger.error(
            "Features not found at %s. Run scripts/build_timeseries.py first.",
            feat_path,
        )
        sys.exit(1)

    logger.info("Loading features from %s …", feat_path)
    features_df = load_competitive_features(feat_path)
    logger.info("Features loaded: %d rows", len(features_df))

    # Configure BOCPD
    config = BOCPDConfig(
        observation_signal="log_price_diff",
        hazard=HazardConfig(lambda_val=hazard_lambda),
        model=NormalGammaConfig(),
        cp_threshold=cp_threshold,
        min_observations_before_detection=3,
        max_run_length=500,
    )
    logger.info("\n%s\n", config.describe())

    # Run BOCPD
    bocpd_df = run_bocpd_on_catalogue(
        features_df, config=config, min_observations=min_obs, max_series_cv=0.15
    )

    if bocpd_df.empty:
        logger.warning("No BOCPD results produced.")
        sys.exit(0)

    # Save BOCPD results
    events_dir = _ROOT / "data" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    bocpd_path = events_dir / "bocpd_results.csv"
    bocpd_df.to_csv(bocpd_path, index=False)
    logger.info(
        "BOCPD results saved: %s (%d rows, %d change-point flags)",
        bocpd_path,
        len(bocpd_df),
        int(bocpd_df["is_change_point"].sum()),
    )

    # Run baseline detectors
    if run_baseline:
        logger.info("Running baseline detectors …")
        features_with_baseline = run_baseline_on_catalogue(
            features_df,
            pct_threshold=pct_threshold,
            zscore_window=zscore_window,
            zscore_threshold=zscore_threshold,
        )
        baseline_path = _ROOT / "data" / "features" / "features_with_baseline.csv"
        features_with_baseline.to_csv(baseline_path, index=False)
        logger.info("Features + baseline flags saved: %s", baseline_path)

        # Comparison summary
        n_bocpd = int(bocpd_df["is_change_point"].sum())
        n_threshold = int(features_with_baseline["baseline_threshold_flag"].sum())
        n_zscore = int(features_with_baseline["baseline_zscore_flag"].sum())
        print(f"\n{'='*50}")
        print("  BOCPD vs Baseline Comparison")
        print(f"{'='*50}")
        print(f"  BOCPD change-point flags   : {n_bocpd:>6,}")
        print(f"  Threshold baseline flags   : {n_threshold:>6,}")
        print(f"  Z-score baseline flags     : {n_zscore:>6,}")
        print(
            f"\n  BOCPD uses the full run-length posterior and adapts to the\n"
            f"  statistical regime of each series, rather than applying a\n"
            f"  global fixed threshold or short-window z-score.\n"
            f"  A higher BOCPD count vs baselines suggests it is more\n"
            f"  sensitive; a lower count suggests it is more conservative.\n"
            f"  Neither comparison implies a confirmed anomaly.\n"
        )

    logger.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run BOCPD on feature data.")
    parser.add_argument("--lambda", dest="hazard_lambda", type=float, default=100.0,
                        help="Expected observations between change points (default: 100).")
    parser.add_argument("--threshold", dest="cp_threshold", type=float, default=0.30,
                        help="BOCPD CP probability threshold (default: 0.30).")
    parser.add_argument("--min-obs", type=int, default=5)
    parser.add_argument("--no-baseline", dest="run_baseline", action="store_false",
                        help="Skip baseline detectors.")
    parser.add_argument("--pct-threshold", type=float, default=10.0)
    parser.add_argument("--zscore-window", type=int, default=5)
    parser.add_argument("--zscore-threshold", type=float, default=2.5)
    args = parser.parse_args()
    main(
        hazard_lambda=args.hazard_lambda,
        cp_threshold=args.cp_threshold,
        min_obs=args.min_obs,
        run_baseline=args.run_baseline,
        pct_threshold=args.pct_threshold,
        zscore_window=args.zscore_window,
        zscore_threshold=args.zscore_threshold,
    )
