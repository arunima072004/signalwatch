"""
src/bocpd/detector.py
======================
Implements two detectors:

1. BOCPDDetector  — the core Bayesian Online Change-Point Detector.
2. BaselineDetector — simple threshold and rolling z-score baseline
   for comparison.

BOCPD Algorithm (Adams & MacKay 2007)
--------------------------------------
Input: observations x_1, x_2, ..., x_T (processed strictly in order)

State maintained:
  R_t  — posterior distribution over run lengths at time t
         R_t[r] = P(run_length_t = r | x_{1:t})

At each time step t:

  1. For each run-length hypothesis r=0..t-1, compute predictive
     probability p(x_t | r, x_{t-r:t-1}) using the Normal-Gamma
     conjugate model.

  2. Update run-length posterior:
       R_t[r+1] ∝ R_{t-1}[r] * p(x_t | r) * (1 - h)   [growth]
       R_t[0]   ∝ Σ_r R_{t-1}[r] * p(x_t | r) * h       [change point]

     where h is the constant hazard probability.

  3. Normalise R_t so it sums to 1.

  4. Record:
     - P(change point at t)  = R_t[0]  (posterior mass on run length 0)
     - MAP run length        = argmax R_t
     - The full R_t distribution (optional, for analysis)

IMPORTANT — historical online replay:
  The dataset is historical.  We replay each product-merchant time
  series in chronological order, feeding observations one at a time to
  the detector.  At no point does the detector see a future observation.
  This is documented explicitly throughout.

Baseline detectors
------------------
  ThresholdBaseline:
    Flags an observation as a change event when |percentage_change| > threshold.
    Simple, interpretable, no distributional assumptions.

  ZScoreBaseline:
    Flags when the rolling z-score of log_price_diff exceeds a threshold.
    z = (x - rolling_mean) / rolling_std  computed over a configurable window.
    Slightly more adaptive than a fixed threshold.

Both baselines are implemented in BaselineDetector.  They are NOT
replacements for BOCPD; they exist solely for comparison.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .config import BOCPDConfig
from .models import NormalGammaModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BOCPD result per observation
# ---------------------------------------------------------------------------

@dataclass
class BOCPDStep:
    """Result of processing one observation through BOCPD."""
    observation_index: int
    observed_at: pd.Timestamp
    observation_value: float       # the signal value fed to BOCPD
    cp_probability: float          # P(run_length = 0 | data up to t)
    map_run_length: int            # argmax of run-length posterior
    run_length_posterior: np.ndarray  # full posterior over run lengths
    is_change_point: bool          # cp_probability >= threshold


@dataclass
class BOCPDResult:
    """
    Container for the BOCPD results for one product-merchant time series.

    Attributes
    ----------
    product_id, merchant : str
        Identifying keys.
    steps : list[BOCPDStep]
        One entry per observation processed.
    config : BOCPDConfig
        The configuration used.
    n_observations : int
        Total number of observations processed.
    n_change_points : int
        Number of detected change points.
    """
    product_id: str
    merchant: str
    steps: list[BOCPDStep] = field(default_factory=list)
    config: BOCPDConfig = field(default_factory=BOCPDConfig)
    n_observations: int = 0
    n_change_points: int = 0

    def to_dataframe(self) -> pd.DataFrame:
        """Convert steps to a flat DataFrame for analysis and saving."""
        if not self.steps:
            return pd.DataFrame()
        rows = []
        for s in self.steps:
            rows.append(
                {
                    "product_id": self.product_id,
                    "merchant": self.merchant,
                    "observation_index": s.observation_index,
                    "observed_at": s.observed_at,
                    "observation_value": s.observation_value,
                    "cp_probability": s.cp_probability,
                    "map_run_length": s.map_run_length,
                    "is_change_point": s.is_change_point,
                }
            )
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# BOCPD Detector
# ---------------------------------------------------------------------------

class BOCPDDetector:
    """
    Bayesian Online Change-Point Detector (Adams & MacKay 2007).

    This is a STATEFUL detector: call process_observation() sequentially
    for each time step.  Call reset() to start a new series.

    Usage pattern (historical online replay):
    -----------------------------------------
        detector = BOCPDDetector(config)
        for _, row in series_df.iterrows():
            step = detector.process_observation(
                x=row["log_price_diff"],
                observed_at=row["observed_at"],
            )
        result = detector.get_result(product_id, merchant)
    """

    def __init__(self, config: BOCPDConfig) -> None:
        self.config = config
        self._model = NormalGammaModel(config.model)
        self._run_length_posterior: np.ndarray = np.array([1.0])
        self._steps: list[BOCPDStep] = []
        self._t: int = 0

    def reset(self) -> None:
        """Reset state to process a new time series from scratch."""
        self._model.reset()
        self._run_length_posterior = np.array([1.0])
        self._steps = []
        self._t = 0

    def process_observation(
        self,
        x: float,
        observed_at: Optional[pd.Timestamp] = None,
    ) -> BOCPDStep:
        """
        Process one observation in strict chronological order.

        This method implements the BOCPD update equations.

        Parameters
        ----------
        x : float
            The observation value (e.g. log_price_diff at time t).
        observed_at : pd.Timestamp, optional
            Timestamp of this observation (for record-keeping only).

        Returns
        -------
        BOCPDStep
            The result for this time step.

        Notes
        -----
        * If x is NaN the step is recorded with cp_probability=NaN and
          is_change_point=False.  NaN observations should be skipped when
          computing change-point probabilities; they typically arise at
          the first observation (no previous price yet).
        * The warm-up period (first min_observations_before_detection obs)
          returns cp_probability=NaN to indicate the posterior is not yet
          reliable.
        """
        t = self._t
        if observed_at is None:
            observed_at = pd.Timestamp.now(tz="UTC")

        # Handle NaN observations (first obs has NaN log_price_diff)
        if np.isnan(x):
            # Keep state consistent: prepend prior and shift posterior without
            # updating the model, so the run-length array length stays in sync
            # with the model hypothesis count for the next real observation.
            self._model.prepend_prior()
            R_prev = np.concatenate([[0.0], self._run_length_posterior])
            # No update: just grow the posterior with a uniform-ish prior step
            R_new = R_prev.copy()
            R_new[0] = self.config.hazard.hazard
            norm = np.sum(R_new)
            if norm > 0:
                R_new /= norm
            max_rl = self.config.max_run_length
            if max_rl > 0 and len(R_new) > max_rl:
                R_new = R_new[:max_rl]
                self._model.truncate(max_rl)
            self._run_length_posterior = R_new
            step = BOCPDStep(
                observation_index=t,
                observed_at=observed_at,
                observation_value=float("nan"),
                cp_probability=float("nan"),
                map_run_length=int(np.argmax(R_new)),
                run_length_posterior=R_new.copy(),
                is_change_point=False,
            )
            self._steps.append(step)
            self._t += 1
            return step

        h = self.config.hazard.hazard

        # ------------------------------------------------------------------
        # Step 1: Predictive probabilities for each active hypothesis
        # ------------------------------------------------------------------
        # Prepend a new r=0 hypothesis (prior) BEFORE computing predictives,
        # so the growth and change-point messages are computed simultaneously.
        self._model.prepend_prior()

        # p(x_t | run_length = r)  for r = 0, 1, ..., current_length
        predictive = self._model.predictive_pdf(x)

        # ------------------------------------------------------------------
        # Step 2: Extend the run-length posterior
        # ------------------------------------------------------------------
        # R_{t-1} had shape (t,); prepend a 0 to align with the new prior
        R_prev = np.concatenate([[0.0], self._run_length_posterior])

        # Growth message: run continues
        growth_msg = R_prev * predictive * (1.0 - h)

        # Change-point message: run resets
        # The new r=0 weight is the sum over all hypotheses of the
        # probability that a change point occurred here.
        cp_msg = np.sum(R_prev * predictive * h)

        # Combine: new posterior
        R_new = growth_msg.copy()
        R_new[0] += cp_msg   # add change-point mass to r=0

        # ------------------------------------------------------------------
        # Step 3: Normalise
        # ------------------------------------------------------------------
        norm = np.sum(R_new)
        if norm > 0:
            R_new /= norm
        else:
            # Numerical underflow — reset to uniform over short runs
            logger.warning(
                "BOCPD normalisation underflow at t=%d.  "
                "Resetting posterior to uniform over run lengths.", t
            )
            R_new = np.ones_like(R_new) / max(len(R_new), 1)

        # ------------------------------------------------------------------
        # Step 4: Update model sufficient statistics with x
        # ------------------------------------------------------------------
        # Update all hypotheses (the prepended prior is already in place)
        self._model.update(x)

        # ------------------------------------------------------------------
        # Step 5: Truncate to max_run_length
        # ------------------------------------------------------------------
        max_rl = self.config.max_run_length
        if max_rl > 0 and len(R_new) > max_rl:
            # Redistribute truncated probability mass to the last kept bucket
            truncated_mass = np.sum(R_new[max_rl:])
            R_new = R_new[:max_rl]
            R_new[-1] += truncated_mass
            self._model.truncate(max_rl)

        self._run_length_posterior = R_new

        # ------------------------------------------------------------------
        # Step 6: Extract statistics
        # ------------------------------------------------------------------
        # cp_probability: probability mass in run_lengths 0..1
        # This captures the "we just reset" signal better than R[0] alone.
        # R[0] is bounded by the hazard h (typically 0.01).
        # R[1] carries the reset mass one step later.
        # We report the combined mass in short run lengths as the change signal.
        cp_prob = float(R_new[0]) + (float(R_new[1]) if len(R_new) > 1 else 0.0)
        map_rl = int(np.argmax(R_new))

        # Apply warm-up mask
        in_warmup = t < self.config.min_observations_before_detection
        if in_warmup:
            cp_prob_out = float("nan")
            is_cp = False
        else:
            cp_prob_out = cp_prob
            is_cp = cp_prob >= self.config.cp_threshold

        step = BOCPDStep(
            observation_index=t,
            observed_at=observed_at,
            observation_value=x,
            cp_probability=cp_prob_out,
            map_run_length=map_rl,
            run_length_posterior=R_new.copy(),
            is_change_point=is_cp,
        )
        self._steps.append(step)
        self._t += 1
        return step

    def get_result(self, product_id: str, merchant: str) -> BOCPDResult:
        """Return a BOCPDResult for the series processed so far."""
        n_cp = sum(1 for s in self._steps if s.is_change_point)
        return BOCPDResult(
            product_id=product_id,
            merchant=merchant,
            steps=list(self._steps),
            config=self.config,
            n_observations=self._t,
            n_change_points=n_cp,
        )


# ---------------------------------------------------------------------------
# Run BOCPD over the full catalogue
# ---------------------------------------------------------------------------

def run_bocpd_on_catalogue(
    features_df: pd.DataFrame,
    config: Optional[BOCPDConfig] = None,
    min_observations: int = 5,
    max_series_cv: float = 0.15,
) -> pd.DataFrame:
    """
    Run BOCPD on every usable (product_id, merchant) time series.

    This function performs the HISTORICAL ONLINE REPLAY:
      - Each series is processed strictly in chronological order.
      - The detector is reset between series.
      - At no point does the detector use future observations.

    Parameters
    ----------
    features_df:
        Full features DataFrame containing at minimum:
        product_id, merchant, observed_at, and the observation_signal
        column defined in config (default: log_price_diff).
    config:
        BOCPDConfig.  If None, default configuration is used.
    min_observations:
        Only process PM pairs with at least this many observations.
    max_series_cv:
        Maximum coefficient of variation (std/mean of price) allowed.
        Series with cv > max_series_cv are flagged as structurally noisy
        (likely multi-SKU collisions or data quality issues) and excluded.
        Default 0.15 retains 86% of pairs.  Set to float('inf') to disable.

    Returns
    -------
    pd.DataFrame
        Flat BOCPD results: one row per (product_id, merchant, observed_at)
        with columns cp_probability, map_run_length, is_change_point.
    """
    if config is None:
        config = BOCPDConfig()

    logger.info("Starting BOCPD historical online replay …")
    logger.info(config.describe())

    signal_col = config.observation_signal
    if signal_col not in features_df.columns:
        raise ValueError(
            f"Observation signal column '{signal_col}' not found in features_df. "
            f"Available columns: {list(features_df.columns)}"
        )

    # Pre-compute series CV for filtering
    series_cv = (
        features_df.groupby(["product_id", "merchant"])["price"]
        .agg(lambda x: x.std() / x.mean() if x.mean() > 0 else float("inf"))
    )

    detector = BOCPDDetector(config)
    all_results: list[pd.DataFrame] = []

    groups = features_df.groupby(["product_id", "merchant"], sort=False)
    n_groups = len(groups)
    processed = 0
    skipped = 0
    skipped_noisy = 0

    for (pid, merch), group in groups:
        group_sorted = group.sort_values("observed_at").reset_index(drop=True)
        n_obs = len(group_sorted)

        if n_obs < min_observations:
            skipped += 1
            continue

        # Skip structurally noisy series
        cv = series_cv.get((pid, merch), float("inf"))
        if cv > max_series_cv:
            skipped_noisy += 1
            continue

        # Valid signal values (exclude rows where signal is NaN for counting)
        valid_signal = group_sorted[signal_col].dropna()
        if len(valid_signal) < 2:
            skipped += 1
            continue

        detector.reset()

        for _, row in group_sorted.iterrows():
            x = row[signal_col]
            ts = row["observed_at"]
            if pd.isna(ts):
                continue
            detector.process_observation(
                x=float("nan") if pd.isna(x) else float(x),
                observed_at=ts,
            )

        result = detector.get_result(pid, merch)
        result_df = result.to_dataframe()

        if not result_df.empty:
            all_results.append(result_df)

        processed += 1
        if processed % 200 == 0 or processed == n_groups:
            logger.info(
                "  BOCPD: %d series processed, %d change points so far",
                processed,
                sum(r["is_change_point"].sum() for r in all_results),
            )

    if not all_results:
        logger.warning("BOCPD produced no results.")
        return pd.DataFrame()

    combined = pd.concat(all_results, ignore_index=True)
    total_cp = int(combined["is_change_point"].sum())

    logger.info(
        "BOCPD complete: %d series processed, %d skipped (<min_obs), "
        "%d skipped (noisy cv>%.2f), "
        "%d total observations, %d change-point flags",
        processed,
        skipped,
        skipped_noisy,
        max_series_cv,
        len(combined),
        total_cp,
    )
    return combined


# ---------------------------------------------------------------------------
# Baseline detector
# ---------------------------------------------------------------------------

class BaselineDetector:
    """
    Two simple baseline detectors for comparison with BOCPD.

    These are NOT replacements for BOCPD.  They exist to provide a
    reference point so we can assess whether BOCPD adds value over
    naive methods.

    Methods
    -------
    threshold_detect(series_df, pct_threshold)
        Flag rows where |percentage_change| > pct_threshold.

    zscore_detect(series_df, window, z_threshold)
        Flag rows where rolling z-score of log_price_diff > z_threshold.
    """

    @staticmethod
    def threshold_detect(
        series_df: pd.DataFrame,
        pct_threshold: float = 10.0,
    ) -> pd.DataFrame:
        """
        Flag observations where the percentage price change exceeds
        a threshold (in absolute value).

        Parameters
        ----------
        series_df : pd.DataFrame
            Must contain 'percentage_change'.
        pct_threshold : float
            Percentage threshold (e.g. 10.0 = 10%).

        Returns
        -------
        pd.DataFrame with column 'baseline_threshold_flag' added.
        """
        df = series_df.copy()
        if "percentage_change" not in df.columns:
            raise ValueError("'percentage_change' column required for threshold baseline.")
        df["baseline_threshold_flag"] = (
            df["percentage_change"].abs() > pct_threshold
        ).fillna(False)
        return df

    @staticmethod
    def zscore_detect(
        series_df: pd.DataFrame,
        window: int = 5,
        z_threshold: float = 2.5,
    ) -> pd.DataFrame:
        """
        Flag observations where the rolling z-score of log_price_diff
        exceeds a threshold.

        The z-score at time t uses only observations from [t-window, t-1]
        — strictly causal.

        Parameters
        ----------
        series_df : pd.DataFrame
            Must contain 'log_price_diff', 'product_id', 'merchant',
            'observed_at'.
        window : int
            Rolling window size.
        z_threshold : float
            Z-score threshold.

        Returns
        -------
        pd.DataFrame with column 'baseline_zscore_flag' added.
        """
        df = series_df.copy()
        if "log_price_diff" not in df.columns:
            raise ValueError("'log_price_diff' column required for z-score baseline.")

        results: list[pd.DataFrame] = []
        for (pid, merch), group in df.groupby(
            ["product_id", "merchant"], sort=False
        ):
            g = group.sort_values("observed_at").reset_index(drop=True)
            roll = g["log_price_diff"].rolling(window=window, min_periods=2)
            roll_mean = roll.mean().shift(1)
            roll_std = roll.std().shift(1)
            z = (g["log_price_diff"] - roll_mean) / roll_std.replace(0, np.nan)
            g["baseline_zscore"] = z
            g["baseline_zscore_flag"] = z.abs() > z_threshold
            g["baseline_zscore_flag"] = g["baseline_zscore_flag"].fillna(False)
            results.append(g)

        return pd.concat(results, ignore_index=True).sort_values(
            ["product_id", "merchant", "observed_at"]
        ).reset_index(drop=True)


def run_baseline_on_catalogue(
    features_df: pd.DataFrame,
    pct_threshold: float = 10.0,
    zscore_window: int = 5,
    zscore_threshold: float = 2.5,
) -> pd.DataFrame:
    """
    Run both baseline detectors on the full features DataFrame.

    Returns the DataFrame with both baseline flag columns added.
    """
    logger.info(
        "Running baseline detectors (threshold=%.1f%%, z-score window=%d, "
        "z-threshold=%.1f) …",
        pct_threshold,
        zscore_window,
        zscore_threshold,
    )
    bd = BaselineDetector()
    df = bd.threshold_detect(features_df, pct_threshold=pct_threshold)
    df = bd.zscore_detect(
        df, window=zscore_window, z_threshold=zscore_threshold
    )
    n_threshold = int(df["baseline_threshold_flag"].sum())
    n_zscore = int(df["baseline_zscore_flag"].sum())
    logger.info(
        "Baseline results: threshold flags=%d, z-score flags=%d",
        n_threshold,
        n_zscore,
    )
    return df
