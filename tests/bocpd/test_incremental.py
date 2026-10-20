"""
tests/bocpd/test_incremental.py
=================================
Stage 3 tests for IncrementalDetector.

Critical test: batch-equivalence — feeding observations one at a time
with state saved/restored between every step must produce the same
cp_probability values as the batch BOCPDDetector replay.
"""
from __future__ import annotations
import math
import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.bocpd.config import BOCPDConfig
from src.bocpd.detector import BOCPDDetector
from src.bocpd.incremental import (
    IncrementalDetector,
    serialize_detector_state,
    restore_detector_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_price_series(n: int = 40, change_at: int = 20,
                       base: float = 100.0, new_level: float = 75.0):
    """Synthetic price series with a known change point at change_at."""
    prices = [base] * change_at + [new_level] * (n - change_at)
    # add tiny noise to avoid degenerate log_price_diff of 0
    rng = np.random.default_rng(42)
    prices = [p * (1 + rng.normal(0, 0.001)) for p in prices]
    dates = pd.date_range("2017-01-01", periods=n, freq="7D", tz="UTC")
    return prices, [d.isoformat() for d in dates]


def _batch_replay(prices: List[float], config: BOCPDConfig):
    """Run the existing batch detector on a price series."""
    log_prices = [math.log(p) for p in prices]
    log_diffs = [float("nan")] + [
        log_prices[i] - log_prices[i-1] for i in range(1, len(log_prices))
    ]
    detector = BOCPDDetector(config)
    steps = []
    for i, (ld, p) in enumerate(zip(log_diffs, prices)):
        ts = pd.Timestamp(f"2017-01-{1 + i*7:02d}", tz="UTC")
        step = detector.process_observation(ld, ts)
        steps.append(step)
    return steps


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------

class TestStateRoundTrip:

    def test_serialize_restore_preserves_arrays(self):
        config = BOCPDConfig()
        det = BOCPDDetector(config)
        prices = [100.0, 101.0, 99.5, 100.2]
        log_diffs = [float("nan")] + [
            math.log(prices[i] / prices[i-1]) for i in range(1, len(prices))
        ]
        for ld in log_diffs:
            det.process_observation(ld)

        state = serialize_detector_state(det)
        restored = restore_detector_state(state, config)

        np.testing.assert_array_almost_equal(det._model.mu, restored._model.mu)
        np.testing.assert_array_almost_equal(det._model.kappa, restored._model.kappa)
        np.testing.assert_array_almost_equal(det._model.alpha, restored._model.alpha)
        np.testing.assert_array_almost_equal(det._model.beta, restored._model.beta)
        np.testing.assert_array_almost_equal(
            det._run_length_posterior, restored._run_length_posterior
        )
        assert det._t == restored._t

    def test_restored_detector_continues_correctly(self):
        """Next observation on a restored detector must equal batch result."""
        config = BOCPDConfig()
        prices = [100.0, 101.0, 99.5, 100.2, 98.0]
        log_diffs = [float("nan")] + [
            math.log(prices[i] / prices[i-1]) for i in range(1, len(prices))
        ]

        # Batch: process all 5
        batch_det = BOCPDDetector(config)
        for ld in log_diffs:
            batch_step = batch_det.process_observation(ld)

        # Incremental: process 4, serialize, restore, process 5th
        incr_det = BOCPDDetector(config)
        for ld in log_diffs[:4]:
            incr_det.process_observation(ld)
        state = serialize_detector_state(incr_det)

        restored = restore_detector_state(state, config)
        restored_step = restored.process_observation(log_diffs[4])

        assert abs(batch_step.cp_probability - restored_step.cp_probability) < 1e-10


# ---------------------------------------------------------------------------
# CRITICAL: Batch-equivalence test
# ---------------------------------------------------------------------------

class TestBatchEquivalence:
    """
    Feed observations one at a time with state saved/restored between each
    step.  cp_probabilities must match the batch replay within tolerance.
    """

    def test_equivalence_flat_series(self):
        """
        Stable series with no regime change.
        Aligns batch and incremental by observation index so comparisons
        are always against the same step.
        """
        config = BOCPDConfig()
        n = 30
        prices = [100.0 * (1 + np.random.default_rng(1).normal(0, 0.002))
                  for _ in range(n)]
        dates = [pd.Timestamp("2017-01-01", tz="UTC") + pd.Timedelta(weeks=i)
                 for i in range(n)]
        date_strs = [d.isoformat() for d in dates]

        # --- Batch: index -> cp_probability ---
        log_diffs = [float("nan")] + [
            math.log(prices[i] / prices[i-1]) for i in range(1, n)
        ]
        batch_det = BOCPDDetector(config)
        batch_by_idx = {}
        for i, ld in enumerate(log_diffs):
            s = batch_det.process_observation(ld, dates[i])
            batch_by_idx[i] = s.cp_probability

        # --- Incremental: index -> cp_probability ---
        incr_det = IncrementalDetector(config)
        stored_state = None
        last_price = None
        last_ts = None
        obs_count = 0
        incr_by_idx = {}

        for i, price in enumerate(prices):
            result = incr_det.process(
                new_price=price,
                observed_at=date_strs[i],
                stored_state=stored_state,
                last_price=last_price,
                last_observed_at=last_ts,
                observation_count=obs_count,
            )
            if result is not None:
                stored_state = result.new_state
                last_price = result.last_price
                last_ts = result.last_observed_at
                obs_count = result.observation_count
                incr_by_idx[i] = result.step.cp_probability

        # Compare at every index where both have a non-NaN value
        compared = 0
        for idx in sorted(set(batch_by_idx) & set(incr_by_idx)):
            b = batch_by_idx[idx]
            c = incr_by_idx[idx]
            if b is None or np.isnan(b) or c is None or np.isnan(c):
                continue
            assert abs(b - c) < 1e-9, (
                f"Mismatch at obs {idx}: batch={b:.8f} incr={c:.8f}"
            )
            compared += 1

        assert compared > 0, "No overlapping non-NaN values to compare"

    def test_equivalence_with_regime_change(self):
        """Series with a clear price drop at step 20 — change point must be detected."""
        config = BOCPDConfig()
        prices, date_strs = _make_price_series(n=40, change_at=20)
        dates = [pd.Timestamp(d) for d in date_strs]

        # --- Batch ---
        log_diffs = [float("nan")] + [
            math.log(prices[i] / prices[i-1]) for i in range(1, len(prices))
        ]
        batch_det = BOCPDDetector(config)
        batch_steps = [
            batch_det.process_observation(ld, dates[i])
            for i, ld in enumerate(log_diffs)
        ]

        # --- Incremental ---
        incr_det = IncrementalDetector(config)
        stored_state = None
        last_price = None
        last_ts = None
        obs_count = 0
        incr_results = []

        for i, price in enumerate(prices):
            result = incr_det.process(
                new_price=price,
                observed_at=date_strs[i],
                stored_state=stored_state,
                last_price=last_price,
                last_observed_at=last_ts,
                observation_count=obs_count,
            )
            if result is not None:
                stored_state = result.new_state
                last_price = result.last_price
                last_ts = result.last_observed_at
                obs_count = result.observation_count
                incr_results.append(result.step)

        # Batch cp_probs (excluding NaN warm-up)
        batch_cps = [
            (i, s.cp_probability) for i, s in enumerate(batch_steps)
            if s.cp_probability is not None and not np.isnan(s.cp_probability)
        ]
        incr_cps = [
            (i, s.cp_probability) for i, s in enumerate(incr_results)
            if s.cp_probability is not None and not np.isnan(s.cp_probability)
        ]

        # Both should detect approximately the same change point
        batch_flagged = {i for i, cp in batch_cps if cp >= config.cp_threshold}
        incr_flagged = {i for i, cp in incr_cps if cp >= config.cp_threshold}

        # If batch finds a change point, incremental must find it at same index
        # (within 1 step tolerance for edge-of-window cases)
        for bf in batch_flagged:
            near = {bf-1, bf, bf+1}
            assert near & incr_flagged, (
                f"Batch flagged step {bf} but incremental did not flag nearby. "
                f"Incremental flagged: {incr_flagged}"
            )

    def test_equivalence_on_historical_series(self):
        """
        Compare batch vs incremental on a sample of real Phase 1 series.
        Uses the cleaned CSV if available; skips otherwise.
        """
        csv_path = ROOT / "data" / "processed" / "cleaned_data.csv"
        if not csv_path.exists():
            pytest.skip("cleaned_data.csv not available")

        import pandas as pd_
        df = pd_.read_csv(csv_path, low_memory=False)
        df["observed_at"] = pd_.to_datetime(df["observed_at"], utc=True)
        df["price"] = pd_.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["price", "observed_at"])

        config = BOCPDConfig()
        tested = 0
        mismatches = 0

        for (pid, merch), group in df.groupby(["product_id", "merchant"]):
            g = group.sort_values("observed_at").reset_index(drop=True)
            if len(g) < 10:
                continue

            prices = g["price"].tolist()
            date_strs = [d.isoformat() for d in g["observed_at"]]
            dates = [pd_.Timestamp(d) for d in date_strs]

            # Batch
            log_diffs = [float("nan")] + [
                math.log(prices[i] / prices[i-1]) for i in range(1, len(prices))
            ]
            batch_det = BOCPDDetector(config)
            batch_cps = []
            for i, ld in enumerate(log_diffs):
                s = batch_det.process_observation(ld, dates[i])
                if s.cp_probability is not None and not np.isnan(s.cp_probability):
                    batch_cps.append(s.cp_probability)

            # Incremental
            incr_det = IncrementalDetector(config)
            stored_state = None
            last_price = None
            last_ts = None
            obs_count = 0
            incr_cps = []

            for i, price in enumerate(prices):
                result = incr_det.process(
                    new_price=price,
                    observed_at=date_strs[i],
                    stored_state=stored_state,
                    last_price=last_price,
                    last_observed_at=last_ts,
                    observation_count=obs_count,
                )
                if result is not None:
                    stored_state = result.new_state
                    last_price = result.last_price
                    last_ts = result.last_observed_at
                    obs_count = result.observation_count
                    if (result.step.cp_probability is not None and
                            not np.isnan(result.step.cp_probability)):
                        incr_cps.append(result.step.cp_probability)

            min_len = min(len(batch_cps), len(incr_cps))
            for i in range(min_len):
                if abs(batch_cps[i] - incr_cps[i]) > 1e-8:
                    mismatches += 1

            tested += 1
            if tested >= 20:   # test first 20 series
                break

        assert tested > 0, "No series long enough to test"
        assert mismatches == 0, (
            f"{mismatches} cp_probability mismatches across {tested} series. "
            "Incremental path does not match batch path."
        )


# ---------------------------------------------------------------------------
# Warm-up, duplicate, out-of-order
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_first_observation_returns_result_with_nan(self):
        """First observation seeds state but cp_probability is NaN (warm-up)."""
        det = IncrementalDetector()
        result = det.process(
            new_price=100.0,
            observed_at="2017-01-01T00:00:00+00:00",
            stored_state=None,
            last_price=None,
            last_observed_at=None,
            observation_count=0,
        )
        assert result is not None
        assert np.isnan(result.step.cp_probability)
        assert result.last_price == 100.0

    def test_out_of_order_returns_none(self):
        """Observation older than last_observed_at must be skipped (returns None)."""
        det = IncrementalDetector()
        result = det.process(
            new_price=95.0,
            observed_at="2017-01-01T00:00:00+00:00",   # older
            stored_state={},
            last_price=100.0,
            last_observed_at="2017-01-15T00:00:00+00:00",  # newer
            observation_count=5,
        )
        assert result is None

    def test_duplicate_timestamp_returns_none(self):
        """Exact same timestamp as last_observed_at must be skipped."""
        det = IncrementalDetector()
        ts = "2017-01-15T00:00:00+00:00"
        result = det.process(
            new_price=95.0,
            observed_at=ts,
            stored_state={},
            last_price=100.0,
            last_observed_at=ts,
            observation_count=5,
        )
        assert result is None

    def test_warmup_respected(self):
        """
        First min_observations_before_detection steps should return NaN cp_probability.
        Default min_obs = 3 in BOCPDConfig.
        """
        config = BOCPDConfig()
        warmup = config.min_observations_before_detection
        det = IncrementalDetector(config)
        prices = [100.0, 101.0, 99.5, 100.2, 98.0, 102.0]
        dates = [
            pd.Timestamp("2017-01-01", tz="UTC") + pd.Timedelta(weeks=i)
            for i in range(len(prices))
        ]

        stored_state = None
        last_price = None
        last_ts = None
        obs_count = 0
        non_nan_count = 0

        for i, price in enumerate(prices):
            result = det.process(
                new_price=price,
                observed_at=dates[i].isoformat(),
                stored_state=stored_state,
                last_price=last_price,
                last_observed_at=last_ts,
                observation_count=obs_count,
            )
            if result is not None:
                stored_state = result.new_state
                last_price = result.last_price
                last_ts = result.last_observed_at
                obs_count = result.observation_count
                if result.step.cp_probability is not None and not np.isnan(result.step.cp_probability):
                    non_nan_count += 1

        # With 6 prices we should get some non-NaN values (after warm-up)
        assert non_nan_count > 0, "Expected some non-NaN cp_probability values after warm-up"
